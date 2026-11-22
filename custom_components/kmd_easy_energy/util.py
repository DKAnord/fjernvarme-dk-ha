"""Helpers for KMD Easy Energy (privacy, cache, identifiers)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

SENSITIVE_CACHE_KEYS = (
    "mitid_otp_code",
    "mitid_qr_svg",
    "access_token",
    "otp_code",
    "qr_svg",
    "Authorization",
    "authorization",
    "refresh_token",
    "wattson_refresh_token",
)

_REDACT_QS = re.compile(
    r"([?&#](?:code|access_token|id_token|refresh_token|token|client_secret)=)[^&]+",
    re.IGNORECASE,
)
_REDACT_BEARER = re.compile(r"(Bearer )\S+", re.IGNORECASE)


def redact_url(url: str | None) -> str:
    """Redact OIDC codes and tokens in URLs before logging."""
    if not url:
        return ""
    return _REDACT_QS.sub(r"\1[REDACTED]", str(url))


def redact_secret(value: str | None) -> str:
    """Redact bearer tokens and query secrets in a log fragment."""
    if not value:
        return ""
    text = _REDACT_BEARER.sub(r"\1[REDACTED]", str(value))
    return redact_url(text)


def sanitize_cache(state: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of coordinator state safe to persist privately."""
    clean = {k: v for k, v in state.items() if k not in SENSITIVE_CACHE_KEYS}
    if clean.get("sync_state") not in (None, "idle"):
        clean["sync_state"] = "idle"
        clean["sync_message"] = ""
    return clean


def unique_id_for(utility_id: str | None, portal_url: str | None = None) -> str:
    """Stable config-entry unique_id: one entry per utility (or custom portal host)."""
    uid = (utility_id or "").strip().lower()
    if uid and uid != "custom":
        return uid
    host = urlparse((portal_url or "").strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"custom:{host}" if host else "custom"


def store_for(hass: HomeAssistant, entry_id: str) -> Store:
    """Private .storage store for one config entry."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


def legacy_www_cache_paths(hass: HomeAssistant, utility_id: str | None) -> list[Path]:
    """Historical (public) cache locations that must be migrated or deleted."""
    paths: list[Path] = []
    uid = (utility_id or "").strip()
    if uid:
        paths.append(Path(hass.config.path(f"www/varme/kmd_easy_energy_cache_{uid}.json")))
    paths.append(Path(hass.config.path("www/varme/kmd_easy_energy_cache.json")))
    # Unique-ify while keeping order
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def read_legacy_www_cache(paths: list[Path]) -> dict[str, Any]:
    """Read the first readable legacy JSON cache (run in executor)."""
    for path in paths:
        try:
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data:
                    _LOGGER.info("Migrating legacy cache from %s", path)
                    return data
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read legacy cache %s: %s", path, err)
    return {}


def delete_legacy_www_cache(paths: list[Path]) -> None:
    """Delete migrated public cache files only (run in executor)."""
    for path in paths:
        try:
            if path.exists() and path.is_file():
                path.unlink()
                _LOGGER.info("Removed public cache file %s", path)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not remove legacy cache %s: %s", path, err)


def cache_has_sensor_data(state: dict[str, Any] | None) -> bool:
    """True if cached state can populate sensors without a live API call."""
    if not state:
        return False
    if state.get("annual") or state.get("daily") or state.get("monthly"):
        return True
    if state.get("balance") or state.get("billing"):
        return True
    if state.get("hourly_kwh") or state.get("hourly_m3") or state.get("hdd_7d") is not None:
        return True
    return False
