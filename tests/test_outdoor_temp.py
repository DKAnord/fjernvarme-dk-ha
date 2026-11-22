"""Outdoor temperature source: location precedence, migration, HA sensor statistics."""

from __future__ import annotations

import asyncio
import datetime as dt_mod
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kmd_easy_energy import outdoor_temp as ot
from kmd_easy_energy.config_flow import _clean_outdoor_options
from kmd_easy_energy.insights import DK_TZ, copenhagen_today

from test_coordinator import make_coordinator  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "custom_components/kmd_easy_energy"

HOME = (55.6761, 12.5683)  # fictitious "home"
UTIL = (56.153, 10.106)  # Aarhus-ish utility coordinates
CUSTOM = (57.0, 9.9)


def cfg(lat=None, lon=None, components=()):
    return SimpleNamespace(latitude=lat, longitude=lon, components=set(components))


# ---------------------------------------------------------------- precedence


@pytest.mark.parametrize(
    "lat,lon,ok",
    [(None, None, False), (0, 0, False), (0.0, 0.0, False), (91, 10, False), (55, 181, False),
     (True, 10, False), ("x", 1, False), (float("nan"), 1, False), (55.1, 0, True), ("55.5", "12.1", True)],
)
def test_coord_pair(lat, lon, ok) -> None:
    assert (ot.coord_pair(lat, lon) is not None) is ok


def test_precedence_override_beats_home_and_utility() -> None:
    loc = ot.resolve_location(
        {"latitude": CUSTOM[0], "longitude": CUSTOM[1]},
        {"utility_latitude": UTIL[0], "utility_longitude": UTIL[1]},
        cfg(*HOME),
    )
    assert (loc.latitude, loc.longitude, loc.kind) == (*CUSTOM, "custom")


def test_precedence_home_beats_utility() -> None:
    loc = ot.resolve_location({}, {"utility_latitude": UTIL[0], "utility_longitude": UTIL[1]}, cfg(*HOME))
    assert (loc.latitude, loc.longitude, loc.kind) == (*HOME, "home")


@pytest.mark.parametrize("home", [(0, 0), (None, None), (0.0, 0.0)])
def test_precedence_unset_home_falls_back_to_utility(home) -> None:
    loc = ot.resolve_location({}, {"utility_latitude": UTIL[0], "utility_longitude": UTIL[1]}, cfg(*home))
    assert loc.kind == "utility" and (loc.latitude, loc.longitude) == UTIL


def test_precedence_legacy_entry_data_is_utility_not_explicit() -> None:
    # Before migration: utility coords copied into entry.data are NOT a user
    # choice, so the HA home location must win over them.
    data = {"latitude": UTIL[0], "longitude": UTIL[1]}
    assert ot.resolve_location({}, data, cfg(*HOME)).kind == "home"
    assert ot.resolve_location({}, data, cfg(0, 0)).kind == "utility"


def test_precedence_incomplete_override_ignored_and_nothing_known() -> None:
    assert ot.resolve_location({"latitude": 57.0}, {}, cfg(*HOME)).kind == "home"
    assert ot.resolve_location({"latitude": 0, "longitude": 0}, {}, cfg(*HOME)).kind == "home"
    assert ot.resolve_location({}, {}, cfg(0, 0)) is None


# ----------------------------------------------------------------- migration


def test_migrate_moves_utility_coords_and_follows_home() -> None:
    data, opts, dropped = ot.migrate_location(
        {"utility_id": "kredslob", "latitude": UTIL[0], "longitude": UTIL[1]}, {}, cfg(*HOME)
    )
    assert "latitude" not in data and "longitude" not in data
    assert (data["utility_latitude"], data["utility_longitude"]) == UTIL
    assert opts == {} and dropped is False
    assert ot.resolve_location(opts, data, cfg(*HOME)).kind == "home"


@pytest.mark.parametrize(
    "opt",
    [UTIL, HOME, (56.15, 10.10), (UTIL[0] + 0.0004, UTIL[1] - 0.0004)],
    ids=["prefilled-utility", "prefilled-home", "form-placeholder", "rounded-utility"],
)
def test_migrate_drops_implicit_option_coords(opt) -> None:
    data, opts, dropped = ot.migrate_location(
        {"latitude": UTIL[0], "longitude": UTIL[1]},
        {"latitude": opt[0], "longitude": opt[1], "price_dkk_per_kwh": 0.7},
        cfg(*HOME),
    )
    assert dropped is True
    assert "latitude" not in opts and "longitude" not in opts
    assert opts["price_dkk_per_kwh"] == 0.7
    assert ot.resolve_location(opts, data, cfg(*HOME)).kind == "home"


def test_migrate_keeps_explicit_override() -> None:
    data, opts, dropped = ot.migrate_location(
        {"latitude": UTIL[0], "longitude": UTIL[1]},
        {"latitude": CUSTOM[0], "longitude": CUSTOM[1]},
        cfg(*HOME),
    )
    assert dropped is False
    assert (opts["latitude"], opts["longitude"]) == CUSTOM
    assert ot.resolve_location(opts, data, cfg(*HOME)).kind == "custom"


def test_migrate_drops_broken_override_and_keeps_existing_utility_keys() -> None:
    data, opts, dropped = ot.migrate_location(
        {"utility_latitude": 1.5, "utility_longitude": 2.5, "latitude": UTIL[0], "longitude": UTIL[1]},
        {"latitude": 57.0},
        cfg(0, 0),
    )
    assert dropped is True and "latitude" not in opts
    assert (data["utility_latitude"], data["utility_longitude"]) == (1.5, 2.5)


def test_migrate_without_any_coordinates_is_noop() -> None:
    data, opts, dropped = ot.migrate_location({"utility_id": "x"}, {"a": 1}, cfg(*HOME))
    assert data == {"utility_id": "x"} and opts == {"a": 1} and dropped is False


def _fake_entry(data, options=None, minor=2):
    return SimpleNamespace(version=1, minor_version=minor, data=dict(data), options=dict(options or {}), title="Kredsløb")


def test_async_migrate_entry_1_2_to_1_3() -> None:
    from kmd_easy_energy import async_migrate_entry

    hass = MagicMock()
    hass.config = cfg(*HOME)
    entry = _fake_entry(
        {"utility_id": "kredslob", "latitude": UTIL[0], "longitude": UTIL[1]},
        {"latitude": UTIL[0], "longitude": UTIL[1], "sync_reminder": False},
    )
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["minor_version"] == 3 and kwargs["version"] == 1
    assert kwargs["data"]["utility_latitude"] == UTIL[0]
    assert "latitude" not in kwargs["data"]
    assert kwargs["options"] == {"sync_reminder": False}


def test_async_migrate_entry_keeps_explicit_and_drops_token_from_1_1() -> None:
    from kmd_easy_energy import async_migrate_entry

    hass = MagicMock()
    hass.config = cfg(*HOME)
    entry = _fake_entry(
        {"utility_id": "kredslob", "access_token": "fake", "latitude": UTIL[0], "longitude": UTIL[1]},
        {"latitude": CUSTOM[0], "longitude": CUSTOM[1]},
        minor=1,
    )
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert "access_token" not in kwargs["data"]
    assert (kwargs["options"]["latitude"], kwargs["options"]["longitude"]) == CUSTOM
    assert hass.config_entries.async_update_entry.call_count == 1


def test_new_entries_store_utility_coords_as_metadata_only() -> None:
    src = (CC / "config_flow.py").read_text()
    assert "entry_data[CONF_LATITUDE]" not in src
    assert "_ef_pending[CONF_LATITUDE]" not in src
    assert "_watts_pending[CONF_LATITUDE]" not in src
    assert "entry_data[CONF_UTILITY_LATITUDE]" in src
    init = (CC / "__init__.py").read_text()
    assert "updates[CONF_UTILITY_LATITUDE]" in init and "updates[CONF_LATITUDE]" not in init


# -------------------------------------------------------------- options flow


@pytest.mark.parametrize(
    "user_input,error,expect",
    [
        ({}, None, {}),
        ({"latitude": None, "longitude": None}, None, {}),
        ({"latitude": 0, "longitude": 0}, None, {}),
        ({"latitude": 57.0}, "location_incomplete", None),
        ({"latitude": 95, "longitude": 9}, "location_invalid", None),
        ({"latitude": "abc", "longitude": 9}, "location_invalid", None),
        ({"latitude": 57, "longitude": 9.9}, None, {"latitude": 57.0, "longitude": 9.9}),
        ({"outdoor_temp_entity": ""}, None, {}),
        ({"outdoor_temp_entity": " sensor.ude "}, None, {"outdoor_temp_entity": "sensor.ude"}),
        ({"outdoor_temp_entity": "weather.home"}, "outdoor_temp_entity_invalid", None),
    ],
)
def test_clean_outdoor_options(user_input, error, expect) -> None:
    cleaned, err = _clean_outdoor_options({"price_dkk_per_kwh": 0.5, **user_input})
    assert err == error
    if expect is not None:
        assert cleaned == {"price_dkk_per_kwh": 0.5, **expect}


def test_options_schema_has_sensor_selector_and_no_prefilled_coordinates() -> None:
    from kmd_easy_energy.config_flow import KMDEasyEnergyOptionsFlow

    flow = KMDEasyEnergyOptionsFlow.__new__(KMDEasyEnergyOptionsFlow)
    flow.hass = MagicMock()
    flow.hass.config = cfg(*HOME)
    entry = SimpleNamespace(
        data={"backend": "kmd", "utility_latitude": UTIL[0], "utility_longitude": UTIL[1], "latitude": UTIL[0]},
        options={"outdoor_temp_entity": "sensor.ude"},
    )
    shown = {}
    flow.async_show_form = lambda **kw: shown.update(kw) or kw
    with patch.object(KMDEasyEnergyOptionsFlow, "config_entry", entry, create=True):
        asyncio.run(flow.async_step_init())
    schema = shown["data_schema"].schema
    by_key = {str(k): k for k in schema}
    assert by_key["outdoor_temp_entity"].description["suggested_value"] == "sensor.ude"
    sel = schema[by_key["outdoor_temp_entity"]]
    assert sel.config["domain"] == ["sensor"] and sel.config["device_class"] == ["temperature"]
    # Only an explicit override is shown; utility / home coordinates are never pre-filled.
    assert by_key["latitude"].description["suggested_value"] is None
    assert by_key["longitude"].description["suggested_value"] is None
    import voluptuous as vol

    assert by_key["latitude"].default is vol.UNDEFINED  # empty field = follow HA home


def test_translations_have_outdoor_fields_and_errors() -> None:
    en = json.loads((CC / "strings.json").read_text())
    for path in ("strings.json", "translations/en.json", "translations/da.json"):
        d = json.loads((CC / path).read_text())
        init = d["options"]["step"]["init"]
        assert set(init["data"]) == set(en["options"]["step"]["init"]["data"])
        assert {"outdoor_temp_entity", "latitude", "longitude"} <= set(init["data_description"])
        assert {"location_incomplete", "location_invalid", "outdoor_temp_entity_invalid"} <= set(d["options"]["error"])
        assert "Open-Meteo" in init["description"]
        assert "http" not in json.dumps(init)  # hassfest: no URLs in translations
    da = json.loads((CC / "translations/da.json").read_text())["options"]["step"]["init"]
    assert "hjemmelokation" in da["data_description"]["latitude"]
    assert "ekstern" in da["description"]


# ------------------------------------------------------- sensor statistics


def _ts(day: dt_mod.date, hour: int) -> float:
    return dt_mod.datetime.combine(day, dt_mod.time(hour), DK_TZ).timestamp()


def test_daily_means_group_by_copenhagen_day_and_filter() -> None:
    d = dt_mod.date(2026, 11, 20)
    rows = [{"start": _ts(d, h), "mean": 4.0 + (h % 2)} for h in range(24)]
    # 23:30 UTC on the 20th is 00:30 local on the 21st.
    rows.append({"start": dt_mod.datetime(2026, 11, 20, 23, 30, tzinfo=dt_mod.timezone.utc), "mean": 1.0})
    rows += [{"start": _ts(d, 3), "mean": None}, {"start": _ts(d, 4), "mean": 99.0}, {"start": None, "mean": 3}]
    means = ot.daily_means_from_hourly(rows)
    assert means["2026-11-20"] == (4.5, 24)
    assert means["2026-11-21"] == (1.0, 1)


def test_usable_sensor_days_thresholds() -> None:
    today = dt_mod.date(2026, 11, 22)
    means = {"2026-11-20": (4.0, 18), "2026-11-21": (3.0, 17), "2026-11-22": (2.0, 6)}
    assert ot.usable_sensor_days(means, today) == {"2026-11-20": 4.0, "2026-11-22": 2.0}
    assert ot.usable_sensor_days({"2026-11-22": (2.0, 5)}, today) == {}
    assert ot.usable_sensor_days(means) == {"2026-11-20": 4.0}


def test_sensor_statistics_use_recorder_executor_readonly() -> None:
    calls = []

    def fake_stats(hass, start, end, ids, period, units, types):
        calls.append((start, end, ids, period, units, types))
        return {"sensor.ude": [{"start": _ts(dt_mod.date(2026, 11, 20), h), "mean": 5.0} for h in range(24)]}

    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    hass = SimpleNamespace(config=cfg(components={"recorder"}))
    with patch("homeassistant.components.recorder.get_instance", return_value=instance) as gi, patch(
        "homeassistant.components.recorder.statistics.statistics_during_period", fake_stats
    ), patch("homeassistant.components.recorder.statistics.async_add_external_statistics") as add_ext, patch(
        "homeassistant.components.recorder.statistics.async_import_statistics"
    ) as add_imp:
        means, status = asyncio.run(
            ot.async_sensor_daily_means(hass, "sensor.ude", dt_mod.date(2026, 11, 15), dt_mod.date(2026, 11, 21))
        )
    gi.assert_called_once_with(hass)
    instance.async_add_executor_job.assert_awaited_once()
    start, end, ids, period, units, types = calls[0]
    assert ids == {"sensor.ude"} and period == "hour" and types == {"mean"}
    assert units == {"temperature": "°C"}
    assert start == dt_mod.datetime(2026, 11, 15, tzinfo=DK_TZ)
    assert end == dt_mod.datetime(2026, 11, 22, tzinfo=DK_TZ)
    assert status == "ok" and means == {"2026-11-20": (5.0, 24)}
    add_ext.assert_not_called()
    add_imp.assert_not_called()


def test_sensor_statistics_without_recorder_or_rows() -> None:
    no_rec = SimpleNamespace(config=cfg())
    assert asyncio.run(ot.async_sensor_daily_means(no_rec, "sensor.x", dt_mod.date.today(), dt_mod.date.today())) == (
        {},
        "no_recorder",
    )
    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(return_value={})
    hass = SimpleNamespace(config=cfg(components={"recorder"}))
    with patch("homeassistant.components.recorder.get_instance", return_value=instance):
        assert asyncio.run(
            ot.async_sensor_daily_means(hass, "sensor.x", dt_mod.date.today(), dt_mod.date.today())
        ) == ({}, "no_statistics")


def test_merge_and_summaries() -> None:
    days = ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]
    temps, by_day = ot.merge_daily(days, {"2026-11-01": 3.0, "2026-11-02": 2.0}, {d: 9.0 for d in days})
    assert temps == {"2026-10-30": 9.0, "2026-10-31": 9.0, "2026-11-01": 3.0, "2026-11-02": 2.0}
    assert ot.source_by_month(by_day) == {"2026-10": "open_meteo", "2026-11": "ha_sensor"}
    loc = ot.Location(1.0, 2.0, "home")
    part = ot.part_summary(by_day, loc)
    assert part == {
        "source": "mixed", "ha_sensor_days": 2, "open_meteo_days": 2,
        "open_meteo_location": "home", "sensor_first_day": "2026-11-01",
    }
    assert ot.combine_parts({"archive": part, "recent": ot.part_summary({"2026-11-21": "ha_sensor"}, loc)})[
        "sensor_since"
    ] == "2026-11-01"
    assert ot.overall_source(0, 5, "utility") == "open_meteo_utility"
    assert ot.overall_source(0, 5, "custom") == "open_meteo_custom"
    assert ot.overall_source(3, 0, None) == "ha_sensor"
    assert ot.overall_source(0, 0, "home") is None
    _, mixed_month = ot.merge_daily(["2026-11-01", "2026-11-02"], {"2026-11-02": 1.0}, {"2026-11-01": 2.0})
    assert ot.source_by_month(mixed_month) == {"2026-11": "mixed"}


def test_signature_is_opaque() -> None:
    sig = ot.source_signature(ot.Location(*UTIL, "utility"), "sensor.ude")
    assert len(sig) == 16 and "56.153" not in sig
    assert sig != ot.source_signature(ot.Location(*UTIL, "utility"), None)
    assert sig != ot.source_signature(ot.Location(*HOME, "home"), "sensor.ude")


# -------------------------------------------------------------- coordinator


def _days(start: dt_mod.date, end: dt_mod.date) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(cur.isoformat())
        cur += dt_mod.timedelta(days=1)
    return out


def _coord(tmp_path, options=None, data=None, home=HOME):
    coord, hass, entry, store = make_coordinator(tmp_path, **(data or {}))
    entry.options = dict(options or {})
    hass.config.latitude, hass.config.longitude = home
    hass.config.components = {"recorder"}
    hass.states.get = MagicMock(return_value=SimpleNamespace(name="Udetermometer"))
    coord._fetch_open_meteo_recent = AsyncMock(return_value={})
    coord._fetch_open_meteo_archive = AsyncMock(return_value={})
    return coord, hass, entry


def _full(days, temp=5.0):
    return {d: (temp, 24) for d in days}


@pytest.mark.asyncio
async def test_weather_from_sensor_only_needs_no_open_meteo(tmp_path) -> None:
    today = copenhagen_today()
    coord, _, _ = _coord(tmp_path, options={"outdoor_temp_entity": "sensor.ude"})
    all_days = _days(dt_mod.date(2022, 1, 1), today)
    means = {**_full(all_days[:-1], 5.0), today.isoformat(): (5.0, 8)}
    with patch("kmd_easy_energy.coordinator.async_sensor_daily_means", AsyncMock(return_value=(means, "ok"))) as sm:
        state: dict = {"monthly": {}}
        await coord._async_update_weather(state)
    coord._fetch_open_meteo_recent.assert_not_awaited()
    coord._fetch_open_meteo_archive.assert_not_awaited()
    assert sm.await_count == 2
    assert state["hdd_7d"] == round(8 * (17 - 5.0), 1)
    coord._enrich_derived(state)
    assert state["temp_source"] == "ha_sensor"
    assert state["outdoor_temp"]["sensor_name"] == "Udetermometer"
    assert state["outdoor_temp"]["entity_id"] == "sensor.ude"
    assert set(state["weather"]["temp_source_by_month"].values()) == {"ha_sensor"}


@pytest.mark.asyncio
async def test_weather_mixed_fetches_only_missing_range_from_home(tmp_path) -> None:
    today = copenhagen_today()
    since = today - dt_mod.timedelta(days=40)
    coord, _, _ = _coord(
        tmp_path,
        options={"outdoor_temp_entity": "sensor.ude"},
        data={"utility_latitude": UTIL[0], "utility_longitude": UTIL[1]},
    )
    sensor = _full(_days(since, today - dt_mod.timedelta(days=1)), 2.0)
    sensor[today.isoformat()] = (2.0, 10)
    coord._fetch_open_meteo_archive = AsyncMock(
        return_value={d: 8.0 for d in _days(dt_mod.date(2022, 1, 1), since - dt_mod.timedelta(days=1))}
    )
    with patch("kmd_easy_energy.coordinator.async_sensor_daily_means", AsyncMock(return_value=(sensor, "ok"))):
        state: dict = {"monthly": {}}
        await coord._async_update_weather(state)
    coord._fetch_open_meteo_recent.assert_not_awaited()  # 7 d window fully covered by the sensor
    args = coord._fetch_open_meteo_archive.await_args.args
    assert args[:2] == HOME  # HA home location, not the utility
    assert args[2] == dt_mod.date(2022, 1, 1) and args[3] == since - dt_mod.timedelta(days=1)
    coord._enrich_derived(state)
    out = state["outdoor_temp"]
    assert state["temp_source"] == "mixed"
    assert out["sensor_since"] == since.isoformat()
    assert out["open_meteo_location"] == "home"
    assert state["weather"]["daily_temp"][(today - dt_mod.timedelta(days=1)).isoformat()] == 2.0
    by_month = state["weather"]["temp_source_by_month"]
    assert by_month.get(since.strftime("%Y-%m")) in ("mixed", "ha_sensor")
    assert "open_meteo" in by_month.values()
    assert not any(str(UTIL[0]) in json.dumps(v) or str(HOME[0]) in json.dumps(v) for v in (out, by_month))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options,home,expect_src,expect_coords",
    [
        ({}, HOME, "open_meteo_home", HOME),
        ({}, (0, 0), "open_meteo_utility", UTIL),
        ({"latitude": CUSTOM[0], "longitude": CUSTOM[1]}, HOME, "open_meteo_custom", CUSTOM),
    ],
)
async def test_weather_open_meteo_location_precedence(tmp_path, options, home, expect_src, expect_coords) -> None:
    today = copenhagen_today()
    coord, _, _ = _coord(
        tmp_path, options=options, data={"utility_latitude": UTIL[0], "utility_longitude": UTIL[1]}, home=home
    )
    window = [(today - dt_mod.timedelta(days=n)).isoformat() for n in range(7, -1, -1)]
    coord._fetch_open_meteo_recent = AsyncMock(return_value={d: 7.0 for d in window})
    coord._fetch_open_meteo_archive = AsyncMock(return_value={"2026-01-01": 1.0})
    state: dict = {"monthly": {}}
    await coord._async_update_weather(state)
    assert coord._fetch_open_meteo_recent.await_args.args == expect_coords
    assert coord._fetch_open_meteo_archive.await_args.args[:2] == expect_coords
    assert state["hdd_7d"] == 80.0
    coord._enrich_derived(state)
    assert state["temp_source"] == expect_src
    assert state["outdoor_temp"]["entity_id"] is None


@pytest.mark.asyncio
async def test_sensor_without_statistics_falls_back_and_reports_status(tmp_path) -> None:
    coord, _, _ = _coord(tmp_path, options={"outdoor_temp_entity": "sensor.ude"})
    coord._fetch_open_meteo_archive = AsyncMock(return_value={"2026-01-01": 1.0})
    with patch("kmd_easy_energy.coordinator.async_sensor_daily_means", AsyncMock(return_value=({}, "no_statistics"))):
        state: dict = {"monthly": {}}
        await coord._async_update_weather(state)
    coord._enrich_derived(state)
    assert state["temp_source"] == "open_meteo_home"
    assert state["outdoor_temp"]["sensor_status"] == "no_statistics"


@pytest.mark.asyncio
async def test_sensor_error_is_contained(tmp_path) -> None:
    coord, _, _ = _coord(tmp_path, options={"outdoor_temp_entity": "sensor.ude"})
    coord._fetch_open_meteo_archive = AsyncMock(return_value={"2026-01-01": 1.0})
    with patch("kmd_easy_energy.coordinator.async_sensor_daily_means", AsyncMock(side_effect=RuntimeError("db"))):
        state: dict = {"monthly": {}}
        await coord._async_update_weather(state)
    coord._enrich_derived(state)
    assert state["outdoor_temp"]["sensor_status"] == "error"
    assert state["temp_source"] == "open_meteo_home"


@pytest.mark.asyncio
async def test_open_meteo_failure_keeps_previous_history(tmp_path) -> None:
    coord, _, _ = _coord(tmp_path)
    state: dict = {"monthly": {}}
    coord._fetch_open_meteo_archive = AsyncMock(return_value={"2026-01-01": 1.0})
    await coord._async_update_weather(state)
    before = dict(state["weather"])
    state["weather_archive_fetched_on"] = "2000-01-01"  # force a new fetch
    coord._fetch_open_meteo_archive = AsyncMock(side_effect=RuntimeError("down"))
    await coord._async_update_weather(state)
    assert state["weather"] == before


@pytest.mark.asyncio
async def test_daily_cache_and_source_change_invalidates(tmp_path) -> None:
    coord, _, entry = _coord(tmp_path)
    coord._fetch_open_meteo_recent = AsyncMock(return_value={"2026-11-20": 1.0})
    coord._fetch_open_meteo_archive = AsyncMock(return_value={"2026-01-01": 1.0})
    state: dict = {"monthly": {}}
    await coord._async_update_weather(state)
    await coord._async_update_weather(state)
    assert coord._fetch_open_meteo_archive.await_count == 1  # once a day
    entry.options = {"latitude": CUSTOM[0], "longitude": CUSTOM[1]}
    coord._enrich_derived(state)
    assert state["outdoor_temp"]["pending"] is True
    await coord._async_update_weather(state)
    assert coord._fetch_open_meteo_archive.await_count == 2  # source changed -> refetch
    coord._enrich_derived(state)
    assert state["temp_source"] == "open_meteo_custom" and state["outdoor_temp"]["pending"] is False


@pytest.mark.asyncio
async def test_options_change_refreshes_weather_without_utility_call(tmp_path) -> None:
    from kmd_easy_energy import _async_entry_updated

    coord = MagicMock()
    coord.is_eforsyning = False
    coord.weather_signature = "new"
    coord.data = {"weather_source_sig": "old"}
    coord.async_refresh_weather = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {"e1": coord}}
    await _async_entry_updated(hass, SimpleNamespace(entry_id="e1"))
    coord.async_refresh_weather.assert_awaited_once()
    coord.data = {"weather_source_sig": "new"}
    coord.async_refresh_weather.reset_mock()
    await _async_entry_updated(hass, SimpleNamespace(entry_id="e1"))
    coord.async_refresh_weather.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_weather_skips_during_sync_and_without_data(tmp_path) -> None:
    coord, _, _ = _coord(tmp_path)
    coord._async_update_weather = AsyncMock()
    coord.data = {}
    await coord.async_refresh_weather()
    coord._async_update_weather.assert_not_awaited()
    coord._sync_task = MagicMock(done=lambda: False)
    coord.data = {"hdd_7d": 3.0}
    await coord.async_refresh_weather()
    coord._async_update_weather.assert_not_awaited()


# ----------------------------------------------- attributes and diagnostics


def test_overview_attributes_are_unrecorded_and_coordinate_free() -> None:
    from kmd_easy_energy.sensor import KMDBaseSensor, KMDOverviewSensor

    coord = MagicMock()
    coord.sync_reminder = lambda: {"last_sync": None}
    coord.data = {
        "temp_source": "mixed",
        "outdoor_temp": {"source": "mixed", "entity_id": "sensor.ude", "sensor_name": "Ude",
                         "sensor_since": "2026-03-01", "latitude": 55.1, "longitude": 12.1},
    }
    entry = SimpleNamespace(entry_id="e1", title="Kredsløb")
    attrs = KMDOverviewSensor(coord, entry).extra_state_attributes
    assert attrs["temp_source"] == "mixed"
    assert attrs["outdoor_temp"]["sensor_name"] == "Ude"
    assert "latitude" not in json.dumps(attrs["outdoor_temp"])
    assert {"temp_source", "outdoor_temp", "weather"} <= KMDBaseSensor._unrecorded_attributes


@pytest.mark.asyncio
async def test_diagnostics_redact_all_coordinates() -> None:
    from kmd_easy_energy.diagnostics import async_get_config_entry_diagnostics

    entry = SimpleNamespace(
        title="Kredsløb", unique_id="k", domain="kmd_easy_energy", version=1, entry_id="e1",
        data={"utility_latitude": 56.987654, "utility_longitude": 10.123456},
        options={"latitude": 57.111111, "longitude": 9.222222, "outdoor_temp_entity": "sensor.ude"},
    )
    coordinator = MagicMock()
    coordinator.data = {"outdoor_temp": {"source": "mixed", "entity_id": "sensor.ude", "configured_location": "custom",
                                         "sensor_since": "2026-03-01", "latitude": 57.111111}}
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {"e1": coordinator}}
    result = await async_get_config_entry_diagnostics(hass, entry)
    blob = json.dumps(result, default=str)
    for secret in ("56.98", "10.12", "57.11", "9.22"):
        assert secret not in blob
    assert result["coordinator"]["outdoor_temp"]["source"] == "mixed"
    assert result["coordinator"]["outdoor_temp"]["configured_location"] == "custom"
    assert result["entry"]["options"]["outdoor_temp_entity"] == "sensor.ude"
