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
from .capabilities import CAP_BILLING, CAP_COST, CAP_TEMPERATURES, CAP_VOLUME
from .coordinator import KMDEasyEnergyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KMD Easy Energy sensors."""
    coordinator: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(sensors_for(coordinator, entry))


# Sensors that need a specific backend capability (others are always created).
SENSOR_CAPABILITY: dict[str, str] = {
    "KMDVolumeSensor": CAP_VOLUME,
    "KMDReturnTempSensor": CAP_TEMPERATURES,
    "KMDBalanceSensor": CAP_BILLING,
    "KMDMotivationStatusSensor": CAP_TEMPERATURES,
    "KMDMotivationAdjustmentSensor": CAP_TEMPERATURES,
    "KMDEnergyPriceSensor": CAP_COST,
    "KMDEffectivePriceSensor": CAP_COST,
    "KMDLatestDayCostSensor": CAP_COST,
    "KMDMonthCostSensor": CAP_COST,
    "KMDYearCostSensor": CAP_COST,
}


def sensors_for(coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> list[SensorEntity]:
    """Only create sensors the backend can fill (no permanently 'unknown' entities)."""
    caps = coordinator.backend_capabilities
    classes = [
        KMDOverviewSensor,
        KMDEnergySensor,
        KMDVolumeSensor,
        KMDReturnTempSensor,
        KMDBalanceSensor,
        KMDHDDSensor,
        KMDEnergyPriceSensor,
        KMDEffectivePriceSensor,
        KMDLatestDayCostSensor,
        KMDMonthCostSensor,
        KMDYearCostSensor,
        KMDMotivationStatusSensor,
        KMDMotivationAdjustmentSensor,
        KMDKwhPerHddSensor,
        KMDNormalizedAnnualSensor,
        KMDForecastAnnualSensor,
        KMDLastSyncSensor,
    ]
    return [
        cls(coordinator, entry)
        for cls in classes
        if SENSOR_CAPABILITY.get(cls.__name__) in (None, *caps)
    ]


class KMDBaseSensor(CoordinatorEntity[KMDEasyEnergyCoordinator], SensorEntity):
    """Base entity for KMD Easy Energy sensors."""

    _attr_has_entity_name = True
    # Belt-and-suspenders: these keys must never hit the recorder even if
    # a future change reintroduces them on attributes.
    _unrecorded_attributes = frozenset(
        {
            "mitid_otp_code",
            "mitid_qr_svg",
            "annual",
            "monthly",
            "daily",
            "hourly",
            "hourly_kwh",
            "hourly_m3",
            "hourly_temp",
            "return_temp",
            "weather",
            "insights",
            "forecast",
            "billing",
            "meters",
            "available_units",
            "hourly_kwh_points",
            "hourly_m3_points",
            "hourly_temp_points",
            "settlement_period",
            "tariff",
            "abnormal_consumption",
            "degree_day",
            "daily_hdd",
            "daily_kwh_history",
            "daily_m3_history",
            "daily_return_temp",
            "daily_forward_temp",
            "daily_expected_return_temp",
            "expected_return_temp",
            "expected_return_auto",
            "forward_temp",
            "forward_temp_source",
            "integration_version",
            "energy_price_dkk_per_kwh",
            "daily_stat_kwh",
            "daily_stat_m3",
            "latest_reading",
            "eforsyning",
            "outdoor_temp",
            "temp_source",
            "wattson",
            "wattson_hours",
            "cost_estimate",
            "monthly_dkk",
        }
    )

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "KMD Easy Energy",
            "manufacturer": "KMD",
        }


_OUTDOOR_ATTR_KEYS = (
    "source",
    "entity_id",
    "sensor_name",
    "sensor_status",
    "configured_location",
    "open_meteo_location",
    "sensor_since",
    "ha_sensor_days",
    "open_meteo_days",
    "pending",
)


def _outdoor_attr(value: Any) -> dict[str, Any]:
    """Outdoor temperature source for the card (location kind only, no coordinates)."""
    if not isinstance(value, dict):
        return {}
    return {k: value.get(k) for k in _OUTDOOR_ATTR_KEYS}


def _sync_attrs(coordinator: KMDEasyEnergyCoordinator) -> dict[str, Any]:
    """Last sync + soft weekend reminder (computed live, no KMD call)."""
    return coordinator.sync_reminder()


def _sum_complete(series: list[dict[str, Any]] | None) -> float | None:
    if not series:
        return None
    vals = [p.get("Value", 0) for p in series if p.get("IsComplete") and p.get("Value") is not None]
    return round(sum(vals), 2) if vals else None


class KMDOverviewSensor(KMDBaseSensor):
    """Full dashboard sensor exposing annual/monthly/daily/hourly/weather/insights/billing."""

    _attr_translation_key = "overview"
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
            "expected_return_temp": data.get("expected_return_temp"),
            "expected_return_auto": bool(data.get("expected_return_auto", False)),
            "forward_temp": data.get("forward_temp"),
            "forward_temp_source": data.get("forward_temp_source"),
            "energy_price_dkk_per_kwh": data.get("energy_price_dkk_per_kwh"),
            "tariff": data.get("tariff") or {},
            "has_mitid_username": bool(data.get("has_mitid_username", False)),
            "mitid_username_masked": data.get("mitid_username_masked", ""),
            "notify_service": data.get("notify_service", ""),
            "entry_id": data.get("entry_id") or self._entry.entry_id,
            "integration_version": data.get("integration_version"),
            "sync_state": data.get("sync_state", "idle"),
            "sync_message": data.get("sync_message", ""),
            "backend": data.get("backend", "kmd"),
            "data_source": data.get("data_source", "KMD Easy Energy"),
            "data_granularity": data.get("data_granularity", "hourly"),
            "auto_sync": bool(data.get("auto_sync", False)),
            "auto_sync_hour": data.get("auto_sync_hour"),
            "login_expires_at": data.get("login_expires_at"),
            "capabilities": data.get("capabilities")
            or sorted(self.coordinator.capabilities(data)),
            "backend_capabilities": data.get("backend_capabilities")
            or sorted(self.coordinator.backend_capabilities),
            "annual": data.get("annual") or {},
            "monthly": data.get("monthly") or {},
            "daily": data.get("daily") or {},
            "hourly": data.get("hourly") or {},
            "return_temp": data.get("return_temp") or {},
            "weather": data.get("weather") or {},
            "temp_source": data.get("temp_source"),
            "outdoor_temp": _outdoor_attr(data.get("outdoor_temp")),
            "insights": data.get("insights") or {},
            "forecast": data.get("forecast") or {},
            "billing": data.get("billing") or {},
            "cost_estimate": data.get("cost_estimate") or {},
            "available_units": data.get("available_units") or [],
            **_sync_attrs(self.coordinator),
        }


class KMDEnergySensor(KMDBaseSensor):
    _attr_translation_key = "energy"
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
            "last_sync": _sync_attrs(self.coordinator)["last_sync"],
            "settlement_period": (
                f"{sp.get('DateFrom', '')[:10]} - {sp.get('DateTo', '')[:10]}"
                if sp.get("DateFrom") and sp.get("DateTo")
                else None
            ),
            "forecast_expected_kwh": (ov.get("Actual") or {}).get("Value"),
            "forecast_budget_kwh": (ov.get("Expected") or {}).get("Value"),
        }


class KMDVolumeSensor(KMDBaseSensor):
    # Circulating district-heating water volume (m³), not drinking water.
    # WATER is used so the entity can be added on the Energy dashboard volume track.
    _attr_translation_key = "volume"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_volume"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        hourly = _sum_complete(data.get("hourly_m3"))
        if hourly is not None:
            return hourly
        # E|Forsyning: month-to-date m³ from daily readings (None = unknown).
        return (data.get("daily_m3") or {}).get("total")


class KMDReturnTempSensor(KMDBaseSensor):
    _attr_translation_key = "return_temperature"
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
        # Daily-reading backends (E|Forsyning): latest daily return temperature.
        latest = (data.get("latest_reading") or {}).get("temp_return")
        if isinstance(latest, (int, float)) and latest > 0:
            return latest
        rt_ann = (data.get("return_temp") or {}).get("annual") or {}
        yr_s = str(dt_util.now().year)
        return rt_ann.get(yr_s)


class KMDBalanceSensor(KMDBaseSensor):
    _attr_translation_key = "balance"
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
    _attr_translation_key = "heating_degree_days"
    _attr_native_unit_of_measurement = "°C·d"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_hdd"

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("hdd_7d")
        return round(float(val), 1) if val is not None else None



class KMDEnergyPriceSensor(KMDBaseSensor):
    """Variable heat price for the Energy dashboard (DKK/kWh, option or published default)."""

    _attr_translation_key = "energy_price"
    _attr_native_unit_of_measurement = "DKK/kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_energy_price"

    @property
    def native_value(self) -> float | None:
        value = (self.coordinator.data or {}).get("energy_price_dkk_per_kwh")
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tariff = (self.coordinator.data or {}).get("tariff") or {}
        return {
            "tariff_year": tariff.get("tariff_year"),
            "source": tariff.get("source"),
            "source_note": tariff.get("source_note"),
            "volume_price_dkk_per_m3": tariff.get("price_dkk_per_m3"),
            "motivation_pct_per_k": tariff.get("motivation_pct_per_k"),
            "fixed_fee_dkk_per_m2_year": tariff.get("fixed_fee_dkk_per_m2_year"),
            "heated_area_m2": tariff.get("heated_area_m2"),
            "fixed_fee_dkk_per_year": tariff.get("fixed_fee_dkk_per_year"),
            "annual_fixed_fee_dkk": tariff.get("annual_fixed_fee_dkk", 0.0),
        }


class KMDEffectivePriceSensor(KMDBaseSensor):
    """Effective variable heat price in DKK/kWh after motivation adjustment."""

    _attr_translation_key = "effective_energy_price"
    _attr_native_unit_of_measurement = "DKK/kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_effective_energy_price"

    @property
    def native_value(self) -> float | None:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        val = est.get("effective_price_dkk_per_kwh")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        return {
            "base_price_dkk_per_kwh": est.get("base_price_dkk_per_kwh"),
            "adjustment_dkk_per_kwh": est.get("adjustment_dkk_per_kwh"),
            "adjustment_pct": est.get("adjustment_pct"),
            "current_return_temp": est.get("current_return_temp"),
        }


class KMDLatestDayCostSensor(KMDBaseSensor):
    """Estimated variable heating cost for the latest complete day (excl. fixed fees)."""

    _attr_translation_key = "latest_day_cost"
    _attr_native_unit_of_measurement = "DKK"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:radiator"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_latest_day_cost"

    @property
    def native_value(self) -> float | None:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        val = est.get("latest_day_dkk")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        return {
            "kwh": est.get("latest_day_kwh"),
            "day": est.get("latest_day_label"),
            "effective_price_dkk_per_kwh": est.get("effective_price_dkk_per_kwh"),
            "daily_fixed_fee_dkk": est.get("daily_fixed_fee_dkk", 0.0),
            "excludes_fixed_fees": est.get("excludes_fixed_fees", True),
        }


class KMDMonthCostSensor(KMDBaseSensor):
    """Estimated variable heating cost for the current month (excl. fixed fees)."""

    _attr_translation_key = "month_cost"
    _attr_native_unit_of_measurement = "DKK"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:radiator"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_month_cost"

    @property
    def native_value(self) -> float | None:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        val = est.get("current_month_dkk")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        return {
            "kwh": est.get("current_month_kwh"),
            "effective_price_dkk_per_kwh": est.get("effective_price_dkk_per_kwh"),
            "fixed_fee_dkk": est.get("current_month_fixed_dkk", 0),
            "excludes_fixed_fees": est.get("excludes_fixed_fees", True),
        }


class KMDYearCostSensor(KMDBaseSensor):
    """Estimated variable heating cost year-to-date (excl. fixed fees)."""

    _attr_translation_key = "year_cost"
    _attr_native_unit_of_measurement = "DKK"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:radiator"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_year_cost"

    @property
    def native_value(self) -> float | None:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        val = est.get("ytd_dkk")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        est = (self.coordinator.data or {}).get("cost_estimate") or {}
        return {
            "year": est.get("year"),
            "monthly_dkk": est.get("monthly_dkk") or {},
            "ytd_variable_dkk": est.get("ytd_variable_dkk"),
            "ytd_fixed_dkk": est.get("ytd_fixed_dkk", 0),
            "annual_fixed_fee_dkk": est.get("annual_fixed_fee_dkk", 0.0),
            "forecast_annual_dkk": est.get("forecast_annual_dkk"),
            "forecast_annual_kwh": est.get("forecast_annual_kwh"),
            "excludes_fixed_fees": est.get("excludes_fixed_fees", True),
        }


class KMDMotivationStatusSensor(KMDBaseSensor):
    """Afkøling vs. the utility motivation tariff: bonus, neutral or penalty."""

    _attr_translation_key = "motivation_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["bonus", "neutral", "penalty"]

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_motivation_status"

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("motivation_status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        tariff = data.get("tariff") or {}
        return {
            "bonus_temp": tariff.get("bonus_temp", data.get("bonus_temp")),
            "penalty_temp": tariff.get("penalty_temp", data.get("penalty_temp")),
            "motivation_bonus": tariff.get("motivation_bonus", True),
            "expected_return_temp": data.get("expected_return_temp"),
            "forward_temp": data.get("forward_temp"),
            "adjustment_dkk_per_kwh": data.get("motivation_dkk_per_kwh"),
        }


class KMDMotivationAdjustmentSensor(KMDBaseSensor):
    """Motivation tariff adjustment in DKK/kWh (negative is a bonus)."""

    _attr_translation_key = "motivation_adjustment"
    _attr_native_unit_of_measurement = "DKK/kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 5

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_motivation_adjustment"

    @property
    def native_value(self) -> float | None:
        value = (self.coordinator.data or {}).get("motivation_dkk_per_kwh")
        return float(value) if value is not None else None


class KMDKwhPerHddSensor(KMDBaseSensor):
    """Recent kWh per heating degree day (HDD17)."""

    _attr_translation_key = "kwh_per_hdd"
    _attr_native_unit_of_measurement = "kWh/HDD"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_kwh_per_hdd"

    @property
    def native_value(self) -> float | None:
        value = ((self.coordinator.data or {}).get("degree_day") or {}).get("kwh_per_hdd")
        return float(value) if value is not None else None


class KMDNormalizedAnnualSensor(KMDBaseSensor):
    """Degree-day-normalised annual consumption (kWh/HDD × normal-year HDD)."""

    _attr_translation_key = "normalized_annual_energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 0

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_normalized_annual_energy"

    @property
    def native_value(self) -> float | None:
        value = ((self.coordinator.data or {}).get("degree_day") or {}).get("normalized_annual_kwh")
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict((self.coordinator.data or {}).get("degree_day") or {})


class KMDForecastAnnualSensor(KMDBaseSensor):
    """Year forecast: year-to-date kWh plus remaining normal-year HDD × kWh/HDD."""

    _attr_translation_key = "forecast_annual_energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 0

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_forecast_annual_energy"

    @property
    def native_value(self) -> float | None:
        value = ((self.coordinator.data or {}).get("degree_day") or {}).get("forecast_annual_kwh")
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dd = dict((self.coordinator.data or {}).get("degree_day") or {})
        return dd


class KMDLastSyncSensor(KMDBaseSensor):
    """Timestamp of the last successful MitID sync ("Sidst synkroniseret")."""

    _attr_translation_key = "last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:cloud-check-outline"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_last_sync"

    @property
    def native_value(self) -> Any:
        return self.coordinator.last_sync

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rem = _sync_attrs(self.coordinator)
        return {"days_since_sync": rem["days_since_sync"]}
