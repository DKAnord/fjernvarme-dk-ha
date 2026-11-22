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

    async def get_profile(self) -> dict[str, Any]:
        """GET /api/profile/get – populates customer id/number if present."""
        url = f"{KMD_API_BASE}/api/profile/get"
        async with self._session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if isinstance(data, dict):
                customers = data.get("Customers") or data.get("customers") or []
                if customers and isinstance(customers[0], dict):
                    c = customers[0]
                    _LOGGER.info("KMD Customers[0] keys: %s", sorted(c.keys()))
                    low = {str(k).lower(): v for k, v in c.items()}
                    cid = low.get("customerid") or low.get("id")
                    cnum = low.get("customernumber") or low.get("customerno") or low.get("number")
                    if cid:
                        self._customer_id = str(cid)
                    if cnum:
                        self._customer_number = str(cnum)
            return data

    async def get_active_meters(self) -> list[dict[str, Any]]:
        """POST /api/meter/customerActiveMeters with IncludeUnits."""
        if not self._customer_id or not self._customer_number:
            await self.get_profile()
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

    @staticmethod
    def find_unit(units: list[dict[str, Any]], name: str = "kWh") -> dict[str, Any] | None:
        """Return first unit matching Name (case-insensitive)."""
        name_l = name.lower()
        for u in units or []:
            if str(u.get("Name") or "").lower() == name_l:
                return u
        return None

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
