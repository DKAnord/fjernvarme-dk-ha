"""Resolve option-based district-heating prices, with published defaults when known."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_ACONTO_DKK_PER_YEAR,
    CONF_BONUS_TEMP,
    CONF_EF_SUPPLIER_ID,
    CONF_FIXED_FEE_DKK_PER_M2_YEAR,
    CONF_FIXED_FEE_DKK_PER_YEAR,
    CONF_FORWARD_TEMP,
    CONF_HEATED_AREA_M2,
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
    motivation_bonus: bool = True
    expected_return_by_forward_temp: list[list[float]] | None = None
    forward_temp: float | None = None
    forward_temp_source: str | None = None
    fixed_fee_dkk_per_m2_year: float | None = None
    heated_area_m2: float | None = None
    fixed_fee_dkk_per_year: float | None = None
    annual_fixed_fee_dkk: float = 0.0
    motivation_bonus_dkk_per_kwh_per_k: float | None = None
    motivation_penalty_dkk_per_kwh_per_k: float | None = None
    motivation_bonus_pct_per_k: float | None = None
    motivation_penalty_pct_per_k: float | None = None
    suggested_fixed_fee_dkk_per_year: float | None = None
    aconto_dkk_per_year: float | None = None


def _parse_forward_curve(raw: Any) -> list[list[float]] | None:
    """Parse [[forward_c, expected_return_c], ...] sorted by forward temp."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    pts: list[list[float]] = []
    for item in raw:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) < 2:
            continue
        try:
            fwd = float(item[0])
            ret = float(item[1])
        except (TypeError, ValueError):
            continue
        if fwd > 0 and ret > 0:
            pts.append([fwd, ret])
    if not pts:
        return None
    pts.sort(key=lambda pair: pair[0])
    return pts


def expected_return_from_forward_temp(
    forward_temp: float | None,
    curve: Sequence[Sequence[float]] | None,
) -> float | None:
    """Interpolate expected return temperature from a supply-temperature schedule."""
    if forward_temp is None:
        return None
    try:
        fwd = float(forward_temp)
    except (TypeError, ValueError):
        return None
    if fwd <= 0:
        return None
    pts = _parse_forward_curve(curve)
    if not pts:
        return None
    if fwd <= pts[0][0]:
        return round(pts[0][1], 1)
    if fwd >= pts[-1][0]:
        return round(pts[-1][1], 1)
    for idx in range(len(pts) - 1):
        x0, y0 = pts[idx]
        x1, y1 = pts[idx + 1]
        if x0 <= fwd <= x1:
            if x1 == x0:
                return round(y1, 1)
            val = y0 + ((fwd - x0) / (x1 - x0)) * (y1 - y0)
            return round(val, 1)
    return round(pts[-1][1], 1)


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
    raw = str(url or "").strip().rstrip("/").lower()
    return re.sub(r"^(https?://)www\.", r"\1", raw)


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
                and portal_url
                in {
                    _norm_portal_url(u.get("portal_url")),
                    *(_norm_portal_url(a) for a in (u.get("portal_aliases") or ())),
                }
            ),
            None,
        )
        if by_portal is not None:
            return by_portal

    return next((u for u in utilities if u.get("id") == utility_id), None)


def _tariff_effective_date(tariff: Mapping[str, Any]) -> date:
    """Return effective start date for a bundled tariff entry."""
    raw = tariff.get("effective_from")
    if isinstance(raw, str) and raw.strip():
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            pass
    try:
        yr = int(tariff.get("year") or 1970)
    except (TypeError, ValueError):
        yr = 1970
    return date(yr, 1, 1)


def published_tariff(
    utility_id: str,
    year: int,
    utilities: list[dict[str, Any]] | None = None,
    *,
    on_date: date | None = None,
) -> dict[str, Any] | None:
    """Return the bundled tariff dict for utility/year (or specific date)."""
    utilities = utilities if utilities is not None else load_utilities()
    match = next((u for u in utilities if u.get("id") == utility_id), None)
    if not match:
        return None
    tariffs = match.get("tariffs") or []
    if on_date is not None:
        active = [t for t in tariffs if _tariff_effective_date(t) <= on_date]
        if active:
            return max(
                active,
                key=lambda t: (_tariff_effective_date(t), int(t.get("year") or 0)),
            )
    exact = next((t for t in tariffs if int(t.get("year") or 0) == year), None)
    if exact:
        return exact
    # Prefer the latest year that is not in the future relative to `year`.
    past = [t for t in tariffs if int(t.get("year") or 0) <= year]
    if not past:
        return None
    return max(past, key=lambda t: int(t.get("year") or 0))


def earliest_tariff_date(
    entry_data: Mapping[str, Any],
    utilities: list[dict[str, Any]] | None = None,
) -> date | None:
    """Return the earliest effective tariff date for a matched utility, or None."""
    matched = match_utility_for_entry(entry_data, utilities)
    tariffs = (matched or {}).get("tariffs") or []
    if not tariffs:
        return None
    return min(_tariff_effective_date(t) for t in tariffs)


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
    forward_temp: float | None = None,
) -> ResolvedTariff:
    """Options override published defaults; zero/empty option means "use default"."""
    today = today or copenhagen_today()
    matched = match_utility_for_entry(entry.data, utilities)
    utility_id = str(
        (matched or {}).get("id") or entry.data.get(CONF_UTILITY_ID) or "kredslob"
    )
    published = published_tariff(utility_id, today.year, utilities, on_date=today)

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

    curve = _parse_forward_curve((published or {}).get("expected_return_by_forward_temp"))
    opt_forward = _opt_float(entry, CONF_FORWARD_TEMP, None)
    if opt_forward is not None and opt_forward > 0:
        eff_forward: float | None = round(opt_forward, 1)
        forward_source: str | None = "manual"
    elif forward_temp is not None:
        try:
            fwd_val = float(forward_temp)
        except (TypeError, ValueError):
            fwd_val = 0.0
        if fwd_val > 0:
            eff_forward = round(fwd_val, 1)
            forward_source = "meter"
        else:
            eff_forward = None
            forward_source = None
    else:
        eff_forward = None
        forward_source = None

    opt_bonus = _opt_float(entry, CONF_BONUS_TEMP, None)
    opt_penalty = _opt_float(entry, CONF_PENALTY_TEMP, None)
    if forward_source == "manual" and curve is not None:
        exp_rt = expected_return_from_forward_temp(eff_forward, curve)
    elif expected_return_temp is not None and float(expected_return_temp) > 0:
        exp_rt = round(float(expected_return_temp), 1)
    elif curve is not None and eff_forward is not None:
        exp_rt = expected_return_from_forward_temp(eff_forward, curve)
    else:
        exp_rt = None

    published_bonus = bool((published or {}).get("motivation_bonus", True))
    if opt_bonus is not None and opt_bonus > 0:
        motivation_bonus = True
        bonus = opt_bonus
    elif not published_bonus:
        motivation_bonus = False
        bonus = 0.0
    else:
        motivation_bonus = True
        if exp_rt is not None:
            bonus = exp_rt
        elif published and published.get("bonus_temp") is not None:
            bonus = float(published["bonus_temp"])
        else:
            bonus = 30.0

    if opt_penalty is not None and opt_penalty > 0:
        penalty = opt_penalty
    elif exp_rt is not None:
        penalty = exp_rt
    elif published and published.get("penalty_temp") is not None:
        penalty = float(published["penalty_temp"])
    else:
        penalty = 40.0

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

    def _resolve_side(side: str) -> tuple[float | None, float | None]:
        side_pct = _published_pos(f"motivation_{side}_pct_per_k")
        eff_pct = side_pct if side_pct is not None else motivation_pct
        side_rate = _published_pos(f"motivation_{side}_dkk_per_kwh_per_k")
        if side_rate is None:
            if side_pct is not None and price is not None:
                side_rate = round(price * (side_pct / 100.0), 6)
            else:
                side_rate = motivation_rate
        return side_rate, eff_pct

    has_user_motiv_override = (
        opt_motiv_rate is not None and opt_motiv_rate > 0
    ) or (opt_motiv_pct is not None)
    if has_user_motiv_override:
        bonus_rate = motivation_rate
        penalty_rate = motivation_rate
        bonus_pct = opt_motiv_pct
        penalty_pct = opt_motiv_pct
    else:
        bonus_rate, bonus_pct = _resolve_side("bonus")
        penalty_rate, penalty_pct = _resolve_side("penalty")
        if motivation_rate is None:
            motivation_rate = penalty_rate if penalty_rate is not None else bonus_rate

    fixed_fee_per_m2 = _pick(CONF_FIXED_FEE_DKK_PER_M2_YEAR, "fixed_fee_dkk_per_m2_year")
    opt_area = _opt_float(entry, CONF_HEATED_AREA_M2, None)
    heated_area = opt_area if (opt_area is not None and opt_area > 0) else None
    opt_flat_fixed = _opt_float(entry, CONF_FIXED_FEE_DKK_PER_YEAR, None)
    fixed_fee_year = opt_flat_fixed if (opt_flat_fixed is not None and opt_flat_fixed > 0) else None
    suggested_fixed_fee_year = _published_pos("fixed_fee_dkk_per_year")
    annual_area_fee = (
        round(fixed_fee_per_m2 * heated_area, 2)
        if (fixed_fee_per_m2 is not None and heated_area is not None)
        else 0.0
    )
    annual_fixed_fee = round(annual_area_fee + (fixed_fee_year or 0.0), 2)
    opt_aconto = _opt_float(entry, CONF_ACONTO_DKK_PER_YEAR, None)
    aconto_dkk_per_year = (
        round(opt_aconto, 2) if (opt_aconto is not None and opt_aconto > 0) else None
    )

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
        motivation_bonus=motivation_bonus,
        expected_return_by_forward_temp=curve,
        forward_temp=eff_forward,
        forward_temp_source=forward_source,
        fixed_fee_dkk_per_m2_year=fixed_fee_per_m2,
        heated_area_m2=heated_area,
        fixed_fee_dkk_per_year=fixed_fee_year,
        annual_fixed_fee_dkk=annual_fixed_fee,
        motivation_bonus_dkk_per_kwh_per_k=bonus_rate,
        motivation_penalty_dkk_per_kwh_per_k=penalty_rate,
        motivation_bonus_pct_per_k=bonus_pct,
        motivation_penalty_pct_per_k=penalty_pct,
        suggested_fixed_fee_dkk_per_year=suggested_fixed_fee_year,
        aconto_dkk_per_year=aconto_dkk_per_year,
    )
