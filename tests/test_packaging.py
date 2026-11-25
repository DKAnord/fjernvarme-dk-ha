"""Repo hygiene: vendored license, manifest, hacs, no dead Aula/Helpers."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "custom_components" / "kmd_easy_energy"


def test_helpers_and_aula_removed() -> None:
    assert not (CC / "mitid_browserclient" / "Helpers.py").exists()
    assert not (CC / "mitid_browserclient" / "login_flows").exists()
    init = (CC / "mitid_browserclient" / "__init__.py").read_text()
    assert "Helpers" not in init
    assert "from .BrowserClient import BrowserClient" in init


def test_vendored_mitid_license_and_notice() -> None:
    license_text = (CC / "mitid_browserclient" / "LICENSE").read_text()
    assert "MIT License" in license_text
    assert "Hundter" in license_text
    notice = (ROOT / "NOTICE").read_text()
    assert "Hundter/MitID-BrowserClient" in notice
    assert "MIT" in notice


def test_manifest_loggers_and_integration_type() -> None:
    manifest = json.loads((CC / "manifest.json").read_text())
    assert manifest["integration_type"] == "service"
    assert "custom_components.kmd_easy_energy" in manifest["loggers"]
    assert manifest["version"] == "1.2.6"
    assert "http" in manifest.get("after_dependencies", [])
    assert "recorder" in manifest.get("after_dependencies", [])
    assert not any(str(r).startswith("requests") for r in manifest["requirements"])


def test_hacs_json_min_version_and_render_readme() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["render_readme"] is True
    # Reauth helpers (_get_reauth_entry, async_update_reload_and_abort)
    # require HA 2024.11+; 2024.12.0 is the conservative documented floor.
    parts = [int(p) for p in hacs["homeassistant"].split(".")]
    assert parts >= [2024, 12, 0]


def test_hassfest_action_is_pinned() -> None:
    wf = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "home-assistant/actions/hassfest@master" not in wf
    assert "home-assistant/actions/hassfest@07f46fd2e19967768b5fd3000f91f857452b767c" in wf


def test_brands_pr_kit_present() -> None:
    base = ROOT / "docs" / "home-assistant-brands" / "custom_integrations" / "kmd_easy_energy"
    assert (base / "icon.png").is_file()
    assert (base / "icon@2x.png").is_file()
    readme = (ROOT / "docs" / "home-assistant-brands" / "README.md").read_text()
    assert "home-assistant/brands" in readme
    assert "DKAnord" in readme
