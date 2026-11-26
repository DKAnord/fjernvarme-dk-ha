"""KMDClient against a mock aiohttp session (no real network)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientResponseError

from kmd_easy_energy.api.kmd_client import KMDClient
from kmd_easy_energy.const import KMD_API_BASE


class FakeResp:
    def __init__(self, status: int, data, headers=None) -> None:
        self.status = status
        self._data = data
        self.headers = headers or {}
        self.request_info = MagicMock()
        self.history = ()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise ClientResponseError(
                self.request_info, self.history, status=self.status, message="error"
            )

    async def json(self):
        return self._data


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.handlers: dict[str, FakeResp] = {}

    def set(self, method: str, suffix: str, resp: FakeResp) -> None:
        self.handlers[f"{method.upper()} {suffix}"] = resp

    def _handle(self, method: str, url: str, **kwargs) -> FakeResp:
        self.calls.append((method, url, kwargs))
        path = url[len(KMD_API_BASE) :] if url.startswith(KMD_API_BASE) else url
        key = f"{method.upper()} {path.split('?')[0]}"
        if key not in self.handlers:
            raise AssertionError(f"unexpected {key}; known={list(self.handlers)}")
        handler = self.handlers[key]
        if callable(handler):
            return handler(method, url, **kwargs)
        return handler

    def get(self, url: str, **kwargs) -> FakeResp:
        return self._handle("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> FakeResp:
        return self._handle("POST", url, **kwargs)


@pytest.mark.asyncio
async def test_get_profile_populates_customer_headers() -> None:
    session = FakeSession()
    session.set(
        "GET",
        "/api/profile/get",
        FakeResp(
            200,
            {"Customers": [{"CustomerId": "cid-1", "CustomerNumber": "cn-9"}]},
        ),
    )
    client = KMDClient(session, "tok", referer="https://minvarme.kredslob.dk/")
    data = await client.get_profile()
    assert data["Customers"][0]["CustomerId"] == "cid-1"
    assert client._customer_id == "cid-1"
    assert client._customer_number == "cn-9"
    auth = session.calls[0][2]["headers"]["Authorization"]
    assert auth == "Bearer tok"


@pytest.mark.asyncio
async def test_active_meters_include_units_and_401() -> None:
    session = FakeSession()
    session.set(
        "POST",
        "/api/meter/customerActiveMeters",
        FakeResp(401, {"error": "expired"}),
    )
    client = KMDClient(session, "tok", customer_id="c", customer_number="n")
    with pytest.raises(ClientResponseError) as err:
        await client.get_active_meters()
    assert err.value.status == 401
    body = session.calls[0][2]["json"]
    assert body == {"IncludeUnits": True}


@pytest.mark.asyncio
async def test_consumption_payload_shape() -> None:
    session = FakeSession()
    session.set(
        "POST",
        "/api/consumption/consumptionTimeSeries",
        FakeResp(200, {"Series": [{"Data": [{"DateFrom": "2026-11-01T00:00:00Z", "Value": 1, "IsComplete": True}]}]}),
    )
    client = KMDClient(session, "tok", customer_id="c", customer_number="n")
    unit = {"Id": 1, "Name": "kWh", "Decimals": 0}
    await client.get_consumption_timeseries(
        "inst", "mp", unit, 3, datetime(2026, 11, 1), datetime(2026, 11, 2)
    )
    payload = session.calls[0][2]["json"]
    assert payload["IncludeUnits"] if "IncludeUnits" in payload else True
    assert payload["PriceData"] is False
    assert payload["ZoomLevel"] == 3
    assert payload["InstallationId"] == "inst"
    assert payload["DateFrom"].endswith("Z")


@pytest.mark.asyncio
async def test_balance_and_settlement_endpoints() -> None:
    session = FakeSession()
    session.set("GET", "/api/balancestatement/getbalance", FakeResp(200, {"Balance": 10.5}))
    session.set(
        "GET",
        "/api/customer/getcurrentsettlementperiod",
        FakeResp(200, {"DateFrom": "2026-01-01", "DateTo": "2026-12-31"}),
    )
    client = KMDClient(session, "tok", customer_id="c", customer_number="n")
    assert (await client.get_balance())["Balance"] == 10.5
    sp = await client.get_current_settlement_period()
    assert sp["DateFrom"].startswith("2026")


def test_format_api_dt_naive_and_aware() -> None:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from kmd_easy_energy.api.kmd_client import _format_api_dt

    naive = datetime(2026, 11, 1)
    assert _format_api_dt(naive) == "2026-11-01T00:00:00.000Z"
    # 00:00 Europe/Copenhagen on 1 Nov 2026 is 23:00 UTC on 31 Oct (CET, UTC+1)
    local_midnight = datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo("Europe/Copenhagen"))
    assert _format_api_dt(local_midnight) == "2026-10-31T23:00:00.000Z"
    assert _format_api_dt(datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)) == "2026-11-01T00:00:00.000Z"


def test_local_day_utc_bounds_cet() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from kmd_easy_energy.api.kmd_client import _local_day_utc_bounds

    start, end = _local_day_utc_bounds(datetime(2026, 11, 1))
    assert start.isoformat() == "2026-10-31T23:00:00+00:00"
    assert end.isoformat() == "2026-11-01T23:00:00+00:00"
    # DST-aware: 29 Mar 2026 is the CET->CEST transition in Denmark
    start_s, end_s = _local_day_utc_bounds(
        datetime(2026, 3, 29, tzinfo=ZoneInfo("Europe/Copenhagen"))
    )
    assert start_s.isoformat() == "2026-03-28T23:00:00+00:00"
    assert end_s.isoformat() == "2026-03-29T22:00:00+00:00"


@pytest.mark.asyncio
async def test_profile_with_two_kundeforhold_does_not_select_first() -> None:
    session = FakeSession()
    session.set(
        "GET",
        "/api/profile/get",
        FakeResp(
            200,
            {
                "Customers": [
                    {"CustomerId": "cust-el-synth", "CustomerNumber": "cn-el"},
                    {"CustomerId": "cust-heat-synth", "CustomerNumber": "cn-heat"},
                ]
            },
        ),
    )
    client = KMDClient(session, "tok", referer="https://example.invalid/")
    data = await client.get_profile()
    assert len(data["Customers"]) == 2
    assert client._customer_id is None
    assert client._customer_number is None


@pytest.mark.asyncio
async def test_discover_accounts_fetches_meters_per_kundeforhold() -> None:
    session = FakeSession()
    session.set(
        "GET",
        "/api/profile/get",
        FakeResp(
            200,
            {
                "Customers": [
                    {"CustomerId": "cust-el-synth", "CustomerNumber": "cn-el"},
                    {"CustomerId": "cust-heat-synth", "CustomerNumber": "cn-heat"},
                ]
            },
        ),
    )

    def meters_resp(method, url, **kwargs):
        headers = (kwargs.get("headers") or {})
        cid = headers.get("Customer-Id")
        if cid == "cust-el-synth":
            body = [
                {
                    "MeasurementPointId": "mp-el-synth",
                    "Type": "El",
                    "TypeCode": "E17",
                    "Units": [{"Name": "kWh"}],
                }
            ]
        elif cid == "cust-heat-synth":
            body = [
                {
                    "MeasurementPointId": "mp-heat-synth",
                    "Type": "Varme",
                    "Units": [{"Name": "kWh"}, {"Name": "m3"}],
                },
                {
                    "MeasurementPointId": "mp-water-synth",
                    "Type": "Vand",
                    "Units": [{"Name": "m3"}],
                },
            ]
        else:
            raise AssertionError(f"unexpected Customer-Id {cid}")
        return FakeResp(200, body)

    session.set("POST", "/api/meter/customerActiveMeters", meters_resp)
    client = KMDClient(session, "tok", referer="https://example.invalid/")
    accounts = await client.discover_accounts()
    assert len(accounts) == 2
    assert accounts[0]["customer_id"] == "cust-el-synth"
    assert accounts[0]["meters"][0]["Type"] == "El"
    assert accounts[1]["customer_id"] == "cust-heat-synth"
    assert [m["Type"] for m in accounts[1]["meters"]] == ["Varme", "Vand"]
    # Two meter POSTs, each with the matching customer header.
    meter_calls = [c for c in session.calls if c[0] == "POST"]
    assert len(meter_calls) == 2
    assert meter_calls[0][2]["headers"]["Customer-Id"] == "cust-el-synth"
    assert meter_calls[1][2]["headers"]["Customer-Id"] == "cust-heat-synth"


@pytest.mark.asyncio
async def test_discover_accounts_falls_back_to_default_when_customers_empty() -> None:
    session = FakeSession()
    session.set(
        "GET",
        "/api/profile/get",
        FakeResp(
            200,
            {"Customers": [{"CustomerId": "cust-empty", "CustomerNumber": "cn-empty"}]},
        ),
    )

    def meters_resp(method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        if headers.get("Customer-Id") == "cust-empty":
            return FakeResp(200, [])
        return FakeResp(
            200,
            [{"MeasurementPointId": "mp-beof-1", "Units": [{"Name": "MWh"}]}],
        )

    session.set("POST", "/api/meter/customerActiveMeters", meters_resp)
    client = KMDClient(session, "tok", referer="https://minforsyning.beof.dk/")
    accounts = await client.discover_accounts()
    assert len(accounts) == 1
    assert accounts[0]["customer_id"] is None
    assert accounts[0]["meters"][0]["MeasurementPointId"] == "mp-beof-1"
