"""Pure helpers for tariffs, hourly statistics, motivation, forecasts and leak detection."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Iterable
from zoneinfo import ZoneInfo

DK_TZ = ZoneInfo("Europe/Copenhagen")

STATUS_BONUS = "bonus"
STATUS_NEUTRAL = "neutral"
STATUS_PENALTY = "penalty"

# Approximate share of annual HDD17 by calendar month for a Danish climate.
# Used only when a full normal-year curve is not available; user-adjustable
# normal_hdd_year is the scale. Shares sum to 1.0.
_HDD_MONTH_SHARE = {
    1: 0.16,
    2: 0.14,
    3: 0.12,
    4: 0.08,
    5: 0.04,
    6: 0.02,
    7: 0.01,
    8: 0.02,
    9: 0.05,
    10: 0.09,
    11: 0.13,
    12: 0.14,
}

# Default annual HDD17 for Aarhus-area (user-adjustable estimate, not an official DMI normal).
DEFAULT_NORMAL_HDD_YEAR = 3100.0


def copenhagen_today(now: datetime | None = None) -> date:
    """Return today's date in Europe/Copenhagen."""
    if now is None:
        now = datetime.now(tz=DK_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=DK_TZ)
    return now.astimezone(DK_TZ).date()


def parse_iso_dt(value: str | None) -> datetime | None:
    """Parse an API ISO timestamp to an aware datetime (UTC if the input was naive Z/naive)."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DK_TZ)
    return parsed


def hour_start_local(dt: datetime) -> datetime:
    """Floor to the local (Copenhagen) hour start, keeping tzinfo."""
    local = dt.astimezone(DK_TZ)
    return local.replace(minute=0, second=0, microsecond=0)


def compact_hourly_point(item: dict[str, Any], *, factor: float = 1.0) -> dict[str, Any] | None:
    """Keep only the fields needed to rebuild Energy statistics."""
    date_from = item.get("DateFrom")
    if not date_from:
        return None
    val = item.get("Value")
    if val is not None and factor != 1.0:
        val = round(float(val) * factor, 4)
    return {
        "DateFrom": date_from,
        "Value": val,
        "IsComplete": bool(item.get("IsComplete")),
    }


def merge_hourly_points(*series: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate hourly points by DateFrom, preferring complete rows."""
    by_key: dict[str, dict[str, Any]] = {}
    for group in series:
        for raw in group:
            point = compact_hourly_point(raw) if not (
                "DateFrom" in raw and set(raw) <= {"DateFrom", "Value", "IsComplete"}
            ) else {
                "DateFrom": raw["DateFrom"],
                "Value": raw.get("Value"),
                "IsComplete": bool(raw.get("IsComplete")),
            }
            if not point or not point["DateFrom"]:
                continue
            key = str(point["DateFrom"])
            existing = by_key.get(key)
            if existing is None or (point["IsComplete"] and not existing["IsComplete"]):
                by_key[key] = point
    return [by_key[k] for k in sorted(by_key)]


def last_local_day(points: Iterable[dict[str, Any]]) -> date | None:
    """Latest Copenhagen calendar day present in compact hourly points."""
    latest: date | None = None
    for item in points or []:
        parsed = parse_iso_dt(str(item.get("DateFrom") or ""))
        if not parsed:
            continue
        day = hour_start_local(parsed).date()
        if latest is None or day > latest:
            latest = day
    return latest


def hourly_points_to_buckets(
    series: Iterable[dict[str, Any]],
    *,
    complete_only: bool = True,
) -> list[tuple[datetime, float]]:
    """Group complete hourly readings into (local hour-start, kWh or m³)."""
    buckets: dict[datetime, list[float]] = {}
    for item in series:
        if complete_only and not item.get("IsComplete"):
            continue
        value = item.get("Value")
        if value is None:
            continue
        dt = parse_iso_dt(str(item.get("DateFrom") or ""))
        if dt is None:
            continue
        start = hour_start_local(dt)
        buckets.setdefault(start, []).append(float(value))
    out = [
        (start, sum(vals) / len(vals))
        for start, vals in sorted(buckets.items())
    ]
    return out


def cumulative_statistic_rows(
    buckets: list[tuple[datetime, float]],
) -> list[dict[str, Any]]:
    """Build StatisticData-like dicts with a running sum from the first hour."""
    running = 0.0
    rows: list[dict[str, Any]] = []
    for start, value in buckets:
        running += value
        rows.append(
            {
                "start": start,
                "state": round(value, 6),
                "sum": round(running, 6),
            }
        )
    return rows


def motivation_status(
    return_temp: float | None,
    bonus_temp: float,
    penalty_temp: float,
    *,
    allow_bonus: bool = True,
) -> str | None:
    """Return bonus / neutral / penalty, or None when temperature is unknown."""
    if return_temp is None:
        return None
    if allow_bonus and bonus_temp > 0 and return_temp < bonus_temp:
        return STATUS_BONUS
    if penalty_temp > 0 and return_temp > penalty_temp:
        return STATUS_PENALTY
    return STATUS_NEUTRAL


def motivation_dkk_per_kwh(
    return_temp: float | None,
    bonus_temp: float,
    penalty_temp: float,
    rate: float | None,
    *,
    max_dkk_per_kwh: float | None = None,
    allow_bonus: bool = True,
    bonus_rate: float | None = None,
    penalty_rate: float | None = None,
) -> float | None:
    """Variable motivation adjustment in DKK/kWh (negative is a bonus)."""
    if return_temp is None:
        return None
    status = motivation_status(
        return_temp, bonus_temp, penalty_temp, allow_bonus=allow_bonus
    )
    if status is None:
        return None
    eff_bonus_rate = bonus_rate if bonus_rate is not None else rate
    eff_penalty_rate = penalty_rate if penalty_rate is not None else rate
    if status == STATUS_BONUS:
        if eff_bonus_rate is None or eff_bonus_rate < 0:
            return None
        raw = -(bonus_temp - return_temp) * eff_bonus_rate
    elif status == STATUS_PENALTY:
        if eff_penalty_rate is None or eff_penalty_rate < 0:
            return None
        raw = (return_temp - penalty_temp) * eff_penalty_rate
    else:
        fallback_rate = rate if rate is not None else (
            eff_penalty_rate if eff_penalty_rate is not None else eff_bonus_rate
        )
        if fallback_rate is None or fallback_rate < 0:
            return None
        raw = 0.0
    if max_dkk_per_kwh is not None and max_dkk_per_kwh > 0:
        cap = float(max_dkk_per_kwh)
        raw = max(-cap, min(cap, raw))
    return round(raw, 5)


def kwh_per_hdd(
    daily_kwh: dict[date, float],
    daily_hdd: dict[date, float],
    *,
    lookback_days: int = 28,
    end: date | None = None,
) -> float | None:
    """kWh per HDD17 over complete days in the lookback window."""
    if not daily_kwh or not daily_hdd:
        return None
    end = end or max(daily_kwh)
    start = end - timedelta(days=lookback_days - 1)
    used_kwh = 0.0
    used_hdd = 0.0
    days = 0
    cursor = start
    while cursor <= end:
        kwh = daily_kwh.get(cursor)
        hdd = daily_hdd.get(cursor)
        if kwh is not None and hdd is not None and hdd > 0:
            used_kwh += kwh
            used_hdd += hdd
            days += 1
        cursor += timedelta(days=1)
    if days < 5 or used_hdd <= 0:
        return None
    return round(used_kwh / used_hdd, 3)


def _hdd_share_until(day: date) -> float:
    """Fraction of annual HDD elapsed at the end of `day` (inclusive)."""
    total = 0.0
    for month, share in _HDD_MONTH_SHARE.items():
        if month < day.month:
            total += share
        elif month == day.month:
            days_in_month = (
                date(day.year + (1 if day.month == 12 else 0), 1 if day.month == 12 else day.month + 1, 1)
                - timedelta(days=1)
            ).day
            total += share * (day.day / days_in_month)
    return min(1.0, max(0.0, total))


def forecast_annual(
    ytd_kwh: float | None,
    kwh_per_hdd_value: float | None,
    normal_hdd_year: float,
    today: date,
) -> dict[str, float | None]:
    """Year forecast and degree-day-normalised annual consumption."""
    elapsed = _hdd_share_until(today)
    remaining_hdd = max(0.0, (1.0 - elapsed) * normal_hdd_year)
    elapsed_hdd = elapsed * normal_hdd_year
    normalized = (
        round(kwh_per_hdd_value * normal_hdd_year, 1)
        if kwh_per_hdd_value is not None
        else None
    )
    remaining_kwh = (
        round(kwh_per_hdd_value * remaining_hdd, 1)
        if kwh_per_hdd_value is not None
        else None
    )
    forecast = None
    if ytd_kwh is not None and remaining_kwh is not None:
        forecast = round(ytd_kwh + remaining_kwh, 1)
    elif normalized is not None:
        forecast = normalized
    return {
        "kwh_per_hdd": kwh_per_hdd_value,
        "normal_hdd_year": normal_hdd_year,
        "elapsed_hdd_estimate": round(elapsed_hdd, 1),
        "remaining_hdd_estimate": round(remaining_hdd, 1),
        "normalized_annual_kwh": normalized,
        "forecast_annual_kwh": forecast,
        "ytd_kwh": ytd_kwh,
    }


def detect_abnormal_consumption(
    daily_kwh: dict[date, float],
    daily_hdd: dict[date, float] | None,
    target: date,
    *,
    min_samples: int = 3,
    ratio: float = 1.5,
    sigma: float = 2.0,
) -> dict[str, Any]:
    """Compare `target` kWh with the same weekday in previous weeks.

    HDD-adjusts when possible. Returns a dict with `abnormal` (bool), expected
    kWh, ratio and a short reason. Not enough history yields abnormal=False and
    reason="insufficient_history".
    """
    actual = daily_kwh.get(target)
    result: dict[str, Any] = {
        "abnormal": False,
        "target": target.isoformat(),
        "actual_kwh": actual,
        "expected_kwh": None,
        "ratio": None,
        "samples": 0,
        "reason": "no_data",
    }
    if actual is None:
        return result

    samples: list[float] = []
    sample_hdd: list[float] = []
    for weeks_back in range(1, 9):
        prior = target - timedelta(days=7 * weeks_back)
        value = daily_kwh.get(prior)
        if value is None:
            continue
        samples.append(float(value))
        if daily_hdd and prior in daily_hdd:
            sample_hdd.append(float(daily_hdd[prior]))

    result["samples"] = len(samples)
    if len(samples) < min_samples:
        result["reason"] = "insufficient_history"
        return result

    avg = mean(samples)
    target_hdd = (daily_hdd or {}).get(target)
    if (
        target_hdd is not None
        and target_hdd > 0
        and len(sample_hdd) >= min_samples
        and mean(sample_hdd) > 0
    ):
        expected = avg * (target_hdd / mean(sample_hdd))
        result["reason"] = "hdd_adjusted"
    else:
        expected = avg
        result["reason"] = "weekday_average"

    result["expected_kwh"] = round(expected, 2)
    result["ratio"] = round(actual / expected, 3) if expected > 0 else None
    spread = pstdev(samples) if len(samples) >= 2 else 0.0
    threshold = max(expected * ratio, expected + sigma * spread) if expected > 0 else actual + 1
    if actual > threshold and expected > 0:
        result["abnormal"] = True
        result["reason"] = f"{result['reason']}_high"
    return result


def daily_kwh_from_history(
    history: dict[str, Any] | None,
    current_month_days: dict[str, Any] | None,
    month: date,
) -> dict[date, float]:
    """Merge ISO-date history with the dashboard's day-of-month map."""
    out: dict[date, float] = {}
    for key, value in (history or {}).items():
        try:
            day = date.fromisoformat(str(key)[:10])
        except ValueError:
            continue
        if isinstance(value, (int, float)):
            out[day] = float(value)
    if current_month_days:
        for day_s, value in current_month_days.items():
            if not isinstance(value, (int, float)):
                continue
            try:
                day_num = int(day_s)
                out[date(month.year, month.month, day_num)] = float(value)
            except (ValueError, TypeError):
                continue
    return out


def daily_hdd_from_temps(
    daily_temp: dict[str, Any] | None,
    *,
    base: float = 17.0,
) -> dict[date, float]:
    """HDD17 per ISO date from Open-Meteo mean temperatures."""
    out: dict[date, float] = {}
    for key, temp in (daily_temp or {}).items():
        try:
            day = date.fromisoformat(str(key)[:10])
        except ValueError:
            continue
        if not isinstance(temp, (int, float)):
            continue
        out[day] = max(0.0, base - float(temp))
    return out


MONTH_LABELS_DA = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Maj",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Okt",
    "Nov",
    "Dec",
)


def estimate_variable_costs(
    *,
    price_dkk_per_kwh: float | None,
    bonus_temp: float,
    penalty_temp: float,
    motivation_rate: float | None,
    current_return_temp: float | None,
    daily: dict[str, Any] | None,
    monthly_cur_year: dict[str, Any] | None,
    return_temp_monthly: dict[str, Any] | None,
    today: date | None = None,
    max_pct: float | None = None,
    expected_return_monthly: dict[str, Any] | None = None,
    allow_bonus: bool = True,
    annual_fixed_fee_dkk: float = 0.0,
    forecast_annual_kwh: float | None = None,
    bonus_rate: float | None = None,
    penalty_rate: float | None = None,
) -> dict[str, Any]:
    """Estimate heating cost in DKK (variable + optional prorated fixed fees)."""
    if price_dkk_per_kwh is None or price_dkk_per_kwh <= 0:
        return {}
    today = today or copenhagen_today()
    base_price = float(price_dkk_per_kwh)
    max_adj = (base_price * (float(max_pct) / 100.0)) if (max_pct is not None and max_pct > 0) else None
    adj = (
        motivation_dkk_per_kwh(
            current_return_temp,
            bonus_temp,
            penalty_temp,
            motivation_rate,
            max_dkk_per_kwh=max_adj,
            allow_bonus=allow_bonus,
            bonus_rate=bonus_rate,
            penalty_rate=penalty_rate,
        )
        or 0.0
    )
    effective_price = round(max(0.0, base_price + adj), 4)
    adjustment_pct = round((adj / base_price) * 100.0, 1)

    annual_fixed = round(max(0.0, float(annual_fixed_fee_dkk or 0.0)), 2)
    has_fixed = annual_fixed > 0.0
    days_in_year = 366 if calendar.isleap(today.year) else 365
    daily_fixed = (annual_fixed / days_in_year) if has_fixed else 0.0

    cur_label = MONTH_LABELS_DA[today.month - 1]
    daily_obj = daily or {}
    days_map = daily_obj.get("days") or {}
    numeric_days: list[tuple[int, float]] = []
    for k, v in days_map.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        try:
            numeric_days.append((int(k), float(v)))
        except (TypeError, ValueError):
            continue

    latest_day_dkk: int | None = None
    latest_day_kwh: float | None = None
    latest_day_label: str | None = None
    latest_day_num: int | None = None
    if numeric_days:
        numeric_days.sort(key=lambda pair: pair[0])
        if daily_obj.get("latest_complete") is False and len(numeric_days) > 1:
            day_num, day_kwh = numeric_days[-2]
        else:
            day_num, day_kwh = numeric_days[-1]
        latest_day_num = day_num
        latest_day_kwh = round(day_kwh, 1)
        latest_day_dkk = int(round(day_kwh * effective_price + daily_fixed))
        month_name = str(daily_obj.get("month") or cur_label).strip()
        latest_day_label = f"{day_num}. {month_name}"

    cur_dim = calendar.monthrange(today.year, today.month)[1]
    daily_matches_cur_month = (
        str(daily_obj.get("latest_date") or "").startswith(f"{today.year:04d}-{today.month:02d}-")
        or str(daily_obj.get("month") or "").strip().lower().startswith(cur_label.lower())
    )
    if daily_matches_cur_month and latest_day_num is not None:
        cur_month_elapsed_days = min(cur_dim, max(1, latest_day_num))
    else:
        cur_month_elapsed_days = today.day

    rt_map = return_temp_monthly or {}
    monthly_map = monthly_cur_year or {}
    monthly_dkk: dict[str, int] = {}
    monthly_variable_dkk: dict[str, int] = {}
    monthly_fixed_total = 0.0
    current_month_fixed = 0.0
    for month_idx, label in enumerate(MONTH_LABELS_DA, start=1):
        raw_kwh = monthly_map.get(label)
        if not isinstance(raw_kwh, (int, float)) or isinstance(raw_kwh, bool):
            continue
        raw_rt = rt_map.get(label)
        m_rt = float(raw_rt) if isinstance(raw_rt, (int, float)) else current_return_temp
        raw_exp = (expected_return_monthly or {}).get(label)
        if (
            isinstance(raw_exp, (int, float))
            and not isinstance(raw_exp, bool)
            and float(raw_exp) > 0
        ):
            m_bonus = float(raw_exp) if allow_bonus else 0.0
            m_penalty = float(raw_exp)
        else:
            m_bonus = bonus_temp if allow_bonus else 0.0
            m_penalty = penalty_temp
        m_adj = (
            motivation_dkk_per_kwh(
                m_rt,
                m_bonus,
                m_penalty,
                motivation_rate,
                max_dkk_per_kwh=max_adj,
                allow_bonus=allow_bonus,
                bonus_rate=bonus_rate,
                penalty_rate=penalty_rate,
            )
            or 0.0
        )
        m_price = max(0.0, base_price + m_adj)
        var_m = float(raw_kwh) * m_price
        dim = calendar.monthrange(today.year, month_idx)[1]
        m_days = cur_month_elapsed_days if month_idx == today.month else dim
        fix_m = (annual_fixed * (m_days / days_in_year)) if has_fixed else 0.0
        monthly_variable_dkk[label] = int(round(var_m))
        monthly_dkk[label] = int(round(var_m + fix_m))
        monthly_fixed_total += fix_m
        if label == cur_label:
            current_month_fixed = fix_m

    current_month_dkk: int | None = monthly_dkk.get(cur_label)
    current_month_kwh: float | None = (
        float(monthly_map[cur_label])
        if isinstance(monthly_map.get(cur_label), (int, float))
        else None
    )
    if current_month_dkk is None and isinstance(daily_obj.get("total"), (int, float)):
        current_month_kwh = float(daily_obj["total"])
        current_month_fixed = (annual_fixed * (cur_month_elapsed_days / days_in_year)) if has_fixed else 0.0
        current_month_dkk = int(round(current_month_kwh * effective_price + current_month_fixed))

    ytd_dkk = int(sum(monthly_dkk.values())) if monthly_dkk else None
    ytd_variable_dkk = int(sum(monthly_variable_dkk.values())) if monthly_dkk else None
    ytd_fixed_dkk = int(round(monthly_fixed_total)) if (has_fixed and monthly_dkk) else 0

    if (
        isinstance(forecast_annual_kwh, (int, float))
        and not isinstance(forecast_annual_kwh, bool)
        and float(forecast_annual_kwh) > 0
    ):
        fc_kwh: float | None = round(float(forecast_annual_kwh), 1)
        fc_var_dkk: int | None = int(round(fc_kwh * effective_price))
        fc_total_dkk: int | None = int(round(fc_kwh * effective_price + annual_fixed))
    else:
        fc_kwh = None
        fc_var_dkk = None
        fc_total_dkk = None

    return {
        "year": today.year,
        "base_price_dkk_per_kwh": round(base_price, 4),
        "effective_price_dkk_per_kwh": effective_price,
        "adjustment_dkk_per_kwh": round(adj, 5),
        "adjustment_pct": adjustment_pct,
        "current_return_temp": round(float(current_return_temp), 1)
        if current_return_temp is not None
        else None,
        "latest_day_dkk": latest_day_dkk,
        "latest_day_kwh": latest_day_kwh,
        "latest_day_label": latest_day_label,
        "current_month_dkk": current_month_dkk,
        "current_month_kwh": round(current_month_kwh, 1)
        if current_month_kwh is not None
        else None,
        "ytd_dkk": ytd_dkk,
        "monthly_dkk": monthly_dkk,
        "excludes_fixed_fees": not has_fixed,
        "annual_fixed_fee_dkk": annual_fixed,
        "daily_fixed_fee_dkk": round(daily_fixed, 2),
        "current_month_fixed_dkk": int(round(current_month_fixed))
        if (has_fixed and current_month_dkk is not None)
        else 0,
        "ytd_fixed_dkk": ytd_fixed_dkk,
        "ytd_variable_dkk": ytd_variable_dkk,
        "forecast_annual_kwh": fc_kwh,
        "forecast_annual_variable_dkk": fc_var_dkk,
        "forecast_annual_dkk": fc_total_dkk,
    }
