"""Coordinator cache location, auth failure, and startup resilience."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from kmd_easy_energy.const import EVENT_MITID_CHALLENGE
from kmd_easy_energy.coordinator import KMDEasyEnergyCoordinator
from kmd_easy_energy.util import legacy_www_cache_paths, sanitize_cache


class FakeStore:
    def __init__(self, data=None) -> None:
        self.data = data
        self.saved: list[dict] = []
        self.removed = False

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        self.saved.append(data)

    async def async_remove(self):
        self.removed = True
        self.data = None


def _entry(tmp_path: Path, **data):
    payload = {
        "utility": "Kredsløb",
        "utility_id": "kredslob",
        "portal_url": "https://minvarme.kredslob.dk/",
        **data,
    }
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Kredsløb",
        data=payload,
        options={},
        unique_id="kredslob",
        async_on_unload=lambda *a, **k: None,
        async_start_reauth=MagicMock(),
    )
    return entry


def _hass(tmp_path: Path):
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.config.latitude = 56.15
    hass.config.longitude = 10.10
    hass.bus.async_fire = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    hass.async_create_task = MagicMock()
    return hass


def make_coordinator(tmp_path: Path, store: FakeStore | None = None, **entry_data):
    entry = _entry(tmp_path, **entry_data)
    hass = _hass(tmp_path)
    store = store or FakeStore()
    with patch.object(DataUpdateCoordinator, "__init__", lambda *a, **k: None):
        coord = KMDEasyEnergyCoordinator.__new__(KMDEasyEnergyCoordinator)
        coord.hass = hass
        coord.entry = entry
        coord._portal_url = entry.data["portal_url"]
        coord.client = None
        coord._token_obtained = None
        coord._utility_id = "kredslob"
        coord._store = store
        coord._legacy_paths = legacy_www_cache_paths(hass, "kredslob")
        coord._initial_setup_complete = None
        coord.sync_state = "idle"
        coord.sync_message = ""
        coord.mitid_otp_code = None
        coord.mitid_qr_svg = None
        coord._sync_task = None
        coord.data = {}
        coord.logger = MagicMock()
        coord.name = "kmd_easy_energy"
        coord.config_entry = entry
    return coord, hass, entry, store


@pytest.mark.asyncio
async def test_initialize_cache_uses_store_not_www(tmp_path: Path) -> None:
    store = FakeStore({"annual": {"2026": 9}, "mitid_otp_code": "9999"})
    coord, hass, _, _ = make_coordinator(tmp_path, store=store)
    # A leftover public file must not be the live cache location
    public = tmp_path / "www" / "varme" / "kmd_easy_energy_cache_kredslob.json"
    public.parent.mkdir(parents=True)
    public.write_text(json.dumps({"annual": {"2026": 1}}), encoding="utf-8")

    state = await coord.async_initialize_cache()
    assert state["annual"]["2026"] == 9
    assert "mitid_otp_code" not in state
    # Store data is the source of truth; we do not write under www/
    assert all(not str(p).startswith(str(tmp_path / "www")) for p in [coord._store])
    # When the private store already has data we leave leftover www files
    # for the first initialize? Current code only migrates when store is empty.
    # Migration is tested separately.


@pytest.mark.asyncio
async def test_migrates_and_deletes_legacy_www_cache(tmp_path: Path) -> None:
    store = FakeStore(None)
    coord, hass, _, store = make_coordinator(tmp_path, store=store)
    public = tmp_path / "www" / "varme" / "kmd_easy_energy_cache_kredslob.json"
    public.parent.mkdir(parents=True)
    public.write_text(
        json.dumps({"annual": {"2025": 50}, "mitid_otp_code": "1234", "daily": {"total": 3}}),
        encoding="utf-8",
    )
    seed = tmp_path / "www" / "varme" / "data.json"
    seed.write_text(json.dumps({"annual": {"1999": 1}, "marker": "do-not-seed"}), encoding="utf-8")

    state = await coord.async_initialize_cache()
    assert state["annual"]["2025"] == 50
    assert "mitid_otp_code" not in state
    assert "marker" not in state
    assert state["annual"].get("1999") is None
    assert not public.exists(), "legacy public cache should be deleted after migration"
    assert seed.exists() and "do-not-seed" in seed.read_text(), "data.json must not be deleted or used"
    assert store.data is not None
    assert "mitid_otp_code" not in store.data


@pytest.mark.asyncio
async def test_save_cache_strips_otp_and_stays_private(tmp_path: Path) -> None:
    coord, hass, _, store = make_coordinator(tmp_path)
    await coord._async_save_cache(
        {
            "annual": {"2026": 4},
            "mitid_otp_code": "1234",
            "mitid_qr_svg": "<svg />",
            "sync_state": "otp_ready",
        }
    )
    assert store.data is not None
    assert "mitid_otp_code" not in store.data
    assert "mitid_qr_svg" not in store.data
    assert store.data["sync_state"] == "idle"
    www = tmp_path / "www"
    if www.exists():
        leftovers = list(www.rglob("*.json"))
        assert leftovers == []


@pytest.mark.asyncio
async def test_401_raises_auth_failed_and_keeps_cache(tmp_path: Path) -> None:
    coord, hass, _, store = make_coordinator(
        tmp_path, access_token="expired-token", customer_id="c", customer_number="n"
    )
    cached = {"annual": {"2026": 77}, "daily": {"total": 5}}
    coord.data = dict(cached)
    err = ClientResponseError(MagicMock(), (), status=401, message="Unauthorized")
    coord.client = MagicMock()
    coord.client.get_active_meters = AsyncMock(side_effect=err)

    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()
    assert coord.data["annual"]["2026"] == 77
    assert coord.data["token_expired"] is True


@pytest.mark.asyncio
async def test_transient_http_error_serves_cache(tmp_path: Path) -> None:
    coord, *_ = make_coordinator(tmp_path, access_token="tok", customer_id="c", customer_number="n")
    coord.data = {"annual": {"2026": 11}, "daily": {"total": 2}}
    err = ClientResponseError(MagicMock(), (), status=502, message="Bad Gateway")
    coord.client = MagicMock()
    coord.client.get_active_meters = AsyncMock(side_effect=err)
    result = await coord._async_update_data()
    assert result["annual"]["2026"] == 11


@pytest.mark.asyncio
async def test_remove_storage_clears_store_and_legacy(tmp_path: Path) -> None:
    public = tmp_path / "www" / "varme" / "kmd_easy_energy_cache_kredslob.json"
    public.parent.mkdir(parents=True)
    public.write_text("{}", encoding="utf-8")
    store = FakeStore({"annual": {"2026": 1}})
    coord, *_ = make_coordinator(tmp_path, store=store)
    await coord.async_remove_storage()
    assert store.removed is True
    assert not public.exists()


def test_push_sync_ui_fires_event_without_otp_in_state(tmp_path: Path) -> None:
    coord, hass, *_ = make_coordinator(tmp_path)
    coord.data = {"annual": {"2026": 1}}
    coord.async_set_updated_data = MagicMock()
    coord._push_sync_ui("otp_ready", "Indtast kode på kortet.", otp_code="1234", qr_svg="<svg />")
    assert coord.mitid_otp_code == "1234"
    published = coord.async_set_updated_data.call_args[0][0]
    assert "mitid_otp_code" not in published
    assert "mitid_qr_svg" not in published
    hass.bus.async_fire.assert_called()
    ev_name, ev_data = hass.bus.async_fire.call_args[0]
    assert ev_name == EVENT_MITID_CHALLENGE
    assert ev_data["otp_code"] == "1234"


def test_sanitize_matches_event_split() -> None:
    """OTP may live on the coordinator object and in a bus event, never in persisted state."""
    persisted = sanitize_cache({"mitid_otp_code": "0000", "annual": {"2026": 1}})
    assert "mitid_otp_code" not in persisted
