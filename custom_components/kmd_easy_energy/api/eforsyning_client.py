"""Async client for E|Forsyning (eforsyning.dk / dff-edb.dk supplier API).

DERIVED WORK NOTICE
This file is derived from kpoppel/homeassistant-eforsyning
(https://github.com/kpoppel/homeassistant-eforsyning, file
custom_components/eforsyning/pyeforsyning/eforsyning.py, upstream commit
1e982e1), Copyright kpoppel and contributors, licensed under the Apache
License, Version 2.0. A copy of that license is shipped next to this file as
LICENSE-eforsyning-Apache-2.0.txt (also http://www.apache.org/licenses/LICENSE-2.0).

Changes were made: this is an independent async (aiohttp) reimplementation
of the protocol handling, not a verbatim copy. Endpoint paths, request field
names and response field names necessarily follow the reference client.
Further changes: no credentials/tokens/URLs with tokens in logs, normalised
output (kWh, m³, °C per reading day; unknown values are None instead of 0),
January year-marker fallback, explicit login vs. transport error types, and
no personal installation data (address, meter or customer number) returned.
Modifications Copyright (c) 2026 Daniel / DKAnord, also available under the
Apache License, Version 2.0 for this file.

Protocol (as handled by kpoppel's client + euser/user support from E|Forsyning SPA):
  1. GET  https://eforsyning.dk/umbraco/dff/dffapi/GetVaerkSettings?forsyningid=<id>
     -> {"AppServerUri": "https://<server>/<vaerk>/", ...}  (public, no login)
  2. GET  <AppServerUri>system/getsecuritytoken/project/app/<kind>/<user>
     -> {"Token": "<server token>"}
     where <kind> is:
       - "euser"    if username contains '@' (lowercased e-mail)
       - "consumer" if username starts with an optional +/- and digit (forbrugernummer)
       - "user"     otherwise (uppercased user ID)
  3. access = md5( md5(password) + Token )   (hex digests)
  4. GET  <AppServerUri>system/login/project/app/<kind>/<user>/installation/1/id/<access>
     -> {"Result": 1} on success
  5. GET  api/getebrugerinfo?id=<access>          -> {"id": .., "indflyttet": "dd-mm-yyyy"}
     POST api/FindInstallationer?id=<access>      -> {"Installationer": [...]}
     POST api/getaktuelaarsmaerke?id=<access>     -> {"aarsmaerke": 2026, ...}
     POST api/getforbrug?id=<access>&unr=<EjendomNr>&anr=..&inr=..  -> ForbrugsLinjer / IaltLinje
     (uses installation's EjendomNr from FindInstallationer for euser/user)
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import logging
import re
import secrets
import string
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

EFORSYNING_BASE_URL = "https://eforsyning.dk/"
_SETTINGS_PATH = "umbraco/dff/dffapi/GetVaerkSettings?forsyningid="
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_ID_CHARS = string.digits + string.ascii_uppercase
# Values above this are treated as a missing decimal comma (seen in the wild).
_TEMP_SANITY_MAX = 150.0
_MONTH_KEYS = ("Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec")


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_UMBRACO_PREFIX_RE = re.compile(r"indstillinger\.umbraco\s*=\s*")
_FORSYNING_ID_RE = re.compile(
    r"forsyning[Ii]d[\"':=\s]+([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})"
)
_SELECT_PLANT_RE = re.compile(
    r"selectPlant\(\s*['\"]([^'\"]+)['\"]\s*\)[^>]*>\s*<h5>(.*?)</h5>",
    re.IGNORECASE | re.DOTALL,
)
_EXCLUDED_DIRECTORY_SLUGS = {"albertslund", "htf"}
_NON_FILE_EXT_RE = re.compile(r"\.(?:php|html?|aspx)$", re.IGNORECASE)
_CONSUMER_ID_RE = re.compile(r"^[+-]?\d")


def normalize_eforsyning_login(username: str) -> tuple[str, str]:
    """Classify and normalize an E|Forsyning login identifier.

    Matches E|Forsyning's Angular SPA (fixCasing + getSecurityTokenUrl):
    - Contains '@': ('euser', lowercased)
    - Starts with digit (JS !isNaN(parseInt(x, 10))): ('consumer', uppercased)
    - Otherwise: ('user', uppercased)
    """
    raw = str(username or "").strip()
    if not raw:
        return ("consumer", "")
    if "@" in raw:
        return ("euser", raw.lower())
    norm = raw.upper()
    if _CONSUMER_ID_RE.match(norm):
        return ("consumer", norm)
    return ("user", norm)


def installation_option_id(inst: dict[str, Any], include_ejendom: bool = False) -> str:
    """Stable installation selector value (composite only when InstallationNr collides)."""
    inr = str(inst.get("InstallationNr") if inst.get("InstallationNr") is not None else 1).strip()
    if not include_ejendom:
        return inr
    ej = str(inst.get("EjendomNr") if inst.get("EjendomNr") is not None else "").strip()
    anr = str(inst.get("AktivNr") if inst.get("AktivNr") is not None else 1).strip()
    return f"{ej}:{anr}:{inr}" if ej else inr


def is_uuid(value: str) -> bool:
    """Return True if value is a standard UUID string."""
    return bool(_UUID_RE.match(str(value or "").strip()))


def _canonical_url_key(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}"


def normalize_eforsyning_url(value: str) -> str | None:
    """Normalize a slug or HTTPS portal URL; reject localhost, IPs, and non-HTTPS."""
    raw = str(value or "").strip()
    if not raw:
        return None
    slug_candidate = raw.strip("/")
    if "/" not in slug_candidate and "." not in slug_candidate and ":" not in slug_candidate:
        if _SLUG_RE.match(slug_candidate):
            return f"https://eforsyning.dk/{slug_candidate}/"
        return None
    lower = raw.lower()
    if lower.startswith(("eforsyning.dk/", "www.eforsyning.dk/")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        return None
    if parsed.username or parsed.password:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in (None, 443):
        return None
    host = (parsed.hostname or "").strip().lower()
    if not host or "." not in host:
        return None
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    path = parsed.path or "/"
    if not path.endswith("/") and not _NON_FILE_EXT_RE.search(path):
        path = f"{path}/"
    netloc = host if port is None else f"{host}:{port}"
    return urlunparse(("https", netloc, path, "", "", ""))


def parse_umbraco_suppliers(html_text: str, page_url: str = "") -> list[dict[str, str]]:
    """Extract E|Forsyning supplier entries from a portal page's HTML."""
    text = str(html_text or "")
    suppliers: list[dict[str, str]] = []
    seen: set[str] = set()

    match = _UMBRACO_PREFIX_RE.search(text)
    if match:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, match.end())
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            default_name = str(obj.get("firmaNavn") or "").strip()
            for entry in obj.get("eforsyninger") or []:
                if not isinstance(entry, dict):
                    continue
                fid = str(entry.get("forsyningId") or "").strip()
                if not is_uuid(fid):
                    continue
                fid_up = fid.upper()
                if fid_up in seen:
                    continue
                seen.add(fid_up)
                firma = entry.get("firmaInfo") if isinstance(entry.get("firmaInfo"), dict) else {}
                suppliers.append(
                    {
                        "supplier_id": fid_up,
                        "name": str(firma.get("firmaNavn") or default_name).strip(),
                        "portal_url": str(entry.get("siteUrl") or page_url or "").strip(),
                        "app_server_url": str(entry.get("appServerUrl") or "").strip(),
                    }
                )

    if len(suppliers) > 1 and page_url:
        target_key = _canonical_url_key(page_url)
        matched = [
            s for s in suppliers if s.get("portal_url") and _canonical_url_key(s["portal_url"]) == target_key
        ]
        if len(matched) == 1:
            return matched

    if not suppliers:
        for fid in _FORSYNING_ID_RE.findall(text):
            fid_up = fid.upper()
            if fid_up in seen:
                continue
            seen.add(fid_up)
            suppliers.append(
                {
                    "supplier_id": fid_up,
                    "name": "",
                    "portal_url": str(page_url or "").strip(),
                    "app_server_url": "",
                }
            )
    return suppliers


def parse_eforsyning_directory(html_text: str) -> list[dict[str, str]]:
    """Parse district-heating utilities from the eforsyning.dk directory page."""
    entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for raw_url, raw_name in _SELECT_PLANT_RE.findall(str(html_text or "")):
        norm_url = normalize_eforsyning_url(raw_url)
        if not norm_url or norm_url in seen_urls:
            continue
        parsed = urlparse(norm_url)
        slug = parsed.path.strip("/").lower()
        if (parsed.hostname or "").lower() in ("eforsyning.dk", "www.eforsyning.dk") and slug in _EXCLUDED_DIRECTORY_SLUGS:
            continue
        name = " ".join(html.unescape(raw_name).split()).strip()
        if not name:
            continue
        low = name.lower()
        if "vand" in low and not any(kw in low for kw in ("varme", "fjernvarme", "kraftvarme")):
            continue
        seen_urls.add(norm_url)
        entries.append({"name": name, "portal_url": norm_url})
    entries.sort(key=lambda item: item["name"].casefold())
    return entries


async def async_lookup_vaerk_settings(
    session: aiohttp.ClientSession,
    supplier_id: str,
    base_url: str = EFORSYNING_BASE_URL,
) -> dict[str, str]:
    """Fetch public GetVaerkSettings metadata for a supplier UUID."""
    fid = str(supplier_id or "").strip()
    if not is_uuid(fid):
        raise EforsyningError("Ugyldigt forsyningid")
    headers = {
        "Accept": "application/json",
        "User-Agent": "HomeAssistant kmd_easy_energy (E|Forsyning backend)",
    }
    try:
        async with session.get(
            f"{base_url}{_SETTINGS_PATH}{fid}", headers=headers, timeout=_TIMEOUT
        ) as resp:
            if resp.status >= 400:
                raise EforsyningError(f"E|Forsyning GetVaerkSettings: HTTP {resp.status}")
            try:
                data = await resp.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError) as err:
                raise EforsyningError("E|Forsyning GetVaerkSettings: ugyldigt svar") from err
    except aiohttp.ClientError as err:
        raise EforsyningError(f"E|Forsyning GetVaerkSettings: {type(err).__name__}") from err

    app_uri = str((data or {}).get("AppServerUri") or "").strip()
    if not app_uri.startswith("https://"):
        raise EforsyningError("E|Forsyning: ukendt forsyningid (ingen AppServerUri)")
    firma = (data or {}).get("FirmaInfo")
    fi = firma if isinstance(firma, dict) else {}
    return {
        "supplier_id": fid.upper(),
        "app_server_url": app_uri if app_uri.endswith("/") else f"{app_uri}/",
        "portal_url": str((data or {}).get("EforsyningUri") or "").strip(),
        "name": str(fi.get("firmaNavn") or "").strip(),
        "city": str(fi.get("by") or "").strip(),
    }


async def async_resolve_supplier_input(
    session: aiohttp.ClientSession,
    raw_input: str,
    base_url: str = EFORSYNING_BASE_URL,
) -> list[dict[str, str]]:
    """Resolve a UUID, slug, or portal URL into validated E|Forsyning supplier dicts."""
    text = str(raw_input or "").strip()
    if not text:
        raise EforsyningError("Tomt forsyningid/URL")
    if is_uuid(text):
        return [await async_lookup_vaerk_settings(session, text, base_url=base_url)]
    url = normalize_eforsyning_url(text)
    if not url:
        raise EforsyningError("Ugyldig E|Forsyning-URL eller forsyningid")
    headers = {"User-Agent": "HomeAssistant kmd_easy_energy (E|Forsyning backend)"}
    try:
        async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
            if resp.status >= 400:
                raise EforsyningError(f"E|Forsyning portalopslag: HTTP {resp.status}")
            page_html = await resp.text()
            final_url = str(getattr(resp, "url", "") or url)
    except aiohttp.ClientError as err:
        raise EforsyningError(f"E|Forsyning portalopslag: {type(err).__name__}") from err

    candidates = parse_umbraco_suppliers(page_html, page_url=final_url)
    if not candidates:
        raise EforsyningError("Fandt intet forsyningid på siden")
    if len(candidates) == 1:
        cand = candidates[0]
        settings = await async_lookup_vaerk_settings(
            session, cand["supplier_id"], base_url=base_url
        )
        return [
            {
                "supplier_id": settings["supplier_id"],
                "app_server_url": settings["app_server_url"],
                "portal_url": settings["portal_url"] or cand.get("portal_url") or url,
                "name": settings["name"] or cand.get("name") or "",
                "city": settings["city"],
            }
        ]
    return candidates


async def async_fetch_eforsyning_directory(
    session: aiohttp.ClientSession, base_url: str = EFORSYNING_BASE_URL
) -> list[dict[str, str]]:
    """Fetch and parse the public E|Forsyning utility directory."""
    headers = {"User-Agent": "HomeAssistant kmd_easy_energy (E|Forsyning backend)"}
    try:
        async with session.get(base_url, headers=headers, timeout=_TIMEOUT) as resp:
            if resp.status >= 400:
                raise EforsyningError(f"E|Forsyning værksliste: HTTP {resp.status}")
            page_html = await resp.text()
    except aiohttp.ClientError as err:
        raise EforsyningError(f"E|Forsyning værksliste: {type(err).__name__}") from err

    directory = parse_eforsyning_directory(page_html)
    if not directory:
        raise EforsyningError("E|Forsyning værksliste var tom")
    return directory


class EforsyningError(RuntimeError):
    """Transport / unexpected-response error from E|Forsyning."""


class EforsyningLoginError(EforsyningError):
    """E|Forsyning rejected the forbrugernummer / webpinkode (a real login failure)."""


def access_token_for(password: str, server_token: str) -> str:
    """md5(md5(webpinkode) + server token), both as lowercase hex."""
    hashed = hashlib.md5(password.encode("utf-8")).hexdigest()  # noqa: S324 - protocol
    return hashlib.md5((hashed + server_token).encode("utf-8")).hexdigest()  # noqa: S324


def parse_number(value: Any, filter_above: float | None = None) -> float | None:
    """Parse a Danish formatted number ("1.234,56" -> 1234.56).

    Returns None for empty/unparseable values (unknown, not 0). Values above
    ``filter_above`` are also treated as unknown.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            val = float(text.replace(".", "").replace(",", "."))
        except ValueError:
            return None
    if filter_above is not None and val > filter_above:
        return None
    return val


def _energy_factor(unit: str | None) -> float | None:
    unit = (unit or "").strip().lower()
    if unit == "mwh":
        return 1000.0
    if unit == "kwh":
        return 1.0
    if unit == "gj":
        return 1.0 / 0.0036
    return None


def _parse_dmy(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value).strip(), "%d-%m-%Y").date()
    except (TypeError, ValueError):
        return None


def parse_readings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a getforbrug (daily) response into one row per reading.

    Each ``ForbrugsLinjer.TForbrugsLinje`` line covers FraDato..TilDato. The
    consumption is attributed to the day before TilDato (for a normal daily
    line that is FraDato). Lines spanning several days are kept as one row
    with ``days`` > 1 so callers can decide how to spread them.
    """
    lines = ((result or {}).get("ForbrugsLinjer") or {}).get("TForbrugsLinje") or []
    if isinstance(lines, dict):
        lines = [lines]
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        d_from = _parse_dmy(line.get("FraDatoStr"))
        d_to = _parse_dmy(line.get("TilDatoStr"))
        if d_from is None or d_to is None:
            continue
        span = max(1, (d_to - d_from).days)
        kwh: float | None = None
        m3: float | None = None
        kwh_end: float | None = None
        m3_end: float | None = None
        for reading in line.get("TForbrugsTaellevaerk") or []:
            if not isinstance(reading, dict):
                continue
            index = str(reading.get("IndexNavn") or "").upper()
            if index == "ENG1":
                factor = _energy_factor(reading.get("Enhed_Txt"))
                used = parse_number(reading.get("Forbrug"))
                end = parse_number(reading.get("Slut"))
                if factor is not None and used is not None:
                    kwh = round(used * factor, 3)
                if factor is not None and end is not None:
                    kwh_end = round(end * factor, 3)
            elif index == "M3":
                m3 = parse_number(reading.get("Forbrug"))
                m3_end = parse_number(reading.get("Slut"))
        rows.append(
            {
                "date": (d_to - timedelta(days=1)).isoformat() if span == 1 else d_from.isoformat(),
                "date_from": d_from.isoformat(),
                "date_to": d_to.isoformat(),
                "days": span,
                "kwh": kwh,
                "m3": round(m3, 4) if m3 is not None else None,
                "kwh_meter": kwh_end,
                "m3_meter": m3_end,
                "temp_forward": parse_number(line.get("Tempfrem"), _TEMP_SANITY_MAX),
                "temp_return": parse_number(line.get("TempRetur"), _TEMP_SANITY_MAX),
                "temp_expected_return": parse_number(line.get("Forv_Retur"), _TEMP_SANITY_MAX),
                "cooling": parse_number(line.get("Afkoling"), _TEMP_SANITY_MAX),
            }
        )
    return rows


def parse_monthly_temperatures(result: dict[str, Any]) -> dict[str, Any]:
    """Extract server-computed monthly/annual temperatures from an afMaanedsvis response."""
    if not response_has_lines(result):
        return {}
    lines = ((result or {}).get("ForbrugsLinjer") or {}).get("TForbrugsLinje") or []
    if isinstance(lines, dict):
        lines = [lines]

    parsed_rows: list[tuple[int, int, dict[str, Any]]] = []
    ym_counts: dict[tuple[int, int], int] = {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        d_from = _parse_dmy(line.get("FraDatoStr"))
        d_to = _parse_dmy(line.get("TilDatoStr"))
        if d_from is None or d_to is None:
            continue
        span = (d_to - d_from).days
        if not (1 <= span <= 35):
            continue
        if span >= 2:
            mid = d_from + timedelta(days=span // 2)
            ym = (mid.year, mid.month)
        elif d_from.day >= 28 and d_to.day == 1:
            ym = (d_to.year, d_to.month)
        else:
            ym = (d_from.year, d_from.month)
        ym_counts[ym] = ym_counts.get(ym, 0) + 1
        parsed_rows.append((ym[0], ym[1], line))

    if not parsed_rows or any(cnt > 1 for cnt in ym_counts.values()):
        return {}

    def _extract_temps(src: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for dst_key, src_key in (
            ("return", "TempRetur"),
            ("forward", "Tempfrem"),
            ("expected_return", "Forv_Retur"),
        ):
            val = parse_number(src.get(src_key), _TEMP_SANITY_MAX)
            if val is not None and val > 0:
                out[dst_key] = round(val, 2)
        return out

    monthly: dict[str, dict[str, dict[str, float]]] = {}
    for yr, mo, line in parsed_rows:
        temps = _extract_temps(line)
        if not temps:
            continue
        m_key = _MONTH_KEYS[mo - 1]
        y_bucket = monthly.setdefault(str(yr), {})
        for kind, val in temps.items():
            y_bucket.setdefault(kind, {})[m_key] = val

    annual: dict[str, dict[str, float]] = {}
    ialt = (result or {}).get("IaltLinje")
    if isinstance(ialt, dict):
        i_from = _parse_dmy(ialt.get("FraDatoStr"))
        i_to = _parse_dmy(ialt.get("TilDatoStr"))
        if (
            i_from is not None
            and i_to is not None
            and i_to.year >= i_from.year
            and i_from in (date(i_to.year, 1, 1), date(i_to.year - 1, 12, 31))
        ):
            a_temps = _extract_temps(ialt)
            if a_temps:
                annual[str(i_to.year)] = a_temps

    out: dict[str, Any] = {}
    if monthly:
        out["monthly"] = monthly
    if annual:
        out["annual"] = annual
    return out


def response_has_lines(result: Any) -> bool:
    """False for the documented "no data" shapes (error text or zero lines)."""
    if not isinstance(result, dict) or "response" in result:
        return False
    fl = result.get("ForbrugsLinjer") or {}
    if str(fl.get("AntLinjer", "")).strip() == "0":
        return False
    return bool(fl.get("TForbrugsLinje"))


class EforsyningClient:
    """One-sync E|Forsyning client. Credentials live only in this object."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        supplier_id: str,
        installation_id: str | None = None,
        base_url: str = EFORSYNING_BASE_URL,
    ) -> None:
        self._session = session
        self._login_kind, self._login_id = normalize_eforsyning_login(username)
        self._username = self._login_id
        self._password = str(password)
        self._supplier_id = str(supplier_id).strip()
        self._configured_installation = str(installation_id).strip() if installation_id else None
        self._base_url = base_url
        self._api: str = ""
        self._access: str = ""
        self._session_id = self._rand_id()
        self.installation: dict[str, Any] | None = None
        self.installations: list[dict[str, Any]] = []
        self.moved_in: date | None = None
        self.year_marker: dict[str, Any] = {}
        self.vaerk_settings: dict[str, Any] = {}

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _rand_id() -> str:
        return "".join(secrets.choice(_ID_CHARS) for _ in range(8))

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Session-ID": self._session_id,
            "X-Correlation-ID": self._rand_id(),
            "User-Agent": "HomeAssistant kmd_easy_energy (E|Forsyning backend)",
        }

    async def _request(
        self, method: str, url: str, body: dict[str, Any] | None = None, what: str = ""
    ) -> Any:
        kwargs: dict[str, Any] = {"headers": self._headers(), "timeout": _TIMEOUT}
        if body is not None:
            # Same wire format as the reference client: JSON text, no Content-Type.
            kwargs["data"] = json.dumps(body).encode("utf-8")
            kwargs["skip_auto_headers"] = ("Content-Type",)
        try:
            async with self._session.request(method, url, **kwargs) as resp:
                if resp.status in (401, 403):
                    raise EforsyningLoginError(f"E|Forsyning afviste login (HTTP {resp.status})")
                if resp.status >= 400:
                    raise EforsyningError(f"E|Forsyning {what or 'API'}: HTTP {resp.status}")
                try:
                    return await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise EforsyningError(f"E|Forsyning {what or 'API'}: ugyldigt svar") from err
        except aiohttp.ClientError as err:
            raise EforsyningError(f"E|Forsyning {what or 'API'}: {type(err).__name__}") from err

    def _api_url(self, path: str) -> str:
        # The access token is part of the URL: never log the full URL.
        return f"{self._api}{path}{self._access}"

    def _ejendom_nr(self) -> str:
        if self._login_kind == "consumer":
            return self._login_id
        inst = self.installation or {}
        for key in ("EjendomNr", "Ejendomnr", "ForbrugerNr"):
            val = inst.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        raise EforsyningError("E|Forsyning returnerede intet ejendomsnummer for installationen")

    def _consumer_query(self) -> str:
        inst = self.installation or {}
        ej = quote(self._ejendom_nr(), safe="")
        return (
            f"&unr={ej}&anr={inst.get('AktivNr', 1)}"
            f"&inr={inst.get('InstallationNr', 1)}"
        )

    # -- login -----------------------------------------------------------
    async def async_get_app_server(self) -> str:
        """Public lookup of the supplier API server (no credentials)."""
        data = await self._request(
            "GET", f"{self._base_url}{_SETTINGS_PATH}{self._supplier_id}", what="GetVaerkSettings"
        )
        self.vaerk_settings = dict(data or {})
        uri = str((data or {}).get("AppServerUri") or "").strip()
        if not uri.startswith("https://"):
            raise EforsyningError("E|Forsyning: ukendt forsyningid (ingen AppServerUri)")
        self._api = uri if uri.endswith("/") else uri + "/"
        return self._api

    async def async_login(self) -> None:
        if not self._login_id or not self._password:
            raise EforsyningLoginError("Forbrugernummer/e-mail og kode skal udfyldes")
        if not self._api:
            await self.async_get_app_server()
        encoded_user = quote(self._login_id, safe="@._+-")
        tok = await self._request(
            "GET",
            f"{self._api}system/getsecuritytoken/project/app/{self._login_kind}/{encoded_user}",
            what="getsecuritytoken",
        )
        server_token = str((tok or {}).get("Token") or "")
        if not server_token:
            raise EforsyningLoginError("E|Forsyning afviste forbrugernummer/e-mail")
        self._access = access_token_for(self._password, server_token)
        res = await self._request(
            "GET",
            f"{self._api}system/login/project/app/{self._login_kind}/{encoded_user}/installation/1/id/{self._access}",
            what="login",
        )
        if (res or {}).get("Result") != 1:
            self._access = ""
            raise EforsyningLoginError("E|Forsyning afviste forbrugernummer/e-mail eller kode")

    def discard_credentials(self) -> None:
        self._access = ""
        self._password = ""

    # -- data ------------------------------------------------------------
    async def async_get_installations(self) -> list[dict[str, Any]]:
        info = await self._request("GET", self._api_url("api/getebrugerinfo?id="), what="ebrugerinfo")
        self.moved_in = _parse_dmy((info or {}).get("indflyttet"))
        body = {
            "Soegetekst": "",
            "Skip": "0",
            "Take": "10000",
            "EBrugerId": (info or {}).get("id"),
            "Huskeliste": "null",
            "MedtagTilknyttede": "true",
        }
        res = await self._request(
            "POST", self._api_url("api/FindInstallationer?id="), body, what="FindInstallationer"
        )
        installs = [i for i in ((res or {}).get("Installationer") or []) if isinstance(i, dict)]
        if not installs:
            raise EforsyningError("E|Forsyning returnerede ingen installationer")
        self.installations = installs
        chosen = installs[0]
        if self._configured_installation:
            chosen = next(
                (
                    i
                    for i in installs
                    if installation_option_id(i, include_ejendom=True)
                    == self._configured_installation
                    or (
                        i.get("InstallationNr") is not None
                        and str(i.get("InstallationNr")) == self._configured_installation
                    )
                ),
                chosen,
            )
        self.installation = chosen
        return installs

    async def async_get_year_marker(self) -> dict[str, Any]:
        res = await self._request(
            "POST", self._api_url("api/getaktuelaarsmaerke?id="), {}, what="aarsmaerke"
        )
        self.year_marker = dict(res or {})
        return self.year_marker

    async def _async_get_forbrug(self, year: int, flt: str) -> dict[str, Any]:
        inst = self.installation or {}
        body = {
            "Ejendomnr": self._ejendom_nr(),
            "AktivNr": str(inst.get("AktivNr", 1)),
            "I_Nr": str(inst.get("InstallationNr", 1)),
            "AarsMaerke": year,
            "ForbrugsAfgraensning_FraDato": "0",
            "ForbrugsAfgraensning_TilDato": "0",
            "ForbrugsAfgraensning_FraAflaesning": "0",
            "ForbrugsAfgraensning_TilAflaesning": "2",
            "ForbrugsAfgraensning_MedtagMellemliggendeMellemaflas": "true",
            "Optioner": "foBestemtBeboer, foSkabDetaljer, foMedtagWebAflaes",
            "AHoejDetail": "false",
            "Aflaesningsfilter": flt,
            "AflaesningsFilterDag": "ULTIMO",
            "AflaesningsUdjaevning": "true",
            "SletFiltreredeAflaesninger": "true",
            "MedForventetForbrug": "true",
            "OmregnForbrugTilAktuelleEnhed": "true",
        }
        url = f"{self._api}api/getforbrug?id={self._access}{self._consumer_query()}"
        return await self._request("POST", url, body, what="getforbrug")

    async def async_get_daily(self, year: int) -> dict[str, Any]:
        """Daily readings (non-averaged temps) for one supplier billing year."""
        return await self._async_get_forbrug(year, "afDagsvis")

    async def async_get_monthly(self, year: int) -> dict[str, Any]:
        """Monthly readings (server-computed ENG2/TV2 temps) for one billing year."""
        return await self._async_get_forbrug(year, "afMaanedsvis")

    async def async_fetch(self, today: date, years_back: int = 1) -> dict[str, Any]:
        """Login and fetch daily readings for the current (+ previous) billing year."""
        await self.async_login()
        await self.async_get_installations()
        self._ejendom_nr()
        marker = await self.async_get_year_marker()
        try:
            latest = int(marker.get("aarsmaerke"))
        except (TypeError, ValueError):
            latest = today.year
        years: list[int] = [latest - n for n in range(years_back, -1, -1)]
        # January: the year marker may not have moved yet; try the new year too.
        if today.year > latest and today.year not in years:
            years.append(today.year)
        if self.moved_in:
            years = [y for y in years if y >= self.moved_in.year - 1] or [latest]
        readings: list[dict[str, Any]] = []
        fetched: list[int] = []
        monthly_temps: dict[str, dict[str, Any]] = {"monthly": {}, "annual": {}}
        for year in years:
            try:
                raw = await self.async_get_daily(year)
            except EforsyningLoginError:
                raise
            except EforsyningError as err:
                _LOGGER.debug("E|Forsyning year %s not available: %s", year, err)
                continue
            if not response_has_lines(raw):
                continue
            readings.extend(parse_readings(raw))
            fetched.append(year)
            try:
                raw_monthly = await self.async_get_monthly(year)
            except EforsyningLoginError:
                raise
            except EforsyningError as err:
                _LOGGER.debug("E|Forsyning monthly %s not available: %s", year, err)
                raw_monthly = None
            if raw_monthly is not None:
                mt = parse_monthly_temperatures(raw_monthly)
                for yr_s, kinds in (mt.get("monthly") or {}).items():
                    dst_yr = monthly_temps["monthly"].setdefault(yr_s, {})
                    for kind, m_map in kinds.items():
                        dst_yr.setdefault(kind, {}).update(m_map)
                for yr_s, a_map in (mt.get("annual") or {}).items():
                    monthly_temps["annual"].setdefault(yr_s, {}).update(a_map)
        inst = self.installation or {}
        out: dict[str, Any] = {
            "readings": readings,
            "years": fetched,
            "year_marker": {
                k: marker.get(k) for k in ("aarsmaerke", "aarsmaerke_start", "aarsmaerke_slut")
            },
            # Only non-identifying installation facts (no address, meter or customer no.).
            "installation": {
                "meter_type": inst.get("Målertype") or inst.get("Maalertype"),
                "installation_count": len(self.installations),
            },
        }
        compact_mt = {k: v for k, v in monthly_temps.items() if v}
        if compact_mt:
            out["monthly_temps"] = compact_mt
        return out
