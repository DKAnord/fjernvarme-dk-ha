"""Thin async client for KMD Easy Energy plugin API (verified live endpoints)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

import aiohttp

from ..const import KMD_API_BASE

_LOGGER = logging.getLogger(__name__)


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
            "DateFrom": date_from.strftime("%Y-%m-%dT00:00:00.000Z"),
            "DateTo": date_to.strftime("%Y-%m-%dT00:00:00.000Z"),
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
        """Fetch hourly data, falling back to per-day parallel batches if truncated."""
        raw = await self.get_consumption_timeseries(
            installation_id, measurement_point_id, unit, 3, date_from, date_to
        )
        series_list = raw.get("Series") or []
        series = (series_list[0] or {}).get("Data") or [] if series_list else []
        expected_min = 24 * max(1, (date_to - date_from).days)
        nonzero_pts = sum(1 for pt in series if (pt.get("Value") or 0) > 0)
        if len(series) >= expected_min * 0.8 and nonzero_pts >= expected_min * 0.5:
            return series

        # Truncated or zero-filled multi-day response – fetch day by day
        days: list[datetime] = []
        cur = date_from
        while cur < date_to:
            days.append(cur)
            cur += timedelta(days=1)

        results: list[dict[str, Any]] = []
        seen_dates: set[str] = set()
        sem = asyncio.Semaphore(max_concurrent)

        async def fetch_day(d: datetime) -> list[dict[str, Any]]:
            async with sem:
                day_to = d + timedelta(days=1)
                try:
                    r = await self.get_consumption_timeseries(
                        installation_id, measurement_point_id, unit, 3, d, day_to
                    )
                    s_list = r.get("Series") or []
                    return (s_list[0] or {}).get("Data") or [] if s_list else []
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Day fetch failed for %s: %s", d.date(), err)
                    return []

        batches = await asyncio.gather(*[fetch_day(d) for d in days])
        for batch in batches:
            for item in batch:
                df = str(item.get("DateFrom") or "")
                if df and df in seen_dates:
                    continue
                if df:
                    seen_dates.add(df)
                results.append(item)
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
