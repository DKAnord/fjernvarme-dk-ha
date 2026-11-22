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

Protocol (as handled by kpoppel's client):
  1. GET  https://eforsyning.dk/umbraco/dff/dffapi/GetVaerkSettings?forsyningid=<id>
     -> {"AppServerUri": "https://<server>/<vaerk>/", ...}  (public, no login)
  2. GET  <AppServerUri>system/getsecuritytoken/project/app/consumer/<forbrugernr>
     -> {"Token": "<server token>"}
  3. access = md5( md5(webpinkode) + Token )   (hex digests)
  4. GET  <AppServerUri>system/login/project/app/consumer/<forbrugernr>/installation/1/id/<access>
     -> {"Result": 1} on success
  5. GET  api/getebrugerinfo?id=<access>          -> {"id": .., "indflyttet": "dd-mm-yyyy"}
     POST api/FindInstallationer?id=<access>      -> {"Installationer": [...]}
     POST api/getaktuelaarsmaerke?id=<access>     -> {"aarsmaerke": 2026, ...}
     POST api/getforbrug?id=<access>&unr=..&anr=..&inr=..  -> ForbrugsLinjer / IaltLinje
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import string
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

EFORSYNING_BASE_URL = "https://eforsyning.dk/"
_SETTINGS_PATH = "umbraco/dff/dffapi/GetVaerkSettings?forsyningid="
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_ID_CHARS = string.digits + string.ascii_uppercase
# Values above this are treated as a missing decimal comma (seen in the wild).
_TEMP_SANITY_MAX = 150.0


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
        self._username = str(username).strip()
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

    def _consumer_query(self) -> str:
        inst = self.installation or {}
        return (
            f"&unr={self._username}&anr={inst.get('AktivNr', 1)}"
            f"&inr={inst.get('InstallationNr', 1)}"
        )

    # -- login -----------------------------------------------------------
    async def async_get_app_server(self) -> str:
        """Public lookup of the supplier API server (no credentials)."""
        data = await self._request(
            "GET", f"{self._base_url}{_SETTINGS_PATH}{self._supplier_id}", what="GetVaerkSettings"
        )
        uri = str((data or {}).get("AppServerUri") or "").strip()
        if not uri.startswith("https://"):
            raise EforsyningError("E|Forsyning: ukendt forsyningid (ingen AppServerUri)")
        self._api = uri if uri.endswith("/") else uri + "/"
        return self._api

    async def async_login(self) -> None:
        if not self._username or not self._password:
            raise EforsyningLoginError("Forbrugernummer og webpinkode skal udfyldes")
        if not self._api:
            await self.async_get_app_server()
        tok = await self._request(
            "GET",
            f"{self._api}system/getsecuritytoken/project/app/consumer/{self._username}",
            what="getsecuritytoken",
        )
        server_token = str((tok or {}).get("Token") or "")
        if not server_token:
            raise EforsyningLoginError("E|Forsyning afviste forbrugernummeret")
        self._access = access_token_for(self._password, server_token)
        res = await self._request(
            "GET",
            f"{self._api}system/login/project/app/consumer/{self._username}/installation/1/id/{self._access}",
            what="login",
        )
        if (res or {}).get("Result") != 1:
            self._access = ""
            raise EforsyningLoginError("E|Forsyning afviste forbrugernummer/webpinkode")

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
                (i for i in installs if str(i.get("InstallationNr")) == self._configured_installation),
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

    async def async_get_daily(self, year: int) -> dict[str, Any]:
        """Daily readings (non-averaged temps) for one supplier billing year."""
        inst = self.installation or {}
        body = {
            "Ejendomnr": self._username,
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
            "Aflaesningsfilter": "afDagsvis",
            "AflaesningsFilterDag": "ULTIMO",
            "AflaesningsUdjaevning": "true",
            "SletFiltreredeAflaesninger": "true",
            "MedForventetForbrug": "true",
            "OmregnForbrugTilAktuelleEnhed": "true",
        }
        url = f"{self._api}api/getforbrug?id={self._access}{self._consumer_query()}"
        return await self._request("POST", url, body, what="getforbrug")

    async def async_fetch(self, today: date, years_back: int = 1) -> dict[str, Any]:
        """Login and fetch daily readings for the current (+ previous) billing year."""
        await self.async_login()
        await self.async_get_installations()
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
        inst = self.installation or {}
        return {
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
