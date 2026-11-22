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


def test_volume_uses_water_device_class() -> None:
    sensor = KMDVolumeSensor(_coord(), _entry())
    assert sensor.device_class == SensorDeviceClass.WATER
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.native_unit_of_measurement == UnitOfVolume.CUBIC_METERS
    assert sensor.native_value == 1.2


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
