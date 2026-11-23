"""E|Forsyning backend: client protocol, parsing, mapping, coordinator, flow.

No network: every response comes from tests/fixtures_eforsyning.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import fixtures_eforsyning as fx
from kmd_easy_energy.api.eforsyning_client import (
    EforsyningClient,
    EforsyningError,
    EforsyningLoginError,
    access_token_for,
    parse_number,
    parse_readings,
    response_has_lines,
)
from kmd_easy_energy.eforsyning_mapping import apply_eforsyning_data

ROOT = Path(__file__).resolve().parents[1]
ACCESS = hashlib.md5(
    (hashlib.md5(fx.PASSWORD.encode()).hexdigest() + fx.SERVER_TOKEN).encode()
).hexdigest()


def _client(session: fx.FakeSession, installation_id: str | None = None) -> EforsyningClient:
    return EforsyningClient(session, fx.USERNAME, fx.PASSWORD, fx.SUPPLIER_ID, installation_id)


# --------------------------------------------------------------------- client
def test_access_token_is_md5_of_md5_password_plus_server_token() -> None:
    assert access_token_for(fx.PASSWORD, fx.SERVER_TOKEN) == ACCESS
    assert len(ACCESS) == 32


@pytest.mark.asyncio
async def test_login_sequence_and_password_never_on_the_wire() -> None:
    session = fx.FakeSession()
    client = _client(session)
    await client.async_login()
    urls = [c["url"] for c in session.calls]
    assert urls[0] == f"https://eforsyning.dk/umbraco/dff/dffapi/GetVaerkSettings?forsyningid={fx.SUPPLIER_ID}"
    assert urls[1] == f"{fx.APP_SERVER}system/getsecuritytoken/project/app/consumer/{fx.USERNAME}"
    assert urls[2] == f"{fx.APP_SERVER}system/login/project/app/consumer/{fx.USERNAME}/installation/1/id/{ACCESS}"
    assert all(fx.PASSWORD not in json.dumps(c, default=str) for c in session.calls)
    assert all(c["headers"]["Accept"] == "application/json" for c in session.calls)
    assert all(len(c["headers"]["X-Session-ID"]) == 8 for c in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "routes",
    [
        {"getsecuritytoken": {"Token": ""}},
        {"system/login": fx.LOGIN_FAIL},
        {"getsecuritytoken": (401, {})},
    ],
)
async def test_rejected_login_is_login_error(routes) -> None:
    with pytest.raises(EforsyningLoginError):
        await _client(fx.FakeSession(routes)).async_login()


@pytest.mark.asyncio
async def test_unknown_supplier_and_http_errors_are_plain_errors() -> None:
    with pytest.raises(EforsyningError) as err:
        await _client(fx.FakeSession({"GetVaerkSettings": {"AppServerUri": None}})).async_login()
    assert not isinstance(err.value, EforsyningLoginError)
    with pytest.raises(EforsyningError) as err:
        await _client(fx.FakeSession({"GetVaerkSettings": (500, {})})).async_login()
    assert not isinstance(err.value, EforsyningLoginError)


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_any_request() -> None:
    session = fx.FakeSession()
    with pytest.raises(EforsyningLoginError):
        await EforsyningClient(session, "", "", fx.SUPPLIER_ID).async_login()
    assert session.calls == []


@pytest.mark.asyncio
async def test_post_bodies_are_json_without_content_type() -> None:
    session = fx.FakeSession()
    client = _client(session)
    await client.async_login()
    await client.async_get_installations()
    await client.async_get_daily(2026)
    posts = [c for c in session.calls if c["method"] == "POST"]
    assert posts and all("Content-Type" in c["skip_auto_headers"] for c in posts)
    body = json.loads(posts[-1]["data"])
    assert body["Aflaesningsfilter"] == "afDagsvis"
    assert body["AarsMaerke"] == 2026
    assert body["Ejendomnr"] == fx.USERNAME
    assert "&anr=1&inr=1" in posts[-1]["url"]


@pytest.mark.asyncio
async def test_installation_selection_prefers_configured_number() -> None:
    two = {"Installationer": [dict(fx.INSTALLATIONS["Installationer"][0]), dict(fx.INSTALLATIONS["Installationer"][0], InstallationNr=2, AktivNr=7)]}
    client = _client(fx.FakeSession({"FindInstallationer": two}), installation_id="2")
    await client.async_login()
    await client.async_get_installations()
    assert client.installation["InstallationNr"] == 2
    assert client.moved_in == date(2019, 6, 1)


@pytest.mark.asyncio
async def test_no_installations_is_an_error() -> None:
    client = _client(fx.FakeSession({"FindInstallationer": {"Installationer": []}}))
    await client.async_login()
    with pytest.raises(EforsyningError):
        await client.async_get_installations()


@pytest.mark.asyncio
async def test_fetch_tries_new_year_in_january_and_skips_empty_years() -> None:
    def forbrug(method, url, kwargs):
        year = json.loads(kwargs["data"])["AarsMaerke"]
        return fx.daily_response() if year == 2026 else fx.NO_DATA_ERROR

    session = fx.FakeSession({"getforbrug": forbrug})
    out = await _client(session).async_fetch(date(2027, 1, 5), years_back=0)
    years = [json.loads(c["data"])["AarsMaerke"] for c in session.calls if "getforbrug" in c["url"]]
    assert years == [2026, 2027]
    assert out["years"] == [2026]
    assert len(out["readings"]) == 3
    assert "Adresse" not in json.dumps(out, ensure_ascii=False)  # no address / meter no. leaks
    assert fx.USERNAME not in json.dumps(out)


@pytest.mark.asyncio
async def test_fetch_first_sync_includes_previous_billing_year() -> None:
    session = fx.FakeSession()
    await _client(session).async_fetch(date(2026, 11, 5), years_back=1)
    years = [json.loads(c["data"])["AarsMaerke"] for c in session.calls if "getforbrug" in c["url"]]
    assert years == [2025, 2026]


@pytest.mark.asyncio
async def test_discard_credentials() -> None:
    client = _client(fx.FakeSession())
    await client.async_login()
    client.discard_credentials()
    assert client._access == "" and client._password == ""


# -------------------------------------------------------------------- parsing
def test_parse_number_danish_format_and_unknowns() -> None:
    assert parse_number("1.234,56") == 1234.56
    assert parse_number("0,025") == 0.025
    assert parse_number("") is None
    assert parse_number(None) is None
    assert parse_number("abc") is None
    assert parse_number("312", filter_above=150) is None  # missing decimal comma
    assert parse_number(31.2) == 31.2


def test_parse_readings_units_and_temps() -> None:
    rows = parse_readings(fx.daily_response())
    assert [r["date"] for r in rows] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    first = rows[0]
    assert first["kwh"] == 25.0  # 0,025 MWh
    assert first["m3"] == 0.6
    assert first["temp_forward"] == 70.5
    assert first["temp_return"] == 31.2
    assert first["temp_expected_return"] == 37.0
    assert first["days"] == 1


def test_parse_readings_gj_kwh_unknown_unit_and_bad_temp() -> None:
    gj = fx._line("01-11-2026", "02-11-2026", "0,36", "1,0", "70", "312", unit="GJ")
    kwh = fx._line("02-11-2026", "03-11-2026", "25", "1,0", "70", "30", unit="kWh")
    odd = fx._line("03-11-2026", "04-11-2026", "25", "1,0", "", "", unit="Mcal")
    rows = parse_readings(fx.daily_response([gj, kwh, odd]))
    assert rows[0]["kwh"] == 100.0
    assert rows[0]["temp_return"] is None  # 312 °C -> unknown, not wrong
    assert rows[1]["kwh"] == 25.0
    assert rows[2]["kwh"] is None and rows[2]["temp_forward"] is None


def test_response_has_lines() -> None:
    assert response_has_lines(fx.daily_response())
    assert not response_has_lines(fx.NO_DATA_ERROR)
    assert not response_has_lines(fx.NO_LINES)
    assert not response_has_lines(None)


# -------------------------------------------------------------------- mapping
def _readings(**overrides):
    rows = parse_readings(fx.daily_response())
    return {"readings": rows, "years": [2026], "year_marker": fx.YEAR_MARKER, "installation": {}, **overrides}


def test_mapping_fills_daily_monthly_temps_and_daily_statistics() -> None:
    state = apply_eforsyning_data({}, _readings(), date(2026, 11, 5))
    assert state["daily"]["days"] == {"1": 25, "2": 30, "3": 20}
    assert state["daily"]["total"] == 75
    assert state["daily"]["latest_date"] == "2026-11-03"
    assert state["monthly"]["2026"]["Nov"] == 75
    assert state["daily_m3"]["total"] == 1.8
    # m³-weighted return temperature: (31.2*0.6 + 30*0.8 + 33*0.4) / 1.8
    assert state["return_temp"]["monthly_2026"]["Nov"] == round((31.2 * 0.6 + 30 * 0.8 + 33 * 0.4) / 1.8, 1)
    assert state["latest_reading"]["temp_return"] == 33.0
    assert [p["DateFrom"] for p in state["daily_stat_kwh"]][0] == "2026-11-01T00:00:00+01:00"
    assert all(p["IsComplete"] for p in state["daily_stat_kwh"])
    assert state["hourly"] == {} and "hourly_kwh" not in state
    assert state["data_granularity"] == "daily"


def test_mapping_annual_only_when_year_is_covered() -> None:
    state = apply_eforsyning_data({}, _readings(), date(2026, 11, 5))
    assert state["annual"] == {}  # history starts in November -> no (wrong) year total
    state["daily_kwh_history"]["2026-01-02"] = 50.0
    state = apply_eforsyning_data(state, _readings(), date(2026, 11, 5))
    assert state["annual"]["2026"] == 125


def test_mapping_merges_history_excludes_today_and_spreads_gaps() -> None:
    gap = fx._line("05-11-2026", "08-11-2026", "0,030", "0,9", "70", "30")
    today = fx._line("08-11-2026", "09-11-2026", "0,010", "0,1", "70", "30")
    state = {"daily_kwh_history": {"2026-10-31": 40.0}}
    state = apply_eforsyning_data(state, {"readings": parse_readings(fx.daily_response([gap, today]))}, date(2026, 11, 8))
    hist = state["daily_kwh_history"]
    assert hist["2026-10-31"] == 40.0  # kept from earlier syncs
    assert hist["2026-11-05"] == hist["2026-11-06"] == hist["2026-11-07"] == 10.0
    assert "2026-11-08" not in hist  # today's partial reading is not used


def test_mapping_is_idempotent_for_repeated_syncs() -> None:
    a = apply_eforsyning_data({}, _readings(), date(2026, 11, 5))
    b = apply_eforsyning_data(json.loads(json.dumps(a)), _readings(), date(2026, 11, 5))
    assert a["daily_stat_kwh"] == b["daily_stat_kwh"]
    assert a["daily_kwh_history"] == b["daily_kwh_history"]


def test_statistics_import_uses_daily_rows_without_hourly() -> None:
    from kmd_easy_energy.statistics import import_hourly_statistics

    hass = MagicMock()
    hass.config.components = {"recorder"}
    state = apply_eforsyning_data({}, _readings(), date(2026, 11, 5))
    with patch("homeassistant.components.recorder.statistics.async_add_external_statistics") as add:
        res = import_hourly_statistics(hass, SimpleNamespace(entry_id="e1", title="Hjørring"), state)
    assert res == {"energy": 3, "volume": 3}
    rows = list(add.call_args_list[0].args[2])
    assert [r["sum"] for r in rows] == [25.0, 55.0, 75.0]
    assert rows[0]["start"].hour == 0


# ---------------------------------------------------------------- coordinator
from test_coordinator import FakeStore, make_coordinator  # noqa: E402

EF_ENTRY = {
    "backend": "eforsyning",
    "utility": "Hjørring Varmeforsyning",
    "utility_id": "hjorring-varmeforsyning",
    "portal_url": "https://eforsyning.dk/hjvarme/",
    "eforsyning_username": fx.USERNAME,
    "eforsyning_password": fx.PASSWORD,
    "eforsyning_supplier_id": "B30A6948-2461-4827-B8EB-5D93169CCB8B",
}


def _ef_coord(tmp_path, store=None):
    coord, hass, entry, store = make_coordinator(tmp_path, store=store, **EF_ENTRY)
    coord.backend = "eforsyning"
    coord.async_set_updated_data = MagicMock()
    coord._async_update_weather = AsyncMock()
    return coord, hass, entry, store


@pytest.mark.asyncio
async def test_eforsyning_sync_maps_saves_and_reports_capabilities(tmp_path: Path) -> None:
    coord, hass, entry, store = _ef_coord(tmp_path, FakeStore({}))
    fetch = AsyncMock(return_value=_readings())
    with patch("kmd_easy_energy.coordinator.EforsyningClient.async_fetch", fetch), patch(
        "kmd_easy_energy.coordinator.copenhagen_today", return_value=date(2026, 11, 5)
    ), patch("kmd_easy_energy.coordinator.async_get_clientsession"):
        await coord.async_sync_eforsyning()
    assert fetch.await_args.kwargs["years_back"] == 1  # first sync: previous billing year too
    saved = store.data
    assert saved["daily"]["total"] == 75
    assert saved["last_sync"] and saved["initial_setup_complete"] is True
    caps = set(saved["capabilities"])
    assert {"daily", "monthly", "temperatures", "volume"} <= caps
    assert not caps & {"hourly", "billing", "forecast", "mitid"}
    assert saved["backend"] == "eforsyning" and saved["data_source"] == "E|Forsyning"
    dumped = json.dumps(saved, default=str, ensure_ascii=False)
    assert fx.PASSWORD not in dumped and fx.USERNAME not in dumped
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_eforsyning_login_error_keeps_cache(tmp_path: Path) -> None:
    coord, _, _, store = _ef_coord(tmp_path, FakeStore({"annual": {"2026": 7}}))
    fetch = AsyncMock(side_effect=EforsyningLoginError("E|Forsyning afviste login"))
    from kmd_easy_energy.coordinator import KMDLoginError

    with patch("kmd_easy_energy.coordinator.EforsyningClient.async_fetch", fetch), patch(
        "kmd_easy_energy.coordinator.async_get_clientsession"
    ):
        with pytest.raises(KMDLoginError):
            await coord.async_sync_eforsyning()
    assert store.saved == [] and coord.last_sync is None


@pytest.mark.asyncio
async def test_eforsyning_run_reports_error_on_card(tmp_path: Path) -> None:
    coord, _, _, _ = _ef_coord(tmp_path)
    coord.async_sync_eforsyning = AsyncMock(side_effect=RuntimeError("nede"))
    coord._push_sync_ui = MagicMock()
    await coord._async_run_eforsyning_sync()
    assert coord._push_sync_ui.call_args_list[-1].args == ("error", "Fejl: nede")


@pytest.mark.asyncio
async def test_start_mitid_sync_delegates_for_eforsyning(tmp_path: Path) -> None:
    coord, hass, _, _ = _ef_coord(tmp_path)
    with patch("kmd_easy_energy.coordinator.KMDMitIDAuthenticator") as mitid:
        await coord.async_start_mitid_sync()
    mitid.assert_not_called()
    hass.async_create_task.assert_called_once()  # E|Forsyning sync task, no MitID
    hass.async_create_task.call_args.args[0].close()


def test_reminder_and_auto_sync_defaults_per_backend(tmp_path: Path) -> None:
    ef, _, ef_entry, _ = _ef_coord(tmp_path)
    kmd, _, _, _ = make_coordinator(tmp_path)
    assert ef.sync_reminder_enabled is False and kmd.sync_reminder_enabled is True
    assert ef.auto_sync_enabled is True and kmd.auto_sync_enabled is False
    assert ef.auto_sync_hour == 6
    ef_entry.options = {"sync_reminder": True, "auto_sync_hour": 30}
    assert ef.sync_reminder_enabled is True and ef.auto_sync_hour == 23


def test_auto_sync_timer_only_for_eforsyning(tmp_path: Path) -> None:
    ef, _, _, _ = _ef_coord(tmp_path)
    kmd, _, _, _ = make_coordinator(tmp_path)
    with patch("kmd_easy_energy.coordinator.async_track_time_change") as track, patch(
        "kmd_easy_energy.coordinator.async_call_later"
    ) as later:
        kmd.async_start_auto_sync()()
        assert track.call_count == 0 and later.call_count == 0
        unsub = ef.async_start_auto_sync()
        assert track.call_args.kwargs["hour"] == 6
        assert later.call_count == 1  # never synced -> one catch-up sync after start
        unsub()
    ef.last_sync = datetime.now(timezone.utc)
    with patch("kmd_easy_energy.coordinator.async_track_time_change"), patch(
        "kmd_easy_energy.coordinator.async_call_later"
    ) as later:
        ef.async_start_auto_sync()
        assert later.call_count == 0


# ---------------------------------------------------------- config / entities
def test_utilities_json_backend_field_and_hjorring() -> None:
    from kmd_easy_energy.config_flow import _format_utility_label

    data = json.loads((ROOT / "custom_components/kmd_easy_energy/utilities.json").read_text())
    by_id = {u["id"]: u for u in data["utilities"]}
    hj = by_id["hjorring-varmeforsyning"]
    assert hj["backend"] == "eforsyning"
    assert hj["eforsyning_supplier_id"] == "B30A6948-2461-4827-B8EB-5D93169CCB8B"
    assert hj["portal_url"] == "https://eforsyning.dk/hjvarme/"
    assert hj["status"] == "pending_test"
    assert _format_utility_label(hj) == "🧪 Hjørring Varmeforsyning (Hjørring) — E|Forsyning (afventer 1. test)"

    soroe = by_id["soroe-fjernvarme"]
    assert soroe["backend"] == "eforsyning"
    assert soroe["status"] == "confirmed"
    assert soroe["tier"] == "confirmed"
    assert soroe["eforsyning_supplier_id"] == "CE44A147-CE18-483B-81AF-29A188E33067"
    assert soroe["portal_url"] == "https://eforsyning.dk/soroe/"
    assert _format_utility_label(soroe) == "✅ Sorø Fjernvarme (Sorø) — E|Forsyning (bekræftet live)"

    fh = by_id["frederikshavn-forsyning"]
    assert fh["backend"] == "kmd"
    assert fh["status"] == "confirmed"
    assert fh["tier"] == "confirmed"

    eforsyning = {u["id"] for u in data["utilities"] if u.get("backend") == "eforsyning"}
    assert eforsyning >= {"soroe-fjernvarme", "hjorring-varmeforsyning"}
    wattson = {u["id"] for u in data["utilities"] if u.get("backend") == "wattson"}
    others = eforsyning | wattson
    assert wattson >= {"aalborg-forsyning", "forsyning-helsingor", "fjernvarme-fyn", "hillerod-forsyning"}
    assert all(u["backend"] == "kmd" for k, u in by_id.items() if k not in others)


def _flow(utility: dict):
    from kmd_easy_energy.config_flow import KMDEasyEnergyConfigFlow

    flow = KMDEasyEnergyConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": "user"}
    flow._selected_utility = utility
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(side_effect=lambda **kw: {"type": "create_entry", **kw})
    flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})
    return flow


HJ = {
    "id": "hjorring-varmeforsyning",
    "name": "Hjørring Varmeforsyning",
    "city": "Hjørring",
    "portal_url": "https://eforsyning.dk/hjvarme/",
    "status": "pending_test",
    "backend": "eforsyning",
    "eforsyning_supplier_id": "B30A6948-2461-4827-B8EB-5D93169CCB8B",
    "latitude": 57.464,
    "longitude": 9.982,
}


@pytest.mark.asyncio
async def test_flow_eforsyning_asks_credentials_not_mitid_and_creates_entry() -> None:
    flow = _flow(dict(HJ))
    form = await flow.async_step_eforsyning()
    fields = [str(k) for k in form["data_schema"].schema]
    assert fields == ["eforsyning_username", "eforsyning_password", "location_name"]  # supplier known
    assert not any("mitid" in f for f in fields)
    with patch(
        "kmd_easy_energy.config_flow.async_validate_eforsyning",
        AsyncMock(return_value=fx.INSTALLATIONS["Installationer"]),
    ):
        res = await flow.async_step_eforsyning(
            {"eforsyning_username": fx.USERNAME, "eforsyning_password": fx.PASSWORD}
        )
    assert res["type"] == "create_entry"
    data = res["data"]
    assert data["backend"] == "eforsyning"
    assert data["eforsyning_supplier_id"] == HJ["eforsyning_supplier_id"]
    assert data["eforsyning_installation_id"] == "1"
    assert "mitid_username" not in data
    assert res["options"] == {"auto_sync": True, "auto_sync_hour": 6, "sync_reminder": False}
    uid = flow.async_set_unique_id.await_args.args[0]
    assert uid.startswith("eforsyning:b30a6948") and fx.USERNAME not in uid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "error"),
    [(EforsyningLoginError("x"), "invalid_auth"), (EforsyningError("x"), "cannot_connect"), (ValueError("x"), "unknown")],
)
async def test_flow_eforsyning_errors(exc, error) -> None:
    flow = _flow(dict(HJ))
    with patch("kmd_easy_energy.config_flow.async_validate_eforsyning", AsyncMock(side_effect=exc)):
        res = await flow.async_step_eforsyning(
            {"eforsyning_username": fx.USERNAME, "eforsyning_password": fx.PASSWORD}
        )
    assert res["type"] == "form" and res["errors"]["base"] == error


@pytest.mark.asyncio
async def test_flow_custom_eforsyning_requires_supplier_id_and_picks_installation() -> None:
    from kmd_easy_energy.config_flow import CUSTOM_EFORSYNING

    flow = _flow(dict(CUSTOM_EFORSYNING))
    form = await flow.async_step_eforsyning()
    assert "eforsyning_supplier_id" in [str(k) for k in form["data_schema"].schema]
    res = await flow.async_step_eforsyning({"eforsyning_username": "1", "eforsyning_password": "2"})
    assert res["errors"] == {"eforsyning_supplier_id": "eforsyning_supplier_required"}
    two = [dict(fx.INSTALLATIONS["Installationer"][0]), dict(fx.INSTALLATIONS["Installationer"][0], InstallationNr=2)]
    with patch("kmd_easy_energy.config_flow.async_validate_eforsyning", AsyncMock(return_value=two)):
        res = await flow.async_step_eforsyning(
            {"eforsyning_username": "1", "eforsyning_password": "2", "eforsyning_supplier_id": fx.SUPPLIER_ID}
        )
    assert res["step_id"] == "eforsyning_installation"
    res = await flow.async_step_eforsyning_installation({"eforsyning_installation_id": "2"})
    assert res["data"]["eforsyning_installation_id"] == "2"


def test_translations_cover_eforsyning_steps() -> None:
    for rel in ("strings.json", "translations/en.json", "translations/da.json"):
        data = json.loads((ROOT / "custom_components/kmd_easy_energy" / rel).read_text())
        steps = data["config"]["step"]
        for step in ("eforsyning", "eforsyning_installation", "reconfigure_eforsyning"):
            assert step in steps
        assert {"eforsyning_username", "eforsyning_password", "eforsyning_supplier_id"} <= set(steps["eforsyning"]["data"])
        assert "{status_badge}" in steps["eforsyning"]["description"]
        assert {"invalid_auth", "cannot_connect", "eforsyning_supplier_required"} <= set(data["config"]["error"])
        assert {"auto_sync", "auto_sync_hour"} <= set(data["options"]["step"]["init"]["data"])
    da_ef_desc = json.loads(
        (ROOT / "custom_components/kmd_easy_energy/translations/da.json").read_text()
    )["config"]["step"]["eforsyning"]["description"]
    assert "Eksperimentel" in da_ef_desc
    assert "Sorø Fjernvarme" in da_ef_desc


@pytest.mark.asyncio
async def test_diagnostics_redact_eforsyning_credentials() -> None:
    from kmd_easy_energy.diagnostics import async_get_config_entry_diagnostics

    entry = SimpleNamespace(
        entry_id="e1", title="Hjørring", unique_id="eforsyning:x", domain="kmd_easy_energy",
        version=1, data=dict(EF_ENTRY, eforsyning_installation_id="1"), options={},
    )
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {}}
    out = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(out, default=str)
    assert fx.PASSWORD not in dumped and fx.USERNAME not in dumped
    assert out["entry"]["data"]["eforsyning_password"] == "**REDACTED**"


def test_services_and_notice() -> None:
    assert "\nsync:" in (ROOT / "custom_components/kmd_easy_energy/services.yaml").read_text()
    notice = (ROOT / "NOTICE").read_text()
    assert "kpoppel/homeassistant-eforsyning" in notice and "Apache License" in notice
    header = (ROOT / "custom_components/kmd_easy_energy/api/eforsyning_client.py").read_text()[:1500]
    assert "kpoppel/homeassistant-eforsyning" in header and "Apache License" in header
    assert "changes" in header.lower()
