"""Install the bundled Lovelace card and keep its resource cache-busted.

Home Assistant serves ``/local/`` with ``Cache-Control: public, max-age=2678400``
(31 days). The integration already overwrites ``www/js/kmd-easy-energy-card.js``
on startup, but a Lovelace resource without ``?v=`` can keep a stale module in
the browser or Companion app. From v0.3.0 the card reads MitID QR/OTP from the
websocket subscription ``kmd_easy_energy/mitid/subscribe``; the v0.2.x card
looked at the removed ``mitid_qr_svg`` / ``mitid_otp_code`` attributes, so a
cached old card shows no QR after the update.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant

from .const import CARD_JS_FILENAME, CARD_RESOURCE_PATH

_LOGGER = logging.getLogger(__name__)


def integration_version() -> str:
    """Return the integration version from manifest.json."""
    path = Path(__file__).parent / "manifest.json"
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def card_resource_url(version: str | None = None) -> str:
    """Return the Lovelace resource URL with a cache-busting query string."""
    return f"{CARD_RESOURCE_PATH}?v={version or integration_version()}"


def is_our_card_resource_url(url: str) -> bool:
    """True if *url* points at the bundled card under ``/local/js/``."""
    raw = (url or "").strip()
    if not raw:
        return False
    path = urlsplit(raw).path.rstrip("/")
    return path == CARD_RESOURCE_PATH or path.endswith(CARD_RESOURCE_PATH)


def install_frontend_card(www_js_dir: Path) -> Path | None:
    """Copy bundled Lovelace card JS to ``<config>/www/js/`` (run in executor)."""
    src = Path(__file__).parent / "frontend" / CARD_JS_FILENAME
    if not src.exists():
        return None
    www_js_dir.mkdir(parents=True, exist_ok=True)
    dst = www_js_dir / CARD_JS_FILENAME
    try:
        if not dst.exists() or src.read_bytes() != dst.read_bytes():
            shutil.copy2(src, dst)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not install frontend card to %s: %s", dst, err)
        return None
    return dst


async def async_ensure_lovelace_card_resource(
    hass: HomeAssistant, version: str | None = None
) -> str:
    """Register or update the Lovelace resource so browsers fetch the current card.

    Storage-mode Lovelace (the default) is updated automatically. YAML mode
    cannot be changed here; a warning is logged if the URL is missing or stale.
    """
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
                "(Home Assistant caches /local for 31 days; without ?v= the browser "
                "may keep an old card that cannot show the MitID QR).",
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
