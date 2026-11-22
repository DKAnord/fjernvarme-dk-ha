"""MitID QR path (setup on a tablet/PC, MitID app on the phone) without real MitID."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import qrcode

from kmd_easy_energy import ws_subscribe_mitid_challenge
from kmd_easy_energy.api.kmd_mitid_auth import KMDMitIDAuthenticator, _qr_to_svg
from kmd_easy_energy.const import DOMAIN, SIGNAL_MITID_CHALLENGE, WS_TYPE_MITID_SUBSCRIBE
from kmd_easy_energy.mitid_browserclient.BrowserClient import BrowserClient


def _fake_client(poll_json: dict) -> BrowserClient:
    """BrowserClient with a scripted poll response (bypasses __init__/network)."""
    client = BrowserClient.__new__(BrowserClient)
    import threading

    client.qr_display_thread_lock = threading.Lock()
    client.poll_url = "https://example.invalid/poll"
    client.ticket = "t"
    resp = SimpleNamespace(status_code=200, json=lambda: poll_json)
    client.session = SimpleNamespace(post=lambda *a, **k: resp)
    return client


def test_poll_once_returns_both_animated_qr_frames() -> None:
    binding = "A" * 22 + "B" * 22
    auth = KMDMitIDAuthenticator.__new__(KMDMitIDAuthenticator)
    auth.mitid_client = _fake_client(
        {"status": "channel_validation_tqr", "channelBindingValue": binding, "updateCount": 3}
    )
    res = auth.poll_once()
    assert res["status"] == "qr_ready"
    frames = res["qr_frames"]
    assert len(frames) == 2 and frames[0] != frames[1]
    assert res["qr_svg"] == frames[0]
    for svg in frames:
        assert svg.lstrip().startswith("<?xml") or svg.lstrip().startswith("<svg")
        assert 'shape-rendering="crispEdges"' in svg
        assert "viewBox" in svg  # scales to any card size
    # Frame payloads carry p=1 / p=2 halves exactly like MitID's own web client.
    q1, q2 = auth.mitid_client.get_current_qr_codes()
    d1 = json.loads(b"".join(seg.data for seg in q1.data_list).decode())
    d2 = json.loads(b"".join(seg.data for seg in q2.data_list).decode())
    assert (d1["p"], d2["p"]) == (1, 2)
    assert d1["h"] + d2["h"] == binding
    assert d1["uc"] == d2["uc"] == 3
    assert (q1.border, q2.border) == (4, 4)


def test_poll_once_otp_and_verified_need_no_qr() -> None:
    auth = KMDMitIDAuthenticator.__new__(KMDMitIDAuthenticator)
    auth.mitid_client = _fake_client({"status": "channel_validation_otp", "channelBindingValue": "1234"})
    res = auth.poll_once()
    assert res["status"] == "otp_ready" and res["otp_code"] == "1234"
    assert "qr_frames" not in res
    auth.mitid_client = _fake_client({"status": "channel_verified"})
    assert auth.poll_once()["status"] == "verified"


def test_qr_svg_scannable_size() -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(json.dumps({"v": 1, "p": 1, "t": 2, "h": "x" * 44, "uc": 12}, separators=(",", ":")))
    qr.make()
    svg = _qr_to_svg(qr)
    # QR version stays small (<= 41 modules) so ~240 px on the card gives >= 5 px/module.
    assert qr.modules_count <= 41
    assert svg.count("<svg") == 1
    assert '<rect width="100%" height="100%" fill="#ffffff"/>' in svg
    assert 'mm"' not in svg


def _ws_setup(coords: dict):
    hass = MagicMock()
    hass.data = {DOMAIN: coords}
    conn = MagicMock()
    conn.subscriptions = {}
    captured = {}

    def fake_connect(h, signal, target):
        captured["signal"] = signal
        captured["target"] = target
        return MagicMock(name="unsub")

    return hass, conn, captured, fake_connect


def test_ws_subscribe_streams_challenge_and_replays_active_flow() -> None:
    active = SimpleNamespace(
        sync_state="qr_ready",
        entry=SimpleNamespace(entry_id="e1"),
        mitid_challenge_payload=lambda: {"entry_id": "e1", "sync_state": "qr_ready", "qr_frames": ["<svg/>"]},
    )
    idle = SimpleNamespace(
        sync_state="idle",
        entry=SimpleNamespace(entry_id="e2"),
        mitid_challenge_payload=lambda: {"entry_id": "e2", "sync_state": "idle"},
    )
    hass, conn, captured, fake_connect = _ws_setup({"e1": active, "e2": idle})
    with patch("kmd_easy_energy.async_dispatcher_connect", side_effect=fake_connect):
        ws_subscribe_mitid_challenge(hass, conn, {"id": 7, "type": WS_TYPE_MITID_SUBSCRIBE})
    assert captured["signal"] == SIGNAL_MITID_CHALLENGE
    assert 7 in conn.subscriptions
    conn.send_result.assert_called_once_with(7)
    # A tablet that opens the card mid-flow immediately gets the current QR.
    sent = [c.args[0] for c in conn.send_message.call_args_list]
    assert len(sent) == 1 and sent[0]["event"]["entry_id"] == "e1"
    # Live updates are forwarded.
    captured["target"]({"entry_id": "e2", "sync_state": "otp_ready", "otp_code": "9999"})
    assert conn.send_message.call_count == 2


def test_ws_subscribe_filters_entry_id() -> None:
    hass, conn, captured, fake_connect = _ws_setup({})
    with patch("kmd_easy_energy.async_dispatcher_connect", side_effect=fake_connect):
        ws_subscribe_mitid_challenge(
            hass, conn, {"id": 3, "type": WS_TYPE_MITID_SUBSCRIBE, "entry_id": "mine"}
        )
    captured["target"]({"entry_id": "other", "otp_code": "1111"})
    conn.send_message.assert_not_called()
    captured["target"]({"entry_id": "mine", "otp_code": "2222"})
    conn.send_message.assert_called_once()


def test_ws_command_is_not_admin_only() -> None:
    """Wall tablets often run as non-admin users; subscribe_events would reject them."""
    schema_types = getattr(ws_subscribe_mitid_challenge, "_ws_command", None)
    assert schema_types == WS_TYPE_MITID_SUBSCRIBE
    assert not getattr(ws_subscribe_mitid_challenge, "_ws_require_admin", False)
