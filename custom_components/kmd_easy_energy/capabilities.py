"""Backend capabilities: what a backend can deliver and what the cache holds.

``backend_capabilities`` is static per backend and decides which entities are
created. ``effective_capabilities`` intersects it with the data actually in
the cache, so the card can hide graphs, tiles and sections that would
otherwise be empty or show "unknown".
"""

from __future__ import annotations

from typing import Any

from .const import BACKEND_EFORSYNING, BACKEND_KMD, BACKEND_WATTSON

CAP_HOURLY = "hourly"
CAP_DAILY = "daily"
CAP_MONTHLY = "monthly"
CAP_TEMPERATURES = "temperatures"
CAP_VOLUME = "volume"
CAP_COST = "cost"
CAP_BILLING = "billing"
CAP_SETTLEMENT = "settlement"
CAP_FORECAST = "forecast"
CAP_MITID = "mitid"
CAP_REMINDER = "reminder"
CAP_AUTO_SYNC = "auto_sync"

# Data capabilities a backend can fill at all.
BACKEND_CAPABILITIES: dict[str, frozenset[str]] = {
    BACKEND_KMD: frozenset(
        {
            CAP_HOURLY,
            CAP_DAILY,
            CAP_MONTHLY,
            CAP_TEMPERATURES,
            CAP_VOLUME,
            CAP_COST,
            CAP_BILLING,
            CAP_SETTLEMENT,
            CAP_FORECAST,
            CAP_MITID,
            CAP_REMINDER,
        }
    ),
    # E|Forsyning: daily readings (kWh, m³, frem/retur °C) + optional billing summary
    # (getberegnregnskab -> settlement vs. aconto); no hourly data or KMD invoices.
    BACKEND_EFORSYNING: frozenset(
        {
            CAP_DAILY,
            CAP_MONTHLY,
            CAP_TEMPERATURES,
            CAP_VOLUME,
            CAP_COST,
            CAP_SETTLEMENT,
            CAP_REMINDER,
            CAP_AUTO_SYNC,
        }
    ),
    # Watts On (Aalborg Forsyning): expected hourly heat data, but the heat
    # field names are not verified, so hourly/temperatures/volume/settlement only
    # count once a sync or option has actually detected them (see DETECTED_CAPABILITIES).
    BACKEND_WATTSON: frozenset(
        {
            CAP_HOURLY,
            CAP_DAILY,
            CAP_MONTHLY,
            CAP_TEMPERATURES,
            CAP_VOLUME,
            CAP_COST,
            CAP_SETTLEMENT,
            CAP_REMINDER,
            CAP_AUTO_SYNC,
        }
    ),
}

# Capabilities that a backend may or may not deliver: their entities are only
# created after a sync or option detected matching data (the entry reloads once then).
DETECTED_CAPABILITIES: dict[str, frozenset[str]] = {
    BACKEND_KMD: frozenset({CAP_SETTLEMENT}),
    BACKEND_EFORSYNING: frozenset({CAP_SETTLEMENT}),
    BACKEND_WATTSON: frozenset({CAP_HOURLY, CAP_TEMPERATURES, CAP_VOLUME, CAP_SETTLEMENT}),
}

_DATA_CAPS = (
    CAP_HOURLY,
    CAP_DAILY,
    CAP_MONTHLY,
    CAP_TEMPERATURES,
    CAP_VOLUME,
    CAP_COST,
    CAP_BILLING,
    CAP_SETTLEMENT,
    CAP_FORECAST,
)


def backend_capabilities(backend: str | None) -> frozenset[str]:
    return BACKEND_CAPABILITIES.get(backend or BACKEND_KMD, BACKEND_CAPABILITIES[BACKEND_KMD])


def entity_capabilities(backend: str | None, detected: Any = None) -> frozenset[str]:
    """Capabilities that decide which entities exist.

    Static for KMD/E|Forsyning. For backends with unverified data (Watts On)
    the optional capabilities are only included once ``detected`` lists them.
    """
    static = backend_capabilities(backend)
    optional = DETECTED_CAPABILITIES.get(backend or BACKEND_KMD)
    if not optional:
        return static
    found = {str(c) for c in (detected or [])}
    return frozenset(c for c in static if c not in optional or c in found)


def _has(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    return bool(value)


def _has_positive_num(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_positive_num(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_positive_num(v) for v in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0


def _has_return_temp(state: dict[str, Any]) -> bool:
    rt = state.get("return_temp")
    if isinstance(rt, dict):
        if _has_positive_num(rt.get("annual")):
            return True
        for key, val in rt.items():
            if str(key).startswith("monthly_") and _has_positive_num(val):
                return True
    hourly_temp = state.get("hourly_temp")
    if isinstance(hourly_temp, list) and any(
        isinstance(pt, dict)
        and isinstance(pt.get("Value"), (int, float))
        and not isinstance(pt.get("Value"), bool)
        for pt in hourly_temp
    ):
        return True
    latest_rt = (state.get("latest_reading") or {}).get("temp_return")
    return isinstance(latest_rt, (int, float)) and not isinstance(latest_rt, bool) and float(latest_rt) > 0


def data_capabilities(state: dict[str, Any] | None) -> set[str]:
    """Data capabilities actually present in a coordinator state/cache."""
    s = state or {}
    caps: set[str] = set()
    if _has((s.get("hourly") or {}).get("kwh")) or _has(s.get("hourly_kwh")):
        caps.add(CAP_HOURLY)
    if _has((s.get("daily") or {}).get("days")) or _has(s.get("daily_kwh_history")):
        caps.add(CAP_DAILY)
    if _has(s.get("monthly")):
        caps.add(CAP_MONTHLY)
    if _has_return_temp(s):
        caps.add(CAP_TEMPERATURES)
    if (
        _has(s.get("hourly_m3"))
        or _has(s.get("daily_m3_history"))
        or ((s.get("daily_m3") or {}).get("total") is not None)
    ):
        caps.add(CAP_VOLUME)
    if s.get("energy_price_dkk_per_kwh"):
        caps.add(CAP_COST)
    bal_val = (s.get("balance") or {}).get("Balance")
    has_bal = isinstance(bal_val, (int, float)) and not isinstance(bal_val, bool)
    if _has(s.get("billing")) or has_bal:
        caps.add(CAP_BILLING)
    rem_val = (s.get("settlement") or {}).get("remaining_dkk")
    if isinstance(rem_val, (int, float)) and not isinstance(rem_val, bool):
        caps.add(CAP_SETTLEMENT)
    exp_kwh = (s.get("forecast") or {}).get("expected_kwh")
    if isinstance(exp_kwh, (int, float)) and not isinstance(exp_kwh, bool) and float(exp_kwh) > 0:
        caps.add(CAP_FORECAST)
    return caps


def effective_capabilities(
    backend: str | None,
    state: dict[str, Any] | None,
    *,
    reminder_enabled: bool = True,
    auto_sync_enabled: bool = False,
) -> list[str]:
    """Static backend caps ∩ data present (+ enabled feature flags), sorted."""
    static = backend_capabilities(backend)
    present = data_capabilities(state)
    caps = {c for c in static if c in _DATA_CAPS and c in present}
    if CAP_MITID in static:
        caps.add(CAP_MITID)
    if CAP_REMINDER in static and reminder_enabled:
        caps.add(CAP_REMINDER)
    if CAP_AUTO_SYNC in static and auto_sync_enabled:
        caps.add(CAP_AUTO_SYNC)
    return sorted(caps)
