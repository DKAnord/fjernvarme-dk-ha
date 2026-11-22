"""Config flow and options flow for KMD Easy Energy."""

from __future__ import annotations

import hashlib
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
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api.eforsyning_client import EforsyningClient, EforsyningError, EforsyningLoginError

from .const import (
    BACKEND_EFORSYNING,
    BACKEND_KMD,
    CONF_AUTO_SYNC,
    CONF_AUTO_SYNC_HOUR,
    CONF_BACKEND,
    CONF_BONUS_TEMP,
    CONF_EF_INSTALLATION_ID,
    CONF_EF_PASSWORD,
    CONF_EF_SUPPLIER_ID,
    CONF_EF_USERNAME,
    CONF_CUSTOMER_ID,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_UTILITY_LATITUDE,
    CONF_UTILITY_LONGITUDE,
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
    DEFAULT_AUTO_SYNC,
    DEFAULT_AUTO_SYNC_HOUR,
    DEFAULT_SYNC_REMINDER,
    DEFAULT_SYNC_REMINDER_BY_BACKEND,
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


CUSTOM_EFORSYNING: dict[str, Any] = {
    "id": "eforsyning-custom",
    "name": "Andet E|Forsyning-værk",
    "city": "",
    "portal_url": "https://eforsyning.dk/",
    "status": "pending_test",
    "tier": "custom",
    "backend": BACKEND_EFORSYNING,
    "notes": "Angiv værkets forsyningid (se hjælpeteksten).",
}

_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def utility_backend(u: dict[str, Any] | None) -> str:
    backend = str((u or {}).get("backend") or BACKEND_KMD).strip().lower()
    return backend if backend in (BACKEND_KMD, BACKEND_EFORSYNING) else BACKEND_KMD


def eforsyning_unique_id(supplier_id: str, username: str) -> str:
    """One entry per supplier + forbrugernummer, without storing the number in clear."""
    digest = hashlib.sha256(f"{supplier_id.strip().lower()}|{username.strip()}".encode()).hexdigest()
    return f"eforsyning:{supplier_id.strip().lower()}:{digest[:12]}"


async def async_validate_eforsyning(
    hass: Any, username: str, password: str, supplier_id: str
) -> list[dict[str, Any]]:
    """Log in once and return the installations (credentials are not logged)."""
    client = EforsyningClient(async_get_clientsession(hass), username, password, supplier_id)
    try:
        await client.async_login()
        return await client.async_get_installations()
    finally:
        client.discard_credentials()


def _installation_label(inst: dict[str, Any]) -> str:
    addr = str(inst.get("Adresse") or "").strip()
    nr = inst.get("InstallationNr")
    return f"{addr} (installation {nr})" if addr else f"Installation {nr}"


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
    if utility_backend(u) == BACKEND_EFORSYNING:
        return f"🧪 {u['name']}{city} — E|Forsyning (eksperimentel)"
    if u.get("status") == "confirmed":
        return f"✅ {u['name']}{city} — Bekræftet / Confirmed"
    if tier == "candidate":
        return f"🔎 {u['name']}{city} — Kandidat (afventer test)"
    return f"🧪 {u['name']}{city} — Afventer 1. test / Pending test"


_LAT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=-90, max=90, step="any", mode=NumberSelectorMode.BOX)
)
_LON_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=-180, max=180, step="any", mode=NumberSelectorMode.BOX)
)


def _clean_outdoor_options(user_input: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Validate the outdoor temperature options.

    Latitude/longitude are an explicit override: both or neither. Empty
    fields (or 0/0) mean "use the HA home location". An empty sensor means
    "Open-Meteo only".
    """
    data = dict(user_input)
    entity = str(data.get(CONF_OUTDOOR_TEMP_ENTITY) or "").strip()
    if entity:
        if not entity.startswith("sensor."):
            return data, "outdoor_temp_entity_invalid"
        data[CONF_OUTDOOR_TEMP_ENTITY] = entity
    else:
        data.pop(CONF_OUTDOOR_TEMP_ENTITY, None)
    lat = data.get(CONF_LATITUDE)
    lon = data.get(CONF_LONGITUDE)
    if lat in (None, "") and lon in (None, ""):
        data.pop(CONF_LATITUDE, None)
        data.pop(CONF_LONGITUDE, None)
        return data, None
    if lat in (None, "") or lon in (None, ""):
        return data, "location_incomplete"
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return data, "location_invalid"
    if la == 0 and lo == 0:
        data.pop(CONF_LATITUDE, None)
        data.pop(CONF_LONGITUDE, None)
        return data, None
    if not (-90 <= la <= 90 and -180 <= lo <= 180):
        return data, "location_invalid"
    data[CONF_LATITUDE], data[CONF_LONGITUDE] = la, lo
    return data, None


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
    MINOR_VERSION = 3

    def __init__(self) -> None:
        self._selected_utility: dict[str, Any] = dict(CUSTOM_UTILITY)
        self._ef_pending: dict[str, Any] = {}
        self._ef_installations: list[dict[str, Any]] = []

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
            elif selected_id == CUSTOM_EFORSYNING["id"]:
                self._selected_utility = dict(CUSTOM_EFORSYNING)
            else:
                self._selected_utility = next(
                    (u for u in utilities if u.get("id") == selected_id),
                    dict(CUSTOM_UTILITY),
                )
            if utility_backend(self._selected_utility) == BACKEND_EFORSYNING:
                return await self.async_step_eforsyning()
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
        options.append(
            SelectOptionDict(
                value=CUSTOM_EFORSYNING["id"],
                label="⚙️ Andet E|Forsyning-værk (eksperimentel, kræver forsyningid)",
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
                # Utility metadata / last-resort Open-Meteo location (the HA
                # home location wins; only options can override it).
                entry_data[CONF_UTILITY_LATITUDE] = u["latitude"]
                entry_data[CONF_UTILITY_LONGITUDE] = u["longitude"]

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

    async def async_step_eforsyning(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """E|Forsyning: forbrugernummer + webpinkode instead of MitID."""
        errors: dict[str, str] = {}
        u = self._selected_utility
        known_supplier = str(u.get("eforsyning_supplier_id") or "").strip()

        if user_input is not None:
            username = str(user_input.get(CONF_EF_USERNAME) or "").strip()
            password = str(user_input.get(CONF_EF_PASSWORD) or "")
            supplier_id = (
                known_supplier or str(user_input.get(CONF_EF_SUPPLIER_ID) or "").strip()
            )
            location_name = (user_input.get(CONF_LOCATION_NAME) or u.get("city") or "").strip()
            if not username or not password:
                errors["base"] = "eforsyning_missing"
            elif not supplier_id:
                errors[CONF_EF_SUPPLIER_ID] = "eforsyning_supplier_required"
            else:
                await self.async_set_unique_id(eforsyning_unique_id(supplier_id, username))
                self._abort_if_unique_id_configured()
                try:
                    installs = await async_validate_eforsyning(
                        self.hass, username, password, supplier_id
                    )
                except EforsyningLoginError:
                    errors["base"] = "invalid_auth"
                except EforsyningError:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected E|Forsyning error during setup")
                    errors["base"] = "unknown"
                else:
                    self._ef_pending = {
                        CONF_BACKEND: BACKEND_EFORSYNING,
                        CONF_UTILITY: u.get("name") or "E|Forsyning",
                        CONF_UTILITY_ID: u.get("id", CUSTOM_EFORSYNING["id"]),
                        CONF_UTILITY_STATUS: u.get("status", "pending_test"),
                        CONF_PORTAL_URL: u.get("portal_url") or "https://eforsyning.dk/",
                        CONF_LOCATION_NAME: location_name,
                        CONF_EF_USERNAME: username,
                        CONF_EF_PASSWORD: password,
                        CONF_EF_SUPPLIER_ID: supplier_id,
                    }
                    if u.get("latitude") is not None:
                        self._ef_pending[CONF_UTILITY_LATITUDE] = u["latitude"]
                        self._ef_pending[CONF_UTILITY_LONGITUDE] = u["longitude"]
                    self._ef_installations = installs
                    if len(installs) > 1:
                        return await self.async_step_eforsyning_installation()
                    if installs and installs[0].get("InstallationNr") is not None:
                        self._ef_pending[CONF_EF_INSTALLATION_ID] = str(
                            installs[0]["InstallationNr"]
                        )
                    return self._create_eforsyning_entry()

        fields: dict[Any, Any] = {
            vol.Required(CONF_EF_USERNAME, default=""): str,
            vol.Required(CONF_EF_PASSWORD): _PASSWORD_SELECTOR,
        }
        if not known_supplier:
            fields[vol.Required(CONF_EF_SUPPLIER_ID, default="")] = str
        fields[vol.Optional(CONF_LOCATION_NAME, default=u.get("city", ""))] = str
        return self.async_show_form(
            step_id="eforsyning",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "utility_name": str(u.get("name") or "E|Forsyning"),
                "portal_url": str(u.get("portal_url") or "https://eforsyning.dk/"),
                "example_url": "https://eforsyning.dk/hjvarme",
            },
        )

    async def async_step_eforsyning_installation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick the installation when the account has more than one."""
        if user_input is not None:
            self._ef_pending[CONF_EF_INSTALLATION_ID] = str(user_input[CONF_EF_INSTALLATION_ID])
            return self._create_eforsyning_entry()
        options = [
            SelectOptionDict(value=str(i.get("InstallationNr")), label=_installation_label(i))
            for i in self._ef_installations
        ]
        return self.async_show_form(
            step_id="eforsyning_installation",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EF_INSTALLATION_ID, default=options[0]["value"]): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )

    def _create_eforsyning_entry(self) -> FlowResult:
        data = dict(self._ef_pending)
        self._ef_pending = {}
        return self.async_create_entry(
            title=str(data.get(CONF_UTILITY) or "E|Forsyning"),
            data=data,
            options={
                CONF_AUTO_SYNC: DEFAULT_AUTO_SYNC,
                CONF_AUTO_SYNC_HOUR: DEFAULT_AUTO_SYNC_HOUR,
                CONF_SYNC_REMINDER: DEFAULT_SYNC_REMINDER_BY_BACKEND[BACKEND_EFORSYNING],
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
        if entry.data.get(CONF_BACKEND) == BACKEND_EFORSYNING:
            return await self.async_step_reconfigure_eforsyning(user_input)

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


    async def async_step_reconfigure_eforsyning(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change forbrugernummer / webpinkode / forsyningid (empty pinkode = keep)."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        data = dict(entry.data)
        if user_input is not None:
            username = str(user_input.get(CONF_EF_USERNAME) or "").strip()
            password = str(user_input.get(CONF_EF_PASSWORD) or "") or str(
                data.get(CONF_EF_PASSWORD) or ""
            )
            supplier_id = str(
                user_input.get(CONF_EF_SUPPLIER_ID) or data.get(CONF_EF_SUPPLIER_ID) or ""
            ).strip()
            try:
                await async_validate_eforsyning(self.hass, username, password, supplier_id)
            except EforsyningLoginError:
                errors["base"] = "invalid_auth"
            except EforsyningError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected E|Forsyning error during reconfigure")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_EF_USERNAME: username,
                        CONF_EF_PASSWORD: password,
                        CONF_EF_SUPPLIER_ID: supplier_id,
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_EF_USERNAME, default=str(data.get(CONF_EF_USERNAME) or "")): str,
                vol.Optional(CONF_EF_PASSWORD, default=""): _PASSWORD_SELECTOR,
                vol.Required(
                    CONF_EF_SUPPLIER_ID, default=str(data.get(CONF_EF_SUPPLIER_ID) or "")
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure_eforsyning",
            data_schema=schema,
            errors=errors,
            description_placeholders={"utility_name": str(data.get(CONF_UTILITY) or entry.title)},
        )


class KMDEasyEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle options for KMD Easy Energy."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned, error = _clean_outdoor_options(user_input)
            if error is None:
                return self.async_create_entry(title="", data=cleaned)
            errors["base"] = error

        opts = {**self.config_entry.data, **self.config_entry.options}
        # Only an explicit options override is a user location; utility
        # coordinates in entry.data are metadata and never pre-filled.
        explicit = self.config_entry.options
        if user_input is not None:
            explicit = {**explicit, **user_input}
        backend = str(self.config_entry.data.get(CONF_BACKEND) or BACKEND_KMD)
        reminder_default = DEFAULT_SYNC_REMINDER_BY_BACKEND.get(backend, DEFAULT_SYNC_REMINDER)
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
                    CONF_OUTDOOR_TEMP_ENTITY,
                    description={"suggested_value": explicit.get(CONF_OUTDOOR_TEMP_ENTITY)},
                ): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(
                    CONF_LATITUDE,
                    description={"suggested_value": explicit.get(CONF_LATITUDE)},
                ): _LAT_SELECTOR,
                vol.Optional(
                    CONF_LONGITUDE,
                    description={"suggested_value": explicit.get(CONF_LONGITUDE)},
                ): _LON_SELECTOR,
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
                    default=bool(opts.get(CONF_SYNC_REMINDER, reminder_default)),
                ): bool,
            }
        )
        if backend == BACKEND_EFORSYNING:
            schema = schema.extend(
                {
                    vol.Optional(
                        CONF_AUTO_SYNC,
                        default=bool(opts.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC)),
                    ): bool,
                    vol.Optional(
                        CONF_AUTO_SYNC_HOUR,
                        default=int(opts.get(CONF_AUTO_SYNC_HOUR, DEFAULT_AUTO_SYNC_HOUR)),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                }
            )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
