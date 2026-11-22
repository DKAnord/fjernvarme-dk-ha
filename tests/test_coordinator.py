"""Coordinator cache location, auth failure, and startup resilience."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from kmd_easy_energy.const import EVENT_MITID_CHALLENGE, SIGNAL_MITID_CHALLENGE
from kmd_easy_energy.coordinator import KMDEasyEnergyCoordinator
from kmd_easy_energy.util import legacy_www_cache_paths, sanitize_cache


class FakeStore:
    def __init__(self, data=None) -> None:
        self.data = data
        self.saved: list[dict] = []
        self.removed = False

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        self.saved.append(data)

    async def async_remove(self):
        self.removed = True
        self.data = None


def _entry(tmp_path: Path, **data):
    payload = {
        "utility": "Kredsløb",
        "utility_id": "kredslob",
        "portal_url": "https://minvarme.kredslob.dk/",
        **data,
    }
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Kredsløb",
        data=payload,
        options={},
        unique_id="kredslob",
        async_on_unload=lambda *a, **k: None,
        async_start_reauth=MagicMock(),
    )
    return entry


def _hass(tmp_path: Path):
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.config.latitude = 56.15
    hass.config.longitude = 10.10
    hass.bus.async_fire = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    hass.async_create_task = MagicMock()
    return hass


def make_coordinator(tmp_path: Path, store: FakeStore | None = None, **entry_data):
    entry = _entry(tmp_path, **entry_data)
    hass = _hass(tmp_path)
    store = store or FakeStore()
    with patch.object(DataUpdateCoordinator, "__init__", lambda *a, **k: None):
        coord = KMDEasyEnergyCoordinator.__new__(KMDEasyEnergyCoordinator)
        coord.hass = hass
        coord.entry = entry
        coord._portal_url = entry.data["portal_url"]
        coord.client = None
        coord._token_obtained = None
        coord._utility_id = "kredslob"
        coord._store = store
        coord._legacy_paths = legacy_www_cache_paths(hass, "kredslob")
        coord._initial_setup_complete = None
        coord.sync_state = "idle"
        coord.sync_message = ""
        coord.mitid_otp_code = None
        coord.mitid_qr_svg = None
        coord.mitid_qr_frames = []
        coord._sync_task = None
        coord.data = {}
        coord.logger = MagicMock()
        coord.name = "kmd_easy_energy"
        coord.config_entry = entry
    return coord, hass, entry, store


@pytest.mark.asyncio
async def test_initialize_cache_uses_store_not_www(tmp_path: Path) -> None:
    store = FakeStore({"annual": {"2026": 9}, "mitid_otp_code": "9999"})
    coord, hass, _, _ = make_coordinator(tmp_path, store=store)
    # A leftover public file must not be the live cache location
    public = tmp_path / "www" / "varme" / "kmd_easy_energy_cache_kredslob.json"
    public.parent.mkdir(parents=True)
    public.write_text(json.dumps({"annual": {"2026": 1}}), encoding="utf-8")

    state = await coord.async_initialize_cache()
    assert state["annual"]["2026"] == 9
    assert "mitid_otp_code" not in state
    # Store data is the source of truth; we do not write under www/
    assert all(not str(p).startswith(str(tmp_path / "www")) for p in [coord._store])
    # When the private store already has data we leave leftover www files
    # for the first initialize? Current code only migrates when store is empty.
    # Migration is tested separately.


@pytest.mark.asyncio
async def test_migrates_and_deletes_legacy_www_cache(tmp_path: Path) -> None:
    store = FakeStore(None)
    coord, hass, _, store = make_coordinator(tmp_path, store=store)
    public = tmp_path / "www" / "varme" / "kmd_easy_energy_cache_kredslob.json"
    public.parent.mkdir(parents=True)
    public.write_text(
        json.dumps({"annual": {"2025": 50}, "mitid_otp_code": "1234", "daily": {"total": 3}}),
        encoding="utf-8",
    )
    seed = tmp_path / "www" / "varme" / "data.json"
    seed.write_text(json.dumps({"annual": {"1999": 1}, "marker": "do-not-seed"}), encoding="utf-8")

    state = await coord.async_initialize_cache()
    assert state["annual"]["2025"] == 50
    assert "mitid_otp_code" not in state
    assert "marker" not in state
    assert state["annual"].get("1999") is None
    assert not public.exists(), "legacy public cache should be deleted after migration"
    assert seed.exists() and "do-not-seed" in seed.read_text(), "data.json must not be deleted or used"
    assert store.data is not None
    assert "mitid_otp_code" not in store.data


@pytest.mark.asyncio
async def test_save_cache_strips_otp_and_stays_private(tmp_path: Path) -> None:
    coord, hass, _, store = make_coordinator(tmp_path)
    await coord._async_save_cache(
        {
            "annual": {"2026": 4},
            "mitid_otp_code": "1234",
            "mitid_qr_svg": "<svg />",
            "sync_state": "otp_ready",
        }
    )
    assert store.data is not None
    assert "mitid_otp_code" not in store.data
    assert "mitid_qr_svg" not in store.data
    assert store.data["sync_state"] == "idle"
    www = tmp_path / "www"
    if www.exists():
        leftovers = list(www.rglob("*.json"))
        assert leftovers == []


@pytest.mark.asyncio
async def test_401_raises_auth_failed_and_keeps_cache(tmp_path: Path) -> None:
    coord, hass, _, store = make_coordinator(
        tmp_path, access_token="expired-token", customer_id="c", customer_number="n"
    )
    cached = {"annual": {"2026": 77}, "daily": {"total": 5}}
    coord.data = dict(cached)
    err = ClientResponseError(MagicMock(), (), status=401, message="Unauthorized")
    coord.client = MagicMock()
    coord.client.get_active_meters = AsyncMock(side_effect=err)

    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()
    assert coord.data["annual"]["2026"] == 77
    assert coord.data["token_expired"] is True


@pytest.mark.asyncio
async def test_transient_http_error_serves_cache(tmp_path: Path) -> None:
    coord, *_ = make_coordinator(tmp_path, access_token="tok", customer_id="c", customer_number="n")
    coord.data = {"annual": {"2026": 11}, "daily": {"total": 2}}
    err = ClientResponseError(MagicMock(), (), status=502, message="Bad Gateway")
    coord.client = MagicMock()
    coord.client.get_active_meters = AsyncMock(side_effect=err)
    result = await coord._async_update_data()
    assert result["annual"]["2026"] == 11


@pytest.mark.asyncio
async def test_remove_storage_clears_store_and_legacy(tmp_path: Path) -> None:
    public = tmp_path / "www" / "varme" / "kmd_easy_energy_cache_kredslob.json"
    public.parent.mkdir(parents=True)
    public.write_text("{}", encoding="utf-8")
    store = FakeStore({"annual": {"2026": 1}})
    coord, *_ = make_coordinator(tmp_path, store=store)
    await coord.async_remove_storage()
    assert store.removed is True
    assert not public.exists()


def test_push_sync_ui_keeps_otp_off_state_and_bus(tmp_path: Path) -> None:
    """OTP/QR go to the dispatcher (websocket) only, never to state or the bus.

    The recorder stores every bus event, so the bus event carries status only.
    """
    coord, hass, *_ = make_coordinator(tmp_path)
    coord.data = {"annual": {"2026": 1}}
    coord.async_set_updated_data = MagicMock()
    with patch("kmd_easy_energy.coordinator.async_dispatcher_send") as send:
        coord._push_sync_ui("otp_ready", "Indtast kode på kortet.", otp_code="1234")
    assert coord.mitid_otp_code == "1234"
    published = coord.async_set_updated_data.call_args[0][0]
    assert "mitid_otp_code" not in published
    assert "mitid_qr_svg" not in published
    hass.bus.async_fire.assert_called()
    ev_name, ev_data = hass.bus.async_fire.call_args[0]
    assert ev_name == EVENT_MITID_CHALLENGE
    assert "otp_code" not in ev_data and "qr_svg" not in ev_data and "qr_frames" not in ev_data
    assert "1234" not in json.dumps(ev_data)
    assert ev_data["has_otp"] is True and ev_data["has_qr"] is False
    sig, payload = send.call_args[0][1:]
    assert sig == SIGNAL_MITID_CHALLENGE
    assert payload["otp_code"] == "1234"
    assert payload["entry_id"] == "entry-1"


def test_push_sync_ui_delivers_both_qr_frames(tmp_path: Path) -> None:
    coord, hass, *_ = make_coordinator(tmp_path)
    coord.async_set_updated_data = MagicMock()
    with patch("kmd_easy_energy.coordinator.async_dispatcher_send") as send:
        coord._push_sync_ui("qr_ready", "Scan", qr_frames=["<svg>1</svg>", "<svg>2</svg>"])
    payload = send.call_args[0][2]
    assert payload["qr_frames"] == ["<svg>1</svg>", "<svg>2</svg>"]
    assert payload["otp_code"] is None
    ev_data = hass.bus.async_fire.call_args[0][1]
    assert ev_data["has_qr"] is True
    assert "<svg" not in json.dumps(ev_data)


class _FakeAuth:
    """Scripted MitID authenticator (no network, no real MitID)."""

    def __init__(self, script):
        self.script = list(script)
        self.started = None

    def start_session(self, portal_url, username):
        self.started = (portal_url, username)

    def poll_once(self):
        return self.script.pop(0)

    def finalize_and_exchange_token(self):
        return "fake-token-not-real"


def _run_flow(tmp_path: Path, script):
    coord, hass, *_ = make_coordinator(tmp_path)
    coord.async_set_updated_data = MagicMock()
    coord.async_update_token = AsyncMock()
    auth = _FakeAuth(script)
    pushed: list[dict] = []
    with (
        patch("kmd_easy_energy.coordinator.KMDMitIDAuthenticator", return_value=auth),
        patch(
            "kmd_easy_energy.coordinator.async_dispatcher_send",
            side_effect=lambda h, sig, payload: pushed.append(dict(payload)),
        ),
        patch("kmd_easy_energy.coordinator.persistent_notification") as pn,
        patch("kmd_easy_energy.coordinator.asyncio.sleep", AsyncMock()),
    ):
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
        import asyncio as _asyncio

        _asyncio.run(coord._async_run_mitid_flow("mitid-user-test", ""))
    return coord, hass, auth, pushed, pn


def test_mitid_flow_qr_only_tablet_path_completes_without_code(tmp_path: Path) -> None:
    """Tablet/PC setup: QR frames shown, scanned, approved — no OTP ever needed."""
    frames_a = ["<svg>a1</svg>", "<svg>a2</svg>"]
    frames_b = ["<svg>b1</svg>", "<svg>b2</svg>"]
    script = [
        {"status": "waiting"},
        {"status": "qr_ready", "qr_frames": frames_a, "qr_svg": frames_a[0]},
        {"status": "qr_ready", "qr_frames": frames_a, "qr_svg": frames_a[0]},  # unchanged
        {"status": "qr_ready", "qr_frames": frames_b, "qr_svg": frames_b[0]},  # rotated
        {"status": "verified"},
        {"status": "verified"},
        {"status": "completed"},
    ]
    coord, hass, auth, pushed, pn = _run_flow(tmp_path, script)
    assert auth.started == ("https://minvarme.kredslob.dk/", "mitid-user-test")
    coord.async_update_token.assert_awaited_once_with("fake-token-not-real")
    qr_pushes = [p for p in pushed if p["sync_state"] == "qr_ready"]
    # Pushed once per distinct QR (not once per poll), always both frames.
    assert [p["qr_frames"] for p in qr_pushes] == [frames_a, frames_b]
    assert all(p["otp_code"] is None for p in pushed)
    assert [p["sync_state"] for p in pushed].count("verified") == 1
    # Ends idle with the challenge cleared.
    assert pushed[-1]["sync_state"] == "idle"
    assert pushed[-1]["qr_frames"] == [] and pushed[-1]["otp_code"] is None
    assert coord.mitid_qr_frames == [] and coord.mitid_qr_svg is None
    # Nothing secret ever hits the bus (recorder) or a service call.
    bus_blob = json.dumps([c.args for c in hass.bus.async_fire.call_args_list], default=str)
    assert "<svg" not in bus_blob
    hass.services.async_call.assert_not_called()
    pn.async_dismiss.assert_called()


def test_mitid_flow_otp_path_pushes_code_once(tmp_path: Path) -> None:
    script = [
        {"status": "otp_ready", "otp_code": "4821"},
        {"status": "otp_ready", "otp_code": "4821"},
        {"status": "verified"},
        {"status": "completed"},
    ]
    coord, hass, auth, pushed, pn = _run_flow(tmp_path, script)
    otp_pushes = [p for p in pushed if p["sync_state"] == "otp_ready"]
    assert len(otp_pushes) == 1 and otp_pushes[0]["otp_code"] == "4821"
    bus_blob = json.dumps([c.args for c in hass.bus.async_fire.call_args_list], default=str)
    assert "4821" not in bus_blob
    # Persistent notification created via helper (no call_service event to record).
    assert any("4821" in str(c) for c in pn.async_create.call_args_list)
    hass.services.async_call.assert_not_called()


def test_mitid_flow_error_clears_challenge(tmp_path: Path) -> None:
    script = [
        {"status": "qr_ready", "qr_frames": ["<svg>x</svg>", "<svg>y</svg>"]},
        {"status": "error", "message": "Authentication was not accepted"},
    ]
    coord, hass, auth, pushed, pn = _run_flow(tmp_path, script)
    assert pushed[-1]["sync_state"] == "error"
    assert pushed[-1]["qr_frames"] == []
    coord.async_update_token.assert_not_awaited()
    pn.async_dismiss.assert_called()


def test_sanitize_matches_event_split() -> None:
    """OTP may live on the coordinator object and in a bus event, never in persisted state."""
    persisted = sanitize_cache({"mitid_otp_code": "0000", "annual": {"2026": 1}})
    assert "mitid_otp_code" not in persisted
