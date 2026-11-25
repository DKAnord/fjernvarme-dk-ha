"""Cross-provider variable cost estimates and percent-based motivation tariffs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from kmd_easy_energy.const import (
    CONF_BONUS_TEMP,
    CONF_MOTIVATION_DKK_PER_KWH_PER_K,
    CONF_PENALTY_TEMP,
    CONF_PRICE_DKK_PER_KWH,
    CONF_UTILITY_ID,
)
from kmd_easy_energy.insights import estimate_variable_costs
from kmd_easy_energy.sensor import (
    KMDEffectivePriceSensor,
    KMDLatestDayCostSensor,
    KMDMonthCostSensor,
    KMDYearCostSensor,
)
from kmd_easy_energy.tariff import resolve_tariff

ROOT = Path(__file__).resolve().parents[1]


def test_percent_motivation_tariff_scales_with_price_and_respects_override() -> None:
    utilities = [
        {
            "id": "aalborg-forsyning",
            "tariffs": [
                {
                    "year": 2026,
                    "price_dkk_per_kwh": 0.956,
                    "motivation_pct_per_k": 2.0,
                    "bonus_temp": 35.0,
                    "penalty_temp": 35.0,
                }
            ],
        }
    ]
    entry = SimpleNamespace(
        data={CONF_UTILITY_ID: "aalborg-forsyning"},
        options={CONF_PRICE_DKK_PER_KWH: 1.0},
    )
    resolved = resolve_tariff(entry, today=date(2026, 11, 22), utilities=utilities)
    assert resolved.price_dkk_per_kwh == 1.0
    assert resolved.motivation_pct_per_k == 2.0
    # 2% of 1.00 DKK/kWh = 0.02 DKK/kWh/°C
    assert resolved.motivation_dkk_per_kwh_per_k == 0.02
    assert resolved.bonus_temp == 35.0 and resolved.penalty_temp == 35.0

    # Explicit DKK/kWh/°C option overrides percent default.
    entry_override = SimpleNamespace(
        data={CONF_UTILITY_ID: "aalborg-forsyning"},
        options={CONF_PRICE_DKK_PER_KWH: 1.0, CONF_MOTIVATION_DKK_PER_KWH_PER_K: 0.015},
    )
    resolved_override = resolve_tariff(
        entry_override, today=date(2026, 11, 22), utilities=utilities
    )
    assert resolved_override.motivation_dkk_per_kwh_per_k == 0.015


def test_estimate_variable_costs_returns_empty_without_price() -> None:
    assert (
        estimate_variable_costs(
            price_dkk_per_kwh=None,
            bonus_temp=30.0,
            penalty_temp=40.0,
            motivation_rate=0.01,
            current_return_temp=28.0,
            daily={"days": {"21": 50.0}, "month": "Nov"},
            monthly_cur_year={"Nov": 500.0},
            return_temp_monthly={"Nov": 28.0},
            today=date(2026, 11, 22),
        )
        == {}
    )


def test_estimate_variable_costs_aalborg_percent_and_kredslob_neutral_zone() -> None:
    # Aalborg-style: base 1.0 DKK/kWh, 2%/°C (0.02), expected return 35 °C
    aal = estimate_variable_costs(
        price_dkk_per_kwh=1.0,
        bonus_temp=35.0,
        penalty_temp=35.0,
        motivation_rate=0.02,
        current_return_temp=30.0,  # 5° better -> -10% -> 0.90 DKK/kWh
        daily={"days": {"20": 50.0, "21": 20.0}, "latest_complete": False, "month": "Nov"},
        monthly_cur_year={"Okt": 1000.0, "Nov": 500.0},
        return_temp_monthly={"Okt": 35.0, "Nov": 30.0},
        today=date(2026, 11, 22),
    )
    assert aal["effective_price_dkk_per_kwh"] == 0.9
    assert aal["adjustment_pct"] == -10.0
    assert aal["latest_day_dkk"] == 45  # 50 kWh (complete day 20) * 0.90
    assert aal["latest_day_label"] == "20. Nov"
    assert aal["monthly_dkk"] == {"Okt": 1000, "Nov": 450}
    assert aal["current_month_dkk"] == 450
    assert aal["ytd_dkk"] == 1450
    assert aal["excludes_fixed_fees"] is True

    # Kredsløb-style: neutral zone 30..40 °C -> 0 adjustment at 34 °C
    kredslob = estimate_variable_costs(
        price_dkk_per_kwh=0.668,
        bonus_temp=30.0,
        penalty_temp=40.0,
        motivation_rate=0.01,
        current_return_temp=34.0,
        daily={"days": {"21": 100.0}, "latest_complete": True, "month": "Nov", "total": 1000.0},
        monthly_cur_year={"Nov": 1000.0},
        return_temp_monthly={"Nov": 34.0},
        today=date(2026, 11, 22),
    )
    assert kredslob["effective_price_dkk_per_kwh"] == 0.668
    assert kredslob["adjustment_pct"] == 0.0
    assert kredslob["latest_day_dkk"] == 67
    assert kredslob["ytd_dkk"] == 668


def test_cost_estimate_sensors_and_translations() -> None:
    coord = MagicMock()
    coord.data = {
        "cost_estimate": {
            "year": 2026,
            "base_price_dkk_per_kwh": 0.668,
            "effective_price_dkk_per_kwh": 0.648,
            "adjustment_dkk_per_kwh": -0.02,
            "adjustment_pct": -3.0,
            "current_return_temp": 28.0,
            "latest_day_dkk": 32,
            "latest_day_kwh": 50.0,
            "latest_day_label": "21. Nov",
            "current_month_dkk": 648,
            "current_month_kwh": 1000.0,
            "ytd_dkk": 7200,
            "monthly_dkk": {"Nov": 648},
            "excludes_fixed_fees": True,
        }
    }
    entry = SimpleNamespace(entry_id="e1", title="Test")
    eff = KMDEffectivePriceSensor(coord, entry)
    day = KMDLatestDayCostSensor(coord, entry)
    mon = KMDMonthCostSensor(coord, entry)
    yr = KMDYearCostSensor(coord, entry)

    assert eff.native_value == 0.648 and eff.extra_state_attributes["adjustment_pct"] == -3.0
    assert day.native_value == 32.0 and day.extra_state_attributes["day"] == "21. Nov"
    assert mon.native_value == 648.0 and mon.extra_state_attributes["kwh"] == 1000.0
    assert yr.native_value == 7200.0 and yr.extra_state_attributes["monthly_dkk"] == {"Nov": 648}

    for rel in ("strings.json", "translations/en.json", "translations/da.json"):
        sensors_tr = json.loads(
            (ROOT / "custom_components" / "kmd_easy_energy" / rel).read_text()
        )["entity"]["sensor"]
        for key in ("effective_energy_price", "latest_day_cost", "month_cost", "year_cost"):
            assert key in sensors_tr and sensors_tr[key]["name"]


def test_estimate_variable_costs_respects_motivation_max_pct_cap() -> None:
    # Middelfart-style: 1.00 DKK/kWh, 1 %/°C (0.01), expected return 37 °C, max ±20 %.
    bonus_capped = estimate_variable_costs(
        price_dkk_per_kwh=1.0,
        bonus_temp=37.0,
        penalty_temp=37.0,
        motivation_rate=0.01,
        current_return_temp=10.0,  # -27 °C would be -27 %, capped at -20 %
        daily={"days": {"21": 100.0}, "latest_complete": True, "month": "Nov"},
        monthly_cur_year={"Nov": 100.0},
        return_temp_monthly={"Nov": 10.0},
        today=date(2026, 11, 23),
        max_pct=20.0,
    )
    assert bonus_capped["adjustment_pct"] == -20.0
    assert bonus_capped["effective_price_dkk_per_kwh"] == 0.8
    assert bonus_capped["latest_day_dkk"] == 80

    penalty_capped = estimate_variable_costs(
        price_dkk_per_kwh=1.0,
        bonus_temp=37.0,
        penalty_temp=37.0,
        motivation_rate=0.01,
        current_return_temp=65.0,  # +28 °C would be +28 %, capped at +20 %
        daily={"days": {"21": 100.0}, "latest_complete": True, "month": "Nov"},
        monthly_cur_year={"Nov": 100.0},
        return_temp_monthly={"Nov": 65.0},
        today=date(2026, 11, 23),
        max_pct=20.0,
    )
    assert penalty_capped["adjustment_pct"] == 20.0
    assert penalty_capped["effective_price_dkk_per_kwh"] == 1.2
    assert penalty_capped["latest_day_dkk"] == 120


def test_estimate_variable_costs_uses_per_month_expected_return_when_present() -> None:
    est = estimate_variable_costs(
        price_dkk_per_kwh=1.0,
        bonus_temp=36.0,
        penalty_temp=36.0,
        motivation_rate=0.01,  # 1%/°C
        current_return_temp=35.0,
        daily={"days": {"21": 100.0}, "latest_complete": True, "month": "Nov"},
        monthly_cur_year={"Jan": 1000.0, "Jul": 1000.0, "Aug": 1000.0},
        return_temp_monthly={"Jan": 35.0, "Jul": 35.0, "Aug": 35.0},
        expected_return_monthly={"Jan": 33.0, "Jul": 39.0},  # Aug falls back to 36.0
        today=date(2026, 11, 23),
        max_pct=20.0,
    )
    # Jan: 35° vs 33° (+2° penalty -> +2% = 1020), Jul: 35° vs 39° (-4° bonus -> -4% = 960),
    # Aug: 35° vs fallback 36° (-1° bonus -> -1% = 990)
    assert est["monthly_dkk"] == {"Jan": 1020, "Jul": 960, "Aug": 990}


def test_estimate_variable_costs_penalty_only_dynamic_months() -> None:
    est = estimate_variable_costs(
        price_dkk_per_kwh=1.0,
        bonus_temp=0.0,
        penalty_temp=40.0,
        motivation_rate=0.01,
        current_return_temp=35.0,
        daily={"days": {"21": 100.0}, "latest_complete": True, "month": "Nov"},
        monthly_cur_year={"Jan": 1000.0, "Jul": 1000.0},
        return_temp_monthly={"Jan": 42.0, "Jul": 35.0},
        expected_return_monthly={"Jan": 37.0, "Jul": 47.0},
        today=date(2026, 11, 25),
        allow_bonus=False,
    )
    assert est["adjustment_pct"] == 0.0
    assert est["effective_price_dkk_per_kwh"] == 1.0
    # Jan: 42° vs 37° (+5% = 1050); Jul: 35° vs 47° (below req, no bonus = 1000)
    assert est["monthly_dkk"] == {"Jan": 1050, "Jul": 1000}


def test_estimate_costs_with_fixed_fee_and_annual_forecast() -> None:
    from kmd_easy_energy.sensor import KMDEnergyPriceSensor

    est = estimate_variable_costs(
        price_dkk_per_kwh=0.93125,
        bonus_temp=40.0,
        penalty_temp=40.0,
        motivation_rate=0.018625,
        current_return_temp=40.0,
        daily={"days": {"24": 40.0}, "latest_complete": True, "month": "Nov", "latest_date": "2026-11-24"},
        monthly_cur_year={"Okt": 1000.0, "Nov": 800.0},
        return_temp_monthly={"Okt": 40.0, "Nov": 40.0},
        today=date(2026, 11, 25),
        annual_fixed_fee_dkk=6733.12,
        forecast_annual_kwh=12000.0,
    )
    assert est["excludes_fixed_fees"] is False
    assert est["annual_fixed_fee_dkk"] == 6733.12
    assert est["daily_fixed_fee_dkk"] == round(6733.12 / 365, 2)
    assert est["latest_day_dkk"] == int(round(40.0 * 0.93125 + 6733.12 / 365))
    okt_fixed = 6733.12 * (31 / 365)
    nov_fixed = 6733.12 * (24 / 365)
    assert est["monthly_dkk"]["Okt"] == int(round(1000.0 * 0.93125 + okt_fixed))
    assert est["monthly_dkk"]["Nov"] == int(round(800.0 * 0.93125 + nov_fixed))
    assert est["current_month_fixed_dkk"] == int(round(nov_fixed))
    assert est["ytd_fixed_dkk"] == int(round(okt_fixed + nov_fixed))
    assert est["forecast_annual_kwh"] == 12000.0
    assert est["forecast_annual_variable_dkk"] == int(round(12000.0 * est["effective_price_dkk_per_kwh"]))
    assert est["forecast_annual_dkk"] == int(round(12000.0 * est["effective_price_dkk_per_kwh"] + 6733.12))

    coord = MagicMock()
    coord.data = {
        "energy_price_dkk_per_kwh": 0.93125,
        "tariff": {
            "tariff_year": 2026,
            "fixed_fee_dkk_per_m2_year": 41.5625,
            "heated_area_m2": 162.0,
            "fixed_fee_dkk_per_year": None,
            "annual_fixed_fee_dkk": 6733.12,
        },
        "cost_estimate": est,
    }
    entry = SimpleNamespace(entry_id="e1", title="Hedensted")
    price_s = KMDEnergyPriceSensor(coord, entry)
    day_s = KMDLatestDayCostSensor(coord, entry)
    mon_s = KMDMonthCostSensor(coord, entry)
    yr_s = KMDYearCostSensor(coord, entry)

    assert price_s.extra_state_attributes["annual_fixed_fee_dkk"] == 6733.12
    assert price_s.extra_state_attributes["heated_area_m2"] == 162.0
    assert day_s.extra_state_attributes["excludes_fixed_fees"] is False
    assert day_s.extra_state_attributes["daily_fixed_fee_dkk"] == round(6733.12 / 365, 2)
    assert mon_s.extra_state_attributes["fixed_fee_dkk"] == int(round(nov_fixed))
    assert yr_s.extra_state_attributes["annual_fixed_fee_dkk"] == 6733.12
    assert yr_s.extra_state_attributes["forecast_annual_dkk"] == est["forecast_annual_dkk"]
