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
    assert "kmd_easy_energy_mitid_challenge" in js
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
