"""Energy dashboard statistics import."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kmd_easy_energy.statistics import (
    energy_statistic_id,
    import_hourly_statistics,
    volume_statistic_id,
)


def test_statistic_ids() -> None:
    assert energy_statistic_id("abc") == "kmd_easy_energy:energy_abc"
    assert volume_statistic_id("abc") == "kmd_easy_energy:volume_abc"


def test_import_skips_without_recorder() -> None:
    hass = MagicMock()
    hass.config.components = set()
    entry = SimpleNamespace(entry_id="e1", title="Kredsløb")
    result = import_hourly_statistics(
        hass,
        entry,
        {
            "hourly_kwh": [
                {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1, "IsComplete": True}
            ]
        },
    )
    assert result == {"energy": 0, "volume": 0}


def test_import_queues_external_statistics() -> None:
    hass = MagicMock()
    hass.config.components = {"recorder"}
    entry = SimpleNamespace(entry_id="e1", title="Kredsløb")
    state = {
        "hourly_kwh": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1.0, "IsComplete": True},
            {"DateFrom": "2026-11-01T01:00:00.000Z", "Value": 2.0, "IsComplete": True},
        ],
        "hourly_m3": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 0.1, "IsComplete": True},
        ],
    }
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        result = import_hourly_statistics(hass, entry, state)
    assert result["energy"] == 2
    assert result["volume"] == 1
    assert add.call_count == 2
    energy_meta = add.call_args_list[0].args[1]
    assert energy_meta["statistic_id"] == "kmd_easy_energy:energy_e1"
    assert energy_meta["source"] == "kmd_easy_energy"
    assert energy_meta["has_sum"] is True
    assert energy_meta["unit_class"] == "energy"
    rows = list(add.call_args_list[0].args[2])
    assert rows[-1]["sum"] == 3.0
