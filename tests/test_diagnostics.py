"""Diagnostics must redact tokens, MitID user, meter/customer IDs and addresses."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kmd_easy_energy.diagnostics import (
    TO_REDACT,
    _summarize_coordinator,
    async_get_config_entry_diagnostics,
)


def test_summarize_omits_series_and_tokens() -> None:
    summary = _summarize_coordinator(
        {
            "utility_id": "kredslob",
            "access_token": "secret-token",
            "mitid_username": "user1234",
            "hourly_kwh": [{"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1}],
            "hourly_m3": [1, 2, 3],
            "meters": [{"InstallationId": "inst-1", "Address": "Hemmeligvej 1"}],
            "available_units": [{"Name": "kWh", "Id": "u1"}],
            "daily": {"total": 12.5},
            "token_expired": False,
        }
    )
    dumped = str(summary)
    assert "secret-token" not in dumped
    assert "user1234" not in dumped
    assert "Hemmeligvej" not in dumped
    assert "inst-1" not in dumped
    assert summary["hourly_kwh_points"] == 1
    assert summary["hourly_m3_points"] == 3
    assert summary["meter_count"] == 1
    assert summary["energy_mtd_kwh"] == 12.5
    assert "kWh" in summary["available_unit_names"]


@pytest.mark.asyncio
async def test_diagnostics_redacts_entry_secrets() -> None:
    entry = SimpleNamespace(
        title="Kredsløb",
        unique_id="kredslob",
        domain="kmd_easy_energy",
        version=1,
        entry_id="entry-1",
        data={
            "access_token": "tok_live_abc",
            "mitid_username": "mitid-user-42",
            "customer_id": "cust-99",
            "customer_number": "cn-88",
            "utility_id": "kredslob",
        },
        options={"portal_url": "https://minvarme.kredslob.dk/"},
    )
    coordinator = MagicMock()
    coordinator.data = {
        "utility_id": "kredslob",
        "meters": [{"InstallationId": "inst-secret", "Address": "Vej 9"}],
        "hourly_m3": [],
    }
    hass = MagicMock()
    hass.data = {"kmd_easy_energy": {"entry-1": coordinator}}

    result = await async_get_config_entry_diagnostics(hass, entry)
    blob = str(result)
    assert "tok_live_abc" not in blob
    assert "mitid-user-42" not in blob
    assert "cust-99" not in blob
    assert "cn-88" not in blob
    assert "inst-secret" not in blob
    assert "Vej 9" not in blob
    assert result["entry"]["data"]["access_token"] == "**REDACTED**"
    assert result["entry"]["data"]["mitid_username"] == "**REDACTED**"
    assert result["entry"]["data"]["customer_id"] == "**REDACTED**"
    assert result["entry"]["data"]["utility_id"] == "kredslob"
    assert result["coordinator"]["utility_id"] == "kredslob"
    assert "access_token" in TO_REDACT
    assert "InstallationId" in TO_REDACT
    assert "Address" in TO_REDACT
