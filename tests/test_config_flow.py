"""Config flow unique_id, session-based sync (no token / reauth), migration, manifest."""

from __future__ import annotations

import json
from pathlib import Path

from kmd_easy_energy.config_flow import KMDEasyEnergyConfigFlow
from kmd_easy_energy.const import DOMAIN, UPDATE_INTERVAL
from kmd_easy_energy.util import unique_id_for


ROOT = Path(__file__).resolve().parents[1]


def test_flow_has_no_token_reauth_and_unique_id_helper() -> None:
    assert not hasattr(KMDEasyEnergyConfigFlow, "async_step_reauth")
    assert not hasattr(KMDEasyEnergyConfigFlow, "async_step_reauth_confirm")
    assert not hasattr(KMDEasyEnergyConfigFlow, "async_step_reauth_mitid")
    assert not hasattr(KMDEasyEnergyConfigFlow, "_validate_token")
    assert hasattr(KMDEasyEnergyConfigFlow, "_async_set_entry_unique_id")
    assert KMDEasyEnergyConfigFlow.VERSION == 1
    assert KMDEasyEnergyConfigFlow.MINOR_VERSION == 3
    src = (ROOT / "custom_components/kmd_easy_energy/config_flow.py").read_text()
    assert "CONF_ACCESS_TOKEN" not in src
    assert "ConfigEntryAuthFailed" not in src


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
    assert manifest["version"] == "1.2.0"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert not any(r.startswith("requests") for r in manifest["requirements"])
    assert hacs["homeassistant"].count(".") == 2
    assert UPDATE_INTERVAL is None  # no background polling against KMD


def test_strings_have_no_token_or_reauth() -> None:
    for rel in (
        "custom_components/kmd_easy_energy/strings.json",
        "custom_components/kmd_easy_energy/translations/en.json",
        "custom_components/kmd_easy_energy/translations/da.json",
    ):
        data = json.loads((ROOT / rel).read_text())
        steps = data["config"]["step"]
        assert "reauth_confirm" not in steps and "reauth_mitid" not in steps
        assert "access_token" not in steps["auth"]["data"]
        assert "access_token" not in steps["reconfigure"]["data"]
        assert "already_configured" in data["config"]["abort"]
        assert "sync_reminder" in data["options"]["step"]["init"]["data"]
        assert "last_sync" in data["entity"]["sensor"]
        assert "sync_reminder" in data["entity"]["binary_sensor"]


def test_auth_step_points_to_dashboard_card() -> None:
    """Config flow must say Submit only creates the entry; MitID is on the card.

    Hassfest rejects HTML-like tags in translations (e.g. <device_id>), so the
    description must not contain < or >.
    """
    en = json.loads((ROOT / "custom_components/kmd_easy_energy/strings.json").read_text())
    da = json.loads((ROOT / "custom_components/kmd_easy_energy/translations/da.json").read_text())
    en_tr = json.loads((ROOT / "custom_components/kmd_easy_energy/translations/en.json").read_text())
    assert en["config"]["step"]["auth"]["description"] == en_tr["config"]["step"]["auth"]["description"]
    en_desc = en["config"]["step"]["auth"]["description"]
    da_desc = da["config"]["step"]["auth"]["description"]
    assert "After Submit" in en_desc
    assert "Gem & Start MitID-synkronisering" in en_desc
    assert "No MitID login happens in this dialog" in en_desc
    assert "Efter Submit" in da_desc
    assert "Gem & Start MitID-synkronisering" in da_desc
    assert "intet MitID-login i denne dialog" in da_desc
    for desc in (en_desc, da_desc):
        assert "<" not in desc and ">" not in desc


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


def test_no_auth_failed_anywhere_in_integration() -> None:
    cc = ROOT / "custom_components/kmd_easy_energy"
    for py in cc.rglob("*.py"):
        text = py.read_text()
        assert "ConfigEntryAuthFailed" not in text, py
        assert "async_start_reauth" not in text, py
        assert "TOKEN_WARN_AGE" not in text, py
        assert "token_expired\"]" not in text, py


def _fake_entry(data, options=None, minor=1):
    from types import SimpleNamespace

    return SimpleNamespace(
        version=1, minor_version=minor, data=dict(data), options=dict(options or {}), title="Kredsløb"
    )


def test_migrate_removes_stored_token_keeps_rest() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from kmd_easy_energy import async_migrate_entry

    entry = _fake_entry(
        {"utility_id": "kredslob", "access_token": "old-fake-token", "mitid_username": "u"},
        {"access_token": "also-old", "price_dkk_per_kwh": 0.7},
    )
    hass = MagicMock()
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert "access_token" not in kwargs["data"]
    assert "access_token" not in kwargs["options"]
    assert kwargs["data"]["mitid_username"] == "u"
    assert kwargs["options"]["price_dkk_per_kwh"] == 0.7
    # 1.1 migrates straight through 1.2 to 1.3 in one update.
    assert kwargs["minor_version"] == 3
    assert hass.config_entries.async_update_entry.call_count == 1


def test_migrate_noop_when_current_and_refuses_future() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from kmd_easy_energy import async_migrate_entry

    hass = MagicMock()
    assert asyncio.run(async_migrate_entry(hass, _fake_entry({"utility_id": "x"}, minor=3))) is True
    hass.config_entries.async_update_entry.assert_not_called()
    future = _fake_entry({})
    future.version = 2
    assert asyncio.run(async_migrate_entry(hass, future)) is False
