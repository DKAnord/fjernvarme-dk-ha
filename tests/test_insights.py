"""Pure helpers for statistics, motivation, forecasts and leak detection."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from kmd_easy_energy.insights import (
    STATUS_BONUS,
    STATUS_NEUTRAL,
    STATUS_PENALTY,
    cumulative_statistic_rows,
    detect_abnormal_consumption,
    forecast_annual,
    hour_start_local,
    hourly_points_to_buckets,
    kwh_per_hdd,
    merge_hourly_points,
    motivation_dkk_per_kwh,
    motivation_status,
)


def test_hourly_buckets_and_cumulative_sum() -> None:
    series = [
        {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1.0, "IsComplete": True},
        {"DateFrom": "2026-11-01T01:00:00.000Z", "Value": 2.0, "IsComplete": True},
        # incomplete last hour is skipped
        {"DateFrom": "2026-11-01T02:00:00.000Z", "Value": 9.0, "IsComplete": False},
        # duplicate hour averages
        {"DateFrom": "2026-11-01T01:00:00.000Z", "Value": 4.0, "IsComplete": True},
    ]
    buckets = hourly_points_to_buckets(series)
    assert len(buckets) == 2
    # 00:00 UTC on 1 Nov 2026 is 01:00 Copenhagen (CET, UTC+1)
    assert buckets[0][0] == datetime(2026, 11, 1, 1, 0, tzinfo=ZoneInfo("Europe/Copenhagen"))
    assert buckets[1][1] == 3.0  # avg of 2 and 4
    rows = cumulative_statistic_rows(buckets)
    assert rows[0]["state"] == 1.0
    assert rows[0]["sum"] == 1.0
    assert rows[1]["state"] == 3.0
    assert rows[1]["sum"] == 4.0


def test_merge_hourly_points_prefers_complete() -> None:
    merged = merge_hourly_points(
        [{"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1, "IsComplete": False}],
        [{"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 2, "IsComplete": True}],
    )
    assert len(merged) == 1
    assert merged[0]["Value"] == 2
    assert merged[0]["IsComplete"] is True


def test_hour_start_local_floors() -> None:
    dt = datetime(2026, 11, 1, 10, 45, tzinfo=ZoneInfo("Europe/Copenhagen"))
    assert hour_start_local(dt).minute == 0


def test_motivation_status_and_rate() -> None:
    assert motivation_status(25.0, 30.0, 40.0) == STATUS_BONUS
    assert motivation_status(35.0, 30.0, 40.0) == STATUS_NEUTRAL
    assert motivation_status(42.0, 30.0, 40.0) == STATUS_PENALTY
    assert motivation_status(None, 30.0, 40.0) is None
    # 5 °C under 30 °C at 0.01 DKK/kWh/K → -0.05
    assert motivation_dkk_per_kwh(25.0, 30.0, 40.0, 0.01) == -0.05
    assert motivation_dkk_per_kwh(35.0, 30.0, 40.0, 0.01) == 0.0
    assert motivation_dkk_per_kwh(42.0, 30.0, 40.0, 0.01) == 0.02


def test_kwh_per_hdd_and_forecast() -> None:
    end = date(2026, 11, 21)
    daily_kwh = {}
    daily_hdd = {}
    for i in range(14):
        day = end - timedelta(days=i)
        daily_kwh[day] = 20.0
        daily_hdd[day] = 10.0
    assert kwh_per_hdd(daily_kwh, daily_hdd, lookback_days=14, end=end) == 2.0
    result = forecast_annual(1000.0, 2.0, 3100.0, date(2026, 11, 22))
    assert result["normalized_annual_kwh"] == 6200.0
    assert result["forecast_annual_kwh"] is not None
    assert result["forecast_annual_kwh"] > 1000.0
    assert result["remaining_hdd_estimate"] > 0


def test_abnormal_consumption_hdd_adjusted() -> None:
    target = date(2026, 11, 21)  # Saturday
    daily_kwh = {target: 30.0}
    daily_hdd = {target: 10.0}
    for weeks in range(1, 6):
        prior = target - timedelta(days=7 * weeks)
        daily_kwh[prior] = 10.0
        daily_hdd[prior] = 10.0
    result = detect_abnormal_consumption(daily_kwh, daily_hdd, target)
    assert result["abnormal"] is True
    assert result["samples"] == 5
    assert result["expected_kwh"] == 10.0
    assert result["ratio"] == 3.0

    # Same kWh but a much colder day should not trip once HDD-adjusted
    daily_kwh[target] = 20.0
    daily_hdd[target] = 20.0
    ok = detect_abnormal_consumption(daily_kwh, daily_hdd, target)
    assert ok["abnormal"] is False
    assert ok["reason"] == "hdd_adjusted"

    thin = detect_abnormal_consumption({target: 30.0}, {}, target)
    assert thin["abnormal"] is False
    assert thin["reason"] == "insufficient_history"
