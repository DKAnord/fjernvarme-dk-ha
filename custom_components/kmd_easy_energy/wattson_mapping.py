"""Map parsed Watts On heat intervals into the coordinator's state format.

Watts On is expected to deliver hourly heat intervals (the Watts app product
sheet says district heating is shown per hour). Field names for heat are not
verified, so everything here is defensive: whatever the parser could not
identify stays absent, the matching capability is not detected, and the card
hides that part. Daily/monthly/annual values reuse the shared daily mapping.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .eforsyning_mapping import M_KEYS, apply_daily_readings

CPH_TZ = ZoneInfo("Europe/Copenhagen")
KEEP_DAYS = 400
HOURLY_TEMP_DAYS = 31
PROFILE_DAYS = 30


def _local_day(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(CPH_TZ).date().isoformat()


def _weighted(pairs: list[tuple[float, float | None]]) -> float | None:
    """m³-weighted mean of temperatures, plain mean when no volume."""
    num = den = 0.0
    plain: list[float] = []
    for temp, weight in pairs:
        plain.append(temp)
        if weight and weight > 0:
            num += temp * weight
            den += weight
    if den > 0:
        return round(num / den, 1)
    return round(sum(plain) / len(plain), 1) if plain else None


def apply_wattson_data(
    state: dict[str, Any],
    parsed: Any,
    today: date,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge one Watts On fetch (a ``HeatParse``) into ``state`` and return it."""
    meta = dict(meta or {})
    cutoff = datetime(today.year, today.month, today.day, tzinfo=CPH_TZ) - timedelta(days=KEEP_DAYS)
    now_utc = datetime.now(CPH_TZ)

    # 1. Merge intervals into the compact private store {start: [kwh, m3, tf, tr, h]}.
    store: dict[str, list[Any]] = {
        k: v for k, v in (state.get("wattson_hours") or {}).items() if isinstance(v, list)
    }
    for it in parsed.intervals:
        store[it["start"]] = [it.get("kwh"), it.get("m3"), it.get("t_fwd"), it.get("t_ret"), it.get("hours", 1.0)]
    store = {
        k: v
        for k, v in sorted(store.items())
        if cutoff <= datetime.fromisoformat(k) <= now_utc
    }
    state["wattson_hours"] = store

    # 2. Per local day aggregates; only complete days before today.
    days: dict[str, dict[str, Any]] = {}
    for start, (kwh, m3, tf, tr, hrs) in store.items():
        d = days.setdefault(_local_day(start), {"hours": 0.0, "kwh": None, "m3": None, "tr": [], "tf": []})
        d["hours"] += float(hrs or 1.0)
        if kwh is not None:
            d["kwh"] = (d["kwh"] or 0.0) + kwh
        if m3 is not None:
            d["m3"] = (d["m3"] or 0.0) + m3
        if tr is not None:
            d["tr"].append((tr, m3))
        if tf is not None:
            d["tf"].append((tf, m3))
    today_s = today.isoformat()
    rows: list[dict[str, Any]] = []
    for day, agg in sorted(days.items()):
        if day >= today_s or agg["hours"] < 22.5:
            continue
        rows.append(
            {
                "date": day,
                "days": 1,
                "kwh": round(agg["kwh"], 4) if agg["kwh"] is not None else None,
                "m3": round(agg["m3"], 4) if agg["m3"] is not None else None,
                "temp_return": _weighted(agg["tr"]),
                "temp_forward": _weighted(agg["tf"]),
            }
        )
    apply_daily_readings(state, rows, today)

    # 3. Hourly series (only when the data really is hourly).
    interval = parsed.interval_hours or meta.get("interval_hours")
    hourly = bool(store) and (interval or 1.0) <= 1.5
    hourly_kwh = [
        {"DateFrom": k, "Value": v[0], "IsComplete": True} for k, v in store.items() if v[0] is not None
    ]
    hourly_m3 = [
        {"DateFrom": k, "Value": v[1], "IsComplete": True} for k, v in store.items() if v[1] is not None
    ]
    temp_cut = (now_utc - timedelta(days=HOURLY_TEMP_DAYS)).isoformat()
    hourly_temp = [
        {"DateFrom": k, "Value": v[3], "IsComplete": True}
        for k, v in store.items()
        if v[3] is not None and k >= temp_cut
    ]
    if hourly:
        if hourly_kwh:
            state["hourly_kwh"] = hourly_kwh
            state["daily_stat_kwh"] = []
        if hourly_m3:
            state["hourly_m3"] = hourly_m3
            state["daily_stat_m3"] = []
        state["hourly_kwh_points"] = len(hourly_kwh)
        state["hourly_temp"] = hourly_temp
        state["has_direct_temp"] = bool(hourly_temp)
        state["data_granularity"] = "hourly" if hourly_kwh else "daily"
        state["hourly"] = _hourly_profile(store, today) if hourly_kwh else {}
    else:
        state["hourly_kwh"] = []
        state["hourly_m3"] = []
        state["hourly_temp"] = []

    detected: set[str] = set()
    if rows and any(r["kwh"] is not None for r in rows):
        detected.update({"daily", "monthly"})
    if hourly and (state.get("hourly") or {}).get("kwh"):
        detected.add("hourly")
    if any(v[1] is not None for v in store.values()):
        detected.add("volume")
    if any(v[3] is not None for v in store.values()):
        detected.add("temperatures")
    wattson_units: list[dict[str, str]] = []
    if hourly_kwh or any(r.get("kwh") is not None for r in rows) or any(v[0] is not None for v in store.values()):
        wattson_units.append({"Name": "kWh"})
    if "volume" in detected:
        wattson_units.append({"Name": "m3"})
    if "temperatures" in detected:
        wattson_units.append({"Name": "°C"})
    state["available_units"] = wattson_units
    state["wattson"] = {
        **meta,
        "keys_seen": getattr(parsed, "keys_seen", []),
        "quality_seen": getattr(parsed, "quality_seen", {}),
        "energy_unit": getattr(parsed, "energy_unit", None),
        "interval_hours": interval,
        "skipped": getattr(parsed, "skipped", {}),
        "assumptions": getattr(parsed, "assumptions", []),
        "intervals_last_fetch": len(parsed.intervals),
        "stored_intervals": len(store),
        "detected": sorted(detected),
    }
    return state


def _hourly_profile(store: dict[str, list[Any]], today: date) -> dict[str, Any]:
    """Average 24-hour kWh profile over recent complete days (as the KMD card expects)."""
    by_day: dict[str, dict[int, float]] = {}
    # Return temperature per (day, hour), so the card can draw its "Retur °C"
    # line (it reads ``ret_temp``; without it only the axis is drawn).
    ret_by_day: dict[str, dict[int, float]] = {}
    first = (today - timedelta(days=PROFILE_DAYS)).isoformat()
    month_prefix = today.strftime("%Y-%m-")
    for start, values in store.items():
        kwh = values[0]
        if kwh is None:
            continue
        loc = datetime.fromisoformat(start).astimezone(CPH_TZ)
        day = loc.date().isoformat()
        if not (first <= day < today.isoformat()):
            continue
        by_day.setdefault(day, {})[loc.hour] = by_day.get(day, {}).get(loc.hour, 0.0) + kwh
        t_ret = values[3] if len(values) > 3 else None
        if t_ret is not None:
            ret_by_day.setdefault(day, {})[loc.hour] = t_ret
    complete = {d: h for d, h in by_day.items() if len(h) >= 23}
    month_days = {d: h for d, h in complete.items() if d.startswith(month_prefix)}
    use = month_days if len(month_days) >= 3 else complete
    if not use:
        return {}
    buckets: list[list[float]] = [[] for _ in range(24)]
    for hours in use.values():
        for hr, val in hours.items():
            buckets[hr].append(val)
    if not all(buckets):
        return {}
    label = (
        f"{M_KEYS[today.month - 1].lower()}-{today.year} MTD ({len(use)} dage)"
        if use is month_days
        else f"seneste {len(use)} dage"
    )
    profile: dict[str, Any] = {
        "period": label,
        "days_averaged": len(use),
        "kwh": [round(sum(b) / len(b), 2) for b in buckets],
    }
    ret_buckets: list[list[float]] = [[] for _ in range(24)]
    for day in use:
        for hr, val in ret_by_day.get(day, {}).items():
            ret_buckets[hr].append(val)
    if any(ret_buckets):
        profile["ret_temp"] = [round(sum(b) / len(b), 1) if b else None for b in ret_buckets]
    return profile
