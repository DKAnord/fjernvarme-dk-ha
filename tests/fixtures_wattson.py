"""Mock Watts On responses for tests (no network, no real tokens).

Verified shapes (from TheRealBatBro/Home-Assistant-Novafos-V2, water):
users/api/v3/User -> {"id": ...}; locations list with "id"; provisioning
location detail with devices ("deviceId", "utilityType", "unit"); hourly
consumption items with short keys "sd"/"ed"/"vol"/"mq". The heat device type
("DistrictHeating") and the heat item keys ("en", "ft", "rt") are INVENTED
guesses — real Aalborg Forsyning data must confirm or correct them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

REFRESH_1 = "fake-refresh-token-one"
REFRESH_2 = "fake-refresh-token-two"
ACCESS = "fake-access-token"
USER_ID = "user-0000-fake"
HEAT_DEVICE = "dev-heat-0001"
WATER_DEVICE = "dev-water-0001"

USER = {"id": USER_ID, "email": "someone@example.invalid", "name": "Test Person"}
LOCATIONS = [{"id": "loc-1", "address": "Testvej 1, 9000 Aalborg"}]
LOCATION_DETAIL = {
    "id": "loc-1",
    "address": "Testvej 1, 9000 Aalborg",
    "devices": [
        {"deviceId": HEAT_DEVICE, "utilityType": "DistrictHeating", "unit": "kWh", "meterNumber": "12345678"},
        {"deviceId": WATER_DEVICE, "utilityType": "Water", "unit": "Liter", "meterNumber": "87654321"},
    ],
}


def token_body(refresh: str = REFRESH_2, access: str = ACCESS) -> dict[str, Any]:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 3600,
        "refresh_token_expires_in": 1209600,
        "token_type": "Bearer",
    }


def heat_items(days: int = 3, end: datetime | None = None, **keys: Any) -> list[dict[str, Any]]:
    """Hourly items ending at ``end`` (UTC, exclusive), invented heat keys."""
    end = end or datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)  # = 6 Nov 00:00 CET
    start = end - timedelta(days=days)
    out = []
    t = start
    while t < end:
        item = {
            "sd": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ed": (t + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "en": 2.0,
            "vol": 0.05,
            "ft": 70.0,
            "rt": 30.0 if t.hour % 2 else 34.0,
            "mq": "Measured",
        }
        item.update(keys)
        item = {k: v for k, v in item.items() if v is not None}
        out.append(item)
        t += timedelta(hours=1)
    return out


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type=None):  # noqa: ARG002
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Routes GET/POST by URL fragment; records every call."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.routes: dict[str, Any] = {
            "oauth2/v2.0/token": token_body(),
            "users/api/v3/User": USER,
            "/locations/loc-1": LOCATION_DETAIL,
            "/locations": LOCATIONS,
            f"dk/heating/api/consumptions/{HEAT_DEVICE}": heat_items(),
        }
        self.routes.update(routes or {})

    def _respond(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        for frag, body in self.routes.items():
            if frag in url:
                if callable(body):
                    body = body(method, url, kwargs)
                if isinstance(body, tuple):
                    return FakeResponse(*body)
                return FakeResponse(200, body)
        return FakeResponse(404, {})

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._respond("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._respond("POST", url, kwargs)
