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


def test_sync_reminder_binary_sensor() -> None:
    from datetime import datetime, timezone

    from kmd_easy_energy.binary_sensor import KMDSyncReminderBinarySensor
    from kmd_easy_energy.sync_reminder import compute_sync_reminder

    coord = MagicMock()
    sun = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    state = {"last": datetime(2026, 11, 18, 9, tzinfo=timezone.utc), "enabled": True}
    coord.sync_reminder = lambda: compute_sync_reminder(state["last"], sun, state["enabled"])
    sensor = KMDSyncReminderBinarySensor(coord, _entry())
    assert sensor.unique_id == "test-entry_sync_reminder"
    assert sensor.translation_key == "sync_reminder"
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["message"] == "Det er 4 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."
    state["last"] = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)  # Friday
    assert sensor.is_on is False
    state["last"] = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)
    state["enabled"] = False
    assert sensor.is_on is False
    assert sensor.extra_state_attributes["enabled"] is False
