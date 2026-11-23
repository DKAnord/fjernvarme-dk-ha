"""Map normalised E|Forsyning readings into the coordinator's state format.

E|Forsyning delivers daily (reading-based) values, not hourly data. This
module fills the same keys the KMD backend fills (``daily``, ``monthly``,
``annual``, ``daily_kwh_history``, ``return_temp`` ...) and leaves the hourly
keys untouched/empty so sensors and the card show "unknown" instead of
invented values. Energy statistics are built from daily rows (one row per
day at local midnight) via ``daily_stat_kwh`` / ``daily_stat_m3``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

CPH_TZ = ZoneInfo("Europe/Copenhagen")
M_KEYS = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
M_FULL = [
    "Januar", "Februar", "Marts", "April", "Maj", "Juni",
    "Juli", "August", "September", "Oktober", "November", "December",
]
# Keep roughly two years of daily rows in the private cache.
KEEP_DAYS = 800
# A year total is only reported when history starts within this many days of 1 Jan.
YEAR_START_SLACK_DAYS = 7


def _num(v: float) -> int | float:
    return int(v) if float(v).is_integer() else round(float(v), 2)


def _spread(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    """Per-day values; multi-day lines are spread evenly over their days."""
    out: dict[str, float] = {}
    for row in rows:
        val = row.get(key)
        if val is None:
            continue
        days = int(row.get("days") or 1)
        if days <= 1:
            out[row["date"]] = float(val)
            continue
        start = date.fromisoformat(row["date_from"])
        share = float(val) / days
        for n in range(days):
            out[(start + timedelta(days=n)).isoformat()] = share
    return out


def _midnight_iso(day: str) -> str:
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, tzinfo=CPH_TZ).isoformat()


def _weighted_temp(days: list[str], temps: dict[str, float], m3: dict[str, float]) -> float | None:
    num = 0.0
    den = 0.0
    plain: list[float] = []
    for d in days:
        t = temps.get(d)
        if t is None or t <= 0:
            continue
        plain.append(t)
        w = m3.get(d)
        if w and w > 0:
            num += t * w
            den += w
    if den > 0:
        return round(num / den, 1)
    if plain:
        return round(sum(plain) / len(plain), 1)
    return None


def apply_eforsyning_data(
    state: dict[str, Any], fetched: dict[str, Any], today: date
) -> dict[str, Any]:
    """Merge one E|Forsyning fetch into ``state`` (in place) and return it."""
    rows = [r for r in (fetched.get("readings") or []) if isinstance(r, dict) and r.get("date")]
    apply_daily_readings(state, rows, today)
    state["eforsyning"] = {
        "years": fetched.get("years") or [],
        "year_marker": fetched.get("year_marker") or {},
        "installation": fetched.get("installation") or {},
        "readings_last_fetch": len(rows),
    }
    return state


def apply_daily_readings(
    state: dict[str, Any], rows: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    """Merge normalised daily rows into ``state`` (shared by daily backends).

    Each row: ``date`` (ISO, local day), optional ``kwh``, ``m3``,
    ``temp_return``, ``temp_forward`` and ``days``/``date_from`` for
    multi-day readings. Hourly keys are cleared; a backend with hourly data
    sets them afterwards.
    """
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    today_s = today.isoformat()

    def merged(key: str, new: dict[str, float]) -> dict[str, float]:
        cur = {k: float(v) for k, v in (state.get(key) or {}).items() if isinstance(v, (int, float))}
        cur.update(new)
        return {k: round(v, 4) for k, v in sorted(cur.items()) if cutoff <= k < today_s}

    kwh = merged("daily_kwh_history", _spread(rows, "kwh"))
    m3 = merged("daily_m3_history", _spread(rows, "m3"))
    temps: dict[str, float] = {
        k: float(v) for k, v in (state.get("daily_return_temp") or {}).items()
        if isinstance(v, (int, float))
    }
    fwd: dict[str, float] = {
        k: float(v) for k, v in (state.get("daily_forward_temp") or {}).items()
        if isinstance(v, (int, float))
    }
    exp_ret: dict[str, float] = {
        k: float(v) for k, v in (state.get("daily_expected_return_temp") or {}).items()
        if isinstance(v, (int, float))
    }
    for row in rows:
        if row.get("temp_return") is not None and row["temp_return"] > 0:
            temps[row["date"]] = round(float(row["temp_return"]), 2)
        if row.get("temp_forward") is not None and row["temp_forward"] > 0:
            fwd[row["date"]] = round(float(row["temp_forward"]), 2)
        if row.get("temp_expected_return") is not None and row["temp_expected_return"] > 0:
            exp_ret[row["date"]] = round(float(row["temp_expected_return"]), 2)
    temps = {k: v for k, v in sorted(temps.items()) if cutoff <= k < today_s}
    fwd = {k: v for k, v in sorted(fwd.items()) if cutoff <= k < today_s}
    exp_ret = {k: v for k, v in sorted(exp_ret.items()) if cutoff <= k < today_s}

    state["daily_kwh_history"] = kwh
    state["daily_m3_history"] = m3
    state["daily_return_temp"] = temps
    state["daily_forward_temp"] = fwd
    state["daily_expected_return_temp"] = exp_ret

    # Current month ("daily") in the same shape as the KMD backend.
    yr, mo = today.year, today.month
    prefix = f"{yr}-{mo:02d}-"
    days = {str(int(k[8:10])): _num(v) for k, v in kwh.items() if k.startswith(prefix)}
    if days:
        vals = list(days.values())
        latest = max(k for k in kwh if k.startswith(prefix))
        state["daily"] = {
            "month": f"{M_FULL[mo - 1]} {yr}",
            "days": days,
            "total": round(sum(vals), 2),
            "gennemsnit": round(sum(vals) / len(vals), 1),
            "minimum": min(vals),
            "maksimum": max(vals),
            "latest_date": latest,
            "latest_complete": True,
        }
    else:
        state["daily"] = {"month": f"{M_FULL[mo - 1]} {yr}", "days": {}, "total": None}
    m3_month = [v for k, v in m3.items() if k.startswith(prefix)]
    state["daily_m3"] = {"total": round(sum(m3_month), 3) if m3_month else None}

    # Monthly / annual from daily history (only years we can actually cover).
    first_day = min(kwh) if kwh else None
    monthly: dict[str, dict[str, int | float]] = {}
    for k, v in kwh.items():
        y, m = k[:4], int(k[5:7])
        bucket = monthly.setdefault(y, {})
        bucket[M_KEYS[m - 1]] = bucket.get(M_KEYS[m - 1], 0.0) + v
    for y, bucket in monthly.items():
        for mk in list(bucket):
            bucket[mk] = _num(bucket[mk])
    state["monthly"] = {y: monthly[y] for y in sorted(monthly) if int(y) >= yr - 1}
    annual: dict[str, int] = {}
    if first_day:
        for y in state["monthly"]:
            year_start = date(int(y), 1, 1)
            if date.fromisoformat(first_day) <= year_start + timedelta(days=YEAR_START_SLACK_DAYS):
                annual[y] = round(sum(v for k, v in kwh.items() if k.startswith(f"{y}-")))
    state["annual"] = annual

    # Return temperature: m³-weighted averages per month and per year.
    rt: dict[str, Any] = {"annual": {}}
    exp_annual: dict[str, float] = {}
    for y in (yr - 1, yr):
        ys = str(y)
        ydays = [d for d in temps if d.startswith(f"{ys}-")]
        avg = _weighted_temp(ydays, temps, m3)
        if avg is not None:
            rt["annual"][ys] = avg
        months: dict[str, float] = {}
        for m in range(1, 13):
            mdays = [d for d in ydays if int(d[5:7]) == m]
            mavg = _weighted_temp(mdays, temps, m3)
            if mavg is not None:
                months[M_KEYS[m - 1]] = mavg
        if months:
            rt[f"monthly_{ys}"] = months

        eydays = [d for d in exp_ret if d.startswith(f"{ys}-")]
        eavg = _weighted_temp(eydays, exp_ret, m3)
        if eavg is not None:
            exp_annual[ys] = eavg
        emonths: dict[str, float] = {}
        for m in range(1, 13):
            emdays = [d for d in eydays if int(d[5:7]) == m]
            emavg = _weighted_temp(emdays, exp_ret, m3)
            if emavg is not None:
                emonths[M_KEYS[m - 1]] = emavg
        if emonths:
            rt[f"expected_monthly_{ys}"] = emonths
    if exp_annual:
        rt["expected_annual"] = exp_annual
    state["return_temp"] = rt
    if temps:
        last_day = max(temps)
        latest_entry: dict[str, Any] = {
            "date": last_day,
            "temp_return": temps.get(last_day),
            "temp_forward": fwd.get(last_day),
            "kwh": kwh.get(last_day),
            "m3": m3.get(last_day),
        }
        if last_day in exp_ret:
            latest_entry["temp_expected_return"] = exp_ret[last_day]
        state["latest_reading"] = latest_entry
    else:
        state["latest_reading"] = {}

    # Energy statistics from daily rows (no hourly data from E|Forsyning).
    state["daily_stat_kwh"] = [
        {"DateFrom": _midnight_iso(k), "Value": v, "IsComplete": True} for k, v in kwh.items()
    ]
    state["daily_stat_m3"] = [
        {"DateFrom": _midnight_iso(k), "Value": v, "IsComplete": True} for k, v in m3.items()
    ]
    # Never pretend to have hourly data.
    state["hourly"] = {}
    state["has_direct_temp"] = False
    state["data_granularity"] = "daily"
    return state
