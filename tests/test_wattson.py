"""Watts On backend (Aalborg Forsyning): client, parsing, mapping, coordinator, flow.

All responses are mocked (tests/fixtures_wattson.py); no network and no real
tokens. Heat field names in the fixtures are invented guesses.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

import fixtures_wattson as fx
from kmd_easy_energy.api.wattson_client import (
    HEAT_ENDPOINT_CANDIDATES,
    WATTS_CLIENT_ID,
    WATTS_REDIRECT_URI,
    WattsOnAuthError,
    WattsOnClient,
    WattsOnError,
    WattsOnNotFound,
    WattsOnRateLimited,
    async_exchange_code,
    classify_device,
    code_from_redirect,
    new_login,
    parse_heat_items,
)
from kmd_easy_energy.capabilities import effective_capabilities, entity_capabilities
from kmd_easy_energy.wattson_mapping import apply_wattson_data

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 6)


# ---------------------------------------------------------------- login (PKCE)
def test_login_url_is_pkce_s256_for_the_watts_app_registration() -> None:
    login = new_login()
    q = parse_qs(urlparse(login.url).query)
    assert q["client_id"] == [WATTS_CLIENT_ID]
    # Same encoding as Novafos-V2 (verified live there): the literal "%3D" is part of the URI.
    assert q["redirect_uri"] == [WATTS_REDIRECT_URI]
    assert q["code_challenge_method"] == ["S256"] and q["state"] == [login.state]
    expected = base64.urlsafe_b64encode(hashlib.sha256(login.verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == [expected]
    assert "offline_access" in q["scope"][0]
    assert login.verifier not in login.url
    assert new_login().state != login.state


@pytest.mark.parametrize(
    "pasted",
    [
        "msauth://com.seasnve.watts/fsJnZjQxAH1FUDb0pBECue0g650%3D?state=S1&code=abc123",
        "Failed to launch 'msauth://com.seasnve.watts/x?code=abc123&state=S1' because the scheme does not have a registered handler.",
        "  code=abc123&state=S1 ",
    ],
)
def test_code_from_redirect_accepts_url_console_line_and_query(pasted: str) -> None:
    assert code_from_redirect(pasted, "S1") == "abc123"


@pytest.mark.parametrize(
    ("pasted", "reason"),
    [
        ("msauth://com.seasnve.watts/x?state=S1", "no_code"),
        ("https://example.invalid/", "no_code"),
        ("msauth://com.seasnve.watts/x?code=abc&state=OTHER", "state_mismatch"),
        ("msauth://com.seasnve.watts/x?error=access_denied&error_description=AADB2C90091", "b2c_error"),
    ],
)
def test_code_from_redirect_errors(pasted: str, reason: str) -> None:
    with pytest.raises(WattsOnAuthError) as err:
        code_from_redirect(pasted, "S1")
    assert str(err.value) == reason


@pytest.mark.asyncio
async def test_exchange_code_posts_pkce_form_and_reports_refresh_expiry() -> None:
    session = fx.FakeSession({"oauth2/v2.0/token": fx.token_body(fx.REFRESH_1)})
    tokens = await async_exchange_code(session, "the-code", "the-verifier")
    form = session.calls[0]["data"]
    assert form["grant_type"] == "authorization_code" and form["code_verifier"] == "the-verifier"
    assert form["redirect_uri"] == WATTS_REDIRECT_URI and form["client_id"] == WATTS_CLIENT_ID
    assert tokens["refresh_token"] == fx.REFRESH_1 and tokens["refresh_expires_at"]


@pytest.mark.asyncio
async def test_exchange_code_rejected_is_auth_error_without_echoing_body() -> None:
    session = fx.FakeSession({"oauth2/v2.0/token": (400, {"error_description": "secret hint"})})
    with pytest.raises(WattsOnAuthError) as err:
        await async_exchange_code(session, "c", "v")
    assert "secret hint" not in str(err.value)


# ---------------------------------------------------------------- client
@pytest.mark.asyncio
async def test_refresh_rotates_and_new_token_is_handed_to_callback() -> None:
    session = fx.FakeSession()
    seen: list[tuple[str, str | None]] = []

    async def store(tok, exp):
        seen.append((tok, exp))

    client = WattsOnClient(session, fx.REFRESH_1, on_refresh_token=store)
    assert await client.async_user_id() == fx.USER_ID
    assert client.refresh_token == fx.REFRESH_2
    assert seen and seen[0][0] == fx.REFRESH_2 and seen[0][1]
    token_call = session.calls[0]
    assert token_call["data"]["grant_type"] == "refresh_token"
    assert token_call["data"]["refresh_token"] == fx.REFRESH_1
    api_calls = [c for c in session.calls if "p.watts-energy.dk" in c["url"]]
    assert api_calls[0]["headers"]["Authorization"] == f"Bearer {fx.ACCESS}"
    for c in session.calls:  # tokens never in URLs
        assert fx.REFRESH_1 not in c["url"] and fx.ACCESS not in c["url"]
    # Access token is cached: a second call does not refresh again.
    n = len(session.calls)
    await client.get("users/api/v3/User")
    assert len(session.calls) == n + 1


@pytest.mark.asyncio
async def test_401_retries_once_then_auth_error() -> None:
    state = {"n": 0}

    def user(method, url, kw):
        state["n"] += 1
        return (401, {}) if state["n"] == 1 else fx.USER

    client = WattsOnClient(fx.FakeSession({"users/api/v3/User": user}), fx.REFRESH_1)
    assert await client.async_user_id() == fx.USER_ID
    client2 = WattsOnClient(fx.FakeSession({"users/api/v3/User": (401, {})}), fx.REFRESH_1)
    with pytest.raises(WattsOnAuthError):
        await client2.async_user_id()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "exc"),
    [
        ({"oauth2/v2.0/token": (400, {})}, WattsOnAuthError),
        ({"users/api/v3/User": (429, {})}, WattsOnRateLimited),
        ({"users/api/v3/User": (500, {})}, WattsOnError),
        ({"users/api/v3/User": (403, {})}, WattsOnAuthError),
    ],
)
async def test_http_errors(route, exc) -> None:
    with pytest.raises(exc):
        await WattsOnClient(fx.FakeSession(route), fx.REFRESH_1).async_user_id()


def test_classify_device() -> None:
    assert classify_device({"utilityType": "DistrictHeating"}) == "heat"
    assert classify_device({"UtilityType": "Varme"}) == "heat"
    assert classify_device({"utilityType": "Water"}) == "water"
    assert classify_device({"deviceType": "Electricity"}) == "electricity"
    assert classify_device({"utilityType": "Gas"}) is None
    assert classify_device({}) is None


@pytest.mark.asyncio
async def test_devices_are_classified_and_carry_no_personal_fields() -> None:
    devices = await WattsOnClient(fx.FakeSession(), fx.REFRESH_1).async_devices()
    by_id = {d["id"]: d for d in devices}
    assert by_id[fx.HEAT_DEVICE]["kind"] == "heat" and by_id[fx.HEAT_DEVICE]["unit"] == "kWh"
    assert by_id[fx.WATER_DEVICE]["kind"] == "water"
    dumped = json.dumps(devices)
    assert "Testvej" not in dumped and "12345678" not in dumped and "someone@" not in dumped


@pytest.mark.asyncio
async def test_heat_endpoint_probing_records_only_templates_and_status() -> None:
    session = fx.FakeSession(
        {
            f"dk/heating/api/v1/devices/{fx.HEAT_DEVICE}/consumption/recent": (404, {}),
            f"dk/heating/api/consumptions/{fx.HEAT_DEVICE}": (404, {}),
            f"dk/districtheating/api/consumptions/{fx.HEAT_DEVICE}": fx.heat_items(1),
        }
    )
    client = WattsOnClient(session, fx.REFRESH_1)
    used, items, probe = await client.async_heat_consumptions(
        fx.HEAT_DEVICE, datetime(2026, 11, 1, tzinfo=timezone.utc)
    )
    assert used == HEAT_ENDPOINT_CANDIDATES[2] and len(items) == 24
    assert probe == [
        {"endpoint": HEAT_ENDPOINT_CANDIDATES[0], "result": "HTTP 404"},
        {"endpoint": HEAT_ENDPOINT_CANDIDATES[1], "result": "HTTP 404"},
        {"endpoint": HEAT_ENDPOINT_CANDIDATES[2], "result": "ok"},
    ]
    call = [c for c in session.calls if "districtheating" in c["url"]][0]
    assert call["params"] == {"startDate": "2026-11-01T00:00:00Z"}
    # Known endpoint: no probing; override with <device_id> placeholder works.
    session.calls.clear()
    used, _, probe = await client.async_heat_consumptions(
        fx.HEAT_DEVICE, datetime(2026, 11, 1, tzinfo=timezone.utc), "districtheating/api/consumptions/<device_id>"
    )
    assert len(probe) == 1 and [c for c in session.calls if "heating" in c["url"]][0]["url"].endswith(fx.HEAT_DEVICE)


def _aalborg_items() -> list[dict]:
    """Shape of an Aalborg Forsyning heat reply (synthetic values, not a live meter hour)."""
    return [
        {"Id": fx.HEAT_DEVICE, "SD": "2026-01-15T13:00:00Z", "ED": "2026-01-15T14:00:00Z",
         "En": 4, "Vol": 0.05806, "Fl": 0.04, "TI": 68.25, "TO": 29.50, "CD": 38.75, "MQ": "measured"},
        {"Id": fx.HEAT_DEVICE, "SD": "2026-01-15T14:00:00Z", "ED": "2026-01-15T15:00:00Z",
         "En": 3, "Vol": 0.04444, "Fl": 0.03, "TI": 67.10, "TO": 28.20, "CD": 38.90, "MQ": "measured"},
    ]


@pytest.mark.asyncio
async def test_verified_heat_endpoint_is_tried_first_with_newer_than() -> None:
    session = fx.FakeSession(
        {f"dk/heating/api/v1/devices/{fx.HEAT_DEVICE}/consumption/recent": _aalborg_items()}
    )
    client = WattsOnClient(session, fx.REFRESH_1)
    used, items, probe = await client.async_heat_consumptions(
        fx.HEAT_DEVICE, datetime(2026, 11, 1, tzinfo=timezone.utc)
    )
    assert used == "heating/api/v1/devices/{device_id}/consumption/recent"
    assert probe == [{"endpoint": used, "result": "ok"}] and len(items) == 2
    call = [c for c in session.calls if "consumption/recent" in c["url"]][0]
    assert call["params"] == {"newerThan": "2026-11-01T00:00:00Z"}


def test_parse_aalborg_heat_items_with_ti_to_temperatures() -> None:
    p = parse_heat_items(_aalborg_items(), unit_hint="kWh")
    assert not p.skipped and not p.assumptions and p.energy_unit == "kWh"
    first = p.intervals[0]
    assert first["kwh"] == 4.0 and first["m3"] == 0.0581 and first["hours"] == 1.0
    assert first["t_fwd"] == 68.25 and first["t_ret"] == 29.50
    assert p.has_energy and p.has_volume and p.has_temps


@pytest.mark.asyncio
async def test_no_heat_endpoint_is_not_found() -> None:
    session = fx.FakeSession({
            f"dk/heating/api/v1/devices/{fx.HEAT_DEVICE}/consumption/recent": (404, {}),
            f"dk/heating/api/consumptions/{fx.HEAT_DEVICE}": (404, {}),
        })
    with pytest.raises(WattsOnNotFound):
        await WattsOnClient(session, fx.REFRESH_1).async_heat_consumptions(
            fx.HEAT_DEVICE, datetime(2026, 11, 1, tzinfo=timezone.utc)
        )


# ---------------------------------------------------------------- parsing
def test_parse_energy_volume_temps_and_quality() -> None:
    items = fx.heat_items(1)
    items[0]["mq"] = "Estimated"
    items[1]["en"] = -1  # "no data"
    items[2]["rt"] = 999  # implausible temperature
    p = parse_heat_items(items, unit_hint="kWh")
    assert p.skipped == {"not_measured": 1}
    assert len(p.intervals) == 23 and p.energy_unit == "kWh" and p.interval_hours == 1.0
    assert p.intervals[0]["kwh"] is None and p.intervals[1]["t_ret"] is None
    assert p.intervals[2]["kwh"] == 2.0 and p.intervals[2]["m3"] == 0.05
    assert p.has_energy and p.has_volume and p.has_temps and not p.assumptions
    assert {"sd", "en", "vol", "rt", "ft", "mq"} <= set(p.keys_seen)


def test_parse_units_mwh_gj_and_override() -> None:
    items = fx.heat_items(1, en=0.002)
    assert parse_heat_items(items, unit_hint="MWh").intervals[0]["kwh"] == 2.0
    assert round(parse_heat_items(fx.heat_items(1, en=0.0072), unit_hint="GJ").intervals[0]["kwh"], 2) == 2.0
    assert parse_heat_items(items, unit_hint="kWh", unit_override="MWh").intervals[0]["kwh"] == 2.0


def test_parse_unknown_unit_uses_heuristic_and_flags_assumption() -> None:
    p = parse_heat_items(fx.heat_items(1, en=0.002), unit_hint="")
    assert p.energy_unit == "MWh" and "energy_unit_assumed_mwh" in p.assumptions
    p = parse_heat_items(fx.heat_items(1), unit_hint=None)
    assert p.energy_unit == "kWh" and "energy_unit_assumed_kwh" in p.assumptions


def test_parse_vol_only_with_energy_unit_is_energy_else_volume() -> None:
    items = fx.heat_items(1, en=None, ft=None, rt=None, vol=1.5)
    p = parse_heat_items(items, unit_hint="kWh")
    assert p.has_energy and not p.has_volume and "vol_as_energy" in p.assumptions
    p = parse_heat_items(items, unit_hint="m3")
    assert not p.has_energy and p.has_volume and not p.has_temps


def test_parse_unknown_fields_only() -> None:
    items = [{"sd": "2026-11-01T00:00:00Z", "foo": 1, "bar": 2}]
    p = parse_heat_items(items, unit_hint="kWh")
    assert p.intervals == [] and p.skipped == {"no_data": 1} and "foo" in p.keys_seen


def test_parse_fjernvarme_fyn_gj_with_non_measured_mq_fallback() -> None:
    # Case 1: All valid rows use MQ="Calculated", plus one "Missing" and one En=-1 no-data row.
    fyn_items = [
        {
            "Id": fx.HEAT_DEVICE,
            "SD": "2026-11-03T00:00:00Z",
            "ED": "2026-11-03T01:00:00Z",
            "En": 0.018,
            "Vol": 0.25,
            "Fl": 0.25,
            "TI": 70.0,
            "TO": 31.0,
            "CD": 39.0,
            "MQ": "Calculated",
        },
        {
            "Id": fx.HEAT_DEVICE,
            "SD": "2026-11-03T01:00:00Z",
            "ED": "2026-11-03T02:00:00Z",
            "En": 0.018,
            "Vol": 0.25,
            "Fl": 0.25,
            "TI": 70.0,
            "TO": 31.0,
            "CD": 39.0,
            "MQ": "Missing",
        },
        {
            "Id": fx.HEAT_DEVICE,
            "SD": "2026-11-03T02:00:00Z",
            "ED": "2026-11-03T03:00:00Z",
            "En": -1,
            "Vol": -1,
            "TI": -1,
            "TO": -1,
            "MQ": "Calculated",
        },
    ]
    p = parse_heat_items(fyn_items, unit_hint="gj")
    assert len(p.intervals) == 1
    assert p.intervals[0]["kwh"] == pytest.approx(5.0)
    assert p.intervals[0]["m3"] == 0.25
    assert p.intervals[0]["t_fwd"] == 70.0 and p.intervals[0]["t_ret"] == 31.0
    assert "quality_fallback" in p.assumptions
    assert p.skipped == {"not_measured": 1, "no_data": 1}
    assert p.quality_seen == {"Calculated": 2, "Missing": 1}

    # Case 2: Empty MQ="" is accepted directly without triggering quality_fallback.
    empty_mq = [dict(fyn_items[0], MQ="")]
    p_empty = parse_heat_items(empty_mq, unit_hint="gj")
    assert len(p_empty.intervals) == 1
    assert "quality_fallback" not in p_empty.assumptions
    assert p_empty.quality_seen == {"(empty)": 1}

    # Case 3: Mixed "Measured" and "Estimated" keeps only "Measured".
    mixed = [dict(fyn_items[0], MQ="Measured"), dict(fyn_items[0], SD="2026-11-03T01:00:00Z", MQ="Estimated")]
    p_mixed = parse_heat_items(mixed, unit_hint="gj")
    assert len(p_mixed.intervals) == 1
    assert "quality_fallback" not in p_mixed.assumptions
    assert p_mixed.skipped == {"not_measured": 1}
    assert p_mixed.quality_seen == {"Estimated": 1, "Measured": 1}


@pytest.mark.asyncio
async def test_diagnostics_include_quality_seen_without_pii() -> None:
    from kmd_easy_energy.diagnostics import async_get_config_entry_diagnostics

    fyn_items = [
        {
            "Id": fx.HEAT_DEVICE,
            "SD": "2026-11-03T00:00:00Z",
            "ED": "2026-11-03T01:00:00Z",
            "En": 0.018,
            "Vol": 0.25,
            "TI": 70.0,
            "TO": 31.0,
            "MQ": "Calculated",
        }
    ]
    state = _mapped(fyn_items, unit="gj")
    entry = SimpleNamespace(
        entry_id="e1",
        title="Fjernvarme Fyn",
        unique_id="wattson:x",
        domain="kmd_easy_energy",
        version=1,
        data=dict(W_ENTRY, wattson_device_id=fx.HEAT_DEVICE),
        options={},
    )
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {"e1": SimpleNamespace(data=state)}}
    out = await async_get_config_entry_diagnostics(hass, entry)
    w = out["coordinator"]["wattson"]
    assert w["quality_seen"] == {"Calculated": 1}
    assert "quality_fallback" in w["assumptions"]
    assert fx.HEAT_DEVICE not in json.dumps(out, default=str)


# ---------------------------------------------------------------- mapping
def _mapped(items=None, unit="kWh", state=None):
    parsed = parse_heat_items(items if items is not None else fx.heat_items(3), unit_hint=unit)
    with patch("kmd_easy_energy.wattson_mapping.datetime") as dt_mock:
        dt_mock.now.return_value = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
        dt_mock.fromisoformat = datetime.fromisoformat
        dt_mock.side_effect = lambda *a, **k: datetime(*a, **k)
        return apply_wattson_data(state if state is not None else {}, parsed, TODAY, {"endpoint": "x"})


def test_mapping_hourly_daily_temps_and_detection() -> None:
    s = _mapped()
    # 3 complete local days (3, 4, 5 Nov), 24 h × 2 kWh each
    assert s["daily_kwh_history"] == {"2026-11-03": 48.0, "2026-11-04": 48.0, "2026-11-05": 48.0}
    assert s["daily"]["total"] == 144 and s["daily_m3"]["total"] == pytest.approx(3.6)
    assert s["monthly"]["2026"]["Nov"] == 144
    assert len(s["hourly_kwh"]) == 72 and s["daily_stat_kwh"] == []
    assert s["hourly"]["kwh"] == [2.0] * 24 and s["hourly"]["days_averaged"] == 3
    # Return temperature per local hour for the card's "Retur °C" line
    # (fixture: 30 °C on odd UTC hours = even CET hours, else 34 °C).
    assert s["hourly"]["ret_temp"] == [30.0 if h % 2 == 0 else 34.0 for h in range(24)]
    assert s["data_granularity"] == "hourly" and s["has_direct_temp"] is True
    assert s["return_temp"]["monthly_2026"]["Nov"] == 32.0
    assert s["latest_reading"]["temp_return"] == 32.0
    assert s["wattson"]["detected"] == ["daily", "hourly", "monthly", "temperatures", "volume"]
    assert [u["Name"] for u in s["available_units"]] == ["kWh", "m3", "°C"]
    assert s["wattson"]["endpoint"] == "x" and s["wattson"]["energy_unit"] == "kWh"
    caps = effective_capabilities("wattson", s, reminder_enabled=False, auto_sync_enabled=True)
    assert {"hourly", "daily", "monthly", "temperatures", "volume", "auto_sync"} <= set(caps)
    assert not set(caps) & {"mitid", "billing", "forecast", "reminder"}


def test_mapping_only_energy_known_hides_temps_and_volume() -> None:
    s = _mapped(fx.heat_items(3, vol=None, ft=None, rt=None))
    assert s["wattson"]["detected"] == ["daily", "hourly", "monthly"]
    assert [u["Name"] for u in s["available_units"]] == ["kWh"]
    caps = effective_capabilities("wattson", s)
    assert "temperatures" not in caps and "volume" not in caps and "hourly" in caps
    assert s["hourly_temp"] == [] and s["has_direct_temp"] is False
    assert "ret_temp" not in s["hourly"]


def test_mapping_incomplete_day_and_today_excluded_and_merge_is_idempotent() -> None:
    items = fx.heat_items(3)[5:]  # first local day incomplete
    s = _mapped(items)
    assert "2026-11-03" not in s["daily_kwh_history"]
    again = _mapped(items, state=s)
    assert again["daily_kwh_history"] == s["daily_kwh_history"]
    assert len(again["hourly_kwh"]) == len(s["hourly_kwh"])


def test_mapping_daily_interval_data_has_no_hourly() -> None:
    items = [
        {"sd": f"2026-11-0{d}T23:00:00Z", "ed": f"2026-11-0{d + 1}T23:00:00Z", "en": 40.0, "mq": "Measured"}
        for d in (2, 3, 4)
    ]
    s = _mapped(items)
    assert s["daily_kwh_history"]["2026-11-04"] == 40.0
    assert s["hourly_kwh"] == [] and s["hourly"] == {} and s["data_granularity"] == "daily"
    assert "hourly" not in s["wattson"]["detected"]
    assert s["daily_stat_kwh"]  # Energy statistics from daily rows


def test_statistics_import_uses_hourly_rows() -> None:
    from kmd_easy_energy.statistics import import_hourly_statistics

    s = _mapped(fx.heat_items(1, end=datetime(2026, 11, 5, 23, tzinfo=timezone.utc)))
    hass = MagicMock()
    hass.config.components = {"recorder"}
    entry = SimpleNamespace(entry_id="e1", title="Aalborg Forsyning")
    with patch("homeassistant.components.recorder.statistics.async_add_external_statistics") as add:
        res = import_hourly_statistics(hass, entry, s)
    assert res == {"energy": 24, "volume": 24, "cost": 0}
    rows = list(add.call_args_list[0].args[2])
    assert rows[-1]["sum"] == 48.0


def test_entity_capabilities_wait_for_detection() -> None:
    before = entity_capabilities("wattson", None)
    assert {"daily", "monthly", "cost", "auto_sync"} <= before
    assert not before & {"hourly", "temperatures", "volume", "mitid", "billing"}
    after = entity_capabilities("wattson", ["daily", "hourly", "monthly", "volume"])
    assert "volume" in after and "hourly" in after and "temperatures" not in after
    assert entity_capabilities("kmd", None) == entity_capabilities("kmd", [])  # static backends


# ---------------------------------------------------------------- coordinator
from test_coordinator import FakeStore, make_coordinator  # noqa: E402

W_ENTRY = {
    "backend": "wattson",
    "utility": "Aalborg Forsyning",
    "utility_id": "aalborg-forsyning",
    "portal_url": "https://aalborgforsyning.dk/services/forbrug/watts-on/",
    "wattson_refresh_token": fx.REFRESH_1,
    "wattson_user_id": fx.USER_ID,
}


def _w_coord(tmp_path, store=None, **extra):
    coord, hass, entry, store = make_coordinator(tmp_path, store=store, **{**W_ENTRY, **extra})
    coord.backend = "wattson"
    coord.async_set_updated_data = MagicMock()
    coord._async_update_weather = AsyncMock()

    def update_entry(e, data=None, **kw):
        if data is not None:
            e.data = data

    hass.config_entries.async_update_entry = MagicMock(side_effect=update_entry)
    return coord, hass, entry, store


@pytest.mark.asyncio
async def test_wattson_sync_rotates_token_detects_device_and_saves(tmp_path: Path) -> None:
    coord, hass, entry, store = _w_coord(tmp_path, FakeStore({}))
    session = fx.FakeSession()
    with patch("kmd_easy_energy.coordinator.async_get_clientsession", return_value=session), patch(
        "kmd_easy_energy.coordinator.copenhagen_today", return_value=TODAY
    ):
        await coord.async_sync_wattson()
    # Rotated refresh token persisted in the config entry; device remembered.
    assert entry.data["wattson_refresh_token"] == fx.REFRESH_2
    assert entry.data["wattson_refresh_expires_at"]
    assert entry.data["wattson_device_id"] == fx.HEAT_DEVICE
    saved = store.data
    assert saved["daily_kwh_history"] and saved["last_sync"]
    assert saved["backend"] == "wattson" and saved["data_source"] == "Watts On"
    assert saved["wattson"]["endpoint"] == HEAT_ENDPOINT_CANDIDATES[0]
    dumped = json.dumps(saved, default=str)
    for secret in (fx.REFRESH_1, fx.REFRESH_2, fx.ACCESS, "Testvej", "12345678"):
        assert secret not in dumped
    # First sync asked from 1 January.
    heat_call = [c for c in session.calls if "consumption" in c["url"]][0]
    assert heat_call["params"]["newerThan"].startswith(f"{datetime.now().year - 1}-12-31T") or heat_call[
        "params"
    ]["newerThan"].startswith(f"{datetime.now().year}-01-01T")
    # New capabilities detected -> one reload so the entities get created.
    hass.config_entries.async_schedule_reload.assert_called_once_with("entry-1")
    coord.data = saved  # what async_set_updated_data does
    assert {"temperatures", "volume", "hourly"} <= set(coord.backend_capabilities)


@pytest.mark.asyncio
async def test_wattson_second_sync_is_incremental_and_skips_discovery(tmp_path: Path) -> None:
    first = _mapped()
    first["wattson"]["device"] = {"kind": "heat", "type": "DistrictHeating", "unit": "kWh"}
    first["wattson"]["endpoint"] = HEAT_ENDPOINT_CANDIDATES[0]
    coord, hass, entry, store = _w_coord(tmp_path, FakeStore(first), wattson_device_id=fx.HEAT_DEVICE)
    session = fx.FakeSession()
    with patch("kmd_easy_energy.coordinator.async_get_clientsession", return_value=session), patch(
        "kmd_easy_energy.coordinator.copenhagen_today", return_value=TODAY
    ):
        await coord.async_sync_wattson()
    urls = [c["url"] for c in session.calls]
    assert not any("locations" in u or "users/api" in u for u in urls)  # no rediscovery
    heat = [c for c in session.calls if "consumption" in c["url"]]
    assert len(heat) == 1  # known endpoint, no probing
    assert heat[0]["params"]["newerThan"] < "2026-11-04"  # two days before newest stored hour
    assert store.data["wattson"]["requests_last_sync"] == 2  # token + one data call
    hass.config_entries.async_schedule_reload.assert_not_called()


@pytest.mark.asyncio
async def test_wattson_auth_error_keeps_cache_and_starts_no_reauth(tmp_path: Path) -> None:
    from kmd_easy_energy.coordinator import KMDLoginError

    coord, hass, entry, store = _w_coord(tmp_path, FakeStore({"annual": {"2026": 7}}))
    session = fx.FakeSession({"oauth2/v2.0/token": (400, {})})
    with patch("kmd_easy_energy.coordinator.async_get_clientsession", return_value=session):
        with pytest.raises(KMDLoginError) as err:
            await coord.async_sync_wattson()
    assert "Genkonfigurer" in str(err.value)
    assert store.saved == [] and coord.last_sync is None
    entry.async_start_reauth.assert_not_called()


@pytest.mark.asyncio
async def test_wattson_no_heat_meter_and_missing_endpoint_are_friendly(tmp_path: Path) -> None:
    coord, _, _, store = _w_coord(tmp_path, FakeStore({}))
    detail = {"devices": [{"deviceId": "w", "utilityType": "Water"}]}
    with patch(
        "kmd_easy_energy.coordinator.async_get_clientsession",
        return_value=fx.FakeSession({"/locations/loc-1": detail}),
    ):
        with pytest.raises(RuntimeError, match="Ingen varmemåler"):
            await coord.async_sync_wattson()
    coord2, _, _, _ = _w_coord(tmp_path, FakeStore({}))
    with patch(
        "kmd_easy_energy.coordinator.async_get_clientsession",
        return_value=fx.FakeSession({
            f"dk/heating/api/v1/devices/{fx.HEAT_DEVICE}/consumption/recent": (404, {}),
            f"dk/heating/api/consumptions/{fx.HEAT_DEVICE}": (404, {}),
        }),
    ):
        with pytest.raises(RuntimeError, match="README"):
            await coord2.async_sync_wattson()
    assert store.saved == []


def test_wattson_defaults_and_mitid_flags(tmp_path: Path) -> None:
    coord, _, _, _ = _w_coord(tmp_path)
    assert coord.uses_mitid is False and coord.auto_sync_enabled is True
    assert coord.sync_reminder_enabled is False and coord.data_source == "Watts On"
    kmd, _, _, _ = make_coordinator(tmp_path)
    assert kmd.uses_mitid is True


@pytest.mark.asyncio
async def test_start_sync_runs_wattson_not_mitid(tmp_path: Path) -> None:
    coord, hass, _, _ = _w_coord(tmp_path)
    coord.async_sync_wattson = AsyncMock()
    coord._push_sync_ui = MagicMock()
    await coord._async_run_backend_sync()
    coord.async_sync_wattson.assert_awaited_once()
    assert coord._push_sync_ui.call_args_list[0].args == ("fetching_data", "Henter data fra Watts On…")
    with patch("kmd_easy_energy.coordinator.KMDMitIDAuthenticator") as mitid:
        await coord.async_start_mitid_sync()
    mitid.assert_not_called()
    hass.async_create_task.call_args.args[0].close()


def test_sensors_follow_detected_capabilities(tmp_path: Path) -> None:
    from kmd_easy_energy.sensor import sensors_for

    coord, _, entry, _ = _w_coord(tmp_path)
    names = {type(s).__name__ for s in sensors_for(coord, entry)}
    assert "KMDVolumeSensor" not in names and "KMDReturnTempSensor" not in names
    assert "KMDBalanceSensor" not in names and "KMDEnergySensor" in names
    coord.data = {"wattson": {"detected": ["daily", "monthly", "volume", "temperatures"]}}
    names = {type(s).__name__ for s in sensors_for(coord, entry)}
    assert {"KMDVolumeSensor", "KMDReturnTempSensor"} <= names and "KMDBalanceSensor" not in names


# ---------------------------------------------------------------- config flow
AAL = {
    "id": "aalborg-forsyning",
    "name": "Aalborg Forsyning",
    "city": "Aalborg",
    "portal_url": "https://aalborgforsyning.dk/services/forbrug/watts-on/",
    "status": "confirmed",
    "backend": "wattson",
    "latitude": 57.048,
    "longitude": 9.921,
}


def _flow(utility: dict | None = None):
    from kmd_easy_energy.config_flow import KMDEasyEnergyConfigFlow

    flow = KMDEasyEnergyConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": "user"}
    flow._selected_utility = dict(utility or AAL)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(side_effect=lambda **kw: {"type": "create_entry", **kw})
    flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})
    flow.async_update_reload_and_abort = MagicMock(side_effect=lambda e, **kw: {"type": "abort", **kw})
    return flow


@pytest.mark.asyncio
async def test_flow_wattson_shows_login_link_and_no_password_field() -> None:
    flow = _flow()
    form = await flow.async_step_wattson()
    fields = [str(k) for k in form["data_schema"].schema]
    assert fields == ["wattson_redirect_url", "wattson_refresh_token"]
    assert not any("password" in f or "mitid" in f for f in fields)
    url = form["description_placeholders"]["auth_url"]
    assert url.startswith("https://wattsenergyassistant.b2clogin.com/") and "code_challenge=" in url
    # Same link while the user is still on the page.
    assert (await flow.async_step_wattson())["description_placeholders"]["auth_url"] == url


@pytest.mark.asyncio
async def test_flow_wattson_pasted_redirect_creates_entry() -> None:
    flow = _flow()
    form = await flow.async_step_wattson()
    state = parse_qs(urlparse(form["description_placeholders"]["auth_url"]).query)["state"][0]
    session = fx.FakeSession({"oauth2/v2.0/token": fx.token_body(fx.REFRESH_1)})
    with patch("kmd_easy_energy.config_flow.async_get_clientsession", return_value=session):
        res = await flow.async_step_wattson(
            {"wattson_redirect_url": f"msauth://com.seasnve.watts/x?code=c0de&state={state}"}
        )
    assert res["type"] == "create_entry"
    data = res["data"]
    assert data["backend"] == "wattson" and data["wattson_refresh_token"] == fx.REFRESH_1
    assert data["wattson_device_id"] == fx.HEAT_DEVICE and data["wattson_user_id"] == fx.USER_ID
    assert data["wattson_refresh_expires_at"]
    assert not any("password" in k or "mitid" in k for k in data)
    assert res["options"] == {"auto_sync": True, "auto_sync_hour": 6, "sync_reminder": False, "wattson_energy_unit": "auto"}
    uid = flow.async_set_unique_id.await_args.args[0]
    assert uid.startswith("wattson:") and fx.USER_ID not in uid
    exchange = [c for c in session.calls if c["method"] == "POST"][0]["data"]
    assert exchange["code"] == "c0de" and exchange["grant_type"] == "authorization_code"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_input", "routes", "error"),
    [
        ({}, {}, "wattson_missing"),
        ({"wattson_redirect_url": "msauth://x?state=zzz"}, {}, "wattson_no_code"),
        ({"wattson_redirect_url": "msauth://x?code=a&state=WRONG"}, {}, "wattson_state_mismatch"),
        ({"wattson_redirect_url": "msauth://x?error=access_denied"}, {}, "wattson_login_cancelled"),
        ({"wattson_redirect_url": "msauth://x?code=a"}, {"oauth2/v2.0/token": (400, {})}, "wattson_code_rejected"),
        ({"wattson_refresh_token": "bad"}, {"oauth2/v2.0/token": (400, {})}, "wattson_token_rejected"),
        ({"wattson_refresh_token": "t"}, {"users/api/v3/User": (500, {})}, "wattson_cannot_connect"),
        (
            {"wattson_refresh_token": "t"},
            {"/locations/loc-1": {"devices": [{"deviceId": "w", "utilityType": "Water"}]}},
            "wattson_no_heat_meter",
        ),
    ],
)
async def test_flow_wattson_errors(user_input, routes, error) -> None:
    flow = _flow()
    await flow.async_step_wattson()
    with patch("kmd_easy_energy.config_flow.async_get_clientsession", return_value=fx.FakeSession(routes)):
        res = await flow.async_step_wattson(user_input)
    assert res["type"] == "form" and res["errors"]["base"] == error


@pytest.mark.asyncio
async def test_flow_wattson_new_link_after_failed_code_exchange() -> None:
    flow = _flow()
    first = (await flow.async_step_wattson())["description_placeholders"]["auth_url"]
    with patch(
        "kmd_easy_energy.config_flow.async_get_clientsession",
        return_value=fx.FakeSession({"oauth2/v2.0/token": (400, {})}),
    ):
        res = await flow.async_step_wattson({"wattson_redirect_url": "msauth://x?code=a"})
    assert res["description_placeholders"]["auth_url"] != first


@pytest.mark.asyncio
async def test_flow_wattson_unrecognised_devices_offer_picker() -> None:
    flow = _flow()
    await flow.async_step_wattson()
    detail = {
        "devices": [
            {"deviceId": "d1", "utilityType": "Unknown1", "unit": "MWh"},
            {"deviceId": "d2", "utilityType": "Water"},
        ]
    }
    with patch(
        "kmd_easy_energy.config_flow.async_get_clientsession",
        return_value=fx.FakeSession({"/locations/loc-1": detail}),
    ):
        res = await flow.async_step_wattson({"wattson_refresh_token": "t"})
    assert res["step_id"] == "wattson_device"
    opts = res["data_schema"].schema["wattson_device_id"].config["options"]
    assert [o["value"] for o in opts] == ["d1"]
    res = await flow.async_step_wattson_device({"wattson_device_id": "d1"})
    assert res["data"]["wattson_device_id"] == "d1"


@pytest.mark.asyncio
async def test_reconfigure_wattson_updates_token_and_rejects_other_account() -> None:
    from kmd_easy_energy.config_flow import wattson_unique_id

    flow = _flow()
    entry = SimpleNamespace(data=dict(W_ENTRY), title="Aalborg Forsyning", unique_id=wattson_unique_id(fx.USER_ID))
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    with patch("kmd_easy_energy.config_flow.async_get_clientsession", return_value=fx.FakeSession()):
        res = await flow.async_step_reconfigure_wattson({"wattson_refresh_token": "t"})
    assert res["type"] == "abort" and res["data_updates"]["wattson_refresh_token"] == fx.REFRESH_2
    entry.unique_id = wattson_unique_id("someone-else")
    with patch("kmd_easy_energy.config_flow.async_get_clientsession", return_value=fx.FakeSession()):
        res = await flow.async_step_reconfigure_wattson({"wattson_refresh_token": "t"})
    assert res["errors"]["base"] == "wattson_wrong_account"


# ---------------------------------------------------------------- docs / privacy
def test_utilities_json_wattson_entries_and_status() -> None:
    from kmd_easy_energy.config_flow import _format_utility_label

    data = json.loads((ROOT / "custom_components/kmd_easy_energy/utilities.json").read_text())
    by_id = {u["id"]: u for u in data["utilities"]}
    wattson_ids = {
        "aalborg-forsyning",
        "forsyning-helsingor",
        "fjernvarme-fyn",
        "hillerod-forsyning",
    }
    required = (
        "id",
        "name",
        "city",
        "portal_url",
        "status",
        "tier",
        "auth_method",
        "backend",
        "latitude",
        "longitude",
        "notes",
    )
    for uid in wattson_ids:
        u = by_id[uid]
        assert set(required) <= set(u)
        assert u["backend"] == "wattson"
        assert isinstance(u["latitude"], (int, float)) and isinstance(u["longitude"], (int, float))
        assert u["portal_url"].startswith("https://")
        assert "Watts On" in u["auth_method"]
    for uid in ("aalborg-forsyning", "fjernvarme-fyn", "hillerod-forsyning"):
        u = by_id[uid]
        assert u["status"] == "confirmed"
        assert u["tier"] == "confirmed"
        label = _format_utility_label(u)
        assert label.startswith("✅") and "Watts On" in label and "bekræftet" in label
    for uid in wattson_ids - {"aalborg-forsyning", "fjernvarme-fyn", "hillerod-forsyning"}:
        u = by_id[uid]
        assert u["status"] == "pending_test"
        assert u["tier"] == "verified_portal"
        label = _format_utility_label(u)
        assert label.startswith("🧪") and "Watts On" in label and "afventer" in label
    names = " ".join(u["name"].lower() for u in data["utilities"])
    ids = " ".join(by_id)
    assert "novafos" not in names and "novafos" not in ids
    assert "hornbæk" not in names and "hornbaek" not in ids




def test_translations_cover_wattson() -> None:
    for rel in ("strings.json", "translations/en.json", "translations/da.json"):
        data = json.loads((ROOT / "custom_components/kmd_easy_energy" / rel).read_text())
        steps = data["config"]["step"]
        for step in ("wattson", "wattson_device", "reconfigure_wattson"):
            assert step in steps
        assert "{auth_url}" in steps["wattson"]["description"]
        assert {"wattson_redirect_url", "wattson_refresh_token"} <= set(steps["wattson"]["data"])
        errs = set(data["config"]["error"])
        assert {"wattson_no_code", "wattson_code_rejected", "wattson_no_heat_meter", "wattson_wrong_account"} <= errs
        assert {"wattson_energy_unit", "wattson_endpoint"} <= set(data["options"]["step"]["init"]["data"])
        for text in json.dumps(data["options"]).split('"'):
            assert "{device_id}" not in text  # braces would be HA placeholders
    da = json.loads((ROOT / "custom_components/kmd_easy_energy/translations/da.json").read_text())
    assert "Eksperimentel" in da["config"]["step"]["wattson"]["description"]
    assert "{status_badge}" in da["config"]["step"]["wattson"]["description"]
    assert "{status_badge}" in da["config"]["step"]["reconfigure_wattson"]["description"]
    assert "Aalborg Forsyning" in da["config"]["step"]["wattson"]["description"]
    assert "msauth://" in da["config"]["step"]["wattson"]["description"]
    assert "Aalborg Forsyning-varmemåler" not in da["config"]["error"]["wattson_no_heat_meter"]


@pytest.mark.asyncio
async def test_diagnostics_redact_watts_token_and_ids() -> None:
    from kmd_easy_energy.diagnostics import async_get_config_entry_diagnostics

    entry = SimpleNamespace(
        entry_id="e1", title="Aalborg", unique_id="wattson:x", domain="kmd_easy_energy",
        version=1, data=dict(W_ENTRY, wattson_device_id=fx.HEAT_DEVICE), options={},
    )
    coord = SimpleNamespace(data=_mapped())
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {"e1": coord}}
    out = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(out, default=str)
    for secret in (fx.REFRESH_1, fx.USER_ID, fx.HEAT_DEVICE):
        assert secret not in dumped
    w = out["coordinator"]["wattson"]
    assert w["endpoint"] == "x" and "en" in w["keys_seen"] and w["energy_unit"] == "kWh"


def test_notice_license_and_header() -> None:
    notice = (ROOT / "NOTICE").read_text()
    assert "TheRealBatBro/Home-Assistant-Novafos-V2" in notice
    assert "Copyright (c) 2026 TheRealBatBro" in notice and "Permission is hereby granted" in notice
    lic = (ROOT / "custom_components/kmd_easy_energy/api/LICENSE-novafos-v2-MIT.txt").read_text()
    assert "Copyright (c) 2026 TheRealBatBro" in lic and "MIT License" in lic
    header = (ROOT / "custom_components/kmd_easy_energy/api/wattson_client.py").read_text()[:2500]
    assert "TheRealBatBro/Home-Assistant-Novafos-V2" in header and "MIT" in header
    assert "Changes were made" in header


def test_no_token_logging_in_wattson_code() -> None:
    for rel in ("api/wattson_client.py", "wattson_mapping.py"):
        text = (ROOT / "custom_components/kmd_easy_energy" / rel).read_text()
        assert "_LOGGER" not in text and "print(" not in text
