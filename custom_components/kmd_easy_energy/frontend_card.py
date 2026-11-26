"""Serve the bundled Lovelace card from an integration-owned static path.

The integration serves ``frontend/kmd-easy-energy-card.js`` directly at
``/kmd_easy_energy/kmd-easy-energy-card.js`` without copying into ``/config/www``
(which belongs to the user), and keeps the storage-mode Lovelace resource URL
cache-busted with ``?v=<version>`` while migrating any legacy ``/local/js/``
resource entries.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant

from .const import (
    CARD_JS_FILENAME,
    CARD_RESOURCE_PATH,
    DOMAIN,
    LEGACY_CARD_RESOURCE_PATH,
)

_LOGGER = logging.getLogger(__name__)
_STATIC_CARD_REGISTERED = f"{DOMAIN}_card_static_registered"


def integration_version() -> str:
    """Return the integration version from manifest.json."""
    path = Path(__file__).parent / "manifest.json"
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def card_resource_url(version: str | None = None) -> str:
    """Return the Lovelace resource URL with a cache-busting query string."""
    return f"{CARD_RESOURCE_PATH}?v={version or integration_version()}"


def is_our_card_resource_url(url: str) -> bool:
    """True if *url* points at the bundled card (current or legacy path)."""
    raw = (url or "").strip()
    if not raw:
        return False
    path = urlsplit(raw).path.rstrip("/")
    return any(
        path == candidate or path.endswith(candidate)
        for candidate in (CARD_RESOURCE_PATH, LEGACY_CARD_RESOURCE_PATH)
    )


async def async_register_frontend_card_static_path(hass: HomeAssistant) -> bool:
    """Serve the bundled card directly at ``/kmd_easy_energy/kmd-easy-energy-card.js``."""
    src = Path(__file__).parent / "frontend" / CARD_JS_FILENAME
    hass_data = getattr(hass, "data", None)
    if isinstance(hass_data, dict) and hass_data.get(_STATIC_CARD_REGISTERED):
        return True
    http = getattr(hass, "http", None)
    register = getattr(http, "async_register_static_paths", None)
    if not callable(register):
        return False
    try:
        from homeassistant.components.http import StaticPathConfig
    except ImportError:
        return False
    try:
        await register([StaticPathConfig(CARD_RESOURCE_PATH, str(src), cache_headers=True)])
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register static path %s: %s", CARD_RESOURCE_PATH, err)
        return False
    if isinstance(hass_data, dict):
        hass_data[_STATIC_CARD_REGISTERED] = True
    return True


async def async_ensure_lovelace_card_resource(
    hass: HomeAssistant, version: str | None = None
) -> str:
    """Register or update the Lovelace resource so browsers fetch the current card.

    Storage-mode Lovelace (the default) is updated automatically. YAML mode
    cannot be changed here; a warning is logged if the URL is missing or stale.
    """
    if version is None:
        if hasattr(hass, "async_add_executor_job"):
            version = await hass.async_add_executor_job(integration_version)
        else:
            version = integration_version()
    target = card_resource_url(version)
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import ResourceStorageCollection
    except ImportError:
        _LOGGER.debug("Lovelace component not available; skip card resource %s", target)
        return target

    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        _LOGGER.debug("Lovelace is not set up; skip card resource %s", target)
        return target

    resources = getattr(lovelace, "resources", None)
    if resources is None:
        return target

    if not isinstance(resources, ResourceStorageCollection):
        items = resources.async_items() or []
        urls = [str(item.get("url") or "") for item in items]
        if not any(is_our_card_resource_url(url) and url.split("#")[0] == target for url in urls):
            _LOGGER.warning(
                "Lovelace is in YAML mode. Add or update the card resource to %s "
                "(migrating from any legacy /local/js/ path; without ?v= the browser "
                "may keep an old cached card that cannot show the MitID QR).",
                target,
            )
        return target

    await resources.async_get_info()
    existing = [
        item
        for item in (resources.async_items() or [])
        if is_our_card_resource_url(str(item.get("url") or ""))
    ]
    if not existing:
        await resources.async_create_item({"res_type": "module", "url": target})
        _LOGGER.info("Registered Lovelace card resource %s", target)
        return target

    first, *duplicates = existing
    updates: dict[str, Any] = {}
    if first.get("url") != target:
        updates["url"] = target
    if first.get("type") != "module":
        updates["res_type"] = "module"
    if updates:
        await resources.async_update_item(str(first["id"]), updates)
        _LOGGER.info("Updated Lovelace card resource to %s (cache-bust)", target)

    for item in duplicates:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        try:
            await resources.async_delete_item(item_id)
            _LOGGER.info("Removed duplicate Lovelace card resource %s", item.get("url"))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not remove duplicate card resource %s: %s", item.get("url"), err)
    return target
