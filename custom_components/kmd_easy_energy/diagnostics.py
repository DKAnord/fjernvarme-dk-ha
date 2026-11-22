"""Diagnostics for KMD Easy Energy with redaction of secrets and PII."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import KMDEasyEnergyCoordinator

# Keys that must never appear in a diagnostics download (tokens, MitID user,
# meter/customer identifiers, addresses and other personal data).
TO_REDACT = {
    "access_token",
    "token",
    "refresh_token",
    "authorization",
    "Authorization",
    "mitid_username",
    "mitid_otp_code",
    "mitid_qr_svg",
    "mitid_qr_frames",
    "customer_id",
    "customer_number",
    "CustomerId",
    "CustomerNumber",
    "Customer-Id",
    "Customer-Number",
    "InstallationId",
    "MeasurementPointId",
    "MeterId",
    "meter_id",
    "MeterNumber",
    "meter_number",
    "Address",
    "address",
    "Street",
    "street",
    "StreetName",
    "PostalCode",
    "postal_code",
    "City",  # keep? city can be the location label; safer to redact in profile dumps
    "email",
    "Email",
    "phone",
    "Phone",
    "PhoneNumber",
    "cpr",
    "CPR",
    "Name",
    "FullName",
    "FirstName",
    "LastName",
    "latitude",
    "longitude",
    "notify_service",
}


def _series_len(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def _summarize_coordinator(data: dict[str, Any] | None) -> dict[str, Any]:
    """Compact, non-PII snapshot of coordinator state for support dumps."""
    data = data or {}
    daily = data.get("daily") or {}
    return {
        "utility": data.get("utility"),
        "utility_id": data.get("utility_id"),
        "utility_status": data.get("utility_status"),
        "location": data.get("location"),
        "token_expired": bool(data.get("token_expired", False)),
        "initial_setup_complete": bool(data.get("initial_setup_complete", True)),
        "sync_state": data.get("sync_state"),
        "has_mitid_username": bool(data.get("has_mitid_username")),
        "updated": data.get("updated"),
        "bonus_temp": data.get("bonus_temp"),
        "penalty_temp": data.get("penalty_temp"),
        "hdd_7d": data.get("hdd_7d"),
        "energy_mtd_kwh": daily.get("total"),
        "hourly_kwh_points": data.get("hourly_kwh_points") or _series_len(data.get("hourly_kwh")),
        "hourly_m3_points": _series_len(data.get("hourly_m3")),
        "hourly_temp_points": _series_len(data.get("hourly_temp")),
        "meter_count": _series_len(data.get("meters")),
        "available_unit_names": [
            u.get("Name") or u.get("Description")
            for u in (data.get("available_units") or [])
            if isinstance(u, dict)
        ],
        "weather_archive_fetched_on": data.get("weather_archive_fetched_on"),
        "statistics_imported_on": data.get("statistics_imported_on"),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: KMDEasyEnergyCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    raw = {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "domain": entry.domain,
            "version": entry.version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": _summarize_coordinator(
            None if coordinator is None else (coordinator.data or {})
        ),
    }
    return async_redact_data(raw, TO_REDACT)
