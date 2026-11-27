"""Import hourly district-heating statistics for the Energy dashboard."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_EF_SUPPLIER_ID,
    CONF_PORTAL_URL,
    CONF_PRICE_DKK_PER_KWH,
    CONF_UTILITY_ID,
    DOMAIN,
)
from .insights import (
    MONTH_LABELS_DA,
    copenhagen_today,
    cumulative_statistic_rows,
    hourly_points_to_buckets,
    motivation_dkk_per_kwh,
)
from .tariff import (
    ResolvedTariff,
    earliest_tariff_date,
    load_utilities,
    resolve_tariff,
)

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


def cost_statistic_id(entry_id: str) -> str:
    return f"{DOMAIN}:cost_{_slug_entry_id(entry_id)}"


def _metadata(
    *,
    statistic_id: str,
    name: str,
    unit: str,
    unit_class: str | None,
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


def _num(val: Any) -> float | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        fval = float(val)
        if math.isfinite(fval):
            return fval
    return None


def _pos_num(val: Any) -> float | None:
    fval = _num(val)
    return fval if (fval is not None and fval > 0.0) else None


def _first_num(*vals: Any) -> float | None:
    for val in vals:
        num = _num(val)
        if num is not None:
            return num
    return None


def _first_pos(*vals: Any) -> float | None:
    for val in vals:
        num = _pos_num(val)
        if num is not None:
            return num
    return None


def _has_entry_tariff_context(entry_data: Any, entry_opts: Any) -> bool:
    if not isinstance(entry_data, Mapping) and not isinstance(entry_opts, Mapping):
        return False
    for mapping in (entry_data, entry_opts):
        if not isinstance(mapping, Mapping):
            continue
        for key in (
            CONF_UTILITY_ID,
            CONF_EF_SUPPLIER_ID,
            CONF_PORTAL_URL,
            CONF_PRICE_DKK_PER_KWH,
        ):
            val = mapping.get(key)
            if isinstance(val, str):
                if val.strip():
                    return True
            elif _pos_num(val) is not None:
                return True
    return False


def build_cost_buckets(
    entry: ConfigEntry,
    state: Mapping[str, Any],
    energy_buckets: list[tuple[datetime, float]],
    *,
    utilities: list[dict[str, Any]] | None = None,
) -> list[tuple[datetime, float]]:
    """Convert (start, kWh) buckets to (start, variable DKK) buckets (excl. fixed fees)."""
    if not energy_buckets:
        return []

    entry_data = getattr(entry, "data", None)
    entry_opts = getattr(entry, "options", None)
    if not _has_entry_tariff_context(entry_data, entry_opts):
        cost_est = state.get("cost_estimate")
        flat_price = _pos_num(
            cost_est.get("effective_price_dkk_per_kwh")
            if isinstance(cost_est, Mapping)
            else None
        )
        if flat_price is None:
            flat_price = _pos_num(state.get("energy_price_dkk_per_kwh"))
        if flat_price is None:
            return []
        return [(start, max(0.0, float(kwh) * flat_price)) for start, kwh in energy_buckets]

    utilities = utilities if utilities is not None else load_utilities()
    data_map = entry_data if isinstance(entry_data, Mapping) else {}
    opts_map = entry_opts if isinstance(entry_opts, Mapping) else {}
    tariff_entry: Any = (
        entry
        if (isinstance(entry_data, Mapping) and isinstance(entry_opts, Mapping))
        else SimpleNamespace(data=data_map, options=opts_map)
    )
    earliest_date = earliest_tariff_date(data_map, utilities)
    current_year = copenhagen_today().year

    rt_map = state.get("return_temp") if isinstance(state.get("return_temp"), Mapping) else {}
    daily_rt = (
        state.get("daily_return_temp")
        if isinstance(state.get("daily_return_temp"), Mapping)
        else {}
    )
    daily_fwd = (
        state.get("daily_forward_temp")
        if isinstance(state.get("daily_forward_temp"), Mapping)
        else {}
    )
    daily_exp = (
        state.get("daily_expected_return_temp")
        if isinstance(state.get("daily_expected_return_temp"), Mapping)
        else {}
    )
    cost_est = (
        state.get("cost_estimate")
        if isinstance(state.get("cost_estimate"), Mapping)
        else {}
    )
    current_rt = _first_num(
        cost_est.get("annual_return_temp"),
        cost_est.get("current_return_temp"),
    )

    tariff_cache: dict[tuple[date, float | None, float | None], ResolvedTariff] = {}
    out: list[tuple[datetime, float]] = []

    for start, kwh in energy_buckets:
        day = start.date()
        day_iso = day.isoformat()
        year = day.year
        year_s = str(year)
        month_label = MONTH_LABELS_DA[day.month - 1]

        exp_monthly = rt_map.get(f"expected_monthly_{year}")
        exp_annual = rt_map.get("expected_annual")
        exp_rt = _first_pos(
            exp_monthly.get(month_label) if isinstance(exp_monthly, Mapping) else None,
            daily_exp.get(day_iso),
            exp_annual.get(year_s) if isinstance(exp_annual, Mapping) else None,
        )

        fwd_monthly = rt_map.get(f"forward_monthly_{year}")
        fwd_annual = rt_map.get("forward_annual")
        fwd_temp = _first_pos(
            fwd_monthly.get(month_label) if isinstance(fwd_monthly, Mapping) else None,
            daily_fwd.get(day_iso),
            fwd_annual.get(year_s) if isinstance(fwd_annual, Mapping) else None,
        )

        cache_key = (day, exp_rt, fwd_temp)
        tariff = tariff_cache.get(cache_key)
        if tariff is None:
            tariff = resolve_tariff(
                tariff_entry,
                today=day,
                utilities=utilities,
                expected_return_temp=exp_rt,
                forward_temp=fwd_temp,
            )
            if (
                tariff.price_dkk_per_kwh is None
                and earliest_date is not None
                and day < earliest_date
            ):
                tariff = resolve_tariff(
                    tariff_entry,
                    today=earliest_date,
                    utilities=utilities,
                    expected_return_temp=exp_rt,
                    forward_temp=fwd_temp,
                )
            tariff_cache[cache_key] = tariff

        base_price = tariff.price_dkk_per_kwh
        if base_price is None or base_price <= 0:
            continue

        rt_monthly = rt_map.get(f"monthly_{year}")
        rt_annual = rt_map.get("annual")
        bucket_rt = _first_num(
            rt_monthly.get(month_label) if isinstance(rt_monthly, Mapping) else None,
            daily_rt.get(day_iso),
            rt_annual.get(year_s) if isinstance(rt_annual, Mapping) else None,
            current_rt if year == current_year else None,
        )

        max_adj = (
            base_price * (tariff.motivation_max_pct / 100.0)
            if (tariff.motivation_max_pct is not None and tariff.motivation_max_pct > 0)
            else None
        )
        adj = (
            motivation_dkk_per_kwh(
                bucket_rt,
                tariff.bonus_temp,
                tariff.penalty_temp,
                tariff.motivation_dkk_per_kwh_per_k,
                max_dkk_per_kwh=max_adj,
                allow_bonus=tariff.motivation_bonus,
                bonus_rate=tariff.motivation_bonus_dkk_per_kwh_per_k,
                penalty_rate=tariff.motivation_penalty_dkk_per_kwh_per_k,
            )
            or 0.0
        )
        effective_price = max(0.0, float(base_price) + adj)
        out.append((start, max(0.0, float(kwh) * effective_price)))

    return out


async def async_get_statistics_base_sums(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: Mapping[str, Any],
    *,
    kinds: Iterable[str] | None = None,
) -> dict[str, float]:
    """Read cumulative sum strictly before the earliest bucket per statistic."""
    components = getattr(getattr(hass, "config", None), "components", None)
    if not components or "recorder" not in components:
        return {}

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistic_during_period
    except ImportError:  # pragma: no cover
        return {}

    wanted = set(kinds) if kinds is not None else {"energy", "volume", "cost"}
    queries: list[tuple[str, str, datetime]] = []

    energy_buckets: list[tuple[datetime, float]] = []
    if "energy" in wanted or "cost" in wanted:
        energy_buckets = hourly_points_to_buckets(
            state.get("hourly_kwh") or state.get("daily_stat_kwh") or [],
            complete_only=True,
        )
    if "energy" in wanted and energy_buckets:
        queries.append(
            (
                "energy",
                energy_statistic_id(entry.entry_id),
                energy_buckets[0][0].astimezone(timezone.utc),
            )
        )
    if "volume" in wanted:
        volume_buckets = hourly_points_to_buckets(
            state.get("hourly_m3") or state.get("daily_stat_m3") or [],
            complete_only=True,
        )
        if volume_buckets:
            queries.append(
                (
                    "volume",
                    volume_statistic_id(entry.entry_id),
                    volume_buckets[0][0].astimezone(timezone.utc),
                )
            )
    if "cost" in wanted and energy_buckets:
        cost_buckets = build_cost_buckets(entry, state, energy_buckets)
        if cost_buckets:
            queries.append(
                (
                    "cost",
                    cost_statistic_id(entry.entry_id),
                    cost_buckets[0][0].astimezone(timezone.utc),
                )
            )

    if not queries:
        return {}

    try:
        recorder = get_instance(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Recorder instance unavailable for base sum lookup: %s", err)
        return {}

    base_sums: dict[str, float] = {}
    for kind, stat_id, first_start_utc in queries:
        try:
            res = await recorder.async_add_executor_job(
                statistic_during_period,
                hass,
                None,
                first_start_utc,
                stat_id,
                {"change"},
                None,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Base sum lookup failed for %s: %s", stat_id, err)
            continue
        change = (res or {}).get("change") if isinstance(res, Mapping) else None
        if isinstance(change, (int, float)) and not isinstance(change, bool) and math.isfinite(change):
            base_sums[kind] = float(change)
    return base_sums


def import_hourly_statistics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: dict[str, Any],
    *,
    base_sums: Mapping[str, float] | None = None,
    kinds: Iterable[str] | None = None,
) -> dict[str, int]:
    """Queue external hourly kWh, m³ and variable DKK cost statistics from coordinator state.

    No-ops when the recorder is not set up (typical for unit tests and slim
    check_config). Uses async_add_external_statistics so the Energy dashboard
    can pick `kmd_easy_energy:energy_<entry>` / `:volume_<entry>` /
    `:cost_<entry>` instead of the month-to-date or YTD entity sensors.

    Backends without hourly data (E|Forsyning) provide ``daily_stat_kwh`` /
    ``daily_stat_m3``: one row per day at local midnight, so the Energy
    dashboard shows correct daily totals (not an hourly profile).
    """
    components = getattr(getattr(hass, "config", None), "components", None)
    if not components or "recorder" not in components:
        _LOGGER.debug("Skipping statistics import (recorder not set up)")
        return {"energy": 0, "volume": 0, "cost": 0}

    try:
        from homeassistant.components.recorder.statistics import async_add_external_statistics
    except ImportError:  # pragma: no cover
        _LOGGER.debug("Recorder statistics API unavailable")
        return {"energy": 0, "volume": 0, "cost": 0}

    imported = {"energy": 0, "volume": 0, "cost": 0}
    wanted = set(kinds) if kinds is not None else {"energy", "volume", "cost"}
    title = entry.title or "KMD Easy Energy"

    energy_buckets: list[tuple[datetime, float]] = []
    if "energy" in wanted or "cost" in wanted:
        energy_buckets = hourly_points_to_buckets(
            state.get("hourly_kwh") or state.get("daily_stat_kwh") or [],
            complete_only=True,
        )
    volume_buckets = (
        hourly_points_to_buckets(
            state.get("hourly_m3") or state.get("daily_stat_m3") or [],
            complete_only=True,
        )
        if "volume" in wanted
        else []
    )
    cost_buckets = (
        build_cost_buckets(entry, state, energy_buckets)
        if ("cost" in wanted and energy_buckets)
        else []
    )

    series = (
        (
            "energy",
            energy_buckets,
            energy_statistic_id(entry.entry_id),
            f"{title} energy (hourly)",
            UnitOfEnergy.KILO_WATT_HOUR,
            "energy",
        ),
        (
            "volume",
            volume_buckets,
            volume_statistic_id(entry.entry_id),
            f"{title} volume (hourly)",
            UnitOfVolume.CUBIC_METERS,
            "volume",
        ),
        (
            "cost",
            cost_buckets,
            cost_statistic_id(entry.entry_id),
            f"{title} cost",
            "DKK",
            None,
        ),
    )
    for kind, buckets, stat_id, name, unit, unit_class in series:
        if kind not in wanted or not buckets:
            continue
        initial_sum = float((base_sums or {}).get(kind, 0.0))
        rows = cumulative_statistic_rows(buckets, initial_sum=initial_sum)
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
    if any(imported.values()):
        _LOGGER.debug(
            "Queued Energy statistics: %s kWh hours, %s m³ hours, %s cost hours",
            imported["energy"],
            imported["volume"],
            imported["cost"],
        )
    return imported
