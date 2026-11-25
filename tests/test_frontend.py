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
    assert 'VER = "1.2.4"' in js
    assert "data-kmd-card-version" in js
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


def test_card_js_harnesses() -> None:
    """Run the Node harnesses (QR animation, session-based sync / reminder)."""
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    harnesses = sorted((ROOT / "tests/js").glob("*.test.js"))
    assert len(harnesses) >= 2
    for harness in harnesses:
        res = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, f"{harness.name}: {res.stdout}{res.stderr}"


def test_card_session_sync_contract() -> None:
    js = CARD.read_text()
    assert "token_expired" not in js
    assert "sync_reminder" in js
    assert "last_sync" in js
    assert '"kmd_easy_energy", "refresh"' not in js


def test_card_cost_estimate_and_utilities_fallback() -> None:
    js = CARD.read_text()
    assert 'data-section="cost-estimate"' in js
    assert 'id: "aalborg-forsyning"' in js and 'status: "confirmed"' in js
    assert 'id: "frederikshavn-forsyning"' in js and 'id: "frederikshavn-forsyning", name: "Frederikshavn Forsyning", city: "Frederikshavn", url: "https://www.forsyningen.dk/selvbetjening", status: "confirmed"' in js
    assert 'id: "soroe-fjernvarme"' in js and 'backend: "eforsyning"' in js
    assert 'id: "hadsund-fjernvarme"' in js and 'status: "confirmed"' in js
    assert 'id: "hedensted-fjernvarme"' in js and 'backend: "eforsyning"' in js
    assert 'id: "fjernvarme-fyn"' in js
    assert 'id: "hillerod-forsyning"' in js
    assert 'id: "hillerod-forsyning", name: "Hillerød Forsyning", city: "Hillerød", url: "https://hfors.dk/selvbetjening/se-forbrug-regninger/watts-on-din-forbrugsapp-til-vand-varme", status: "confirmed", backend: "wattson"' in js
