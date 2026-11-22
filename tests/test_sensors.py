"""Sensor device_class / state_class and attribute privacy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume

from kmd_easy_energy.sensor import (
    KMDBalanceSensor,
    KMDEnergySensor,
    KMDOverviewSensor,
    KMDReturnTempSensor,
    KMDVolumeSensor,
)


def _coord(data: dict | None = None):
    coord = MagicMock()
    coord.data = data or {
        "annual": {"2026": 1234.0},
        "daily": {"total": 210.5, "days": {"1": 10}},
        "hourly_m3": [{"Value": 1.2, "IsComplete": True}],
        "mitid_otp_code": "1234",  # must never leak even if present in coordinator data
        "mitid_qr_svg": "<svg />",
        "sync_state": "otp_ready",
        "entry_id": "test-entry",
    }
    return coord


def _entry():
    return SimpleNamespace(entry_id="test-entry", title="Kredsløb")


def test_energy_and_overview_classes() -> None:
    entry = _entry()
    coord = _coord()
    energy = KMDEnergySensor(coord, entry)
    overview = KMDOverviewSensor(coord, entry)
    assert energy.device_class == SensorDeviceClass.ENERGY
    assert energy.state_class == SensorStateClass.TOTAL_INCREASING
    assert energy.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
    assert energy.native_value == 210.5
    assert overview.device_class == SensorDeviceClass.ENERGY
    assert overview.state_class == SensorStateClass.TOTAL
    assert overview.native_value == 1234.0
    assert overview.unique_id == "test-entry_overview"
    assert energy.unique_id == "test-entry_energy"
    assert energy.translation_key == "energy"
    assert overview.translation_key == "overview"


def test_volume_uses_water_device_class() -> None:
    sensor = KMDVolumeSensor(_coord(), _entry())
    assert sensor.device_class == SensorDeviceClass.WATER
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.native_unit_of_measurement == UnitOfVolume.CUBIC_METERS
    assert sensor.native_value == 1.2
    assert sensor.translation_key == "volume"


def test_return_temp_and_balance_classes() -> None:
    temp = KMDReturnTempSensor(_coord(), _entry())
    bal = KMDBalanceSensor(_coord({"billing": {"saldo_kr": 42.5}}), _entry())
    assert temp.device_class == SensorDeviceClass.TEMPERATURE
    assert temp.state_class == SensorStateClass.MEASUREMENT
    assert bal.device_class == SensorDeviceClass.MONETARY
    assert bal.state_class is None
    assert bal.native_value == 42.5


def test_overview_attributes_exclude_otp_and_qr() -> None:
    attrs = KMDOverviewSensor(_coord(), _entry()).extra_state_attributes
    assert "mitid_otp_code" not in attrs
    assert "mitid_qr_svg" not in attrs
    assert attrs["entry_id"] == "test-entry"
    assert attrs["annual"]["2026"] == 1234.0
    assert "mitid_otp_code" in KMDOverviewSensor._unrecorded_attributes
    assert "mitid_qr_svg" in KMDOverviewSensor._unrecorded_attributes


def test_entity_translation_keys_match_strings() -> None:
    import json
    from pathlib import Path

    strings = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components/kmd_easy_energy/strings.json").read_text()
    )
    da = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components/kmd_easy_energy/translations/da.json").read_text()
    )
    assert set(strings["entity"]["sensor"]) == set(da["entity"]["sensor"])
    assert set(strings["entity"]["button"]) == set(da["entity"]["button"])
    assert "fjernvarmevand" in da["entity"]["sensor"]["volume"]["name"]
    from kmd_easy_energy.button import KMDSyncButton
    from kmd_easy_energy.sensor import KMDHDDSensor

    assert KMDSyncButton(_coord(), _entry()).translation_key == "sync"
    assert KMDHDDSensor(_coord(), _entry()).translation_key == "heating_degree_days"
    assert "hourly_kwh" in KMDOverviewSensor._unrecorded_attributes
    assert "meters" in KMDOverviewSensor._unrecorded_attributes



def test_price_motivation_and_forecast_sensors() -> None:
    from kmd_easy_energy.sensor import (
        KMDEnergyPriceSensor,
        KMDForecastAnnualSensor,
        KMDKwhPerHddSensor,
        KMDMotivationAdjustmentSensor,
        KMDMotivationStatusSensor,
        KMDNormalizedAnnualSensor,
    )

    coord = _coord(
        {
            "energy_price_dkk_per_kwh": 0.668,
            "motivation_status": "bonus",
            "motivation_dkk_per_kwh": -0.05,
            "tariff": {"tariff_year": 2026, "source": "https://www.kredslob.dk/privat/fjernvarme/fjernvarmepriser"},
            "degree_day": {
                "kwh_per_hdd": 2.0,
                "normalized_annual_kwh": 6200.0,
                "forecast_annual_kwh": 5400.0,
            },
        }
    )
    entry = _entry()
    price = KMDEnergyPriceSensor(coord, entry)
    assert price.native_value == 0.668
    assert price.translation_key == "energy_price"
    assert price.native_unit_of_measurement == "DKK/kWh"
    assert "kredslob.dk" in (price.extra_state_attributes["source"] or "")
    status = KMDMotivationStatusSensor(coord, entry)
    assert status.native_value == "bonus"
    assert status.options == ["bonus", "neutral", "penalty"]
    adj = KMDMotivationAdjustmentSensor(coord, entry)
    assert adj.native_value == -0.05
    assert KMDKwhPerHddSensor(coord, entry).native_value == 2.0
    assert KMDNormalizedAnnualSensor(coord, entry).native_value == 6200.0
    assert KMDForecastAnnualSensor(coord, entry).native_value == 5400.0
