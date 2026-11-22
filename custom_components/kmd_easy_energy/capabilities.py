"""Backend capabilities: what a backend can deliver and what the cache holds.

``backend_capabilities`` is static per backend and decides which entities are
created. ``effective_capabilities`` intersects it with the data actually in
the cache, so the card can hide graphs, tiles and sections that would
otherwise be empty or show "unknown".
"""

from __future__ import annotations

from typing import Any

from .const import BACKEND_EFORSYNING, BACKEND_KMD

CAP_HOURLY = "hourly"
CAP_DAILY = "daily"
CAP_MONTHLY = "monthly"
CAP_TEMPERATURES = "temperatures"
CAP_VOLUME = "volume"
CAP_COST = "cost"
CAP_BILLING = "billing"
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
            CAP_FORECAST,
            CAP_MITID,
            CAP_REMINDER,
        }
    ),
    # E|Forsyning: daily readings (kWh, m³, frem/retur °C); no hourly data,
    # no balance/invoices and no settlement forecast in this backend (yet).
    BACKEND_EFORSYNING: frozenset(
        {
            CAP_DAILY,
            CAP_MONTHLY,
            CAP_TEMPERATURES,
            CAP_VOLUME,
            CAP_COST,
            CAP_REMINDER,
            CAP_AUTO_SYNC,
        }
    ),
}

_DATA_CAPS = (
    CAP_HOURLY,
    CAP_DAILY,
    CAP_MONTHLY,
    CAP_TEMPERATURES,
    CAP_VOLUME,
    CAP_COST,
    CAP_BILLING,
    CAP_FORECAST,
)


def backend_capabilities(backend: str | None) -> frozenset[str]:
    return BACKEND_CAPABILITIES.get(backend or BACKEND_KMD, BACKEND_CAPABILITIES[BACKEND_KMD])


def _has(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    return bool(value)


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
    if (
        _has(s.get("return_temp"))
        or _has(s.get("hourly_temp"))
        or _has((s.get("latest_reading") or {}).get("temp_return"))
    ):
        caps.add(CAP_TEMPERATURES)
    if _has(s.get("hourly_m3")) or _has(s.get("daily_m3_history")):
        caps.add(CAP_VOLUME)
    if s.get("energy_price_dkk_per_kwh"):
        caps.add(CAP_COST)
    if _has(s.get("billing")) or "Balance" in (s.get("balance") or {}):
        caps.add(CAP_BILLING)
    if _has((s.get("forecast") or {}).get("expected_kwh")):
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
