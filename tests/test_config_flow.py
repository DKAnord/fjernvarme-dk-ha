"""Config flow unique_id, reauth steps, and manifest contract."""

from __future__ import annotations

import json
from pathlib import Path

from kmd_easy_energy.config_flow import KMDEasyEnergyConfigFlow
from kmd_easy_energy.const import DOMAIN, UPDATE_INTERVAL
from kmd_easy_energy.util import unique_id_for


ROOT = Path(__file__).resolve().parents[1]


def test_flow_has_reauth_and_unique_id_helper() -> None:
    assert hasattr(KMDEasyEnergyConfigFlow, "async_step_reauth")
    assert hasattr(KMDEasyEnergyConfigFlow, "async_step_reauth_confirm")
    assert hasattr(KMDEasyEnergyConfigFlow, "async_step_reauth_mitid")
    assert hasattr(KMDEasyEnergyConfigFlow, "_async_set_entry_unique_id")
    assert KMDEasyEnergyConfigFlow.VERSION == 1


def test_duplicate_unique_ids_collide() -> None:
    first = unique_id_for("kredslob", "https://minvarme.kredslob.dk/")
    second = unique_id_for("kredslob", "https://minvarme.kredslob.dk/")
    other = unique_id_for("envafors", "https://skenergi.dk/minforsyning/")
    custom_a = unique_id_for("custom", "https://varme.example.dk/login")
    custom_b = unique_id_for("custom", "https://www.varme.example.dk/other")
    assert first == second == "kredslob"
    assert other != first
    assert custom_a == custom_b == "custom:varme.example.dk"


def test_manifest_and_hacs_versions() -> None:
    manifest = json.loads((ROOT / "custom_components/kmd_easy_energy/manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert manifest["domain"] == DOMAIN
    assert manifest["version"] == "0.3.0"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert not any(r.startswith("requests") for r in manifest["requirements"])
    assert hacs["homeassistant"].count(".") == 2
    assert UPDATE_INTERVAL.total_seconds() == 30 * 60


def test_strings_cover_reauth() -> None:
    for rel in (
        "custom_components/kmd_easy_energy/strings.json",
        "custom_components/kmd_easy_energy/translations/en.json",
        "custom_components/kmd_easy_energy/translations/da.json",
    ):
        data = json.loads((ROOT / rel).read_text())
        assert "reauth_confirm" in data["config"]["step"]
        assert "reauth_mitid" in data["config"]["step"]
        assert "already_configured" in data["config"]["abort"]
        assert "reauth_successful" in data["config"]["abort"]


def test_services_include_start_mitid_sync() -> None:
    text = (ROOT / "custom_components/kmd_easy_energy/services.yaml").read_text()
    assert "start_mitid_sync:" in text


def test_notify_service_selector_discovers_mobile_first() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from kmd_easy_energy.config_flow import _notify_service_selector

    hass = SimpleNamespace(
        services=SimpleNamespace(
            async_services=MagicMock(
                return_value={
                    "notify": {
                        "persistent_notification": {},
                        "send_message": {},
                        "slack_alerts": {},
                        "mobile_app_phone_b": {},
                        "mobile_app_phone_a": {},
                    }
                }
            )
        )
    )
    sel = _notify_service_selector(hass, current="notify.legacy_custom")
    opts = sel.config["options"]
    vals = [o["value"] for o in opts]
    assert vals == ["", "mobile_app_phone_a", "mobile_app_phone_b", "slack_alerts", "legacy_custom"]
    assert sel.config["custom_value"] is True
