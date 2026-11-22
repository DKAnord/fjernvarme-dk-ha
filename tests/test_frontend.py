"""Frontend contract: no OTP attributes, robust MitID service, files in sync."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "custom_components/kmd_easy_energy/frontend/kmd-easy-energy-card.js"
DIST = ROOT / "dist/kmd-easy-energy-card.js"


def test_frontend_copies_identical() -> None:
    assert CARD.read_bytes() == DIST.read_bytes()


def test_card_uses_event_and_service() -> None:
    js = CARD.read_text()
    assert "kmd_easy_energy/mitid/subscribe" in js
    assert "subscribeMessage" in js
    # The admin-only, recorder-stored bus subscription is no longer used for OTP/QR.
    assert "subscribeEvents" not in js
    assert "start_mitid_sync" in js
    assert "mitid_otp_code" not in js
    assert "mitid_qr_svg" not in js
    assert 'VER = "0.3.0"' in js
    # Must not guess button.<utility_id>_sync as the only path
    assert "button.${activeUtilId" not in js


def test_card_keeps_upstream_peak_detection() -> None:
    js = CARD.read_text()
    assert "identifyPeakHours" in js
    assert "_renderHourlyAvgSvg" in js
    assert "spidstimer" in js


def test_card_has_notify_service_dropdown() -> None:
    js = CARD.read_text()
    assert "notifySel" in js
    assert "services?.notify" in js


def test_card_mitid_text_same_phone_only() -> None:
    js = CARD.read_text()
    assert "Kun hvis du opsætter på samme telefon som MitID-appen" in js
    assert "Tablet eller computer + MitID-app på telefonen" in js
    assert "headless browser" not in js
    assert "Vigtigt for nye brugere" not in js


def test_card_js_harness_qr_animation() -> None:
    """Run the Node harness (QR frames alternate, websocket subscription)."""
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    harness = ROOT / "tests/js/card_mitid_qr.test.js"
    res = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
