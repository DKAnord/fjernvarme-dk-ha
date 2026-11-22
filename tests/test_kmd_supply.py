"""Synthetic KMD / MF2 multi-kundeforhold selection (no live or real meter data)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from kmd_easy_energy.coordinator import (
    _compute_weather_and_insights,
    clear_consumption_cache,
    consumption_history_stale,
    refresh_insights,
)
from kmd_easy_energy.kmd_supply import (
    classify_kmd_meter,
    extract_customers,
    select_heat_meter,
    supply_key,
    diagnostics_supplies,
    customer_identity,
)


# Obviously fake identifiers — not copied from any live account.
EL_GSRN = "571300000000000001"
HEAT_GSRN = "575500000000000001"
EL_METER = "10000001"
HEAT_METER = "20000002"
WATER_METER = "20000003"


def _unit(*names: str) -> list[dict]:
    return [{"Id": i, "Name": n, "Decimals": 2} for i, n in enumerate(names, 1)]


def _el_meter() -> dict:
    return {
        "InstallationId": "inst-el-synth",
        "MeasurementPointId": "mp-el-synth",
        "Name": f"El ({EL_METER} - {EL_GSRN} - E17, Forbrug)",
        "Type": "El",
        "TypeCode": "E17",
        "EAN": EL_GSRN,
        "MeterNumber": EL_METER,
        "Units": _unit("kWh"),
    }


def _heat_meter() -> dict:
    return {
        "InstallationId": "inst-heat-synth",
        "MeasurementPointId": "mp-heat-synth",
        "Name": f"Varme ({HEAT_METER} - {HEAT_GSRN})",
        "Type": "Varme",
        "MeterNumber": HEAT_METER,
        "Units": _unit("kWh", "m3", "°C"),
    }


def _water_meter() -> dict:
    return {
        "InstallationId": "inst-heat-synth",
        "MeasurementPointId": "mp-water-synth",
        "Name": f"Vand ({WATER_METER})",
        "Type": "Vand",
        "MeterNumber": WATER_METER,
        "Units": _unit("m3"),
    }


def _split_account() -> list[dict]:
    """Two kundeforhold: #1 electricity (default), #2 heat + water."""
    return [
        {
            "customer": {"CustomerId": "cust-el-synth", "CustomerNumber": "cn-el"},
            "customer_index": 1,
            "customer_id": "cust-el-synth",
            "customer_number": "cn-el",
            "meters": [_el_meter()],
        },
        {
            "customer": {"CustomerId": "cust-heat-synth", "CustomerNumber": "cn-heat"},
            "customer_index": 2,
            "customer_id": "cust-heat-synth",
            "customer_number": "cn-heat",
            "meters": [_heat_meter(), _water_meter()],
        },
    ]


def test_classify_el_e17_and_gsrn() -> None:
    assert classify_kmd_meter(_el_meter()) == "electricity"


def test_classify_varme_by_type_and_units() -> None:
    assert classify_kmd_meter(_heat_meter()) == "heat"


def test_classify_vand_by_type_and_m3_only() -> None:
    assert classify_kmd_meter(_water_meter()) == "water"


def test_classify_consumption_type_ids() -> None:
    assert classify_kmd_meter({"ConsumptionType": 5, "Units": _unit("kWh")}) == "heat"
    assert classify_kmd_meter({"ConsumptionTypeId": 6, "Units": _unit("m3")}) == "water"


def test_extract_customers_and_identity() -> None:
    profile = {
        "Customers": [
            {"CustomerId": "cust-el-synth", "CustomerNumber": "cn-el"},
            {"CustomerId": "cust-heat-synth", "CustomerNumber": "cn-heat"},
        ]
    }
    customers = extract_customers(profile)
    assert len(customers) == 2
    assert customer_identity(customers[1]) == ("cust-heat-synth", "cn-heat")
    assert extract_customers({"Profile": {"customers": [{"Id": "x", "Number": "y"}]}})[0][
        "Id"
    ] == "x"


def test_select_heat_skips_default_el_kundeforhold() -> None:
    result = select_heat_meter(_split_account())
    assert result["status"] == "ok"
    assert result["account"]["customer_id"] == "cust-heat-synth"
    assert result["meter"]["MeasurementPointId"] == "mp-heat-synth"
    assert result["meter"]["Type"] == "Varme"
    assert result["supplies"]["selection"] == "auto"
    assert result["supplies"]["customer_count"] == 2
    kinds = {row["kind"] for row in result["supplies"]["meters"]}
    assert kinds == {"electricity", "heat", "water"}
    selected = [row for row in result["supplies"]["meters"] if row["selected"]]
    assert len(selected) == 1
    assert selected[0]["kind"] == "heat"


def test_never_silently_use_el_when_no_heat() -> None:
    only_el = [
        {
            "customer_index": 1,
            "customer_id": "cust-el-synth",
            "customer_number": "cn-el",
            "meters": [_el_meter()],
        }
    ]
    result = select_heat_meter(only_el)
    assert result["status"] == "no_heat"
    assert result["meter"] is None


def test_multiple_heat_meters_require_choice() -> None:
    heat_b = _heat_meter()
    heat_b["MeasurementPointId"] = "mp-heat-b-synth"
    accounts = [
        {
            "customer_index": 1,
            "customer_id": "cust-heat-a",
            "meters": [_heat_meter()],
        },
        {
            "customer_index": 2,
            "customer_id": "cust-heat-b",
            "meters": [heat_b],
        },
    ]
    result = select_heat_meter(accounts)
    assert result["status"] == "multiple"
    assert result["meter"] is None

    key = supply_key("cust-heat-b", "mp-heat-b-synth")
    chosen = select_heat_meter(accounts, preferred_key=key)
    assert chosen["status"] == "ok"
    assert chosen["meter"]["MeasurementPointId"] == "mp-heat-b-synth"
    assert chosen["supplies"]["selection"] == "options"


def test_preferred_el_is_ignored() -> None:
    """A stored electricity preference must not win over the heat meter."""
    result = select_heat_meter(
        _split_account(),
        preferred_customer_id="cust-el-synth",
        preferred_measurement_point_id="mp-el-synth",
    )
    assert result["status"] == "ok"
    assert result["meter"]["Type"] == "Varme"


def test_diagnostics_supplies_drop_keys() -> None:
    summary = select_heat_meter(_split_account())["supplies"]
    dumped = str(diagnostics_supplies(summary))
    assert "cust-el-synth" not in dumped
    assert "cust-heat-synth" not in dumped
    assert "mp-heat-synth" not in dumped
    assert "5713" not in dumped
    assert "key" not in dumped
    assert "heat" in dumped


def test_insights_skip_zero_months_and_unreliable_years() -> None:
    # Seasonal 2026 (complete enough), incomplete/zero 2025, current month Nov ignored.
    monthly = {
        "2025": {"Jan": 0, "Feb": 0, "Mar": 0, "Apr": 0},
        "2026": {
            "Jan": 400,
            "Feb": 350,
            "Mar": 280,
            "Apr": 200,
            "Maj": 120,
            "Jun": 80,
            "Jul": 70,
            "Aug": 75,
            "Sep": 110,
            "Okt": 180,
            "Nov": 200,
        },
    }
    # Daily temps so monthly averages exist; winter cold, summer warm.
    daily_temp: dict[str, float] = {}
    temps = {
        1: 1.0,
        2: 2.0,
        3: 4.0,
        4: 8.0,
        5: 12.0,
        6: 16.0,
        7: 18.0,
        8: 17.0,
        9: 13.0,
        10: 8.0,
        11: 5.0,
        12: 2.0,
    }
    for year in (2025, 2026):
        for month, t in temps.items():
            # 3 days per month is enough for a monthly mean.
            for day in (1, 10, 20):
                daily_temp[f"{year}-{month:02d}-{day:02d}"] = t

    with patch("kmd_easy_energy.coordinator.copenhagen_today", return_value=date(2026, 11, 22)):
        out = _compute_weather_and_insights({"monthly": monthly}, daily_temp)
    insights = out["insights"]
    assert "2025" not in insights["kwh_per_hdd"]
    assert "2026" in insights["kwh_per_hdd"]
    assert insights["kwh_per_hdd"]["2026"] > 0
    assert insights["baseload_kwh_mo"] == 72.5  # Jul 70 + Aug 75
    assert insights["temp_r2_pct"] is not None
    assert insights["temp_r2_pct"] > 80
    assert insights["temp_r2_reliable"] is True


def test_insights_no_hdd_when_baseload_eats_year() -> None:
    # Flat high summer and winter — space heating after baseload is 0.
    monthly = {
        "2026": {m: 600 for m in (
            "Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt"
        )}
    }
    daily_temp = {f"2026-{m:02d}-01": (2.0 if m <= 4 else 16.0) for m in range(1, 12)}
    with patch("kmd_easy_energy.coordinator.copenhagen_today", return_value=date(2026, 11, 22)):
        insights = _compute_weather_and_insights({"monthly": monthly}, daily_temp)["insights"]
    assert insights["kwh_per_hdd"] == {}
    assert insights["baseload_kwh_mo"] == 600.0
    assert insights["temp_r2_reliable"] is False


def _seasonal_monthly() -> dict:
    return {
        "2026": {
            "Jan": 400, "Feb": 350, "Mar": 280, "Apr": 200, "Maj": 120,
            "Jun": 80, "Jul": 70, "Aug": 75, "Sep": 110, "Okt": 180, "Nov": 200,
        }
    }


def _seasonal_temps() -> dict[str, float]:
    temps = {1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0, 5: 12.0, 6: 16.0, 7: 18.0, 8: 17.0, 9: 13.0, 10: 8.0, 11: 5.0}
    daily: dict[str, float] = {}
    for month, temp in temps.items():
        for day in (1, 10, 20):
            daily[f"2026-{month:02d}-{day:02d}"] = temp
    return daily


def test_insights_recomputed_when_weather_archive_already_fetched() -> None:
    """Same-day resync after switching to Varme must not keep the El insights."""
    daily_temp = _seasonal_temps()
    flat = {"2026": {m: 600 for m in (
        "Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt"
    )}}
    with patch("kmd_easy_energy.coordinator.copenhagen_today", return_value=date(2026, 11, 22)):
        stale = _compute_weather_and_insights({"monthly": flat}, daily_temp)
        state = {
            "monthly": _seasonal_monthly(),
            "weather": stale["weather"],
            "insights": stale["insights"],
            "weather_archive_fetched_on": "2026-11-22",
        }
        assert state["insights"]["kwh_per_hdd"] == {}
        assert state["insights"]["temp_r2_reliable"] is False
        refresh_insights(state)
    assert state["insights"]["temp_r2_reliable"] is True
    assert state["insights"]["temp_r2_pct"] > 80
    assert state["insights"]["baseload_kwh_mo"] == 72.5
    assert "2026" in state["insights"]["kwh_per_hdd"]
    assert "monthly_hdd" in state["weather"]


def test_consumption_history_stale_when_daily_is_el_and_monthly_is_heat() -> None:
    # Synthetic flat ~20 kWh/day (El-like) vs seasonal monthly totals (Varme).
    history = {f"2026-01-{d:02d}": 20.0 for d in range(1, 32)}
    state = {"daily_kwh_history": history, "monthly": {"2026": {"Jan": 400}}}
    assert consumption_history_stale(state) is True
    # Matching history is not stale.
    state["daily_kwh_history"] = {f"2026-01-{d:02d}": 400 / 31 for d in range(1, 32)}
    assert consumption_history_stale(state) is False


def test_clear_consumption_cache_keeps_weather() -> None:
    state = {
        "monthly": {"2026": {"Jan": 400}},
        "hourly_kwh": [{"DateFrom": "2026-01-01T00:00:00+01:00", "Value": 1}],
        "hourly": {"kwh": [0.17] * 24, "days_averaged": 10},
        "insights": {"temp_r2_pct": 0.5},
        "daily_kwh_history": {"2026-01-01": 20},
        "weather": {"monthly_temp": {"2026-01": 1.0}},
        "weather_archive_fetched_on": "2026-11-22",
        "selected_supply_key": "cust-el::mp-el",
    }
    clear_consumption_cache(state)
    assert "monthly" not in state
    assert "hourly_kwh" not in state
    assert "hourly" not in state
    assert "insights" not in state
    assert "daily_kwh_history" not in state
    assert state["weather"]["monthly_temp"]["2026-01"] == 1.0
    assert state["weather_archive_fetched_on"] == "2026-11-22"
    assert state["selected_supply_key"] == "cust-el::mp-el"
