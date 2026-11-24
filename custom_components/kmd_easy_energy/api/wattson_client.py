"""Async client for the Watts On backend (Watts A/S), used for district heating.

DERIVED WORK NOTICE
-------------------
The login flow, the API base URL and the endpoint/field names below were
learned from TheRealBatBro/Home-Assistant-Novafos-V2
(https://github.com/TheRealBatBro/Home-Assistant-Novafos-V2, commit 920e41f,
files ``custom_components/novafos_watts/api.py``, ``const.py``, ``__init__.py``
and ``tools/login.py``), which reads Novafos WATER data via Watts On.

    Copyright (c) 2026 TheRealBatBro
    Licensed under the MIT License; the full copyright and permission notice
    is reproduced in ``LICENSE-novafos-v2-MIT.txt`` next to this file and in
    the repository NOTICE file.

Changes were made. This file is an independent reimplementation, not a copy:
  * the in-browser login is done inside a Home Assistant config flow (PKCE
    pair + paste of the final ``msauth://`` redirect) instead of a CLI tool;
  * rotating refresh tokens are handed to a callback so the integration can
    persist them in the config entry, together with their expiry when the
    token endpoint reports one;
  * device discovery returns only non-personal fields and classifies heat,
    water and electricity devices (the original only looks for water);
  * district-heating consumption endpoints are UNKNOWN (the original only
    covers ``water/api/consumptions``); a small list of candidate paths is
    probed and the probe outcome (paths + HTTP status, no data) is kept for
    diagnostics, with an advanced override;
  * defensive parsing of heat fields (energy/volume/temperatures) with unit
    handling (kWh/MWh/GJ) and explicit "assumption" flags;
  * HTTP 429 handling and no logging of tokens, codes or redirect URLs.

Modifications Copyright (c) 2026 Daniel / DKAnord, under the license of this
repository.

What is verified (from the Novafos-V2 code, water only) vs. assumed (heat) is
documented in README.md. Nothing in this module has been tested against a
real Aalborg Forsyning heat meter yet.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

# --- Public identifiers of the Watts On app registration (Azure AD B2C). ---
# Taken from Novafos-V2 (verified there against the live service for water).
WATTS_TENANT = "wattsenergyassistant"
WATTS_POLICY = "B2C_1A_JITMigraion_signup_signin"  # sic, as registered by Watts
WATTS_CLIENT_ID = "a19dc71d-697e-451a-86c4-cc112b202c90"
# The app registration only accepts the Android app's own redirect URI.
WATTS_REDIRECT_URI = "msauth://com.seasnve.watts/fsJnZjQxAH1FUDb0pBECue0g650%3D"
WATTS_SCOPE = (
    f"https://{WATTS_TENANT}.onmicrosoft.com/{WATTS_CLIENT_ID}/Watts.API offline_access openid"
)
WATTS_AUTHORITY = (
    f"https://{WATTS_TENANT}.b2clogin.com/tfp/{WATTS_TENANT}.onmicrosoft.com/"
    f"{WATTS_POLICY}/oauth2/v2.0"
)
WATTS_AUTHORIZE_URL = f"{WATTS_AUTHORITY}/authorize"
WATTS_TOKEN_URL = f"{WATTS_AUTHORITY}/token"
WATTS_API_BASE = "https://p.watts-energy.dk/"

# Verified (Novafos-V2, water): users/api/v3/User, installations/api/v3/users/
# {user}/locations, provisioning/api/v1/locations/{loc}, water/api/consumptions/
# {device}?startDate=. Heat: the first candidate is verified live against an
# Aalborg Forsyning district-heating meter (2026-11-22) and is the path the
# Watts On app itself uses; it takes ?newerThan= (?startDate= gives HTTP 400).
# Its items are {Id, SD, ED, En (kWh), Vol (m³), Fl, TI, TO, CD, MQ}, with
# TI/TO = supply/return temperature. The other candidates are older guesses.
HEAT_ENDPOINT_CANDIDATES: tuple[str, ...] = (
    "heating/api/v1/devices/{device_id}/consumption/recent",
    "heating/api/consumptions/{device_id}",
    "districtheating/api/consumptions/{device_id}",
    "heat/api/consumptions/{device_id}",
)

_TIMEOUT = aiohttp.ClientTimeout(total=45)


class WattsOnError(Exception):
    """Any failure talking to Watts On."""


class WattsOnAuthError(WattsOnError):
    """The refresh token (or the login code) was rejected: log in again."""


class WattsOnRateLimited(WattsOnError):
    """HTTP 429 from Watts On."""


class WattsOnNotFound(WattsOnError):
    """HTTP 404/400/405 for an endpoint (used while probing candidates)."""


# ---------------------------------------------------------------------------
# Browser login (PKCE + pasted msauth:// redirect)
# ---------------------------------------------------------------------------
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass
class PkceLogin:
    """One login attempt; lives only in the config-flow instance (memory)."""

    verifier: str
    state: str
    url: str


def new_login() -> PkceLogin:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(12)
    query = urlencode(
        {
            "client_id": WATTS_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": WATTS_REDIRECT_URI,
            "response_mode": "query",
            "scope": WATTS_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return PkceLogin(verifier=verifier, state=state, url=f"{WATTS_AUTHORIZE_URL}?{query}")


def code_from_redirect(pasted: str, expected_state: str | None) -> str:
    """Extract ``code`` from the pasted ``msauth://...?code=...&state=...`` URL.

    Accepts the full URL, just the query string, or a Chrome console line
    ("Failed to launch 'msauth://...' because ..."). Raises WattsOnAuthError
    with a short reason ("no_code", "state_mismatch", "b2c_error").
    """
    text = (pasted or "").strip().strip("'\"<>")
    if "msauth://" in text:
        text = text[text.index("msauth://") :]
        for stop in ("'", '"', " ", "\n"):
            if stop in text:
                text = text.split(stop, 1)[0]
    query = urlparse(text).query if "?" in text else text.lstrip("?#")
    params = parse_qs(query)
    if params.get("error"):
        raise WattsOnAuthError("b2c_error")
    code = (params.get("code") or [""])[0].strip()
    if not code:
        raise WattsOnAuthError("no_code")
    state = (params.get("state") or [""])[0]
    if expected_state and state and state != expected_state:
        raise WattsOnAuthError("state_mismatch")
    return code


def _expires_at(body: dict[str, Any]) -> str | None:
    try:
        secs = int(body.get("refresh_token_expires_in"))
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat(timespec="seconds")


async def _token_request(session: aiohttp.ClientSession, form: dict[str, str]) -> dict[str, Any]:
    try:
        async with session.post(WATTS_TOKEN_URL, data=form, timeout=_TIMEOUT) as resp:
            try:
                body = await resp.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                body = {}
            if resp.status in (400, 401):
                # Do not echo the body: it can contain hints about the token.
                raise WattsOnAuthError(f"token endpoint refused ({resp.status})")
            if resp.status == 429:
                raise WattsOnRateLimited("token endpoint rate limited")
            if resp.status >= 400 or not isinstance(body, dict):
                raise WattsOnError(f"token endpoint HTTP {resp.status}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise WattsOnError(f"token endpoint unreachable: {type(err).__name__}") from err
    if not body.get("access_token") or not body.get("refresh_token"):
        raise WattsOnError("token endpoint returned no tokens")
    return body


async def async_exchange_code(
    session: aiohttp.ClientSession, code: str, verifier: str
) -> dict[str, Any]:
    """Authorization code -> {refresh_token, access_token, expires_in, refresh_expires_at}."""
    body = await _token_request(
        session,
        {
            "grant_type": "authorization_code",
            "client_id": WATTS_CLIENT_ID,
            "code": code,
            "redirect_uri": WATTS_REDIRECT_URI,
            "code_verifier": verifier,
            "scope": WATTS_SCOPE,
        },
    )
    body["refresh_expires_at"] = _expires_at(body)
    return body


# ---------------------------------------------------------------------------
# Helpers for the PascalCase / camelCase / short-name JSON
# ---------------------------------------------------------------------------
def ci_get(data: Any, *keys: str) -> Any:
    """First non-null value among ``keys`` (case-insensitive)."""
    if not isinstance(data, dict):
        return None
    lowered = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        val = lowered.get(key.lower())
        if val is not None:
            return val
    return None


def as_list(data: Any, *wrappers: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in (*wrappers, "items", "data", "values", "result"):
            found = ci_get(data, key)
            if isinstance(found, list):
                return [x for x in found if isinstance(x, dict)]
    return []


def walk_dicts(data: Any):
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from walk_dicts(value)
    elif isinstance(data, list):
        for value in data:
            yield from walk_dicts(value)


_HEAT_WORDS = ("districtheat", "district_heat", "district heat", "heating", "heat", "varme")
_WATER_WORDS = ("water", "vand")
_ELEC_WORDS = ("electric", "power", "elmåler", "electricity")


def classify_device(dev: dict[str, Any]) -> str | None:
    """'heat' | 'water' | 'electricity' | None, from type-like fields only."""
    text = " ".join(
        str(ci_get(dev, k) or "")
        for k in ("utilityType", "type", "deviceType", "meterType", "supplyType", "utility")
    ).lower()
    if not text.strip():
        return None
    if any(w in text for w in _HEAT_WORDS):
        return "heat"
    if any(w in text for w in _WATER_WORDS):
        return "water"
    if any(w in text for w in _ELEC_WORDS) or text.strip() in ("el", "electricity"):
        return "electricity"
    return None


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
class WattsOnClient:
    """Keeps a short-lived access token fresh from a rotating refresh token.

    The access token only lives in this object. Every new refresh token is
    handed to ``on_refresh_token(token, expires_at_iso_or_None)`` so the
    caller can persist it (B2C rotates it; losing the new one ends the
    session). Tokens are never logged.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str,
        *,
        on_refresh_token: Callable[[str, str | None], Awaitable[None] | None] | None = None,
        access_token: str | None = None,
        access_expires_in: int | None = None,
    ) -> None:
        self._session = session
        self._refresh_token = refresh_token
        self._on_refresh_token = on_refresh_token
        self._access_token = access_token
        self._access_expires = time.monotonic() + int(access_expires_in or 0) if access_token else 0.0
        self._lock = asyncio.Lock()
        self.user_id: str | None = None
        self.requests = 0

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def discard(self) -> None:
        """Forget the access token (the refresh token stays with the caller)."""
        self._access_token = None
        self._access_expires = 0.0

    async def _access(self) -> str:
        async with self._lock:
            if self._access_token and time.monotonic() < self._access_expires - 120:
                return self._access_token
            body = await _token_request(
                self._session,
                {
                    "grant_type": "refresh_token",
                    "client_id": WATTS_CLIENT_ID,
                    "refresh_token": self._refresh_token,
                    "scope": WATTS_SCOPE,
                },
            )
            self.requests += 1
            self._access_token = str(body["access_token"])
            self._access_expires = time.monotonic() + int(body.get("expires_in") or 3600)
            new_refresh = str(body.get("refresh_token") or "")
            if new_refresh and new_refresh != self._refresh_token:
                self._refresh_token = new_refresh
                if self._on_refresh_token is not None:
                    result = self._on_refresh_token(new_refresh, _expires_at(body))
                    if asyncio.iscoroutine(result):
                        await result
            return self._access_token

    async def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET ``API_BASE + path``. One retry with a fresh token on 401."""
        for attempt in (1, 2):
            token = await self._access()
            self.requests += 1
            try:
                async with self._session.get(
                    WATTS_API_BASE + path.lstrip("/"),
                    params=params,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        self._access_token = None
                        if attempt == 1:
                            continue
                        raise WattsOnAuthError("API rejected a fresh access token")
                    if resp.status == 403:
                        raise WattsOnAuthError("API refused access (403)")
                    if resp.status == 429:
                        raise WattsOnRateLimited("API rate limited (429)")
                    if resp.status in (400, 404, 405):
                        raise WattsOnNotFound(f"HTTP {resp.status}")
                    if resp.status == 204:
                        return []
                    if resp.status >= 400:
                        raise WattsOnError(f"API HTTP {resp.status}")
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                raise WattsOnError(f"API unreachable: {type(err).__name__}") from err
        raise WattsOnAuthError("API rejected a fresh access token")

    async def async_user_id(self) -> str:
        """Backend user id (it is not the token's sub/oid, so ask the API)."""
        if not self.user_id:
            me = await self.get("users/api/v3/User")
            uid = ci_get(me, "id", "userId")
            if not uid:
                raise WattsOnError("users/api/v3/User returned no id")
            self.user_id = str(uid)
        return self.user_id

    async def async_devices(self) -> list[dict[str, Any]]:
        """All devices across the user's locations, non-personal fields only."""
        user_id = await self.async_user_id()
        locations = as_list(
            await self.get(f"installations/api/v3/users/{user_id}/locations"), "locations"
        )
        found: dict[str, dict[str, Any]] = {}
        for loc in locations:
            loc_id = ci_get(loc, "id", "locationId")
            if not loc_id:
                continue
            detail = await self.get(f"provisioning/api/v1/locations/{loc_id}")
            for dev in walk_dicts(detail):
                dev_id = ci_get(dev, "deviceId")
                if dev_id is None and ci_get(dev, "utilityType", "deviceType", "meterType"):
                    dev_id = ci_get(dev, "id")
                if dev_id is None:
                    continue
                found.setdefault(
                    str(dev_id),
                    {
                        "id": str(dev_id),
                        "kind": classify_device(dev),
                        "type": str(
                            ci_get(dev, "utilityType", "deviceType", "meterType", "type") or ""
                        )[:40],
                        "unit": str(ci_get(dev, "unit", "unitOfMeasure") or "")[:16],
                        "location_id": str(loc_id),
                    },
                )
        return list(found.values())

    async def async_heat_consumptions(
        self,
        device_id: str,
        start: datetime,
        endpoint: str | None = None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        """Hourly heat intervals from ``start``: (endpoint_template, items, probe).

        ``endpoint`` (a template with ``{device_id}``) skips probing. The probe
        list holds only templates and HTTP outcomes, never data or ids.
        """
        stamp = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        candidates = [endpoint] if endpoint else list(HEAT_ENDPOINT_CANDIDATES)
        probe: list[dict[str, Any]] = []
        for template in candidates:
            path = template.replace("{device_id}", device_id).replace("<device_id>", device_id)
            try:
                # The app's /recent endpoints take newerThan; the others startDate.
                param = "newerThan" if path.rstrip("/").endswith("/recent") else "startDate"
                data = await self.get(path, {param: stamp})
            except WattsOnNotFound as err:
                probe.append({"endpoint": template, "result": str(err)})
                continue
            probe.append({"endpoint": template, "result": "ok"})
            return template, as_list(data, "consumptions"), probe
        raise WattsOnNotFound("no heat consumption endpoint answered")


# ---------------------------------------------------------------------------
# Parsing heat intervals (Aalborg: SD/ED/En/Vol/TI/TO/MQ verified; other shapes still use the same key lists)
# ---------------------------------------------------------------------------
START_KEYS = ("sd", "startDate", "start", "from", "dateFrom", "fromDate", "timestamp")
END_KEYS = ("ed", "endDate", "end", "to", "dateTo", "toDate")
ENERGY_KEYS = ("energy", "en", "heat", "heatEnergy", "energyConsumption", "kwh", "mwh", "gj")
VOLUME_KEYS = ("vol", "volume", "m3", "waterVolume")
FWD_KEYS = (
    "ft", "forwardTemperature", "flowTemperature", "supplyTemperature", "tempForward",
    "inletTemperature", "t1", "ti",
)
RET_KEYS = ("rt", "returnTemperature", "tempReturn", "outletTemperature", "t2", "to")
QUALITY_KEYS = ("mq", "measuredQuality", "quality")
GENERIC_KEYS = ("value", "consumption", "val")

_MEASURED_QUALITIES = frozenset(
    {"measured", "m", "a04", "actual", "validated", "valid", "ok", "final"}
)
_INVALID_QUALITIES = frozenset(
    {
        "missing",
        "invalid",
        "error",
        "nodata",
        "no_data",
        "no-data",
        "notavailable",
        "not_available",
        "unavailable",
        "deleted",
        "corrupt",
        "bad",
    }
)

_ENERGY_UNITS = {"kwh": 1.0, "mwh": 1000.0, "gj": 1 / 0.0036}


def energy_factor(unit: str | None) -> float | None:
    u = str(unit or "").strip().lower().replace(" ", "").replace("kilowatthour", "kwh")
    u = u.replace("megawatthour", "mwh").replace("gigajoule", "gj")
    return _ENERGY_UNITS.get(u)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        try:
            out = float(value.replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    if out != out or out < 0:  # NaN, or -1 meaning "no data"
        return None
    return out


def _temp(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and 0 < out < 150 else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class HeatParse:
    """Normalised heat intervals plus what we had to assume."""

    intervals: list[dict[str, Any]] = field(default_factory=list)
    keys_seen: list[str] = field(default_factory=list)
    energy_unit: str | None = None
    interval_hours: float | None = None
    skipped: dict[str, int] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    quality_seen: dict[str, int] = field(default_factory=dict)

    @property
    def has_energy(self) -> bool:
        return any(i.get("kwh") is not None for i in self.intervals)

    @property
    def has_volume(self) -> bool:
        return any(i.get("m3") is not None for i in self.intervals)

    @property
    def has_temps(self) -> bool:
        return any(i.get("t_ret") is not None or i.get("t_fwd") is not None for i in self.intervals)


def parse_heat_items(
    items: list[dict[str, Any]],
    unit_hint: str | None = None,
    unit_override: str | None = None,
) -> HeatParse:
    """Map raw interval dicts to {start, hours, kwh, m3, t_fwd, t_ret}.

    Rules (documented as assumptions where not verified):
      * explicit energy keys -> energy; ``vol`` -> m³ (verified for water);
      * only ``vol``/``value`` and the device unit is an energy unit -> energy
        ("vol_as_energy"/"value_as_energy");
      * unit: override > device unit > heuristic (median hourly < 0.05 -> MWh)
        > kWh ("energy_unit_assumed_*");
      * ``mq``/quality present and not "measured" -> skipped (as Novafos-V2);
      * negative numbers (-1 = no data) and temps outside 0-150 °C -> None.
    """
    out = HeatParse()
    keys: set[str] = set()
    measured_raw: list[dict[str, Any]] = []
    fallback_raw: list[dict[str, Any]] = []
    measured_assumptions: list[str] = []
    fallback_assumptions: list[str] = []
    quality_counts: dict[str, int] = {}
    fallback_skipped = 0
    fallback_no_data = 0
    invalid_quality_skipped = 0
    hint_factor = energy_factor(unit_hint)
    for item in items or []:
        if not isinstance(item, dict):
            continue
        keys.update(str(k) for k in item)
        start = _parse_dt(ci_get(item, *START_KEYS))
        if start is None:
            out.skipped["no_start"] = out.skipped.get("no_start", 0) + 1
            continue
        quality = ci_get(item, *QUALITY_KEYS)
        if quality is None:
            is_measured = True
        else:
            q_raw = str(quality).strip()
            q_label = q_raw[:32] if q_raw else "(empty)"
            quality_counts[q_label] = quality_counts.get(q_label, 0) + 1
            q_low = q_raw.lower()
            if not q_low or q_low in _MEASURED_QUALITIES:
                is_measured = True
            elif q_low in _INVALID_QUALITIES:
                invalid_quality_skipped += 1
                continue
            else:
                is_measured = False
        end = _parse_dt(ci_get(item, *END_KEYS))
        hours = (end - start).total_seconds() / 3600 if end and end > start else 1.0
        energy = _num(ci_get(item, *ENERGY_KEYS))
        volume = _num(ci_get(item, *VOLUME_KEYS))
        generic = _num(ci_get(item, *GENERIC_KEYS))
        has_energy_key = ci_get(item, *ENERGY_KEYS) is not None
        target_assumptions = measured_assumptions if is_measured else fallback_assumptions
        if not has_energy_key and hint_factor is not None:
            if ci_get(item, *VOLUME_KEYS) is not None:
                energy, volume = volume, None
                if "vol_as_energy" not in target_assumptions:
                    target_assumptions.append("vol_as_energy")
            elif generic is not None:
                energy = generic
                if "value_as_energy" not in target_assumptions:
                    target_assumptions.append("value_as_energy")
        rec = {
            "start": start,
            "hours": round(hours, 3),
            "energy": energy,
            "m3": volume,
            "t_fwd": _temp(ci_get(item, *FWD_KEYS)),
            "t_ret": _temp(ci_get(item, *RET_KEYS)),
        }
        if all(v is None for v in (energy, volume)) and rec["t_ret"] is None:
            if is_measured:
                out.skipped["no_data"] = out.skipped.get("no_data", 0) + 1
            else:
                fallback_no_data += 1
            continue
        if is_measured:
            measured_raw.append(rec)
        else:
            fallback_raw.append(rec)
            fallback_skipped += 1

    out.quality_seen = dict(
        sorted(quality_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    )
    if measured_raw:
        raw = measured_raw
        out.assumptions.extend(measured_assumptions)
        not_measured = invalid_quality_skipped + fallback_skipped
        if not_measured:
            out.skipped["not_measured"] = not_measured
    elif fallback_raw:
        raw = fallback_raw
        out.assumptions.extend(fallback_assumptions)
        if "quality_fallback" not in out.assumptions:
            out.assumptions.append("quality_fallback")
        if invalid_quality_skipped:
            out.skipped["not_measured"] = invalid_quality_skipped
        if fallback_no_data:
            out.skipped["no_data"] = out.skipped.get("no_data", 0) + fallback_no_data
    else:
        raw = []
        not_measured = invalid_quality_skipped + fallback_skipped
        if not_measured:
            out.skipped["not_measured"] = not_measured

    out.keys_seen = sorted(keys)[:40]
    factor: float | None = None
    if unit_override and unit_override != "auto":
        factor = energy_factor(unit_override)
        out.energy_unit = unit_override
    elif hint_factor is not None:
        factor = hint_factor
        out.energy_unit = str(unit_hint)
    energies = [r["energy"] for r in raw if r["energy"]]
    if factor is None and energies:
        per_hour = [r["energy"] / max(r["hours"], 1e-6) for r in raw if r["energy"]]
        if statistics.median(per_hour) < 0.05:
            factor, out.energy_unit = 1000.0, "MWh"
            out.assumptions.append("energy_unit_assumed_mwh")
        else:
            factor, out.energy_unit = 1.0, "kWh"
            out.assumptions.append("energy_unit_assumed_kwh")
    factor = factor or 1.0
    for r in raw:
        out.intervals.append(
            {
                "start": r["start"].isoformat(),
                "hours": r["hours"],
                "kwh": round(r["energy"] * factor, 4) if r["energy"] is not None else None,
                "m3": round(r["m3"], 4) if r["m3"] is not None else None,
                "t_fwd": r["t_fwd"],
                "t_ret": r["t_ret"],
            }
        )
    out.intervals.sort(key=lambda i: i["start"])
    if raw:
        out.interval_hours = statistics.median(r["hours"] for r in raw)
    return out
