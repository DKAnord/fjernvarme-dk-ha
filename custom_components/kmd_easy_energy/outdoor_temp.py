"""Outdoor temperature source: location precedence and HA sensor statistics.

Daily mean outdoor temperatures feed HDD17 (graddage), kWh/HDD and the
temperature lines on the card. Sources, in order:

1. An optional Home Assistant outdoor temperature sensor (local-first): daily
   means are computed from the recorder's *long-term statistics* (hourly
   ``mean``) of that entity. Read-only, no extra database writes.
2. Open-Meteo (external service) for every day the sensor has no (complete)
   statistics for, e.g. history from before the sensor existed. Location:
   explicit override in options -> HA home location -> utility coordinates.

No coordinates are ever exposed in attributes or diagnostics; only the kind of
location (``custom`` / ``home`` / ``utility``) and the sensor's entity id/name.
"""

from __future__ import annotations

import datetime as dt_mod
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_UTILITY_LATITUDE,
    CONF_UTILITY_LONGITUDE,
)
from .insights import DK_TZ

LOC_CUSTOM = "custom"
LOC_HOME = "home"
LOC_UTILITY = "utility"

SOURCE_HA_SENSOR = "ha_sensor"
SOURCE_MIXED = "mixed"
SOURCE_OPEN_METEO = "open_meteo"
OPEN_METEO_SOURCE_BY_LOCATION = {
    LOC_CUSTOM: "open_meteo_custom",
    LOC_HOME: "open_meteo_home",
    LOC_UTILITY: "open_meteo_utility",
}

# Status of the optional sensor (attributes / diagnostics / card hint).
SENSOR_OK = "ok"
SENSOR_NO_STATISTICS = "no_statistics"
SENSOR_NO_RECORDER = "no_recorder"
SENSOR_ERROR = "error"

# A day counts as measured by the sensor only with enough hourly means:
# a full local day has 23-25 hours (DST); today (HDD 7 d window) is partial.
MIN_HOURS_FULL_DAY = 18
MIN_HOURS_TODAY = 6

# Coordinates the old options form pre-filled when HA had no home location.
_FORM_PLACEHOLDERS: tuple[tuple[float, float], ...] = ((56.15, 10.10),)


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    kind: str  # LOC_CUSTOM | LOC_HOME | LOC_UTILITY


def coord_pair(lat: Any, lon: Any) -> tuple[float, float] | None:
    """Valid (lat, lon) or None. 0/0 (HA's unset default) counts as unset."""
    if lat is None or lon is None or isinstance(lat, bool) or isinstance(lon, bool):
        return None
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if la != la or lo != lo:  # NaN
        return None
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return None
    if la == 0.0 and lo == 0.0:
        return None
    return la, lo


def home_location(config: Any) -> tuple[float, float] | None:
    return coord_pair(getattr(config, "latitude", None), getattr(config, "longitude", None))


def utility_location(data: Mapping[str, Any]) -> tuple[float, float] | None:
    """Utility coordinates (new key; legacy ``latitude`` in entry.data before migration)."""
    return coord_pair(data.get(CONF_UTILITY_LATITUDE), data.get(CONF_UTILITY_LONGITUDE)) or coord_pair(
        data.get(CONF_LATITUDE), data.get(CONF_LONGITUDE)
    )


def resolve_location(
    options: Mapping[str, Any], data: Mapping[str, Any], config: Any
) -> Location | None:
    """Open-Meteo location: options override -> HA home -> utility coordinates."""
    override = coord_pair(options.get(CONF_LATITUDE), options.get(CONF_LONGITUDE))
    if override:
        return Location(override[0], override[1], LOC_CUSTOM)
    home = home_location(config)
    if home:
        return Location(home[0], home[1], LOC_HOME)
    util = utility_location(data)
    if util:
        return Location(util[0], util[1], LOC_UTILITY)
    return None


def _same(a: tuple[float, float] | None, b: tuple[float, float] | None, tol: float = 1e-3) -> bool:
    return bool(a and b and abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol)


def migrate_location(
    data: Mapping[str, Any], options: Mapping[str, Any], config: Any
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Entry 1.2 -> 1.3: utility coordinates are metadata, not the user location.

    * ``entry.data`` latitude/longitude (copied from utilities.json at setup)
      move to ``utility_latitude``/``utility_longitude``.
    * ``options`` latitude/longitude stay an explicit override, unless they
      merely equal what the old options form pre-filled (the utility
      coordinates, the HA home location or the 56.15/10.10 placeholder) —
      then they were never a real choice and are dropped, so the entry
      follows the HA home location from now on.

    Returns (data, options, override_dropped).
    """
    new_data = dict(data)
    new_opts = dict(options)
    legacy = coord_pair(new_data.pop(CONF_LATITUDE, None), new_data.pop(CONF_LONGITUDE, None))
    if legacy and coord_pair(new_data.get(CONF_UTILITY_LATITUDE), new_data.get(CONF_UTILITY_LONGITUDE)) is None:
        new_data[CONF_UTILITY_LATITUDE] = legacy[0]
        new_data[CONF_UTILITY_LONGITUDE] = legacy[1]
    utility = utility_location(new_data)
    dropped = False
    if CONF_LATITUDE in new_opts or CONF_LONGITUDE in new_opts:
        opt = coord_pair(new_opts.get(CONF_LATITUDE), new_opts.get(CONF_LONGITUDE))
        implicit = opt is None or any(
            _same(opt, ref) for ref in (utility, home_location(config), *_FORM_PLACEHOLDERS)
        )
        if implicit:
            new_opts.pop(CONF_LATITUDE, None)
            new_opts.pop(CONF_LONGITUDE, None)
            dropped = True
    return new_data, new_opts, dropped


def source_signature(location: Location | None, entity_id: str | None) -> str:
    """Opaque cache key for the configured source (no readable coordinates)."""
    loc = f"{location.kind}:{location.latitude:.3f},{location.longitude:.3f}" if location else "none"
    raw = f"{entity_id or ''}|{loc}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _row_start(value: Any) -> dt_mod.datetime | None:
    if isinstance(value, dt_mod.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_mod.timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return dt_mod.datetime.fromtimestamp(float(value), tz=dt_mod.timezone.utc)
    return None


def daily_means_from_hourly(rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[float, int]]:
    """Hourly statistics rows (``start``, ``mean``) -> {local date: (mean °C, hours)}."""
    acc: dict[str, list[float]] = {}
    for row in rows or []:
        start = _row_start(row.get("start"))
        mean = row.get("mean")
        if start is None or not isinstance(mean, (int, float)) or isinstance(mean, bool):
            continue
        if mean != mean or not (-60.0 <= float(mean) <= 60.0):  # NaN / implausible
            continue
        day = start.astimezone(DK_TZ).date().isoformat()
        acc.setdefault(day, []).append(float(mean))
    return {d: (round(sum(v) / len(v), 1), len(v)) for d, v in sorted(acc.items())}


def usable_sensor_days(
    means: Mapping[str, tuple[float, int]], today: dt_mod.date | None = None
) -> dict[str, float]:
    """Days the sensor covers well enough (full days; today may be partial)."""
    today_s = today.isoformat() if today else None
    out: dict[str, float] = {}
    for day, (temp, hours) in means.items():
        need = MIN_HOURS_TODAY if day == today_s else MIN_HOURS_FULL_DAY
        if hours >= need:
            out[day] = temp
    return out


async def async_sensor_daily_means(
    hass: Any, entity_id: str, start: dt_mod.date, end: dt_mod.date
) -> tuple[dict[str, tuple[float, int]], str]:
    """Daily means of ``entity_id`` from recorder long-term statistics.

    Runs ``statistics_during_period`` in the recorder's executor (read-only)
    and converts to °C. Returns ({date: (mean, hours)}, status).
    """
    if "recorder" not in getattr(hass.config, "components", set()):
        return {}, SENSOR_NO_RECORDER
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
    except ImportError:  # pragma: no cover - recorder always ships with HA
        return {}, SENSOR_NO_RECORDER
    start_dt = dt_mod.datetime.combine(start, dt_mod.time.min, DK_TZ)
    end_dt = dt_mod.datetime.combine(end + dt_mod.timedelta(days=1), dt_mod.time.min, DK_TZ)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start_dt,
        end_dt,
        {entity_id},
        "hour",
        {"temperature": "°C"},
        {"mean"},
    )
    rows = (result or {}).get(entity_id) or []
    if not rows:
        return {}, SENSOR_NO_STATISTICS
    means = daily_means_from_hourly(rows)
    return means, (SENSOR_OK if means else SENSOR_NO_STATISTICS)


def merge_daily(
    days: Iterable[str], sensor: Mapping[str, float], meteo: Mapping[str, float]
) -> tuple[dict[str, float], dict[str, str]]:
    """Per day: the sensor value if present, else Open-Meteo. Returns (temps, source per day)."""
    temps: dict[str, float] = {}
    source: dict[str, str] = {}
    for day in days:
        if day in sensor:
            temps[day], source[day] = sensor[day], SOURCE_HA_SENSOR
        elif day in meteo:
            temps[day], source[day] = meteo[day], SOURCE_OPEN_METEO
    return temps, source


def part_summary(source_by_day: Mapping[str, str], location: Location | None) -> dict[str, Any]:
    """Counts for one period (``recent`` = HDD 7 d, ``archive`` = history)."""
    sensor_days = sorted(d for d, s in source_by_day.items() if s == SOURCE_HA_SENSOR)
    meteo_days = [d for d, s in source_by_day.items() if s == SOURCE_OPEN_METEO]
    return {
        "source": overall_source(len(sensor_days), len(meteo_days), location.kind if location else None),
        "ha_sensor_days": len(sensor_days),
        "open_meteo_days": len(meteo_days),
        "open_meteo_location": location.kind if (location and meteo_days) else None,
        "sensor_first_day": sensor_days[0] if sensor_days else None,
    }


def overall_source(sensor_days: int, meteo_days: int, location_kind: str | None) -> str | None:
    if sensor_days and meteo_days:
        return SOURCE_MIXED
    if sensor_days:
        return SOURCE_HA_SENSOR
    if meteo_days:
        return OPEN_METEO_SOURCE_BY_LOCATION.get(location_kind or "", SOURCE_OPEN_METEO)
    return None


def source_by_month(source_by_day: Mapping[str, str]) -> dict[str, str]:
    """{YYYY-MM: ha_sensor | open_meteo | mixed} for the monthly temperature line."""
    months: dict[str, set[str]] = {}
    for day, src in source_by_day.items():
        months.setdefault(day[:7], set()).add(src)
    return {ym: (next(iter(s)) if len(s) == 1 else SOURCE_MIXED) for ym, s in sorted(months.items())}


def combine_parts(parts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Overall source over the stored periods (``recent`` + ``archive``)."""
    sensor = sum(int((p or {}).get("ha_sensor_days") or 0) for p in parts.values())
    meteo = sum(int((p or {}).get("open_meteo_days") or 0) for p in parts.values())
    loc = next(
        (p.get("open_meteo_location") for p in parts.values() if p and p.get("open_meteo_location")),
        None,
    )
    firsts = [p.get("sensor_first_day") for p in parts.values() if p and p.get("sensor_first_day")]
    return {
        "source": overall_source(sensor, meteo, loc),
        "ha_sensor_days": sensor,
        "open_meteo_days": meteo,
        "open_meteo_location": loc,
        "sensor_since": min(firsts) if firsts else None,
    }
