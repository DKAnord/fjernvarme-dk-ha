"""Sensors for KMD Easy Energy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfTemperature, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import KMDEasyEnergyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KMD Easy Energy sensors."""
    coordinator: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            KMDOverviewSensor(coordinator, entry),
            KMDEnergySensor(coordinator, entry),
            KMDVolumeSensor(coordinator, entry),
            KMDReturnTempSensor(coordinator, entry),
            KMDBalanceSensor(coordinator, entry),
            KMDHDDSensor(coordinator, entry),
        ]
    )


class KMDBaseSensor(CoordinatorEntity[KMDEasyEnergyCoordinator], SensorEntity):
    """Base entity for KMD Easy Energy sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "KMD Easy Energy",
            "manufacturer": "KMD",
        }


def _sum_complete(series: list[dict[str, Any]] | None) -> float | None:
    if not series:
        return None
    vals = [p.get("Value", 0) for p in series if p.get("IsComplete") and p.get("Value") is not None]
    return round(sum(vals), 2) if vals else None


class KMDOverviewSensor(KMDBaseSensor):
    """Full dashboard sensor exposing annual/monthly/daily/hourly/weather/insights/billing."""

    _attr_name = "Overview"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_overview"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        yr_s = str(dt_util.now().year)
        annual = data.get("annual") or {}
        if yr_s in annual:
            return annual[yr_s]
        daily = data.get("daily") or {}
        return daily.get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "updated": data.get("updated"),
            "utility": data.get("utility"),
            "utility_id": data.get("utility_id"),
            "utility_status": data.get("utility_status"),
            "portal_url": data.get("portal_url"),
            "location": data.get("location"),
            "initial_setup_complete": bool(data.get("initial_setup_complete", True)),
            "bonus_temp": data.get("bonus_temp", 30.0),
            "penalty_temp": data.get("penalty_temp", 40.0),
            "has_mitid_username": bool(data.get("has_mitid_username", False)),
            "mitid_username_masked": data.get("mitid_username_masked", ""),
            "notify_service": data.get("notify_service", ""),
            "sync_state": data.get("sync_state", "idle"),
            "sync_message": data.get("sync_message", ""),
            "mitid_otp_code": data.get("mitid_otp_code"),
            "mitid_qr_svg": data.get("mitid_qr_svg"),
            "annual": data.get("annual") or {},
            "monthly": data.get("monthly") or {},
            "daily": data.get("daily") or {},
            "hourly": data.get("hourly") or {},
            "return_temp": data.get("return_temp") or {},
            "weather": data.get("weather") or {},
            "insights": data.get("insights") or {},
            "forecast": data.get("forecast") or {},
            "billing": data.get("billing") or {},
            "available_units": data.get("available_units") or [],
            "token_expired": bool(data.get("token_expired", False)),
        }


class KMDEnergySensor(KMDBaseSensor):
    _attr_name = "Energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_energy"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        daily = data.get("daily") or {}
        if daily.get("total") is not None:
            return daily["total"]
        return _sum_complete(data.get("hourly_kwh"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        sp = data.get("settlement_period") or {}
        ov = data.get("overview") or {}
        return {
            "updated": data.get("updated"),
            "available_units": data.get("available_units") or [],
            "meter_count": len(data.get("meters") or []),
            "hourly_kwh_points": data.get("hourly_kwh_points", 0),
            "hourly_m3_points": len(data.get("hourly_m3") or []),
            "hourly_temp_points": len(data.get("hourly_temp") or []),
            "token_expired": bool(data.get("token_expired", False)),
            "settlement_period": (
                f"{sp.get('DateFrom', '')[:10]} - {sp.get('DateTo', '')[:10]}"
                if sp.get("DateFrom") and sp.get("DateTo")
                else None
            ),
            "forecast_expected_kwh": (ov.get("Actual") or {}).get("Value"),
            "forecast_budget_kwh": (ov.get("Expected") or {}).get("Value"),
        }


class KMDVolumeSensor(KMDBaseSensor):
    _attr_name = "Volume"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_volume"

    @property
    def native_value(self) -> float | None:
        return _sum_complete((self.coordinator.data or {}).get("hourly_m3"))


class KMDReturnTempSensor(KMDBaseSensor):
    _attr_name = "Return temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_return_temp"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        if data.get("has_direct_temp"):
            series = data.get("hourly_temp") or []
            complete = [p for p in series if p.get("IsComplete") and p.get("Value") is not None]
            if complete:
                return complete[-1].get("Value")
        rt_ann = (data.get("return_temp") or {}).get("annual") or {}
        yr_s = str(dt_util.now().year)
        return rt_ann.get(yr_s)


class KMDBalanceSensor(KMDBaseSensor):
    _attr_name = "Balance"
    _attr_native_unit_of_measurement = "DKK"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_balance"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        bal = data.get("balance") or {}
        if "Balance" in bal:
            return bal["Balance"]
        return (data.get("billing") or {}).get("saldo_kr")


class KMDHDDSensor(KMDBaseSensor):
    _attr_name = "Heating degree days (7d)"
    _attr_native_unit_of_measurement = "°C·d"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_hdd"

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("hdd_7d")
        return round(float(val), 1) if val is not None else None
