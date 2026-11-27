"""E|Forsyning backend: client protocol, parsing, mapping, coordinator, flow.

No network: every response comes from tests/fixtures_eforsyning.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
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
    async_resolve_supplier_input,
    is_uuid,
    normalize_eforsyning_url,
    parse_eforsyning_directory,
    parse_number,
    parse_readings,
    parse_umbraco_suppliers,
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
    assert state["return_temp"]["expected_annual"]["2026"] == 37.0
    assert state["return_temp"]["expected_monthly_2026"]["Nov"] == 37.0
    assert state["daily_expected_return_temp"]["2026-11-01"] == 37.0
    assert state["latest_reading"]["temp_return"] == 33.0
    assert state["latest_reading"]["temp_expected_return"] == 37.0
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
    assert res == {"energy": 3, "volume": 3, "cost": 0}
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
    assert [u["Name"] for u in saved["available_units"]] == ["kWh", "m3", "°C"]
    assert saved["has_direct_temp"] is False
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
        assert later.call_count == 1  # never synced -> quick catch-up sync after start
        assert later.call_args.args[1] == 10
        unsub()
    ef.last_sync = datetime.now(timezone.utc) - timedelta(hours=30)
    with patch("kmd_easy_energy.coordinator.async_track_time_change"), patch(
        "kmd_easy_energy.coordinator.async_call_later"
    ) as later:
        unsub = ef.async_start_auto_sync()
        assert later.call_count == 1
        assert later.call_args.args[1] == 120
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
    assert len(eforsyning) == 43
    assert "hoje-taastrup-fjernvarme" not in by_id
    assert eforsyning >= {
        "soroe-fjernvarme",
        "hadsund-fjernvarme",
        "hedensted-fjernvarme",
        "dronninglund-fjernvarme",
        "kongerslev-fjernvarme",
        "grenaa-varmevaerk",
        "hjorring-varmeforsyning",
        "fjernvarme-horsens",
        "vestforbraending",
        "vejle-fjernvarme",
        "sonderborg-varme",
        "kjellerup-fjernvarme",
        "nykobing-sj",
        "viborg-varme",
        "naestved-fjernvarme",
        "svendborg-fjernvarme",
        "norfors-fjernvarme",
        "taarnby-forsyning",
    }
    hadsund = by_id["hadsund-fjernvarme"]
    assert hadsund["status"] == "confirmed"
    assert hadsund["tier"] == "confirmed"
    assert hadsund["eforsyning_supplier_id"] == "49C73776-76BE-4382-BA5C-2B4E7384CC34"
    assert hadsund["portal_url"] == "https://eforsyning.dk/hadsundfjernvarme/"
    hedensted = by_id["hedensted-fjernvarme"]
    assert hedensted["status"] == "confirmed"
    assert hedensted["tier"] == "confirmed"
    assert hedensted["eforsyning_supplier_id"] == "4F2200AF-8833-4237-81D9-E5CEF34582A2"
    assert hedensted["portal_url"] == "https://eforsyning.dk/hedenstedfjernvarme/"
    dronninglund = by_id["dronninglund-fjernvarme"]
    assert dronninglund["status"] == "confirmed"
    assert dronninglund["tier"] == "confirmed"
    assert dronninglund["eforsyning_supplier_id"] == "66D241DC-AE10-49F5-A176-81CC8C58BEF7"
    assert dronninglund["portal_url"] == "https://eforsyning.dk/dronninglundfjernvarme/"
    kongerslev = by_id["kongerslev-fjernvarme"]
    assert kongerslev["status"] == "confirmed"
    assert kongerslev["tier"] == "confirmed"
    assert kongerslev["eforsyning_supplier_id"] == "4A530E73-227F-4ACB-9D9B-A84905470921"
    assert kongerslev["portal_url"] == "https://eforsyning.dk/kongerslev/"
    grenaa = by_id["grenaa-varmevaerk"]
    assert grenaa["status"] == "confirmed"
    assert grenaa["tier"] == "confirmed"
    assert grenaa["eforsyning_supplier_id"] == "BE112409-C45D-4E63-BFF6-1C4E8F9ED990"
    assert grenaa["portal_url"] == "https://eforsyning.dk/grenaa-varmevaerk/"
    sonderborg = by_id["sonderborg-varme"]
    assert sonderborg["status"] == "confirmed"
    assert sonderborg["tier"] == "confirmed"
    assert sonderborg["eforsyning_supplier_id"] == "0DA4BF5F-2857-44FA-9CA3-F90A3C04B01F"
    assert sonderborg["portal_url"] == "https://www.sonderborg-varme.dk/eforsyning/"
    for uid in eforsyning:
        u = by_id[uid]
        assert is_uuid(u["eforsyning_supplier_id"]), uid
        assert u["portal_url"].startswith("https://"), uid
        assert isinstance(u["latitude"], (int, float)) and isinstance(u["longitude"], (int, float)), uid
    albertslund = by_id["albertslund-forsyning"]
    assert albertslund["backend"] == "kmd"
    assert albertslund["status"] == "confirmed"
    assert albertslund["tier"] == "confirmed"
    assert albertslund["auth_method"] == "MitID"
    kalundborg = by_id["kalundborg-forsyning"]
    assert kalundborg["backend"] == "kmd"
    assert kalundborg["status"] == "confirmed"
    assert kalundborg["tier"] == "confirmed"
    assert kalundborg["auth_method"] == "MitID"
    vestforsyning = by_id["vestforsyning"]
    assert vestforsyning["backend"] == "kmd"
    assert vestforsyning["status"] == "confirmed"
    assert vestforsyning["tier"] == "confirmed"
    assert vestforsyning["auth_method"] == "MitID"
    wattson = {u["id"] for u in data["utilities"] if u.get("backend") == "wattson"}
    others = eforsyning | wattson
    assert wattson >= {"aalborg-forsyning", "forsyning-helsingor", "fjernvarme-fyn", "hillerod-forsyning"}
    assert by_id["hillerod-forsyning"]["status"] == "confirmed"
    assert by_id["hillerod-forsyning"]["tier"] == "confirmed"
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
        for step in (
            "eforsyning",
            "eforsyning_directory",
            "eforsyning_supplier",
            "eforsyning_installation",
            "reconfigure_eforsyning",
        ):
            assert step in steps
            desc = steps[step].get("description", "")
            assert "<" not in desc and ">" not in desc
        assert {"eforsyning_username", "eforsyning_password", "eforsyning_supplier_id"} <= set(steps["eforsyning"]["data"])
        assert "{status_badge}" in steps["eforsyning"]["description"]
        assert "eforsyning_directory_url" in steps["eforsyning_directory"]["data"]
        assert "eforsyning_supplier_id" in steps["eforsyning_supplier"]["data"]
        assert {
            "invalid_auth",
            "cannot_connect",
            "eforsyning_supplier_required",
            "eforsyning_supplier_lookup_failed",
            "eforsyning_directory_failed",
        } <= set(data["config"]["error"])
        assert {"auto_sync", "auto_sync_hour"} <= set(data["options"]["step"]["init"]["data"])
        raw_dump = json.dumps(data)
        assert "https://" not in raw_dump and "http://" not in raw_dump
    da_ef_desc = json.loads(
        (ROOT / "custom_components/kmd_easy_energy/translations/da.json").read_text()
    )["config"]["step"]["eforsyning"]["description"]
    assert "Eksperimentel" in da_ef_desc
    assert "Sorø Fjernvarme" in da_ef_desc


# ---------------------------------------------- discovery & directory (B + C)
def test_is_uuid_and_normalize_eforsyning_url() -> None:
    assert is_uuid("8B563AC8-706E-45C6-A23C-A6CABCAE3E41")
    assert not is_uuid("horsens")
    assert normalize_eforsyning_url("horsens") == "https://eforsyning.dk/horsens/"
    assert normalize_eforsyning_url("/horsens/") == "https://eforsyning.dk/horsens/"
    assert normalize_eforsyning_url("eforsyning.dk/horsens") == "https://eforsyning.dk/horsens/"
    assert normalize_eforsyning_url("https://www.vejlefjernvarme.dk/eforsyning") == "https://www.vejlefjernvarme.dk/eforsyning/"
    for bad in (
        "",
        "http://eforsyning.dk/horsens/",
        "https://localhost/eforsyning/",
        "https://127.0.0.1/eforsyning/",
        "https://ha.local/eforsyning/",
        "https://eforsyning.dk:8443/horsens/",
        "https://user:pass@eforsyning.dk/horsens/",
    ):
        assert normalize_eforsyning_url(bad) is None


def test_parse_umbraco_suppliers_single_multi_and_fallback() -> None:
    single = (
        '<script>indstillinger.umbraco = {"firmaNavn":"Fjernvarme Horsens","eforsyninger":'
        '[{"forsyningId":"8B563AC8-706E-45C6-A23C-A6CABCAE3E41","siteUrl":"https://eforsyning.dk/horsens/",'
        '"appServerUrl":"https://apiapp.dff-edb.dk/horsens/"}]};</script>'
    )
    res = parse_umbraco_suppliers(single, "https://eforsyning.dk/horsens/")
    assert res == [{
        "supplier_id": "8B563AC8-706E-45C6-A23C-A6CABCAE3E41",
        "name": "Fjernvarme Horsens",
        "portal_url": "https://eforsyning.dk/horsens/",
        "app_server_url": "https://apiapp.dff-edb.dk/horsens/",
    }]

    multi = (
        '<script>indstillinger.umbraco = {"firmaNavn":"Kjellerup Fjernvarme Amba","eforsyninger":['
        '{"forsyningId":"07026EBC-5635-4A70-B381-34BB896ACEDD","siteUrl":"https://eforsyning.dk/kjellerupfjernvarme-varme/","appServerUrl":"https://apiapp.dff-edb.dk/kjellerup/"},'
        '{"forsyningId":"8CD51FA1-33B8-4982-8C39-A830E6AE1D79","siteUrl":"https://eforsyning.dk/kjellerupfjernvarme-vand/","appServerUrl":"https://apiapp.dff-edb.dk/kjellerupvand/"}'
        ']};</script>'
    )
    matched = parse_umbraco_suppliers(multi, "https://eforsyning.dk/kjellerupfjernvarme-varme/")
    assert len(matched) == 1 and matched[0]["supplier_id"] == "07026EBC-5635-4A70-B381-34BB896ACEDD"
    all_choices = parse_umbraco_suppliers(multi, "https://eforsyning.dk/other/")
    assert len(all_choices) == 2

    fallback = '<script>var x = { forsyningId: "8B563AC8-706E-45C6-A23C-A6CABCAE3E41" };</script>'
    fb = parse_umbraco_suppliers(fallback, "https://eforsyning.dk/horsens/")
    assert len(fb) == 1 and fb[0]["supplier_id"] == "8B563AC8-706E-45C6-A23C-A6CABCAE3E41"


def test_parse_eforsyning_directory_filters_water_and_albertslund() -> None:
    sample_html = """
    <a href="javascript:selectPlant('https://eforsyning.dk/addit/');"><h5>Addit Vandv&#xE6;rk</h5></a>
    <a href="javascript:selectPlant('https://eforsyning.dk/albertslund/');"><h5>Albertslund Forsyning</h5></a>
    <a href="javascript:selectPlant('https://eforsyning.dk/htf/');"><h5>H&#xF8;je Taastrup Fjernvarme</h5></a>
    <a href="javascript:selectPlant('https://eforsyning.dk/aulumfjernvarme/');"><h5>Aulum Fjernvarme a.m.b.a. og Aulum Vandv&#xE6;rk a.m.b.a.</h5></a>
    <a href="javascript:selectPlant('https://eforsyning.dk/horsens/');"><h5>Fjernvarme Horsens</h5></a>
    <a href="javascript:selectPlant('https://www.vejlefjernvarme.dk/eforsyning/');"><h5>Vejle Fjernvarme</h5></a>
    """
    parsed = parse_eforsyning_directory(sample_html)
    names = [p["name"] for p in parsed]
    assert "Addit Vandværk" not in names
    assert "Albertslund Forsyning" not in names
    assert "Høje Taastrup Fjernvarme" not in names
    assert names == [
        "Aulum Fjernvarme a.m.b.a. og Aulum Vandværk a.m.b.a.",
        "Fjernvarme Horsens",
        "Vejle Fjernvarme",
    ]


class _LookupSession:
    def __init__(self, responses: dict[str, tuple[int, str]]) -> None:
        self._responses = responses
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        for key, val in self._responses.items():
            if key in url:
                status, text = val
                return _FakeResp(status, text, url)
        return _FakeResp(404, "", url)


class _FakeResp:
    def __init__(self, status: int, text: str, url: str) -> None:
        self.status = status
        self._text = text
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self) -> str:
        return self._text

    async def json(self, content_type=None):
        return json.loads(self._text)


@pytest.mark.asyncio
async def test_async_resolve_supplier_input_slug_and_errors() -> None:
    horsens_html = (
        '<script>indstillinger.umbraco = {"firmaNavn":"Fjernvarme Horsens","eforsyninger":'
        '[{"forsyningId":"8B563AC8-706E-45C6-A23C-A6CABCAE3E41","siteUrl":"https://eforsyning.dk/horsens/"}]};</script>'
    )
    gvs_json = json.dumps({
        "AppServerUri": "https://apiapp.dff-edb.dk/horsens/",
        "EforsyningUri": "https://eforsyning.dk/horsens/",
        "FirmaInfo": {"firmaNavn": "Fjernvarme Horsens", "by": "Horsens"},
    })
    sess = _LookupSession({
        "GetVaerkSettings": (200, gvs_json),
        "eforsyning.dk/horsens/": (200, horsens_html),
    })
    resolved = await async_resolve_supplier_input(sess, "horsens")
    assert len(resolved) == 1
    assert resolved[0]["supplier_id"] == "8B563AC8-706E-45C6-A23C-A6CABCAE3E41"
    assert resolved[0]["name"] == "Fjernvarme Horsens"
    assert resolved[0]["city"] == "Horsens"

    with pytest.raises(EforsyningError):
        await async_resolve_supplier_input(sess, "http://insecure.example/x")
    with pytest.raises(EforsyningError):
        await async_resolve_supplier_input(_LookupSession({"eforsyning.dk/empty/": (200, "<html></html>")}), "empty")


@pytest.mark.asyncio
async def test_flow_eforsyning_directory_and_url_lookup() -> None:
    from kmd_easy_energy.config_flow import DIRECTORY_EFORSYNING_ID, KMDEasyEnergyConfigFlow

    flow = _flow(dict(HJ))
    flow._utilities_cache = [
        {
            "id": "soroe-fjernvarme",
            "name": "Sorø Fjernvarme",
            "city": "Sorø",
            "portal_url": "https://eforsyning.dk/soroe/",
            "status": "confirmed",
            "backend": "eforsyning",
            "eforsyning_supplier_id": "CE44A147-CE18-483B-81AF-29A188E33067",
        }
    ]
    with patch(
        "kmd_easy_energy.config_flow.async_fetch_eforsyning_directory",
        AsyncMock(return_value=[
            {"name": "Avedøre Fjernvarme", "portal_url": "https://eforsyning.dk/avedore/"},
            {"name": "Sorø Fjernvarme", "portal_url": "https://eforsyning.dk/soroe/"},
        ]),
    ), patch("kmd_easy_energy.config_flow.async_get_clientsession"):
        form = await flow.async_step_eforsyning_directory()
    assert form["step_id"] == "eforsyning_directory"

    with patch(
        "kmd_easy_energy.config_flow.async_resolve_supplier_input",
        AsyncMock(return_value=[{
            "supplier_id": "CE44A147-CE18-483B-81AF-29A188E33067",
            "name": "Sorø Fjernvarme",
            "city": "Sorø",
            "portal_url": "https://eforsyning.dk/soroe/",
        }]),
    ), patch("kmd_easy_energy.config_flow.async_get_clientsession"):
        next_step = await flow.async_step_eforsyning_directory(
            {"eforsyning_directory_url": "https://eforsyning.dk/soroe/"}
        )
    assert next_step["step_id"] == "eforsyning"
    assert flow._selected_utility["id"] == "soroe-fjernvarme"
    assert flow._selected_utility["status"] == "confirmed"

    # Offline directory fallback goes straight to manual eforsyning step
    offline_flow = _flow(dict(HJ))
    with patch(
        "kmd_easy_energy.config_flow.async_fetch_eforsyning_directory",
        AsyncMock(side_effect=EforsyningError("offline")),
    ), patch("kmd_easy_energy.config_flow.async_get_clientsession"):
        fb = await offline_flow.async_step_eforsyning_directory()
    assert fb["step_id"] == "eforsyning"
    assert offline_flow._selected_utility["id"] == "eforsyning-custom"

    # Manual slug lookup on eforsyning-custom sets real utility name & portal URL
    from kmd_easy_energy.config_flow import CUSTOM_EFORSYNING

    slug_flow = _flow(dict(CUSTOM_EFORSYNING))
    with patch(
        "kmd_easy_energy.config_flow.async_resolve_supplier_input",
        AsyncMock(return_value=[{
            "supplier_id": "A16B623F-9AE8-4152-949B-03B19A96F644",
            "name": "Avedøre Fjernvarme amba",
            "city": "Hvidovre",
            "portal_url": "https://eforsyning.dk/avedore/",
        }]),
    ), patch(
        "kmd_easy_energy.config_flow.async_validate_eforsyning",
        AsyncMock(return_value=fx.INSTALLATIONS["Installationer"]),
    ), patch("kmd_easy_energy.config_flow.async_get_clientsession"):
        created = await slug_flow.async_step_eforsyning({
            "eforsyning_username": fx.USERNAME,
            "eforsyning_password": fx.PASSWORD,
            "eforsyning_supplier_id": "avedore",
        })
    assert created["type"] == "create_entry"
    assert created["title"] == "Avedøre Fjernvarme amba"
    assert created["data"]["portal_url"] == "https://eforsyning.dk/avedore/"
    assert created["data"]["eforsyning_supplier_id"] == "A16B623F-9AE8-4152-949B-03B19A96F644"

    # Multi-candidate portal shows eforsyning_supplier step and finishes setup
    multi_flow = _flow(dict(CUSTOM_EFORSYNING))
    with patch(
        "kmd_easy_energy.config_flow.async_resolve_supplier_input",
        AsyncMock(return_value=[
            {"supplier_id": "0EF3EA2A-DA10-416F-AF1C-B36FD44393C9", "name": "Ringkøbing", "portal_url": "https://eforsyning.dk/rfv/"},
            {"supplier_id": "2B956C80-A167-43DC-A29A-10F87AE69CFD", "name": "Tim", "portal_url": "https://eforsyning.dk/rfv-tim-fjernvarme/"},
        ]),
    ), patch("kmd_easy_energy.config_flow.async_get_clientsession"):
        pick = await multi_flow.async_step_eforsyning({
            "eforsyning_username": fx.USERNAME,
            "eforsyning_password": fx.PASSWORD,
            "eforsyning_supplier_id": "rfv",
        })
    assert pick["step_id"] == "eforsyning_supplier"
    with patch(
        "kmd_easy_energy.config_flow.async_validate_eforsyning",
        AsyncMock(return_value=fx.INSTALLATIONS["Installationer"]),
    ):
        done = await multi_flow.async_step_eforsyning_supplier({
            "eforsyning_supplier_id": "2B956C80-A167-43DC-A29A-10F87AE69CFD"
        })
    assert done["type"] == "create_entry"
    assert done["title"] == "Tim"


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
