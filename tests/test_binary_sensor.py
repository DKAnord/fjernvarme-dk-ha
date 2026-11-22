"""Motivation penalty and abnormal-consumption binary sensors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from kmd_easy_energy.binary_sensor import (
    KMDAbnormalConsumptionBinarySensor,
    KMDMotivationPenaltyBinarySensor,
)


def _entry():
    return SimpleNamespace(entry_id="test-entry", title="Kredsløb")


def test_motivation_penalty_binary() -> None:
    coord = MagicMock()
    coord.data = {"motivation_status": "penalty"}
    sensor = KMDMotivationPenaltyBinarySensor(coord, _entry())
    assert sensor.is_on is True
    assert sensor.translation_key == "motivation_penalty"
    coord.data = {"motivation_status": "bonus"}
    assert sensor.is_on is False


def test_abnormal_consumption_binary() -> None:
    coord = MagicMock()
    coord.data = {
        "abnormal_consumption": {
            "abnormal": True,
            "actual_kwh": 30,
            "expected_kwh": 10,
            "reason": "hdd_adjusted_high",
        }
    }
    sensor = KMDAbnormalConsumptionBinarySensor(coord, _entry())
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["ratio"] if "ratio" in sensor.extra_state_attributes else True
    assert sensor.extra_state_attributes["actual_kwh"] == 30
    coord.data = {"abnormal_consumption": {"abnormal": False, "reason": "insufficient_history"}}
    assert sensor.is_on is False
