"""Capability-driven entities and card data for all backends."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from kmd_easy_energy.capabilities import (
    BACKEND_CAPABILITIES,
    data_capabilities,
    effective_capabilities,
)

FULL_KMD_STATE = {
    "hourly": {"kwh": [0.5] * 24},
    "hourly_kwh": [{"DateFrom": "x", "Value": 1, "IsComplete": True}],
    "daily": {"days": {"1": 10}},
    "monthly": {"2026": {"Jan": 100}},
    "return_temp": {"annual": {"2026": 31.0}},
    "hourly_m3": [{"DateFrom": "x", "Value": 0.1, "IsComplete": True}],
    "energy_price_dkk_per_kwh": 0.668,
    "billing": {"saldo_kr": -12.0},
    "forecast": {"expected_kwh": 9000},
}


def test_static_backend_capabilities() -> None:
    assert {"hourly", "mitid", "billing"} <= BACKEND_CAPABILITIES["kmd"]
    ef = BACKEND_CAPABILITIES["eforsyning"]
    assert {"daily", "monthly", "temperatures", "volume"} <= ef
    assert not ef & {"hourly", "mitid", "billing", "forecast"}


def test_kmd_full_data_has_everything() -> None:
    caps = effective_capabilities("kmd", FULL_KMD_STATE)
    assert set(caps) == BACKEND_CAPABILITIES["kmd"]


def test_kmd_without_hourly_or_temps_hides_them() -> None:
    state = {k: v for k, v in FULL_KMD_STATE.items() if k not in ("hourly", "hourly_kwh", "return_temp")}
    caps = effective_capabilities("kmd", state)
    assert "hourly" not in caps and "temperatures" not in caps
    assert "daily" in caps and "mitid" in caps


def test_empty_values_do_not_count_as_data() -> None:
    state = {"hourly": {"kwh": []}, "billing": {}, "forecast": {"expected_kwh": None}, "return_temp": {"annual": {}}}
    assert data_capabilities(state) == set()


def test_eforsyning_never_claims_hourly_even_if_data_present() -> None:
    caps = effective_capabilities("eforsyning", FULL_KMD_STATE, reminder_enabled=False, auto_sync_enabled=True)
    assert "hourly" not in caps and "billing" not in caps
    assert "reminder" not in caps and "auto_sync" in caps


def test_never_synced_kmd_still_offers_mitid() -> None:
    assert effective_capabilities("kmd", {}) == ["mitid", "reminder"]


def _coord(backend: str):
    from kmd_easy_energy.capabilities import backend_capabilities

    coord = MagicMock()
    coord.backend_capabilities = backend_capabilities(backend)
    coord.data = {}
    return coord


def test_sensors_only_created_when_backend_can_fill_them() -> None:
    from kmd_easy_energy.sensor import sensors_for

    entry = SimpleNamespace(entry_id="e1", title="T")
    kmd = {type(s).__name__ for s in sensors_for(_coord("kmd"), entry)}
    ef = {type(s).__name__ for s in sensors_for(_coord("eforsyning"), entry)}
    assert len(kmd) == 17
    assert "KMDBalanceSensor" in kmd and "KMDBalanceSensor" not in ef
    assert {
        "KMDVolumeSensor",
        "KMDReturnTempSensor",
        "KMDEnergySensor",
        "KMDLastSyncSensor",
        "KMDEffectivePriceSensor",
        "KMDYearCostSensor",
    } <= ef


def test_binary_sensors_follow_capabilities() -> None:
    import asyncio

    from kmd_easy_energy import binary_sensor

    for backend, expected in (("kmd", 3), ("eforsyning", 3)):
        coord = _coord(backend)
        hass = MagicMock()
        hass.data = {"kmd_easy_energy": {"e1": coord}}
        added = []
        asyncio.run(
            binary_sensor.async_setup_entry(hass, SimpleNamespace(entry_id="e1", title="T"), added.extend)
        )
        assert len(added) == expected
    coord = MagicMock()
    coord.backend_capabilities = frozenset({"daily"})
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {"e1": coord}}
    added = []
    asyncio.run(binary_sensor.async_setup_entry(hass, SimpleNamespace(entry_id="e1", title="T"), added.extend))
    assert [type(b).__name__ for b in added] == ["KMDAbnormalConsumptionBinarySensor"]


def test_coordinator_publishes_capabilities_in_state(tmp_path) -> None:
    from test_coordinator import make_coordinator

    coord, _, _, _ = make_coordinator(tmp_path)
    state = dict(FULL_KMD_STATE)
    coord._enrich_derived(state)
    assert set(state["capabilities"]) == BACKEND_CAPABILITIES["kmd"]
    assert state["backend_capabilities"] == sorted(BACKEND_CAPABILITIES["kmd"])


def test_tightened_capability_predicates() -> None:
    # Balance: None (without invoice totals) does NOT claim billing capability
    assert "billing" not in data_capabilities({"balance": {"Balance": None}, "billing": {}})
    # Forecast with 0 expected_kwh does NOT claim forecast capability
    assert "forecast" not in data_capabilities({"forecast": {"expected_kwh": 0, "budget_kwh": 0}})
    # Forward-only return_temp dict (no actual return temperature) does NOT claim temperatures
    assert "temperatures" not in data_capabilities(
        {"return_temp": {"forward_annual": {"2026": 65.0}, "forward_monthly_2026": {"Jan": 65.0}}}
    )
    # Cooling-derived daily_m3 total claims volume capability
    assert "volume" in data_capabilities(
        {"daily_m3": {"month": "November 2026", "total": 42.5, "source": "kmd_cooling"}}
    )
