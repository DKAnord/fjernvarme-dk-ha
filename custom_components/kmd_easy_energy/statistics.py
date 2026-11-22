"""Import hourly district-heating statistics for the Energy dashboard."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .insights import cumulative_statistic_rows, hourly_points_to_buckets

_LOGGER = logging.getLogger(__name__)


def _mean_type_none() -> Any:
    try:
        from homeassistant.components.recorder.models.statistics import StatisticMeanType

        return StatisticMeanType.NONE
    except (ImportError, AttributeError):  # pragma: no cover - older HA
        return None


def _slug_entry_id(entry_id: str) -> str:
    """Normalize a Home Assistant config entry ULID/ID to lowercase statistic_id slug."""
    return re.sub(r"[^a-z0-9_]", "_", str(entry_id).lower())


def energy_statistic_id(entry_id: str) -> str:
    return f"{DOMAIN}:energy_{_slug_entry_id(entry_id)}"


def volume_statistic_id(entry_id: str) -> str:
    return f"{DOMAIN}:volume_{_slug_entry_id(entry_id)}"


def _metadata(
    *,
    statistic_id: str,
    name: str,
    unit: str,
    unit_class: str,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "has_mean": False,
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": unit,
        "unit_class": unit_class,
    }
    mean_type = _mean_type_none()
    if mean_type is not None:
        meta["mean_type"] = mean_type
    return meta


def import_hourly_statistics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: dict[str, Any],
) -> dict[str, int]:
    """Queue external hourly kWh and m³ statistics from coordinator state.

    No-ops when the recorder is not set up (typical for unit tests and slim
    check_config). Uses async_add_external_statistics so the Energy dashboard
    can pick `kmd_easy_energy:energy_<entry>` / `:volume_<entry>` instead of
    the month-to-date entity sensors.
    """
    components = getattr(getattr(hass, "config", None), "components", None)
    if not components or "recorder" not in components:
        _LOGGER.debug("Skipping statistics import (recorder not set up)")
        return {"energy": 0, "volume": 0}

    try:
        from homeassistant.components.recorder.statistics import async_add_external_statistics
    except ImportError:  # pragma: no cover
        _LOGGER.debug("Recorder statistics API unavailable")
        return {"energy": 0, "volume": 0}

    imported = {"energy": 0, "volume": 0}
    title = entry.title or "KMD Easy Energy"
    series = (
        (
            "energy",
            state.get("hourly_kwh") or [],
            energy_statistic_id(entry.entry_id),
            f"{title} energy (hourly)",
            UnitOfEnergy.KILO_WATT_HOUR,
            "energy",
        ),
        (
            "volume",
            state.get("hourly_m3") or [],
            volume_statistic_id(entry.entry_id),
            f"{title} volume (hourly)",
            UnitOfVolume.CUBIC_METERS,
            "volume",
        ),
    )
    for kind, points, stat_id, name, unit, unit_class in series:
        buckets = hourly_points_to_buckets(points, complete_only=True)
        rows = cumulative_statistic_rows(buckets)
        if not rows:
            continue
        try:
            async_add_external_statistics(
                hass,
                _metadata(statistic_id=stat_id, name=name, unit=unit, unit_class=unit_class),
                rows,
            )
            imported[kind] = len(rows)
        except (HomeAssistantError, TypeError, ValueError) as err:
            _LOGGER.warning("Could not import %s statistics: %s", kind, err)
    if imported["energy"] or imported["volume"]:
        _LOGGER.debug(
            "Queued Energy statistics: %s kWh hours, %s m³ hours",
            imported["energy"],
            imported["volume"],
        )
    return imported
