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
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BONUS_TEMP,
    CONF_CUSTOMER_ID,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_LOCATION_NAME,
    CONF_MITID_USERNAME,
    CONF_MOTIVATION_DKK_PER_KWH_PER_K,
    CONF_NORMAL_HDD_YEAR,
    CONF_NOTIFY_SERVICE,
    CONF_PENALTY_TEMP,
    CONF_PORTAL_URL,
    CONF_PRICE_DKK_PER_KWH,
    CONF_PRICE_DKK_PER_M3,
    CONF_SYNC_REMINDER,
    CONF_UTILITY,
    CONF_UTILITY_ID,
    CONF_UTILITY_STATUS,
    DEFAULT_SYNC_REMINDER,
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


def _notify_service_selector(hass: Any, current: str = "") -> SelectSelector:
    """Build a dropdown selector of available Home Assistant notify services."""
    services_map: dict[str, Any] = {}
    try:
        all_services = hass.services.async_services() if hass and hasattr(hass, "services") else {}
        if isinstance(all_services, dict):
            raw_notify = all_services.get("notify") or {}
            if isinstance(raw_notify, dict):
                services_map = raw_notify
    except Exception:  # noqa: BLE001
        services_map = {}

    excluded = {"persistent_notification", "send_message", "notify"}
    names = [str(k) for k in services_map if str(k) not in excluded]
    mobile = sorted(n for n in names if n.startswith("mobile_app_"))
    other = sorted(n for n in names if not n.startswith("mobile_app_"))

    options: list[SelectOptionDict] = [
        SelectOptionDict(value="", label="— Ingen mobil-push / None —"),
    ]
    for svc in mobile:
        friendly = svc[len("mobile_app_") :].replace("_", " ").title()
        options.append(SelectOptionDict(value=svc, label=f"📱 {friendly} ({svc})"))
    for svc in other:
        options.append(SelectOptionDict(value=svc, label=f"🔔 {svc}"))

    cur = str(current or "").replace("notify.", "").strip()
    if cur and cur not in names:
        options.append(SelectOptionDict(value=cur, label=cur))

    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


class KMDEasyEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a 2-step config flow for KMD Easy Energy."""

    VERSION = 1
    # 1.2: KMD access tokens are no longer stored (session-based sync).
    MINOR_VERSION = 2

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: smart utility dropdown (or direct 1-step API submission)."""
        utilities = await self.hass.async_add_executor_job(_load_utilities)

        if user_input is not None:
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
        """Step 2: utility portal, MitID User ID and optional notify service."""
        errors: dict[str, str] = {}
        u = self._selected_utility

        if user_input is not None:
            portal_url = (user_input.get(CONF_PORTAL_URL) or u.get("portal_url") or "").strip()
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
                vol.Optional(CONF_NOTIFY_SERVICE, default=""): _notify_service_selector(self.hass),
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
        """Allow updating portal URL, MitID User ID, notify service or customer ID."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        current_data = {**entry.data, **entry.options}
        utility_name = str(current_data.get(CONF_UTILITY) or entry.title or "KMD Easy Energy")

        if user_input is not None:
            portal_url = (user_input.get(CONF_PORTAL_URL) or current_data.get(CONF_PORTAL_URL) or "").strip()
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
                    default=str(current_data.get(CONF_NOTIFY_SERVICE, "")).replace("notify.", "").strip(),
                ): _notify_service_selector(
                    self.hass, str(current_data.get(CONF_NOTIFY_SERVICE, ""))
                ),
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
                    CONF_NOTIFY_SERVICE,
                    default=str(opts.get(CONF_NOTIFY_SERVICE, "")).replace("notify.", "").strip(),
                ): _notify_service_selector(
                    self.hass, str(opts.get(CONF_NOTIFY_SERVICE, ""))
                ),
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
                vol.Optional(
                    CONF_PRICE_DKK_PER_KWH,
                    default=float(opts.get(CONF_PRICE_DKK_PER_KWH) or 0.0),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_PRICE_DKK_PER_M3,
                    default=float(opts.get(CONF_PRICE_DKK_PER_M3) or 0.0),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_MOTIVATION_DKK_PER_KWH_PER_K,
                    default=float(opts.get(CONF_MOTIVATION_DKK_PER_KWH_PER_K) or 0.0),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_NORMAL_HDD_YEAR,
                    default=float(opts.get(CONF_NORMAL_HDD_YEAR) or 0.0),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_SYNC_REMINDER,
                    default=bool(opts.get(CONF_SYNC_REMINDER, DEFAULT_SYNC_REMINDER)),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
