"""Resolve option-based district-heating prices, with published defaults when known."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_BONUS_TEMP,
    CONF_EF_SUPPLIER_ID,
    CONF_MOTIVATION_DKK_PER_KWH_PER_K,
    CONF_MOTIVATION_PCT_PER_K,
    CONF_NORMAL_HDD_YEAR,
    CONF_PENALTY_TEMP,
    CONF_PORTAL_URL,
    CONF_PRICE_DKK_PER_KWH,
    CONF_PRICE_DKK_PER_M3,
    CONF_UTILITY_ID,
)
from .insights import DEFAULT_NORMAL_HDD_YEAR, copenhagen_today

_LOGGER = logging.getLogger(__name__)

_UTILITIES_PATH = Path(__file__).parent / "utilities.json"
_UTILITIES_CACHE: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ResolvedTariff:
    """Effective prices after options override published defaults."""

    price_dkk_per_kwh: float | None
    price_dkk_per_m3: float | None
    motivation_dkk_per_kwh_per_k: float | None
    bonus_temp: float
    penalty_temp: float
    normal_hdd_year: float
    tariff_year: int
    source: str | None
    source_note: str | None
    utility_id: str
    motivation_pct_per_k: float | None = None
    motivation_max_pct: float | None = None


def load_utilities() -> list[dict[str, Any]]:
    """Load bundled utilities.json (cached for the process lifetime)."""
    global _UTILITIES_CACHE
    if _UTILITIES_CACHE is not None:
        return _UTILITIES_CACHE
    try:
        data = json.loads(_UTILITIES_PATH.read_text(encoding="utf-8"))
        _UTILITIES_CACHE = list(data.get("utilities") or [])
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.warning("Could not load utilities.json: %s", err)
        _UTILITIES_CACHE = []
    return _UTILITIES_CACHE


def cached_utilities() -> list[dict[str, Any]] | None:
    """Return the already-loaded utilities cache without disk I/O."""
    return _UTILITIES_CACHE


_GENERIC_UTILITY_IDS = ("custom", "eforsyning-custom")
_GENERIC_PORTAL_URLS = {"https:", "http:", "https://eforsyning.dk", "http://eforsyning.dk"}


def _norm_portal_url(url: Any) -> str:
    return str(url or "").strip().rstrip("/").lower()


def match_utility_for_entry(
    entry_data: Mapping[str, Any],
    utilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Resolve an entry's utility preset, upgrading generic custom entries when known."""
    utilities = utilities if utilities is not None else load_utilities()
    utility_id = str(entry_data.get(CONF_UTILITY_ID) or "kredslob").strip() or "kredslob"
    if utility_id not in _GENERIC_UTILITY_IDS:
        direct = next((u for u in utilities if u.get("id") == utility_id), None)
        if direct is not None:
            return direct

    supplier_id = str(entry_data.get(CONF_EF_SUPPLIER_ID) or "").strip().lower()
    if supplier_id:
        by_supplier = next(
            (
                u
                for u in utilities
                if u.get("id") not in _GENERIC_UTILITY_IDS
                and str(u.get("eforsyning_supplier_id") or "").strip().lower() == supplier_id
            ),
            None,
        )
        if by_supplier is not None:
            return by_supplier

    portal_url = _norm_portal_url(entry_data.get(CONF_PORTAL_URL))
    if portal_url and portal_url not in _GENERIC_PORTAL_URLS:
        by_portal = next(
            (
                u
                for u in utilities
                if u.get("id") not in _GENERIC_UTILITY_IDS
                and _norm_portal_url(u.get("portal_url")) == portal_url
            ),
            None,
        )
        if by_portal is not None:
            return by_portal

    return next((u for u in utilities if u.get("id") == utility_id), None)


def published_tariff(
    utility_id: str,
    year: int,
    utilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return the bundled tariff dict for utility/year, if one was published."""
    utilities = utilities if utilities is not None else load_utilities()
    match = next((u for u in utilities if u.get("id") == utility_id), None)
    if not match:
        return None
    tariffs = match.get("tariffs") or []
    exact = next((t for t in tariffs if int(t.get("year") or 0) == year), None)
    if exact:
        return exact
    # Prefer the latest year that is not in the future relative to `year`.
    past = [t for t in tariffs if int(t.get("year") or 0) <= year]
    if not past:
        return None
    return max(past, key=lambda t: int(t.get("year") or 0))


def _opt_float(entry: ConfigEntry, key: str, default: float | None = None) -> float | None:
    raw = entry.options.get(key)
    if raw is None:
        raw = entry.data.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value


def resolve_tariff(
    entry: ConfigEntry,
    *,
    today: date | None = None,
    utilities: list[dict[str, Any]] | None = None,
    expected_return_temp: float | None = None,
) -> ResolvedTariff:
    """Options override published defaults; zero/empty option means "use default"."""
    today = today or copenhagen_today()
    matched = match_utility_for_entry(entry.data, utilities)
    utility_id = str(
        (matched or {}).get("id") or entry.data.get(CONF_UTILITY_ID) or "kredslob"
    )
    published = published_tariff(utility_id, today.year, utilities)

    def _published_pos(key: str) -> float | None:
        if published and published.get(key) is not None:
            try:
                value = float(published[key])
            except (TypeError, ValueError):
                return None
            return value if value > 0 else None
        return None

    def _pick(option_key: str, published_key: str) -> float | None:
        option = _opt_float(entry, option_key, None)
        if option is not None and option > 0:
            return option
        return _published_pos(published_key)

    opt_bonus = _opt_float(entry, CONF_BONUS_TEMP, None)
    opt_penalty = _opt_float(entry, CONF_PENALTY_TEMP, None)
    exp_rt = (
        round(float(expected_return_temp), 1)
        if expected_return_temp is not None and float(expected_return_temp) > 0
        else None
    )
    if opt_bonus is not None and opt_bonus > 0:
        bonus = opt_bonus
    elif exp_rt is not None:
        bonus = exp_rt
    else:
        bonus = float((published or {}).get("bonus_temp") or 30.0)

    if opt_penalty is not None and opt_penalty > 0:
        penalty = opt_penalty
    elif exp_rt is not None:
        penalty = exp_rt
    else:
        penalty = float((published or {}).get("penalty_temp") or 40.0)

    normal = _opt_float(entry, CONF_NORMAL_HDD_YEAR, None)
    if normal is None or normal <= 0:
        normal = float((published or {}).get("normal_hdd_year") or DEFAULT_NORMAL_HDD_YEAR)

    price = _pick(CONF_PRICE_DKK_PER_KWH, "price_dkk_per_kwh")
    opt_motiv_pct = _opt_float(entry, CONF_MOTIVATION_PCT_PER_K, None)
    if opt_motiv_pct is not None and opt_motiv_pct <= 0:
        opt_motiv_pct = None
    motivation_pct = opt_motiv_pct if opt_motiv_pct is not None else _published_pos("motivation_pct_per_k")

    opt_motiv_rate = _opt_float(entry, CONF_MOTIVATION_DKK_PER_KWH_PER_K, None)
    if opt_motiv_rate is not None and opt_motiv_rate > 0:
        motivation_rate: float | None = opt_motiv_rate
    elif opt_motiv_pct is not None:
        motivation_rate = round(price * (opt_motiv_pct / 100.0), 6) if price is not None else None
    else:
        motivation_rate = _published_pos("motivation_dkk_per_kwh_per_k")
        if motivation_rate is None and motivation_pct is not None and price is not None:
            # Percent-based motivation tariffs (e.g. Aalborg Forsyning ±2 %/°C)
            # scale automatically when the user changes heat price in options.
            motivation_rate = round(price * (motivation_pct / 100.0), 6)

    motivation_max_pct = _published_pos("motivation_max_pct")

    return ResolvedTariff(
        price_dkk_per_kwh=price,
        price_dkk_per_m3=_pick(CONF_PRICE_DKK_PER_M3, "price_dkk_per_m3"),
        motivation_dkk_per_kwh_per_k=motivation_rate,
        bonus_temp=bonus,
        penalty_temp=penalty,
        normal_hdd_year=normal,
        tariff_year=int((published or {}).get("year") or today.year),
        source=(published or {}).get("source"),
        source_note=(published or {}).get("source_note"),
        utility_id=utility_id,
        motivation_pct_per_k=motivation_pct,
        motivation_max_pct=motivation_max_pct,
    )
