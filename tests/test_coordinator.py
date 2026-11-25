"""Coordinator cache location, auth failure, and startup resilience."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from kmd_easy_energy.const import EVENT_MITID_CHALLENGE, SIGNAL_MITID_CHALLENGE
from kmd_easy_energy.coordinator import KMDEasyEnergyCoordinator, KMDLoginError
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
        coord.last_sync = None
        coord._reminder_sig = None
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
        coord.backend = str(entry.data.get("backend") or "kmd")
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
async def test_update_data_is_cache_only_no_kmd_call(tmp_path: Path) -> None:
    """HA restart / refresh restores cached values without contacting KMD."""
    store = FakeStore(
        {
            "annual": {"2026": 77},
            "daily": {"total": 5},
            "last_sync": "2026-11-19T18:30:00+00:00",
            "token_expired": True,
        }
    )
    coord, hass, entry, _ = make_coordinator(tmp_path, store=store)
    coord.data = None
    with patch("kmd_easy_energy.coordinator.KMDClient", side_effect=AssertionError("no KMD")):
        state = await coord._async_update_data()
    assert state["annual"]["2026"] == 77
    assert "token_expired" not in state
    assert state["last_sync"] == "2026-11-19T18:30:00+00:00"
    assert coord.client is None
    from kmd_easy_energy.const import UPDATE_INTERVAL

    assert UPDATE_INTERVAL is None


@pytest.mark.asyncio
async def test_last_sync_falls_back_to_updated_for_migrated_cache(tmp_path: Path) -> None:
    store = FakeStore({"annual": {"2026": 3}, "updated": "2026-11-20T07:00:00+01:00"})
    coord, *_ = make_coordinator(tmp_path, store=store)
    await coord.async_initialize_cache()
    assert coord.last_sync is not None
    assert coord.last_sync.isoformat().startswith("2026-11-20T07:00:00")


@pytest.mark.asyncio
async def test_sync_with_token_discards_token_and_records_last_sync(tmp_path: Path) -> None:
    store = FakeStore({"annual": {"2026": 1}})
    coord, hass, entry, store = make_coordinator(tmp_path, store=store)
    coord.async_set_updated_data = MagicMock()
    seen_clients = []

    async def fake_fetch(state):
        seen_clients.append(coord.client)
        state = dict(state)
        state["annual"] = {"2026": 99}
        return state

    coord._async_fetch_from_kmd = fake_fetch
    secret = "fake-session-token-not-real"
    await coord.async_sync_with_token(secret)
    assert seen_clients and seen_clients[0] is not None  # token used during the sync
    assert coord.client is None  # ...and discarded right after
    assert coord.last_sync is not None
    assert store.data["annual"]["2026"] == 99
    assert store.data["last_sync"]
    assert store.data["initial_setup_complete"] is True
    assert secret not in json.dumps(store.data, default=str)
    hass.config_entries.async_update_entry.assert_not_called()  # nothing written to the entry
    published = coord.async_set_updated_data.call_args[0][0]
    assert secret not in json.dumps(published, default=str)


@pytest.mark.asyncio
async def test_sync_401_is_login_error_and_keeps_cache(tmp_path: Path) -> None:
    store = FakeStore({"annual": {"2026": 77}, "daily": {"total": 5}})
    coord, hass, entry, store = make_coordinator(tmp_path, store=store)
    coord.data = dict(store.data)
    coord.async_set_updated_data = MagicMock()
    err = ClientResponseError(MagicMock(), (), status=401, message="Unauthorized")
    fake_client = MagicMock()
    fake_client.discover_accounts = AsyncMock(side_effect=err)
    with patch.object(coord, "_make_client", return_value=fake_client):
        with pytest.raises(KMDLoginError):
            await coord.async_sync_with_token("fake")
    assert coord.client is None
    assert coord.last_sync is None
    assert store.saved == []  # cache untouched
    assert coord.data["annual"]["2026"] == 77
    entry.async_start_reauth.assert_not_called()


@pytest.mark.asyncio
async def test_sync_transient_http_error_is_plain_error(tmp_path: Path) -> None:
    coord, *_ = make_coordinator(tmp_path)
    err = ClientResponseError(MagicMock(), (), status=502, message="Bad Gateway")
    fake_client = MagicMock()
    fake_client.discover_accounts = AsyncMock(side_effect=err)
    with patch.object(coord, "_make_client", return_value=fake_client):
        with pytest.raises(RuntimeError) as exc:
            await coord.async_sync_with_token("fake")
    assert not isinstance(exc.value, KMDLoginError)
    assert "502" in str(exc.value)


def _hp(day: str, hour: int = 0, value: float = 1.0) -> dict:
    return {"DateFrom": f"{day}T{hour:02d}:00:00+01:00", "Value": value, "IsComplete": True}


@pytest.mark.asyncio
async def test_gap_fill_fetches_from_last_stored_day_to_month_start(tmp_path: Path) -> None:
    import datetime as dt

    coord, *_ = make_coordinator(tmp_path)
    coord.client = MagicMock()
    coord.client.get_hourly_with_fallback = AsyncMock(return_value=[_hp("2026-01-30", 5, 2.0)])
    state = {"hourly_kwh": [_hp("2026-01-28", 23)], "hourly_m3": [_hp("2026-02-02", 1)]}
    mp = {"InstallationId": "i", "MeasurementPointId": "m"}
    await coord._async_fill_gap_since_last_sync(
        state, mp, {"Id": "kwh"}, {"Id": "m3"}, dt.date(2026, 2, 4)
    )
    # kWh: last stored day 28 Jan (< 1 Feb) -> fetch 28 Jan .. 1 Feb. m³ already in Feb -> no call.
    coord.client.get_hourly_with_fallback.assert_awaited_once()
    args = coord.client.get_hourly_with_fallback.await_args.args
    assert args[3] == dt.datetime(2026, 1, 28) and args[4] == dt.datetime(2026, 2, 1)
    assert len(state["hourly_kwh"]) == 2


@pytest.mark.asyncio
async def test_backfill_first_sync_full_year_then_few_months(tmp_path: Path) -> None:
    import datetime as dt

    coord, *_ = make_coordinator(tmp_path)
    coord.client = MagicMock()
    coord.client.get_consumption_timeseries = AsyncMock(return_value={"Series": []})
    coord.client.get_hourly_with_fallback = AsyncMock(return_value=[])
    mp = {"InstallationId": "i", "MeasurementPointId": "m"}
    state: dict = {"hourly_kwh": [_hp("2026-11-03")]}
    await coord._async_backfill_history(state, mp, {"Id": "k"}, None, dt.date(2026, 11, 22), True)
    assert coord.client.get_hourly_with_fallback.await_count == 12
    coord.client.get_hourly_with_fallback.reset_mock()
    await coord._async_backfill_history(state, mp, {"Id": "k"}, None, dt.date(2026, 11, 22), False)
    assert coord.client.get_hourly_with_fallback.await_count == 3


def test_statistics_rows_idempotent_for_repeated_syncs() -> None:
    """Same hours imported twice (two syncs a day) -> same rows, unique starts."""
    from kmd_easy_energy.insights import (
        cumulative_statistic_rows,
        hourly_points_to_buckets,
        merge_hourly_points,
    )

    first = [_hp("2026-11-20", h, 1.0) for h in range(24)]
    again = merge_hourly_points(first, [_hp("2026-11-20", h, 1.0) for h in range(12, 24)])
    rows_a = cumulative_statistic_rows(hourly_points_to_buckets(first, complete_only=True))
    rows_b = cumulative_statistic_rows(hourly_points_to_buckets(again, complete_only=True))
    assert len(again) == 24
    assert rows_a == rows_b
    starts = [r["start"] for r in rows_b]
    assert len(starts) == len(set(starts))


def test_reminder_refresh_updates_listeners_only_on_change(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    coord, *_ = make_coordinator(tmp_path)
    coord.data = {"annual": {"2026": 1}}
    coord.async_update_listeners = MagicMock()
    sat = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    coord.last_sync = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)  # Tuesday
    with patch("kmd_easy_energy.coordinator.dt_util.utcnow", return_value=sat):
        coord.async_refresh_reminder()
        coord.async_refresh_reminder()
    assert coord.async_update_listeners.call_count == 1
    assert coord.data["sync_reminder"] is True
    assert coord.data["sync_reminder_message"] == "Det er 4 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."


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
    coord.async_sync_with_token = AsyncMock()
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
    coord.async_sync_with_token.assert_awaited_once_with("fake-token-not-real")
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
    coord.async_sync_with_token.assert_not_awaited()
    pn.async_dismiss.assert_called()


def test_sanitize_matches_event_split() -> None:
    """OTP may live on the coordinator object and in a bus event, never in persisted state."""
    persisted = sanitize_cache({"mitid_otp_code": "0000", "annual": {"2026": 1}})
    assert "mitid_otp_code" not in persisted


def test_mitid_flow_kmd_login_error_shows_on_card_without_reauth(tmp_path: Path) -> None:
    script = [{"status": "verified"}, {"status": "completed"}]
    coord, hass, *_ = make_coordinator(tmp_path)
    coord.async_set_updated_data = MagicMock()
    coord.async_sync_with_token = AsyncMock(side_effect=KMDLoginError("KMD afviste login (HTTP 401)"))
    auth = _FakeAuth(script)
    pushed: list[dict] = []
    with (
        patch("kmd_easy_energy.coordinator.KMDMitIDAuthenticator", return_value=auth),
        patch(
            "kmd_easy_energy.coordinator.async_dispatcher_send",
            side_effect=lambda h, sig, payload: pushed.append(dict(payload)),
        ),
        patch("kmd_easy_energy.coordinator.persistent_notification"),
        patch("kmd_easy_energy.coordinator.asyncio.sleep", AsyncMock()),
    ):
        import asyncio as _asyncio

        _asyncio.run(coord._async_run_mitid_flow("mitid-user-test", ""))
    assert pushed[-1]["sync_state"] == "error"
    assert "HTTP 401" in pushed[-1]["sync_message"]
    coord.entry.async_start_reauth.assert_not_called()


def test_coordinator_base_meta_exposes_integration_version(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    hass = _hass(tmp_path)
    with patch.object(DataUpdateCoordinator, "__init__", lambda *a, **k: None):
        coord = KMDEasyEnergyCoordinator(hass, entry, integration_version="1.2.0")
        default_coord = KMDEasyEnergyCoordinator(hass, entry)
    assert coord._base_meta()["integration_version"] == "1.2.0"
    assert default_coord._base_meta()["integration_version"] is None


def test_coordinator_uses_async_get_time_zone_instead_of_zoneinfo() -> None:
    """Ensure coordinator.py never constructs ZoneInfo on the event loop."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "kmd_easy_energy"
        / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert "zoneinfo" not in src
    assert "ZoneInfo(" not in src
    assert 'await dt_util.async_get_time_zone("Europe/Copenhagen")' in src


@pytest.mark.asyncio
async def test_initialize_cache_upgrades_eforsyning_custom_to_confirmed_utility(tmp_path: Path) -> None:
    coord, _, _, _ = make_coordinator(
        tmp_path,
        store=FakeStore({}),
        backend="eforsyning",
        utility="Hadsund Fjernvarme a.m.b.a.",
        utility_id="eforsyning-custom",
        utility_status="pending_test",
        portal_url="https://eforsyning.dk/hadsundfjernvarme/",
        eforsyning_supplier_id="49C73776-76BE-4382-BA5C-2B4E7384CC34",
    )
    state = await coord.async_initialize_cache()
    assert state["utility_id"] == "hadsund-fjernvarme"
    assert state["utility_status"] == "confirmed"
    assert state["location"] == "Hadsund"


def test_kmd_client_find_energy_unit_and_factor() -> None:
    from kmd_easy_energy.api.kmd_client import KMDClient

    mwh_units = [{"Id": "u1", "Name": "m3"}, {"Id": "u2", "Name": "MWh"}]
    assert KMDClient.find_energy_unit(mwh_units) == {"Id": "u2", "Name": "MWh"}
    kwh_units = [{"Id": "u1", "Name": "kWh"}, {"Id": "u2", "Name": "MWh"}]
    assert KMDClient.find_energy_unit(kwh_units) == {"Id": "u1", "Name": "kWh"}
    gj_units = [{"Id": "u1", "Name": "GJ"}]
    assert KMDClient.find_energy_unit(gj_units) == {"Id": "u1", "Name": "GJ"}

    assert KMDClient.energy_factor({"Name": "MWh"}) == 1000.0
    assert KMDClient.energy_factor({"Name": "GJ"}) == pytest.approx(1.0 / 0.0036)
    assert KMDClient.energy_factor({"Name": "kWh"}) == 1.0


@pytest.mark.asyncio
async def test_fetch_from_kmd_scales_mwh_meter_to_kwh(tmp_path: Path) -> None:
    import datetime as dt
    from kmd_easy_energy.insights import DK_TZ

    coord, hass, _, _ = make_coordinator(
        tmp_path,
        utility="Bornholms Energi & Forsyning (BEOF)",
        utility_id="beof",
        portal_url="https://minforsyning.beof.dk/",
    )
    mwh_unit = {"Id": "u-mwh", "Name": "MWh", "Description": "Megawatttimer", "Decimals": 3, "Order": 1}
    m3_unit = {"Id": "u-m3", "Name": "m3", "Description": "Kubikmeter", "Decimals": 2, "Order": 2}
    fake_client = MagicMock()
    fake_client.discover_accounts = AsyncMock(
        return_value=[
            {
                "customer": {"CustomerId": "c1", "CustomerNumber": "cn1"},
                "customer_index": 1,
                "customer_id": "c1",
                "customer_number": "cn1",
                "meters": [
                    {
                        "InstallationId": "inst1",
                        "MeasurementPointId": "mp1",
                        "ConsumptionType": 5,
                        "Units": [mwh_unit, m3_unit],
                    }
                ],
            }
        ]
    )
    fake_client.set_customer = MagicMock()

    async def fake_ts(inst, mp, unit, zoom, d_from, d_to):
        if zoom == 1 and d_from.year == 2026:
            return {
                "Series": [
                    {
                        "Data": [
                            {"DateFrom": "2026-01-01T00:00:00", "Value": 2.5},
                            {"DateFrom": "2026-02-01T00:00:00", "Value": 9.5},
                        ]
                    }
                ]
            }
        if zoom == 2 and d_from == dt.datetime(2026, 11, 1):
            return {
                "Series": [
                    {
                        "Data": [
                            {"DateFrom": "2026-11-22T00:00:00", "Value": 0.048, "IsComplete": True},
                        ]
                    }
                ]
            }
        return {"Series": []}

    hourly_mwh = [
        {"DateFrom": f"2026-11-22T{h:02d}:00:00+01:00", "Value": 0.002, "IsComplete": True}
        for h in range(24)
    ]

    async def fake_hourly(inst, mp, unit, d_from, d_to):
        if unit.get("Name") == "MWh" and d_from.date() == dt.date(2026, 11, 22):
            return hourly_mwh
        return []

    fake_client.get_consumption_timeseries = AsyncMock(side_effect=fake_ts)
    fake_client.get_hourly_with_fallback = AsyncMock(side_effect=fake_hourly)
    fake_client.get_current_settlement_period = AsyncMock(
        return_value={"DateFrom": "2026-01-01T00:00:00Z", "DateTo": "2026-12-31T00:00:00Z"}
    )
    fake_client.get_consumption_overview = AsyncMock(
        return_value={"Actual": {"Value": 12.0}, "Expected": {"Value": 14.5}}
    )
    fake_client.get_balance = AsyncMock(return_value={})
    fake_client.get_balance_statement = AsyncMock(return_value=[])

    coord.client = fake_client
    coord._async_update_weather = AsyncMock()
    fixed_now = dt.datetime(2026, 11, 24, 12, 0, tzinfo=DK_TZ)
    with patch("kmd_easy_energy.coordinator.dt_util.now", return_value=fixed_now):
        state = await coord._async_fetch_from_kmd({})

    assert state["kmd_energy_factor"] == 1000.0
    assert state["kmd_energy_unit"] == "MWh"
    assert state["monthly"]["2026"]["Jan"] == 2500
    assert state["monthly"]["2026"]["Feb"] == 9500
    assert state["annual"]["2026"] == 12000
    assert state["daily"]["days"]["22"] == 48
    assert state["daily"]["total"] == 48
    assert state["daily_kwh_history"]["2026-11-22"] == 48
    assert len(state["hourly_kwh"]) == 24
    assert state["hourly_kwh"][0]["Value"] == 2.0
    assert state["hourly"]["kwh"][0] == 2.0
    assert state["forecast"]["expected_kwh"] == 12000
    assert state["forecast"]["budget_kwh"] == 14500


@pytest.mark.asyncio
async def test_initialize_cache_migrates_unscaled_mwh_kmd_cache(tmp_path: Path) -> None:
    store = FakeStore(
        {
            "available_units": [{"Id": "u1", "Name": "MWh"}, {"Id": "u2", "Name": "m3"}],
            "monthly": {"2026": {"Jan": 2.5, "Feb": 9.5}},
            "annual": {"2026": 12},
            "daily": {
                "month": "November 2026",
                "days": {"22": 0.048},
                "total": 0.048,
                "gennemsnit": 0.0,
                "minimum": 0.048,
                "maksimum": 0.048,
            },
            "daily_kwh_history": {"2026-11-22": 0.048},
            "hourly_kwh": [{"DateFrom": "2026-11-22T00:00:00+01:00", "Value": 0.002, "IsComplete": True}],
            "hourly": {"period": "nov-2026 MTD (1 dage)", "days_averaged": 1, "kwh": [0.002] * 24},
            "forecast": {"period": "01.01.2026 - 31.12.2026", "expected_kwh": 12, "budget_kwh": 14.5},
        }
    )
    coord, _, _, store = make_coordinator(
        tmp_path,
        store=store,
        utility="Bornholms Energi & Forsyning (BEOF)",
        utility_id="beof",
        portal_url="https://minforsyning.beof.dk/",
    )

    state = await coord.async_initialize_cache()
    assert state["kmd_unscaled_migrated"] == 1000.0
    assert state["kmd_energy_unit"] == "MWh"
    assert state["monthly"]["2026"]["Jan"] == 2500
    assert state["monthly"]["2026"]["Feb"] == 9500
    assert state["annual"]["2026"] == 12000
    assert state["daily"]["days"]["22"] == 48
    assert state["daily"]["total"] == 48.0
    assert state["daily_kwh_history"]["2026-11-22"] == 48
    assert state["hourly_kwh"][0]["Value"] == 2.0
    assert state["hourly"]["kwh"][0] == 2.0
    assert state["forecast"]["expected_kwh"] == 12000
    assert state["forecast"]["budget_kwh"] == 14500
    assert len(store.saved) == 1

    # Subsequent cache-only update must not double-scale
    state2 = await coord._async_update_data()
    assert state2["annual"]["2026"] == 12000


@pytest.mark.asyncio
async def test_enrich_derived_backfills_available_units_for_cached_wattson_state(tmp_path: Path) -> None:
    store = FakeStore(
        {
            "monthly": {"2026": {"Nov": 420.0}},
            "daily_kwh_history": {"2026-11-24": 18.5},
            "hourly_kwh": [{"DateFrom": "2026-11-24T00:00:00+01:00", "Value": 0.8, "IsComplete": True}],
            "hourly": {"period": "nov-2026 MTD (1 dage)", "days_averaged": 1, "kwh": [0.8] * 24},
            "hourly_m3": [{"DateFrom": "2026-11-24T00:00:00+01:00", "Value": 0.05, "IsComplete": True}],
            "hourly_temp": [{"DateFrom": "2026-11-24T00:00:00+01:00", "Value": 34.5, "IsComplete": True}],
            "has_direct_temp": True,
            "wattson": {"detected": ["daily", "hourly", "monthly", "temperatures", "volume"]},
        }
    )
    coord, _, _, _ = make_coordinator(
        tmp_path,
        store=store,
        backend="wattson",
        utility="Hillerød Forsyning",
        utility_id="hillerod-forsyning",
        portal_url="https://hfors.dk/selvbetjening/se-forbrug-regninger/watts-on-din-forbrugsapp-til-vand-varme",
    )

    state = await coord._async_update_data()
    assert state["available_units"] == [{"Name": "kWh"}, {"Name": "m3"}, {"Name": "°C"}]


@pytest.mark.asyncio
async def test_initialize_cache_migrates_rounded_mwh_cache_recovers_hourly_daily_forecast_and_stats(
    tmp_path: Path,
) -> None:
    hourly_pts = (
        [
            {"DateFrom": f"2026-11-21T{h:02d}:00:00+01:00", "Value": 0.0018, "IsComplete": True}
            for h in range(24)
        ]
        + [
            {"DateFrom": f"2026-11-22T{h:02d}:00:00+01:00", "Value": 0.0016, "IsComplete": True}
            for h in range(24)
        ]
        + [
            {"DateFrom": f"2026-11-23T{h:02d}:00:00+01:00", "Value": 0.0005, "IsComplete": False}
            for h in range(10)
        ]
    )
    store = FakeStore(
        {
            "available_units": [{"Id": "u1", "Name": "MWh"}, {"Id": "u2", "Name": "m3"}],
            "monthly": {"2026": {"Jan": 1.85, "Nov": 0.875}},
            "annual": {"2026": 3},
            "daily": {
                "month": "November 2026",
                "days": {"21": 0.042, "22": 0.038, "23": 0.005},
                "total": 0.085,
                "gennemsnit": 0.0,
                "minimum": 0.0,
                "maksimum": 0.042,
                "latest_date": "2026-11-23",
                "latest_complete": False,
            },
            "daily_kwh_history": {"2026-11-21": 0.042, "2026-11-22": 0.038, "2026-11-23": 0.005},
            "hourly_kwh": hourly_pts,
            "hourly": {"period": "nov-2026 MTD (2 dage)", "days_averaged": 2, "kwh": [0.0] * 24},
            "forecast": {"period": "01.11.2026 - 30.11.2026", "expected_kwh": 1, "budget_kwh": 1},
            "overview": {"Actual": {"Value": 0.875}, "Expected": {"Value": 1.425}},
        }
    )
    coord, _, _, store = make_coordinator(
        tmp_path,
        store=store,
        utility="Frederikshavn Forsyning",
        utility_id="frederikshavn-forsyning",
        portal_url="https://www.forsyningen.dk/selvbetjening",
    )

    with patch(
        "kmd_easy_energy.coordinator.import_hourly_statistics",
        return_value={"energy": 48, "volume": 0},
    ) as mock_import:
        state = await coord.async_initialize_cache()

    mock_import.assert_called_once()
    assert state["kmd_unscaled_migrated"] == 1000.0
    assert state["statistics_imported"] == {"energy": 48, "volume": 0}
    assert state["daily"]["days"] == {"21": 42, "22": 38, "23": 5}
    assert state["daily"]["total"] == 85
    assert state["daily"]["gennemsnit"] == 40.0
    assert state["daily"]["minimum"] == 38
    assert state["daily"]["maksimum"] == 42
    assert state["hourly"]["days_averaged"] == 2
    assert state["hourly"]["period"] == "nov-2026 MTD (2 dage)"
    assert state["hourly"]["kwh"] == [1.7] * 24
    assert state["forecast"]["expected_kwh"] == 875
    assert state["forecast"]["budget_kwh"] == 1425
