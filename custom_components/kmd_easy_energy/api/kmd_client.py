"""Thin async client for KMD Easy Energy plugin API (verified live endpoints)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Callable
from zoneinfo import ZoneInfo

import aiohttp

from ..const import KMD_API_BASE

_LOGGER = logging.getLogger(__name__)
DK_TZ = ZoneInfo("Europe/Copenhagen")


def _parse_iso_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (handling trailing 'Z') into a datetime."""
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _format_api_dt(dt: datetime) -> str:
    """Format aware datetimes in UTC ISO-8601, preserving naive date-only midnight."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return dt.strftime("%Y-%m-%dT00:00:00.000Z")


def _local_day_utc_bounds(day: datetime, tz: ZoneInfo = DK_TZ) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for a calendar day in local Danish time."""
    local_date = day.astimezone(tz).date() if day.tzinfo else day.date()
    next_date = local_date + timedelta(days=1)
    start_local = datetime(local_date.year, local_date.month, local_date.day, 0, 0, 0, tzinfo=tz)
    end_local = datetime(next_date.year, next_date.month, next_date.day, 0, 0, 0, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


class KMDClient:
    """Async client matching verified live easy-energy-plugin-api.kmd.dk behavior."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        customer_id: str | None = None,
        customer_number: str | None = None,
        referer: str | None = "https://minvarme.kredslob.dk/",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._session = session
        token = access_token.strip()
        self._access_token = token if token.startswith("Bearer ") else f"Bearer {token}"
        self._customer_id = customer_id.strip() if customer_id else None
        self._customer_number = customer_number.strip() if customer_number else None
        self._referer = referer.strip() if referer else None
        self._extra_headers = dict(extra_headers) if extra_headers else {}
        self._profile: dict[str, Any] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": self._access_token,
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        if self._referer:
            headers["Referer"] = self._referer
        if self._customer_id:
            headers["Customer-Id"] = self._customer_id
        if self._customer_number:
            headers["Customer-Number"] = self._customer_number
        return headers

    def set_customer(self, customer_id: str | None, customer_number: str | None) -> None:
        """Select a kundeforhold for subsequent API calls (Customer-Id / Customer-Number)."""
        self._customer_id = customer_id.strip() if customer_id else None
        self._customer_number = customer_number.strip() if customer_number else None

    async def get_profile(self) -> dict[str, Any]:
        """GET /api/profile/get.

        If the profile lists exactly one kundeforhold and none is already
        selected, that customer is applied. Several relationships are left
        unselected — the caller must pick the district-heating one.
        """
        from ..kmd_supply import customer_identity, extract_customers

        url = f"{KMD_API_BASE}/api/profile/get"
        async with self._session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._profile = data if isinstance(data, dict) else None
            customers = extract_customers(data if isinstance(data, dict) else {})
            if customers:
                _LOGGER.info(
                    "KMD profile kundeforhold=%d, first keys=%s",
                    len(customers),
                    sorted(customers[0].keys()),
                )
            if len(customers) == 1 and not self._customer_id and not self._customer_number:
                cid, cnum = customer_identity(customers[0])
                self.set_customer(cid, cnum)
            return data

    async def _fetch_active_meters(self) -> list[dict[str, Any]]:
        """POST /api/meter/customerActiveMeters with the current customer headers."""
        url = f"{KMD_API_BASE}/api/meter/customerActiveMeters"
        hdrs = self._headers()
        async with self._session.post(url, headers=hdrs, json={"IncludeUnits": True}) as resp:
            if resp.status in (401, 403):
                _LOGGER.info(
                    "KMD customerActiveMeters HTTP %s; sent header names=%s",
                    resp.status,
                    sorted(hdrs.keys()),
                )
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, list) else data.get("Meters") or data.get("meters") or []

    async def get_active_meters(self) -> list[dict[str, Any]]:
        """Meters for the currently selected kundeforhold (or the token default)."""
        if not self._customer_id or not self._customer_number:
            await self.get_profile()
        return await self._fetch_active_meters()

    async def discover_accounts(self) -> list[dict[str, Any]]:
        """List every kundeforhold from the profile and fetch its meters.

        Logs only counts and kinds of type-field names — never addresses,
        names, customer numbers or meter identifiers.
        """
        from ..kmd_supply import classify_kmd_meter, customer_identity, extract_customers

        orig_cid, orig_cnum = self._customer_id, self._customer_number
        profile = self._profile if self._profile is not None else await self.get_profile()
        customers = extract_customers(profile if isinstance(profile, dict) else {})
        accounts: list[dict[str, Any]] = []
        if customers:
            for idx, customer in enumerate(customers, 1):
                cid, cnum = customer_identity(customer)
                if cid or cnum:
                    self.set_customer(cid, cnum)
                else:
                    self.set_customer(orig_cid, orig_cnum)
                try:
                    meters = await self._fetch_active_meters()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("KMD meters for kundeforhold %s failed: %s", idx, err)
                    meters = []
                kinds = sorted(
                    {classify_kmd_meter(m) for m in meters if isinstance(m, dict)}
                )
                unit_names = sorted(
                    {
                        str(u.get("Name") or "")
                        for m in meters if isinstance(m, dict)
                        for u in (m.get("Units") or [])
                        if isinstance(u, dict) and u.get("Name")
                    }
                )
                _LOGGER.info(
                    "KMD kundeforhold %s/%s: meters=%d kinds=%s units=%s",
                    idx,
                    len(customers),
                    len(meters),
                    kinds,
                    unit_names,
                )
                accounts.append(
                    {
                        "customer": customer,
                        "customer_index": idx,
                        "customer_id": cid,
                        "customer_number": cnum,
                        "meters": meters,
                    }
                )
            if sum(len(a["meters"]) for a in accounts) == 0:
                fallback_candidates: list[tuple[str | None, str | None]] = [(orig_cid, orig_cnum)]
                if (orig_cid, orig_cnum) != (None, None):
                    fallback_candidates.append((None, None))
                for fb_cid, fb_cnum in fallback_candidates:
                    self.set_customer(fb_cid, fb_cnum)
                    try:
                        meters = await self._fetch_active_meters()
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("KMD fallback meters failed: %s", err)
                        meters = []
                    if meters:
                        _LOGGER.info(
                            "KMD fallback default customer meters=%d",
                            len(meters),
                        )
                        accounts = [
                            {
                                "customer": {},
                                "customer_index": 1,
                                "customer_id": fb_cid,
                                "customer_number": fb_cnum,
                                "meters": meters,
                            }
                        ]
                        break
            return accounts

        meters = await self._fetch_active_meters()
        _LOGGER.info("KMD profile had no kundeforhold list; meters=%d", len(meters))
        return [
            {
                "customer": {},
                "customer_index": 1,
                "customer_id": self._customer_id,
                "customer_number": self._customer_number,
                "meters": meters,
            }
        ]

    async def get_consumption_timeseries(
        self,
        installation_id: str,
        measurement_point_id: str,
        unit: dict[str, Any],
        zoom_level: int,
        date_from: datetime,
        date_to: datetime,
    ) -> dict[str, Any]:
        """POST /api/consumption/consumptionTimeSeries.

        PriceData is boolean false. Dates as YYYY-MM-DDT00:00:00.000Z.
        """
        url = f"{KMD_API_BASE}/api/consumption/consumptionTimeSeries"
        payload = {
            "InstallationId": installation_id,
            "MeasurementPointId": measurement_point_id,
            "Unit": unit,
            "ZoomLevel": zoom_level,
            "PriceData": False,
            "Interval": "PT1H",
            "DateFrom": _format_api_dt(date_from),
            "DateTo": _format_api_dt(date_to),
        }
        async with self._session.post(url, headers=self._headers(), json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_hourly_with_fallback(
        self,
        installation_id: str,
        measurement_point_id: str,
        unit: dict[str, Any],
        date_from: datetime,
        date_to: datetime,
        max_concurrent: int = 4,
    ) -> list[dict[str, Any]]:
        """Fetch hourly data in Europe/Copenhagen bounds, falling back per-day if truncated."""
        start_d = date_from.astimezone(DK_TZ).date() if date_from.tzinfo else date_from.date()
        end_d = date_to.astimezone(DK_TZ).date() if date_to.tzinfo else date_to.date()
        n_req_days = max(1, (end_d - start_d).days)
        range_start_utc = datetime(start_d.year, start_d.month, start_d.day, tzinfo=DK_TZ).astimezone(
            timezone.utc
        )
        range_end_utc = datetime(end_d.year, end_d.month, end_d.day, tzinfo=DK_TZ).astimezone(
            timezone.utc
        )

        raw = await self.get_consumption_timeseries(
            installation_id, measurement_point_id, unit, 3, range_start_utc, range_end_utc
        )
        series_list = raw.get("Series") or []
        series = (series_list[0] or {}).get("Data") or [] if series_list else []
        expected_min = 24 * n_req_days
        nonzero_pts = sum(1 for pt in series if (pt.get("Value") or 0) > 0)

        hour_nonzero_ok = True
        if n_req_days >= 3 and series:
            hr_nonzero = [0] * 24
            for pt in series:
                if (pt.get("Value") or 0) <= 0:
                    continue
                dt_obj = _parse_iso_dt(pt.get("DateFrom"))
                if not dt_obj:
                    continue
                dt_loc = dt_obj.astimezone(DK_TZ) if dt_obj.tzinfo else dt_obj.replace(tzinfo=DK_TZ)
                hr_nonzero[dt_loc.hour] += 1
            med_nonzero = median(hr_nonzero)
            if med_nonzero >= n_req_days * 0.4 and any(c == 0 for c in hr_nonzero):
                hour_nonzero_ok = False

        if len(series) >= expected_min * 0.8 and nonzero_pts >= expected_min * 0.5 and hour_nonzero_ok:
            return series

        # Truncated, zero-filled, or missing-hour multi-day response – fetch day by day in local TZ
        days: list[datetime.date] = []
        cur = start_d
        while cur < end_d:
            days.append(cur)
            cur += timedelta(days=1)

        sem = asyncio.Semaphore(max_concurrent)

        async def fetch_day(d_date: Any) -> tuple[str, list[dict[str, Any]]]:
            async with sem:
                d_start_utc, d_end_utc = _local_day_utc_bounds(
                    datetime(d_date.year, d_date.month, d_date.day)
                )
                try:
                    r = await self.get_consumption_timeseries(
                        installation_id, measurement_point_id, unit, 3, d_start_utc, d_end_utc
                    )
                    s_list = r.get("Series") or []
                    return d_date.isoformat(), (s_list[0] or {}).get("Data") or [] if s_list else []
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Day fetch failed for %s: %s", d_date, err)
                    return d_date.isoformat(), []

        batches = await asyncio.gather(*[fetch_day(d) for d in days])
        merged: dict[str, tuple[tuple[int, int, int, float], dict[str, Any]]] = {}
        extra: list[dict[str, Any]] = []
        for target_day_iso, batch in batches:
            for item in batch:
                df = str(item.get("DateFrom") or "")
                if not df:
                    extra.append(item)
                    continue
                dt_obj = _parse_iso_dt(df)
                dt_loc = (
                    dt_obj.astimezone(DK_TZ)
                    if (dt_obj and dt_obj.tzinfo)
                    else (dt_obj.replace(tzinfo=DK_TZ) if dt_obj else None)
                )
                val = float(item.get("Value") or 0)
                has_val = 1 if val > 0 else 0
                is_comp = 1 if item.get("IsComplete") else 0
                matches_day = 1 if (dt_loc and dt_loc.date().isoformat() == target_day_iso) else 0
                score = (has_val, is_comp, matches_day, val)
                if df not in merged or score > merged[df][0]:
                    merged[df] = (score, item)

        results = [entry[1] for _, entry in sorted(merged.items(), key=lambda kv: kv[0])]
        results.extend(extra)
        return results

    async def get_current_settlement_period(self) -> dict[str, Any]:
        """GET /api/customer/getcurrentsettlementperiod"""
        url = f"{KMD_API_BASE}/api/customer/getcurrentsettlementperiod"
        async with self._session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_consumption_overview(
        self,
        installation_id: str,
        measurement_point_id: str,
        unit: dict[str, Any],
        date_from: datetime,
        date_to: datetime,
    ) -> dict[str, Any]:
        """POST /api/consumption-overview/consumptionOverviewSeries"""
        url = f"{KMD_API_BASE}/api/consumption-overview/consumptionOverviewSeries"
        payload = {
            "InstallationId": installation_id,
            "MeasurementPointId": measurement_point_id,
            "DateFrom": date_from.strftime("%Y-%m-%dT00:00:00.000Z"),
            "DateTo": date_to.strftime("%Y-%m-%dT00:00:00.000Z"),
            "UnitId": unit.get("Id"),
            "UnitName": unit.get("Name"),
            "UnitDecimals": unit.get("Decimals", 0),
        }
        async with self._session.post(url, headers=self._headers(), json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_balance(self) -> dict[str, Any]:
        """GET /api/balancestatement/getbalance"""
        url = f"{KMD_API_BASE}/api/balancestatement/getbalance"
        async with self._session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_balance_statement(self, from_idx: int = 0, to_idx: int = 10) -> list[dict[str, Any]]:
        """GET /api/balancestatement/getbalancestatement?from=&to="""
        url = f"{KMD_API_BASE}/api/balancestatement/getbalancestatement?from={from_idx}&to={to_idx}"
        async with self._session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, list) else []

    async def get_cooling_info(
        self,
        measurement_point_id: str,
        meter_type_id: Any,
        zoom_level: int,
        date_from: datetime,
        date_to: datetime,
    ) -> dict[str, Any]:
        """POST /api/cooling/getcoolinginfo (return/supply temps and volume flow)."""
        url = f"{KMD_API_BASE}/api/cooling/getcoolinginfo"
        payload: dict[str, Any] = {
            "MeasurementPointId": measurement_point_id,
            "DateFrom": date_from.strftime("%Y-%m-%dT00:00:00.000Z"),
            "DateTo": date_to.strftime("%Y-%m-%dT23:59:59.000Z"),
            "ZoomLevel": zoom_level,
        }
        if meter_type_id is not None:
            payload["MetertypeId"] = meter_type_id
        async with self._session.post(url, headers=self._headers(), json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, dict) else {}

    @staticmethod
    def find_unit(units: list[dict[str, Any]], name: str = "kWh") -> dict[str, Any] | None:
        """Return first unit matching Name (case-insensitive)."""
        name_l = name.lower()
        for u in units or []:
            if isinstance(u, dict) and str(u.get("Name") or "").lower() == name_l:
                return u
        return None

    @staticmethod
    def find_energy_unit(units: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Return first district-heating energy unit (kWh, MWh, or GJ)."""
        for name in ("kWh", "MWh", "GJ"):
            found = KMDClient.find_unit(units, name)
            if found is not None:
                return found
        for u in units or []:
            if not isinstance(u, dict):
                continue
            norm = str(u.get("Name") or "").strip().lower().replace("³", "3").replace("°", "")
            if norm not in ("m3", "c", "l", "liter"):
                return u
        return units[0] if units else None

    @staticmethod
    def energy_factor(unit: dict[str, Any] | str | None) -> float:
        """Multiplier converting raw API values in ``unit`` to kWh."""
        if isinstance(unit, dict):
            raw = unit.get("Name") or unit.get("Description") or ""
        else:
            raw = str(unit or "")
        norm = str(raw).strip().lower().replace(" ", "")
        if norm in ("mwh", "megawatthour", "megawatt-hour"):
            return 1000.0
        if norm in ("gj", "gigajoule"):
            return 1.0 / 0.0036
        return 1.0

    @staticmethod
    def find_unit_matching(
        units: list[dict[str, Any]],
        predicate: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any] | None:
        """Return first unit satisfying predicate."""
        for u in units or []:
            if predicate(u):
                return u
        return None
