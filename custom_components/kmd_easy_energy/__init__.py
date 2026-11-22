"""KMD Easy Energy integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BONUS_TEMP,
    CONF_LOCATION_NAME,
    CONF_MITID_USERNAME,
    CONF_NOTIFY_SERVICE,
    CONF_PENALTY_TEMP,
    CONF_PORTAL_URL,
    CONF_UTILITY,
    CONF_UTILITY_ID,
    CONF_UTILITY_LATITUDE,
    CONF_UTILITY_LONGITUDE,
    CONF_UTILITY_STATUS,
    DOMAIN,
    SIGNAL_MITID_CHALLENGE,
    WS_TYPE_MITID_SUBSCRIBE,
)
from .coordinator import KMDEasyEnergyCoordinator
from .frontend_card import async_ensure_lovelace_card_resource, install_frontend_card
from .outdoor_temp import migrate_location
from .util import store_for, unique_id_for, delete_legacy_www_cache, legacy_www_cache_paths

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "button", "binary_sensor"]
DEFAULT_PORTAL_URL = "https://minvarme.kredslob.dk/"


def _find_utility_meta(utility_id: str | None, utility_name: str | None = None) -> dict[str, Any] | None:
    """Look up utility metadata in bundled utilities.json (run in executor)."""
    path = Path(__file__).parent / "utilities.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("utilities") or data.get("verified_or_high_confidence") or []
        target_id = (utility_id or "").strip().lower()
        target_name = (utility_name or "").strip().lower()
        for item in items:
            if not isinstance(item, dict):
                continue
            if (target_id and str(item.get("id", "")).strip().lower() == target_id) or (
                target_name and str(item.get("name", "")).strip().lower() == target_name
            ):
                return item
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not read utilities.json: %s", err)
    return None


def _resolve_portal_url(utility_name: str | None, utility_id: str | None = None) -> str:
    """Resolve portal_url for a utility from bundled utilities.json (run in executor)."""
    item = _find_utility_meta(utility_id, utility_name)
    if item:
        raw_url = str(item.get("portal_url") or "").split("(")[0].strip()
        if raw_url.startswith("http"):
            return raw_url
    return DEFAULT_PORTAL_URL


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services once."""

    def _pick_entry(entry_id: str | None) -> ConfigEntry | None:
        entries = hass.config_entries.async_entries(DOMAIN)
        return (
            next((e for e in entries if e.entry_id == entry_id), None)
            if entry_id
            else (entries[0] if entries else None)
        )

    async def handle_update_token(call: ServiceCall) -> None:
        entry = _pick_entry(call.data.get("entry_id"))
        if not entry:
            _LOGGER.error("No config entry found for kmd_easy_energy.update_token")
            return
        coord: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
        # One-shot sync with a manually obtained token; the token is not stored.
        try:
            await coord.async_sync_with_token(
                call.data["access_token"],
                call.data.get("customer_id"),
                call.data.get("customer_number"),
            )
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Synkronisering fejlede: {str(err)[:160]}") from err

    async def handle_sync(call: ServiceCall) -> None:
        """Backend-independent sync (MitID for KMD, login for E|Forsyning)."""
        entry = _pick_entry(call.data.get("entry_id"))
        if not entry:
            _LOGGER.error("No config entry found for kmd_easy_energy.sync")
            return
        coord: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coord.async_start_sync()

    async def handle_refresh(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        domain_data: dict[str, KMDEasyEnergyCoordinator] = hass.data.get(DOMAIN, {})
        if entry_id:
            coord = domain_data.get(entry_id)
            if coord:
                await coord.async_request_refresh()
            return
        for coord in domain_data.values():
            await coord.async_request_refresh()

    async def handle_configure_utility(call: ServiceCall) -> None:
        entry = _pick_entry(call.data.get("entry_id"))
        if not entry:
            _LOGGER.error("No config entry found for kmd_easy_energy.configure_utility")
            return
        coord: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
        utility_id = str(call.data.get("utility_id") or entry.data.get(CONF_UTILITY_ID, "kredslob")).strip()
        meta = await hass.async_add_executor_job(_find_utility_meta, utility_id)

        updates: dict[str, Any] = {CONF_UTILITY_ID: utility_id}
        if meta:
            updates[CONF_UTILITY] = meta.get("name", utility_id)
            updates[CONF_UTILITY_STATUS] = meta.get("status", "pending_test")
            updates[CONF_PORTAL_URL] = meta.get("portal_url", DEFAULT_PORTAL_URL)
            if meta.get("city"):
                updates[CONF_LOCATION_NAME] = meta["city"]
            if meta.get("latitude") is not None:
                # Utility metadata / last-resort Open-Meteo location — not a
                # user location override (that only lives in options).
                updates[CONF_UTILITY_LATITUDE] = meta["latitude"]
                updates[CONF_UTILITY_LONGITUDE] = meta["longitude"]

        if call.data.get("portal_url"):
            updates[CONF_PORTAL_URL] = str(call.data["portal_url"]).strip()
        if call.data.get("location_name") is not None:
            updates[CONF_LOCATION_NAME] = str(call.data["location_name"]).strip()
        if call.data.get("bonus_temp") is not None:
            updates[CONF_BONUS_TEMP] = float(call.data["bonus_temp"])
        if call.data.get("penalty_temp") is not None:
            updates[CONF_PENALTY_TEMP] = float(call.data["penalty_temp"])
        mitid_user = call.data.get("mitid_username")
        if mitid_user:
            updates[CONF_MITID_USERNAME] = str(mitid_user).strip()
        notify_svc = call.data.get("notify_service")
        if notify_svc is not None:
            updates[CONF_NOTIFY_SERVICE] = str(notify_svc).strip()

        complete_setup = bool(call.data.get("complete_setup", False))
        await coord.async_set_setup_state(complete_setup, meta_updates=updates)

        if call.data.get("start_sync", False):
            await coord.async_start_mitid_sync(
                mitid_username=str(mitid_user).strip() if mitid_user else None,
                notify_service=str(notify_svc).strip() if notify_svc is not None else None,
            )

    async def handle_reset_setup(call: ServiceCall) -> None:
        entry = _pick_entry(call.data.get("entry_id"))
        if not entry:
            _LOGGER.error("No config entry found for kmd_easy_energy.reset_setup")
            return
        coord: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coord.async_set_setup_state(False)

    async def handle_start_mitid_sync(call: ServiceCall) -> None:
        entry = _pick_entry(call.data.get("entry_id"))
        if not entry and call.data.get("utility_id"):
            want = str(call.data["utility_id"]).strip().lower()
            entry = next(
                (
                    e
                    for e in hass.config_entries.async_entries(DOMAIN)
                    if str(e.data.get(CONF_UTILITY_ID, "")).strip().lower() == want
                ),
                None,
            )
        if not entry:
            _LOGGER.error("No config entry found for kmd_easy_energy.start_mitid_sync")
            return
        coord: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coord.async_start_mitid_sync(
            mitid_username=(
                str(call.data["mitid_username"]).strip()
                if call.data.get("mitid_username")
                else None
            ),
            notify_service=(
                str(call.data["notify_service"]).strip()
                if call.data.get("notify_service") is not None
                else None
            ),
        )

    for svc_name, handler in (
        ("update_token", handle_update_token),
        ("refresh", handle_refresh),
        ("configure_utility", handle_configure_utility),
        ("reset_setup", handle_reset_setup),
        ("start_mitid_sync", handle_start_mitid_sync),
        ("sync", handle_sync),
    ):
        if not hass.services.has_service(DOMAIN, svc_name):
            hass.services.async_register(DOMAIN, svc_name, handler)


_WS_REGISTERED = f"{DOMAIN}_ws_registered"
# Sync states where a live challenge (or its status) is worth replaying to a
# card that subscribes mid-flow, e.g. a wall tablet that opens the dashboard
# after the sync was started from another device.
_ACTIVE_SYNC_STATES = {"starting", "waiting_app", "otp_ready", "qr_ready", "verified", "fetching_data"}


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_MITID_SUBSCRIBE,
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_subscribe_mitid_challenge(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream the live MitID challenge (OTP / QR frames) to the Lovelace card.

    Unlike ``subscribe_events`` this also works for non-admin users (typical
    wall tablet), and nothing passes the event bus, so the OTP / QR never
    reach the recorder.
    """
    want = msg.get("entry_id")

    @callback
    def forward(payload: dict[str, Any]) -> None:
        if want and payload.get("entry_id") != want:
            return
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_MITID_CHALLENGE, forward
    )
    connection.send_result(msg["id"])

    for coord in list(hass.data.get(DOMAIN, {}).values()):
        if getattr(coord, "sync_state", "idle") in _ACTIVE_SYNC_STATES:
            forward(coord.mitid_challenge_payload())


@callback
def _async_register_websocket(hass: HomeAssistant) -> None:
    if hass.data.get(_WS_REGISTERED):
        return
    websocket_api.async_register_command(hass, ws_subscribe_mitid_challenge)
    hass.data[_WS_REGISTERED] = True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply option changes (reminder on/off, prices) from cache — no KMD call."""
    coord: KMDEasyEnergyCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coord is None:
        return
    if not coord.uses_mitid and coord.auto_sync_signature != coord.started_auto_sync_signature:
        # Auto-sync on/off or hour changed: re-create the timer via reload.
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    coord._reminder_sig = None
    if coord.weather_signature != (coord.data or {}).get("weather_source_sig", coord.weather_signature):
        # Outdoor temperature source changed (sensor / location): recompute the
        # temperatures from the new source now instead of at the next sync.
        try:
            await coord.async_refresh_weather()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not refresh outdoor temperatures: %s", err)
    await coord.async_request_refresh()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries (minor versions only; nothing user-visible breaks).

    1.1 -> 1.2: drop the stored KMD access token (session-based sync).
    1.2 -> 1.3: utility coordinates in entry.data become utility metadata
    (``utility_latitude``/``utility_longitude``); the outdoor temperature
    location now follows the HA home location unless options hold an explicit
    override (see ``outdoor_temp.migrate_location``).
    """
    if entry.version > 1:
        return False
    if entry.version != 1 or entry.minor_version >= 3:
        return True
    data = dict(entry.data)
    options = dict(entry.options)
    if entry.minor_version < 2:
        data = {k: v for k, v in data.items() if k != CONF_ACCESS_TOKEN}
        options = {k: v for k, v in options.items() if k != CONF_ACCESS_TOKEN}
        _LOGGER.info("Removed stored KMD access token from %s (session-based sync)", entry.title)
    data, options, dropped = migrate_location(data, options, hass.config)
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=1, minor_version=3
    )
    _LOGGER.info(
        "Migrated %s to 1.3: outdoor temperature location %s",
        entry.title,
        "follows the HA home location (implicit coordinates removed)"
        if dropped
        else (
            "keeps the explicit override from options"
            if "latitude" in options
            else "follows the HA home location"
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KMD Easy Energy from a config entry."""
    await hass.async_add_executor_job(
        install_frontend_card, Path(hass.config.path("www/js"))
    )
    await async_ensure_lovelace_card_resource(hass)
    portal_url = (
        entry.options.get(CONF_PORTAL_URL)
        or entry.data.get(CONF_PORTAL_URL)
        or await hass.async_add_executor_job(
            _resolve_portal_url,
            entry.data.get(CONF_UTILITY),
            entry.data.get(CONF_UTILITY_ID),
        )
    )
    if not entry.unique_id:
        hass.config_entries.async_update_entry(
            entry,
            unique_id=unique_id_for(
                entry.data.get(CONF_UTILITY_ID),
                entry.data.get(CONF_PORTAL_URL) or portal_url,
            ),
        )

    coordinator = KMDEasyEnergyCoordinator(hass, entry, portal_url=portal_url)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await coordinator.async_initialize_cache()
    # Session-based: the first refresh only reads the private cache, so an HA
    # restart restores the last synced values without contacting KMD.
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(coordinator.async_start_reminder_timer())
    # E|Forsyning only (no MitID needed): optional daily automatic sync.
    entry.async_on_unload(coordinator.async_start_auto_sync())
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    await _async_setup_services(hass)
    _async_register_websocket(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            for svc_name in (
                "update_token",
                "refresh",
                "configure_utility",
                "reset_setup",
                "start_mitid_sync",
                "sync",
            ):
                hass.services.async_remove(DOMAIN, svc_name)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean private storage and leftover public www/ cache files."""
    store = store_for(hass, entry.entry_id)
    await store.async_remove()
    paths = legacy_www_cache_paths(hass, entry.data.get(CONF_UTILITY_ID))
    await hass.async_add_executor_job(delete_legacy_www_cache, paths)
