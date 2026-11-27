"""Diagnostics for KMD Easy Energy with redaction of secrets and PII."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import KMDEasyEnergyCoordinator
from .kmd_supply import diagnostics_supplies

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
    "measurement_point_id",
    "kmd_supply",
    "key",
    "selected_supply_key",
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
    "utility_latitude",
    "utility_longitude",
    "notify_service",
    # E|Forsyning credentials / identifiers
    "eforsyning_username",
    "eforsyning_password",
    "eforsyning_installation_id",
    "ForbrugerNr",
    "MålerNr",
    "Adresse",
    "EjendomNr",
    # Watts On credentials / identifiers
    "wattson_refresh_token",
    "wattson_redirect_url",
    "wattson_user_id",
    "wattson_device_id",
    "id_token",
    "code",
    "code_verifier",
}


def _series_len(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


_OUTDOOR_KEYS = (
    "source",
    "entity_id",
    "sensor_status",
    "configured_location",
    "open_meteo_location",
    "ha_sensor_days",
    "open_meteo_days",
    "sensor_since",
    "pending",
)


def _outdoor_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {k: value.get(k) for k in _OUTDOOR_KEYS}


def _summarize_coordinator(data: dict[str, Any] | None) -> dict[str, Any]:
    """Compact, non-PII snapshot of coordinator state for support dumps."""
    data = data or {}
    daily = data.get("daily") or {}
    return {
        "utility": data.get("utility"),
        "utility_id": data.get("utility_id"),
        "utility_status": data.get("utility_status"),
        "backend": data.get("backend", "kmd"),
        "data_granularity": data.get("data_granularity", "hourly"),
        "auto_sync": data.get("auto_sync"),
        "daily_kwh_days": _series_len(data.get("daily_kwh_history")),
        "eforsyning": {
            "years": (data.get("eforsyning") or {}).get("years"),
            "readings_last_fetch": (data.get("eforsyning") or {}).get("readings_last_fetch"),
        }
        if data.get("eforsyning")
        else None,
        # Watts On: only shapes and outcomes (endpoint templates, HTTP results,
        # JSON key names, unit, assumptions) — never values, ids or tokens.
        "wattson": {
            k: (data.get("wattson") or {}).get(k)
            for k in (
                "endpoint",
                "probe",
                "device",
                "keys_seen",
                "quality_seen",
                "energy_unit",
                "interval_hours",
                "skipped",
                "assumptions",
                "detected",
                "intervals_last_fetch",
                "stored_intervals",
                "requests_last_sync",
            )
        }
        if data.get("wattson")
        else None,
        "location": data.get("location"),
        "last_sync": data.get("last_sync"),
        "sync_reminder": data.get("sync_reminder"),
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
        "kmd_cooling": data.get("kmd_cooling"),
        "meter_count": _series_len(data.get("meters")),
        "kmd_supplies": diagnostics_supplies(data.get("kmd_supplies")),
        "has_selected_supply": bool(data.get("selected_supply_key")),
        "available_unit_names": [
            u.get("Name") or u.get("Description")
            for u in (data.get("available_units") or [])
            if isinstance(u, dict)
        ],
        "weather_archive_fetched_on": data.get("weather_archive_fetched_on"),
        # Source only (sensor entity id, location *kind*, day counts) — never coordinates.
        "outdoor_temp": _outdoor_summary(data.get("outdoor_temp")),
        "statistics_imported_on": data.get("statistics_imported_on"),
        "statistics_imported": data.get("statistics_imported"),
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
