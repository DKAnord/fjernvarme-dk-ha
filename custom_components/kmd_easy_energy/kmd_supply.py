"""Classify and select the district-heating kundeforhold / meter on KMD / MF2.

A Min Forsyning 2 account can have several customer relationships
(kundeforhold) for the same person. The profile list and the default
Customer-Id often start with electricity (El, E17, GSRN/EAN 5713…), while
district heating (Varme) and water (Vand) live on a later relationship.
Never silently use the first customer or the first meter.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Literal


from .const import CONSUMPTION_TYPE_HEATING, CONSUMPTION_TYPE_WATER

Kind = Literal["heat", "water", "electricity", "unknown"]

# Danish electricity GSRN/EAN (18 digits) starts with 5713.
_ELEC_GSRN = re.compile(r"\b5713\d{14}\b")
# Settlement / metering point type codes used on electricity (El, E17, …).
_ELEC_CODE = re.compile(r"\bE1[7-9]\b|\bE20\b", re.IGNORECASE)

_HEAT_WORDS = (
    "fjernvarme",
    "districtheat",
    "district heat",
    "district_heat",
    "district-heating",
    "heating",
    "varme",
    "heat",
)
_WATER_WORDS = ("fjernvarmevand", "drikkevand", "coldwater", "hotwater", "water", "vand")
_ELEC_WORDS = (
    "electricity",
    "electric",
    "elmåler",
    "elmaaler",
    "power",
    "elsalg",
    "elnet",
    "el ",
    " el",
)

_TYPE_KEYS = (
    "ConsumptionType",
    "ConsumptionTypeId",
    "ConsumptionTypeName",
    "Forbrugstype",
    "UtilityType",
    "UtilityTypeId",
    "UtilityTypeName",
    "SupplyType",
    "SupplyTypeName",
    "MeterType",
    "MeterTypeName",
    "ProductType",
    "Product",
    "Type",
    "TypeId",
    "TypeName",
    "TypeCode",
    "Category",
    "CategoryName",
    "Utility",
    "Medium",
    "MediumName",
    "Description",
    "Name",
    "MeasurementPointType",
    "InstallationType",
    "SettlementType",
)

_ID_KEYS = (
    "MeasurementPointId",
    "MeasurementPointNumber",
    "MeteringPointId",
    "MeteringPointNumber",
    "MeterNumber",
    "MeterId",
    "EAN",
    "Ean",
    "GSRN",
    "Gsrn",
    "InstallationNumber",
    "InstallationId",
    "Number",
    "Id",
)


def extract_customers(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the kundeforhold list from a /api/profile/get payload."""
    if not isinstance(profile, dict):
        return []
    for key in (
        "Customers",
        "customers",
        "CustomerRelations",
        "CustomerRelationships",
        "Relations",
        "Accounts",
    ):
        val = profile.get(key)
        if isinstance(val, list) and any(isinstance(x, dict) for x in val):
            return [x for x in val if isinstance(x, dict)]
    for nest in ("Profile", "Data", "Result", "profile", "data", "result"):
        inner = profile.get(nest)
        if isinstance(inner, dict):
            found = extract_customers(inner)
            if found:
                return found
    return []


def customer_identity(customer: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(customer_id, customer_number) from a profile customer object."""
    if not isinstance(customer, dict):
        return None, None
    low = {str(k).lower(): v for k, v in customer.items()}
    cid = (
        low.get("customerid")
        or low.get("customerrelationid")
        or low.get("accountid")
        or low.get("id")
    )
    cnum = (
        low.get("customernumber")
        or low.get("customerno")
        or low.get("accountnumber")
        or low.get("agreementnumber")
        or low.get("debtornumber")
        or low.get("number")
    )
    return (str(cid).strip() if cid else None, str(cnum).strip() if cnum else None)


def supply_key(customer_id: str | None, measurement_point_id: str | None) -> str:
    """Stable options-flow value (contains ids; redact in diagnostics)."""
    return f"{customer_id or ''}::{measurement_point_id or ''}"


def parse_supply_key(key: str | None) -> tuple[str | None, str | None]:
    raw = (key or "").strip()
    if not raw or "::" not in raw:
        return None, (raw or None)
    cid, _, mp = raw.partition("::")
    return (cid or None, mp or None)


def _unit_names(meter: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for unit in meter.get("Units") or meter.get("units") or []:
        if not isinstance(unit, dict):
            continue
        for key in ("Name", "Description", "UnitName", "Symbol", "UnitCode"):
            val = unit.get(key)
            if val:
                names.append(str(val))
    return names


def _norm_units(names: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for raw in names:
        n = str(raw).strip().lower().replace("³", "3").replace("°", "")
        n = n.replace(" ", "")
        if n:
            out.add(n)
    return out


def _type_text(meter: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _TYPE_KEYS:
        val = meter.get(key)
        if val is not None and not isinstance(val, (dict, list)):
            parts.append(str(val))
    return " ".join(parts).lower()


def _id_text(meter: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _ID_KEYS:
        val = meter.get(key)
        if val is not None and not isinstance(val, (dict, list)):
            parts.append(str(val))
    return " ".join(parts)


def _consumption_type_id(meter: dict[str, Any]) -> int | None:
    for key in (
        "ConsumptionType",
        "ConsumptionTypeId",
        "UtilityTypeId",
        "TypeId",
        "Type",
    ):
        val = meter.get(key)
        if isinstance(val, bool) or val is None:
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.strip().isdigit():
            return int(val.strip())
    return None


def classify_kmd_meter(meter: dict[str, Any] | None) -> Kind:
    """Return heat / water / electricity / unknown for one customerActiveMeters row."""
    if not isinstance(meter, dict):
        return "unknown"

    text = _type_text(meter)
    ids = _id_text(meter)
    type_id = _consumption_type_id(meter)
    units = _norm_units(_unit_names(meter))
    has_heat_unit = any(
        u in {"mwh", "gj"} or "mwh" in u or u.startswith("gj")
        for u in units
    )
    has_energy = has_heat_unit or any(u == "kwh" or "kwh" in u for u in units)
    has_volume = any(u in {"m3", "m³"} or "m3" in u for u in units)
    has_temp = any("c" == u or u.endswith("c") or "temp" in u for u in units)

    if type_id == CONSUMPTION_TYPE_HEATING:
        return "heat"
    if type_id == CONSUMPTION_TYPE_WATER:
        return "water"

    if any(w in text for w in _HEAT_WORDS) and "vand" not in text and "water" not in text:
        return "heat"
    # "fjernvarmevand" / "vand" after heat, so a water-only type is not heat.
    if any(w in text for w in ("fjernvarmevand",)) or (
        any(w in text for w in _WATER_WORDS) and not any(w in text for w in _HEAT_WORDS)
    ):
        return "water"
    if (
        _ELEC_CODE.search(text)
        or _ELEC_CODE.search(ids)
        or _ELEC_GSRN.search(ids)
        or _ELEC_GSRN.search(text)
        or any(w in f" {text} " for w in (" el ", "electricity", "electric", "elmåler", "elmaaler"))
        or re.search(r"\bel\b", text)
    ):
        return "electricity"

    # MWh/GJ meters without el/water indicators are district heating (even without m3/°C),
    # and kWh meters with volume and/or temperature are district heating.
    if has_heat_unit or (has_energy and (has_volume or has_temp)):
        return "heat"
    if has_volume and not has_energy:
        return "water"
    return "unknown"


def classify_customer_kinds(meters: Iterable[dict[str, Any]]) -> set[Kind]:
    return {classify_kmd_meter(m) for m in meters}


def meter_point_id(meter: dict[str, Any]) -> str | None:
    for key in ("MeasurementPointId", "MeasurementPointID", "MeteringPointId", "Id"):
        val = meter.get(key)
        if val:
            return str(val)
    return None


def summarize_accounts(
    accounts: list[dict[str, Any]],
    selected_key: str | None = None,
) -> dict[str, Any]:
    """PII-free overview of discovered kundeforhold and meters (keys are ids)."""
    rows: list[dict[str, Any]] = []
    for acc in accounts:
        idx = int(acc.get("customer_index") or 0)
        cid = acc.get("customer_id")
        for meter in acc.get("meters") or []:
            if not isinstance(meter, dict):
                continue
            mp = meter_point_id(meter)
            key = supply_key(str(cid) if cid else None, mp)
            units = _unit_names(meter)
            rows.append(
                {
                    "kind": classify_kmd_meter(meter),
                    "units": units,
                    "customer_index": idx,
                    "key": key,
                    "selected": bool(selected_key and key == selected_key),
                }
            )
    kinds = sorted({r["kind"] for r in rows})
    return {
        "customer_count": len(accounts),
        "meter_count": len(rows),
        "kinds": kinds,
        "meters": rows,
    }


def diagnostics_supplies(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop supply keys (they embed customer / measurement-point ids)."""
    if not isinstance(summary, dict):
        return None
    meters = []
    for row in summary.get("meters") or []:
        if not isinstance(row, dict):
            continue
        meters.append(
            {
                "kind": row.get("kind"),
                "units": row.get("units"),
                "customer_index": row.get("customer_index"),
                "selected": bool(row.get("selected")),
            }
        )
    return {
        "customer_count": summary.get("customer_count"),
        "meter_count": summary.get("meter_count"),
        "kinds": summary.get("kinds"),
        "selection": summary.get("selection"),
        "selected_kind": summary.get("selected_kind"),
        "meters": meters,
    }


def _matches_preferred(
    acc: dict[str, Any],
    meter: dict[str, Any],
    preferred_key: str | None,
    preferred_customer_id: str | None,
    preferred_mp: str | None,
) -> bool:
    cid = acc.get("customer_id")
    mp = meter_point_id(meter)
    key = supply_key(str(cid) if cid else None, mp)
    if preferred_key and key == preferred_key:
        return True
    if preferred_mp and mp and str(mp) == str(preferred_mp):
        if not preferred_customer_id or (cid and str(cid) == str(preferred_customer_id)):
            return True
    return False


def select_heat_meter(
    accounts: list[dict[str, Any]],
    *,
    preferred_key: str | None = None,
    preferred_customer_id: str | None = None,
    preferred_measurement_point_id: str | None = None,
) -> dict[str, Any]:
    """Pick the Varme meter, never El.

    Returns a dict with status 'ok' | 'no_heat' | 'multiple', the chosen
    account/meter when status is ok, and a PII-free supplies summary.
    A stored preference is honoured only when it still points at a heat meter.
    """
    heat: list[tuple[dict[str, Any], dict[str, Any]]] = []
    preferred_heat: tuple[dict[str, Any], dict[str, Any]] | None = None
    for acc in accounts:
        for meter in acc.get("meters") or []:
            if not isinstance(meter, dict):
                continue
            kind = classify_kmd_meter(meter)
            is_pref = _matches_preferred(
                acc,
                meter,
                preferred_key,
                preferred_customer_id,
                preferred_measurement_point_id,
            )
            if kind == "heat":
                pair = (acc, meter)
                heat.append(pair)
                if is_pref:
                    preferred_heat = pair

    def _result(
        status: str,
        acc: dict[str, Any] | None = None,
        meter: dict[str, Any] | None = None,
        selection: str = "none",
    ) -> dict[str, Any]:
        selected_key = None
        if acc is not None and meter is not None:
            selected_key = supply_key(
                str(acc.get("customer_id") or "") or None,
                meter_point_id(meter),
            )
        summary = summarize_accounts(accounts, selected_key)
        summary["selection"] = selection
        summary["selected_kind"] = classify_kmd_meter(meter) if meter else None
        return {
            "status": status,
            "account": acc,
            "meter": meter,
            "supplies": summary,
        }

    if preferred_heat:
        return _result("ok", preferred_heat[0], preferred_heat[1], "options")
    if len(heat) == 1:
        return _result("ok", heat[0][0], heat[0][1], "auto")
    if len(heat) > 1:
        return _result("multiple")
    return _result("no_heat")


# Danish card / log messages (no meter numbers, addresses or names).
MSG_NO_HEAT = (
    "Ingen fjernvarmemåler blev fundet på kontoen. Hvis portalen har flere "
    "kundeforhold, skal du vælge det med varme (ikke el) og synkronisere igen."
)
MSG_MULTIPLE_HEAT = (
    "Kontoen har flere fjernvarmemålere. Vælg varmemåleren under "
    "integrationens indstillinger, og synkroniser igen."
)

_KIND_LABELS_DA = {
    "electricity": "el",
    "water": "vand",
    "unknown": "ukendt",
}


def format_no_heat_message(supplies: dict[str, Any] | None) -> str:
    """Return a concise, PII-free Danish error explaining what meters were found."""
    if not isinstance(supplies, dict):
        return MSG_NO_HEAT
    meters = [m for m in (supplies.get("meters") or []) if isinstance(m, dict)]
    meter_count = int(supplies.get("meter_count") or len(meters))
    if meter_count == 0:
        return (
            "Ingen aktive målere blev fundet på kontoen (0 målere). "
            "Tjek på selvbetjeningen at varmemåleren er tilknyttet dit MitID-login."
        )

    kinds = [str(m.get("kind") or "unknown") for m in meters] or [
        str(k) for k in (supplies.get("kinds") or [])
    ]
    unknown_units: list[str] = []
    seen_units: set[str] = set()
    for m in meters:
        if m.get("kind") != "unknown":
            continue
        for raw_u in m.get("units") or []:
            u = str(raw_u).strip()
            if u and u not in seen_units:
                seen_units.add(u)
                unknown_units.append(u)

    if unknown_units:
        units_txt = ", ".join(unknown_units[:5])
        msg = (
            "Ingen fjernvarmemåler blev fundet på kontoen "
            f"(fandt ukendt målertype med enheder: {units_txt})."
        )
        return msg[:190]

    seen_kinds: list[str] = []
    for k in kinds:
        label = _KIND_LABELS_DA.get(k, k)
        if label and label not in seen_kinds:
            seen_kinds.append(label)
    if seen_kinds:
        msg = (
            "Ingen fjernvarmemåler blev fundet på kontoen "
            f"(fandt kun: {', '.join(seen_kinds)}). "
            "Tjek på selvbetjeningen at varme er tilknyttet dit MitID-login."
        )
        return msg[:190]

    return MSG_NO_HEAT


class KMDSupplySelectionError(RuntimeError):
    """Heat meter could not be chosen uniquely; supplies are safe to cache."""

    def __init__(self, message: str, supplies: dict[str, Any]) -> None:
        super().__init__(message)
        self.supplies = supplies
