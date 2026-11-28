"""Service permission and schema tests (admin vs. non-admin wall-tablet sync)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import Context, HassJobType, ServiceRegistry
from homeassistant.exceptions import Unauthorized

from kmd_easy_energy import _async_setup_services
from kmd_easy_energy.const import CONF_UTILITY_ID, DOMAIN


def _build_hass():
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_UTILITY_ID: "kredslob"},
        options={},
    )
    coord = SimpleNamespace(
        uses_mitid=True,
        async_sync_with_token=AsyncMock(),
        async_start_sync=AsyncMock(),
        async_request_refresh=AsyncMock(),
        async_set_setup_state=AsyncMock(),
        async_start_mitid_sync=AsyncMock(),
    )

    users = {
        "admin-user": SimpleNamespace(id="admin-user", is_admin=True),
        "tablet-user": SimpleNamespace(id="tablet-user", is_admin=False),
    }

    async def fake_get_user(user_id: str):
        return users.get(user_id)

    async def fake_executor(func, *args):
        return func(*args)

    def fake_run_hass_job(hassjob, *args, background=False):
        if hassjob.job_type is HassJobType.Callback:
            hassjob.target(*args)
            return None
        return asyncio.ensure_future(hassjob.target(*args))

    def fake_update_entry(target_entry, *, data=None, options=None):
        if data is not None:
            target_entry.data = dict(data)
        if options is not None:
            target_entry.options = dict(options)

    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: coord}},
        auth=SimpleNamespace(async_get_user=fake_get_user),
        bus=SimpleNamespace(async_fire_internal=MagicMock()),
        config_entries=SimpleNamespace(
            async_entries=lambda domain: [entry] if domain == DOMAIN else [],
            async_update_entry=fake_update_entry,
        ),
        async_add_executor_job=fake_executor,
        async_run_hass_job=fake_run_hass_job,
        async_create_task_internal=lambda coro, *a, **kw: asyncio.ensure_future(coro),
        verify_event_loop_thread=lambda *a, **kw: None,
    )
    hass.services = ServiceRegistry(hass)
    return hass, entry, coord


@pytest.mark.asyncio
async def test_admin_services_reject_non_admin_user() -> None:
    hass, _, coord = _build_hass()
    await _async_setup_services(hass)
    tablet_ctx = Context(user_id="tablet-user")

    for service_name, payload in (
        ("configure_utility", {"entry_id": "entry-1", "price_dkk_per_kwh": 0.85}),
        ("reset_setup", {"entry_id": "entry-1"}),
        ("update_token", {"entry_id": "entry-1", "access_token": "tok-123"}),
        ("start_mitid_sync", {"entry_id": "entry-1", "mitid_username": "user1"}),
    ):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN, service_name, payload, blocking=True, context=tablet_ctx
            )

    coord.async_set_setup_state.assert_not_awaited()
    coord.async_sync_with_token.assert_not_awaited()
    coord.async_start_mitid_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_services_succeed_for_admin_user() -> None:
    hass, entry, coord = _build_hass()
    await _async_setup_services(hass)
    admin_ctx = Context(user_id="admin-user")

    await hass.services.async_call(
        DOMAIN,
        "configure_utility",
        {
            "entry_id": "entry-1",
            "utility_id": "kredslob",
            "portal_url": "https://minvarme.kredslob.dk/",
            "price_dkk_per_kwh": 0.79,
            "bonus_temp": 30,
            "penalty_temp": 40,
            "fixed_fee_dkk_per_m2_year": 33.75,
            "heated_area_m2": 162,
            "fixed_fee_dkk_per_year": 787.5,
            "aconto_dkk_per_year": 12500,
            "mitid_username": "admin-mitid",
            "notify_service": "mobile_app_phone",
            "complete_setup": True,
            "start_sync": False,
        },
        blocking=True,
        context=admin_ctx,
    )
    assert entry.options["price_dkk_per_kwh"] == 0.79
    assert entry.options["heated_area_m2"] == 162.0
    assert entry.options["aconto_dkk_per_year"] == 12500.0
    coord.async_set_setup_state.assert_awaited_once()

    await hass.services.async_call(
        DOMAIN,
        "reset_setup",
        {"entry_id": "entry-1"},
        blocking=True,
        context=admin_ctx,
    )
    assert coord.async_set_setup_state.await_count == 2

    await hass.services.async_call(
        DOMAIN,
        "update_token",
        {"entry_id": "entry-1", "access_token": "tok-abc"},
        blocking=True,
        context=admin_ctx,
    )
    coord.async_sync_with_token.assert_awaited_once_with("tok-abc", None, None)

    await hass.services.async_call(
        DOMAIN,
        "start_mitid_sync",
        {"utility_id": "kredslob", "mitid_username": "u2", "notify_service": ""},
        blocking=True,
        context=admin_ctx,
    )
    coord.async_start_mitid_sync.assert_awaited_once_with(
        mitid_username="u2", notify_service=""
    )


@pytest.mark.asyncio
async def test_non_admin_wall_tablet_can_sync_and_refresh_only() -> None:
    hass, _, coord = _build_hass()
    await _async_setup_services(hass)
    tablet_ctx = Context(user_id="tablet-user")

    await hass.services.async_call(
        DOMAIN, "sync", {"entry_id": "entry-1"}, blocking=True, context=tablet_ctx
    )
    await hass.services.async_call(
        DOMAIN, "sync", {"utility_id": "kredslob"}, blocking=True, context=tablet_ctx
    )
    assert coord.async_start_sync.await_count == 2

    await hass.services.async_call(
        DOMAIN, "refresh", {"entry_id": "entry-1"}, blocking=True, context=tablet_ctx
    )
    coord.async_request_refresh.assert_awaited_once()

    for forbidden_field in ("mitid_username", "notify_service"):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN,
                "sync",
                {"entry_id": "entry-1", forbidden_field: "spoof"},
                blocking=True,
                context=tablet_ctx,
            )
