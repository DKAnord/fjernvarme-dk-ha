"""Config flow and options flow for KMD Easy Energy."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api.kmd_client import KMDClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BONUS_TEMP,
    CONF_CUSTOMER_ID,
    CONF_CUSTOMER_NUMBER,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_LOCATION_NAME,
    CONF_MITID_USERNAME,
    CONF_NOTIFY_SERVICE,
    CONF_PENALTY_TEMP,
    CONF_PORTAL_URL,
    CONF_UTILITY,
    CONF_UTILITY_ID,
    CONF_UTILITY_STATUS,
    DOMAIN,
)
from .util import unique_id_for

_LOGGER = logging.getLogger(__name__)

CUSTOM_UTILITY: dict[str, Any] = {
    "id": "custom",
    "name": "Custom KMD Easy Energy Utility",
    "city": "",
    "portal_url": "https://",
    "status": "pending_test",
    "tier": "custom",
    "notes": "Enter your utility's KMD Easy Energy self-service login URL.",
}


def _load_utilities() -> list[dict[str, Any]]:
    """Load utilities from bundled utilities.json (run in executor)."""
    path = Path(__file__).parent / "utilities.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("utilities") or data.get("verified_or_high_confidence") or []
        return [u for u in items if isinstance(u, dict) and u.get("name")]
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not load utilities.json: %s", err)
        return [
            {
                "id": "kredslob",
                "name": "Kredsløb",
                "city": "Aarhus",
                "portal_url": "https://minvarme.kredslob.dk/",
                "status": "confirmed",
                "tier": "confirmed",
                "notes": "Confirmed working.",
            }
        ]


def _format_utility_label(u: dict[str, Any]) -> str:
    tier = u.get("tier") or ("confirmed" if u.get("status") == "confirmed" else "verified_portal")
    city = f" ({u['city']})" if u.get("city") else ""
    if u.get("status") == "confirmed":
        return f"✅ {u['name']}{city} — Bekræftet / Confirmed"
    if tier == "candidate":
        return f"🔎 {u['name']}{city} — Kandidat (afventer test)"
    return f"🧪 {u['name']}{city} — Afventer 1. test / Pending test"


class KMDEasyEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a 2-step config flow for KMD Easy Energy."""

    VERSION = 1

    def __init__(self) -> None:
        self._selected_utility: dict[str, Any] = dict(CUSTOM_UTILITY)

    async def _async_set_entry_unique_id(
        self, utility_id: str | None, portal_url: str | None
    ) -> None:
        await self.async_set_unique_id(unique_id_for(utility_id, portal_url))
        self._abort_if_unique_id_configured()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> KMDEasyEnergyOptionsFlow:
        return KMDEasyEnergyOptionsFlow()

    async def _validate_token(
        self, token: str, customer_id: str, portal_url: str
    ) -> tuple[bool, KMDClient]:
        session = async_get_clientsession(self.hass)
        client = KMDClient(
            session,
            token,
            customer_id=customer_id or None,
            referer=portal_url or "https://minvarme.kredslob.dk/",
        )
        authenticated = False
        try:
            profile = await client.get_profile()
            if profile:
                authenticated = True
        except Exception as err:  # noqa: BLE001
            _LOGGER.info("KMD get_profile failed (%s); checking fallback", type(err).__name__)

        if not authenticated and customer_id:
            try:
                meters = await client.get_active_meters()
                if meters is not None:
                    authenticated = True
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("KMD get_active_meters fallback failed: %s", type(err).__name__)
        return authenticated, client

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: smart utility dropdown (or direct 1-step API submission)."""
        utilities = await self.hass.async_add_executor_job(_load_utilities)

        if user_input is not None:
            # Backwards-compatible 1-step automated flow when access_token is supplied directly
            if CONF_ACCESS_TOKEN in user_input:
                token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
                customer_id = (user_input.get(CONF_CUSTOMER_ID) or "").strip()
                utility_name = (user_input.get(CONF_UTILITY) or "Kredsløb").strip()
                matched = next(
                    (
                        u
                        for u in utilities
                        if u["id"] == user_input.get(CONF_UTILITY_ID)
                        or u["name"].lower() == utility_name.lower()
                    ),
                    utilities[0] if utilities else CUSTOM_UTILITY,
                )
                portal_url = (user_input.get(CONF_PORTAL_URL) or matched.get("portal_url") or "").strip()
                ok, client = await self._validate_token(token, customer_id, portal_url)
                if not ok:
                    return self.async_abort(reason="invalid_auth")
                entry_data: dict[str, Any] = {
                    CONF_UTILITY: matched.get("name") or utility_name,
                    CONF_UTILITY_ID: matched.get("id", "kredslob"),
                    CONF_UTILITY_STATUS: matched.get("status", "confirmed"),
                    CONF_PORTAL_URL: portal_url,
                    CONF_ACCESS_TOKEN: token,
                    CONF_LOCATION_NAME: matched.get("city", ""),
                }
                if matched.get("latitude") is not None:
                    entry_data[CONF_LATITUDE] = matched["latitude"]
                    entry_data[CONF_LONGITUDE] = matched["longitude"]
                if client._customer_id or customer_id:
                    entry_data[CONF_CUSTOMER_ID] = client._customer_id or customer_id
                if client._customer_number:
                    entry_data[CONF_CUSTOMER_NUMBER] = client._customer_number
                await self._async_set_entry_unique_id(
                    entry_data.get(CONF_UTILITY_ID), entry_data.get(CONF_PORTAL_URL)
                )
                return self.async_create_entry(
                    title=entry_data[CONF_UTILITY],
                    data=entry_data,
                )

            selected_id = user_input[CONF_UTILITY_ID]
            if selected_id == "custom":
                self._selected_utility = dict(CUSTOM_UTILITY)
            else:
                self._selected_utility = next(
                    (u for u in utilities if u.get("id") == selected_id),
                    dict(CUSTOM_UTILITY),
                )
            return await self.async_step_auth()

        options: list[SelectOptionDict] = [
            SelectOptionDict(value=u["id"], label=_format_utility_label(u))
            for u in utilities
        ]
        options.append(
            SelectOptionDict(
                value="custom",
                label="⚙️ Andet KMD Easy Energy værk (brugerdefineret URL)",
            )
        )
        default_id = utilities[0]["id"] if utilities else "kredslob"
        schema = vol.Schema(
            {
                vol.Required(CONF_UTILITY_ID, default=default_id): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: show selected utility login URL + status and accept optional token."""
        errors: dict[str, str] = {}
        u = self._selected_utility

        if user_input is not None:
            portal_url = (user_input.get(CONF_PORTAL_URL) or u.get("portal_url") or "").strip()
            token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            customer_id = (user_input.get(CONF_CUSTOMER_ID) or "").strip()
            location_name = (user_input.get(CONF_LOCATION_NAME) or u.get("city") or "").strip()
            mitid_username = (user_input.get(CONF_MITID_USERNAME) or "").strip()
            notify_service = (user_input.get(CONF_NOTIFY_SERVICE) or "").strip()

            entry_data: dict[str, Any] = {
                CONF_UTILITY: u.get("name") or "KMD Easy Energy",
                CONF_UTILITY_ID: u.get("id", "custom"),
                CONF_UTILITY_STATUS: u.get("status", "pending_test"),
                CONF_PORTAL_URL: portal_url,
                CONF_LOCATION_NAME: location_name,
            }
            if mitid_username:
                entry_data[CONF_MITID_USERNAME] = mitid_username
            if notify_service:
                entry_data[CONF_NOTIFY_SERVICE] = notify_service
            if u.get("latitude") is not None:
                entry_data[CONF_LATITUDE] = u["latitude"]
                entry_data[CONF_LONGITUDE] = u["longitude"]

            if token:
                ok, client = await self._validate_token(token, customer_id, portal_url)
                if not ok:
                    errors["base"] = "invalid_auth"
                else:
                    entry_data[CONF_ACCESS_TOKEN] = token
                    if client._customer_id or customer_id:
                        entry_data[CONF_CUSTOMER_ID] = client._customer_id or customer_id
                    if client._customer_number:
                        entry_data[CONF_CUSTOMER_NUMBER] = client._customer_number
                    await self._async_set_entry_unique_id(
                        entry_data.get(CONF_UTILITY_ID), entry_data.get(CONF_PORTAL_URL)
                    )
                    return self.async_create_entry(
                        title=entry_data[CONF_UTILITY],
                        data=entry_data,
                    )
            else:
                if customer_id:
                    entry_data[CONF_CUSTOMER_ID] = customer_id
                await self._async_set_entry_unique_id(
                    entry_data.get(CONF_UTILITY_ID), entry_data.get(CONF_PORTAL_URL)
                )
                return self.async_create_entry(
                    title=entry_data[CONF_UTILITY],
                    data=entry_data,
                )

        status_badge = (
            "✅ Bekræftet (Confirmed working)"
            if u.get("status") == "confirmed"
            else "🧪 Afventer første test (Pending initial test)"
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_PORTAL_URL, default=u.get("portal_url", "https://")): str,
                vol.Optional(CONF_MITID_USERNAME, default=""): str,
                vol.Optional(CONF_NOTIFY_SERVICE, default=""): str,
                vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
                vol.Optional(CONF_CUSTOMER_ID, default=""): str,
                vol.Optional(CONF_LOCATION_NAME, default=u.get("city", "")): str,
            }
        )
        return self.async_show_form(
            step_id="auth",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "utility_name": str(u.get("name") or "KMD Easy Energy"),
                "portal_url": str(u.get("portal_url") or "https://"),
                "status_badge": status_badge,
                "notes": str(u.get("notes") or ""),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow updating token, portal URL, or customer ID after first-time setup."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        current_data = {**entry.data, **entry.options}
        utility_name = str(current_data.get(CONF_UTILITY) or entry.title or "KMD Easy Energy")

        if user_input is not None:
            portal_url = (user_input.get(CONF_PORTAL_URL) or current_data.get(CONF_PORTAL_URL) or "").strip()
            token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            customer_id = (user_input.get(CONF_CUSTOMER_ID) or "").strip()
            location_name = (user_input.get(CONF_LOCATION_NAME) or "").strip()
            mitid_username = (user_input.get(CONF_MITID_USERNAME) or "").strip()
            notify_service = (user_input.get(CONF_NOTIFY_SERVICE) or "").strip()

            updates: dict[str, Any] = {
                CONF_PORTAL_URL: portal_url,
                CONF_LOCATION_NAME: location_name,
            }
            if mitid_username:
                updates[CONF_MITID_USERNAME] = mitid_username
            if notify_service:
                updates[CONF_NOTIFY_SERVICE] = notify_service
            if customer_id:
                updates[CONF_CUSTOMER_ID] = customer_id

            if token:
                ok, client = await self._validate_token(token, customer_id, portal_url)
                if not ok:
                    errors["base"] = "invalid_auth"
                else:
                    updates[CONF_ACCESS_TOKEN] = token
                    if client._customer_id or customer_id:
                        updates[CONF_CUSTOMER_ID] = client._customer_id or customer_id
                    if client._customer_number:
                        updates[CONF_CUSTOMER_NUMBER] = client._customer_number

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=updates,
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PORTAL_URL,
                    default=current_data.get(CONF_PORTAL_URL, "https://minvarme.kredslob.dk/"),
                ): str,
                vol.Optional(
                    CONF_MITID_USERNAME,
                    default=current_data.get(CONF_MITID_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=current_data.get(CONF_NOTIFY_SERVICE, ""),
                ): str,
                vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
                vol.Optional(
                    CONF_CUSTOMER_ID,
                    default=current_data.get(CONF_CUSTOMER_ID, ""),
                ): str,
                vol.Optional(
                    CONF_LOCATION_NAME,
                    default=current_data.get(CONF_LOCATION_NAME, ""),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "utility_name": utility_name,
                "portal_url": str(current_data.get(CONF_PORTAL_URL, "https://minvarme.kredslob.dk/")),
            },
        )


    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start reauth when the KMD Bearer token is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Paste a fresh token or start a native MitID login."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        current = {**entry.data, **entry.options}
        utility_name = str(current.get(CONF_UTILITY) or entry.title or "KMD Easy Energy")

        if user_input is not None:
            token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            mitid_username = (user_input.get(CONF_MITID_USERNAME) or "").strip()
            notify_service = (user_input.get(CONF_NOTIFY_SERVICE) or "").strip()
            start_mitid = bool(user_input.get("start_mitid"))
            portal_url = (
                user_input.get(CONF_PORTAL_URL)
                or current.get(CONF_PORTAL_URL)
                or ""
            ).strip()
            customer_id = (user_input.get(CONF_CUSTOMER_ID) or current.get(CONF_CUSTOMER_ID) or "").strip()

            updates: dict[str, Any] = {CONF_PORTAL_URL: portal_url}
            if mitid_username:
                updates[CONF_MITID_USERNAME] = mitid_username
            if notify_service:
                updates[CONF_NOTIFY_SERVICE] = notify_service
            if customer_id:
                updates[CONF_CUSTOMER_ID] = customer_id

            if token:
                ok, client = await self._validate_token(token, customer_id, portal_url)
                if not ok:
                    errors["base"] = "invalid_auth"
                else:
                    updates[CONF_ACCESS_TOKEN] = token
                    if client._customer_id or customer_id:
                        updates[CONF_CUSTOMER_ID] = client._customer_id or customer_id
                    if client._customer_number:
                        updates[CONF_CUSTOMER_NUMBER] = client._customer_number
                    return self.async_update_reload_and_abort(entry, data_updates=updates)

            elif start_mitid:
                if mitid_username or notify_service or portal_url:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, **updates}
                    )
                coord = (self.hass.data.get(DOMAIN) or {}).get(entry.entry_id)
                if coord is None:
                    errors["base"] = "mitid_unavailable"
                else:
                    await coord.async_start_mitid_sync(
                        mitid_username=mitid_username or None,
                        notify_service=notify_service if notify_service else None,
                    )
                    return await self.async_step_reauth_mitid()
            else:
                errors["base"] = "token_or_mitid_required"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PORTAL_URL,
                    default=current.get(CONF_PORTAL_URL, "https://minvarme.kredslob.dk/"),
                ): str,
                vol.Optional(
                    CONF_MITID_USERNAME,
                    default=current.get(CONF_MITID_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=current.get(CONF_NOTIFY_SERVICE, ""),
                ): str,
                vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
                vol.Optional(
                    CONF_CUSTOMER_ID,
                    default=current.get(CONF_CUSTOMER_ID, ""),
                ): str,
                vol.Optional("start_mitid", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "utility_name": utility_name,
                "portal_url": str(current.get(CONF_PORTAL_URL, "")),
            },
        )

    async def async_step_reauth_mitid(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for the in-progress MitID flow.

        The 4-digit code is shown in a persistent notification and on the
        Lovelace card via a bus event — not in entity state or the recorder.
        The optional otp_hint placeholder is only rendered in this transient
        config-flow form.
        """
        entry = self._get_reauth_entry()
        coord = (self.hass.data.get(DOMAIN) or {}).get(entry.entry_id)
        if coord is None:
            return self.async_abort(reason="mitid_unavailable")

        otp_hint = coord.mitid_otp_code or "—"
        sync_state = coord.sync_state or "starting"
        sync_message = coord.sync_message or (
            "Åbn MitID-appen og godkend. Tryk på Send for at opdatere status."
        )

        if user_input is not None:
            if sync_state == "error":
                return self.async_show_form(
                    step_id="reauth_mitid",
                    data_schema=vol.Schema({}),
                    errors={"base": "mitid_failed"},
                    description_placeholders={
                        "sync_message": sync_message,
                        "otp_hint": otp_hint,
                        "sync_state": sync_state,
                    },
                )
            if sync_state == "idle" and (
                coord.entry.data.get(CONF_ACCESS_TOKEN)
                or entry.data.get(CONF_ACCESS_TOKEN)
            ):
                return self.async_update_reload_and_abort(entry, data_updates={})

        return self.async_show_form(
            step_id="reauth_mitid",
            data_schema=vol.Schema({}),
            description_placeholders={
                "sync_message": sync_message,
                "otp_hint": otp_hint,
                "sync_state": sync_state,
            },
        )



class KMDEasyEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle options for KMD Easy Energy."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PORTAL_URL,
                    default=opts.get(CONF_PORTAL_URL, "https://minvarme.kredslob.dk/"),
                ): str,
                vol.Optional(
                    CONF_LOCATION_NAME,
                    default=opts.get(CONF_LOCATION_NAME, ""),
                ): str,
                vol.Optional(
                    CONF_BONUS_TEMP,
                    default=float(opts.get(CONF_BONUS_TEMP, 30.0)),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_PENALTY_TEMP,
                    default=float(opts.get(CONF_PENALTY_TEMP, 40.0)),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_LATITUDE,
                    default=float(opts.get(CONF_LATITUDE) or self.hass.config.latitude or 56.15),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_LONGITUDE,
                    default=float(opts.get(CONF_LONGITUDE) or self.hass.config.longitude or 10.10),
                ): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
