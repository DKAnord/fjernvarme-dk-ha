"""Mock E|Forsyning API responses.

Shapes follow the response formats documented/handled in kpoppel's
homeassistant-eforsyning (Apache-2.0); all values are invented.
"""

from __future__ import annotations

from typing import Any

APP_SERVER = "https://api.example.invalid/testvaerk/"
SUPPLIER_ID = "00000000-1111-2222-3333-444444444444"
USERNAME = "123456"  # fake forbrugernummer
PASSWORD = "fake-pin-not-real"  # fake webpinkode
SERVER_TOKEN = "server-token-abc"


def _line(day_from: str, day_to: str, mwh: str, m3: str, fwd: str, ret: str, unit: str = "MWh") -> dict[str, Any]:
    return {
        "FraDatoStr": day_from,
        "TilDatoStr": day_to,
        "Tempfrem": fwd,
        "TempRetur": ret,
        "Forv_Retur": "37",
        "Afkoling": "39,3",
        "ForventetForbrugM3": "0,5",
        "ForventetAflaesningM3": "100,5",
        "ForventetForbrugENG1": "0,03",
        "ForventetAflaesningENG1": "10,03",
        "TForbrugsTaellevaerk": [
            {"IndexNavn": "ENG1", "Enhed_Txt": unit, "Start": "10,000", "Slut": "10,025", "Forbrug": mwh},
            {"IndexNavn": "M3", "Enhed_Txt": "M3", "Start": "100,0", "Slut": "100,6", "Forbrug": m3},
        ],
    }


def daily_response(lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    lines = lines if lines is not None else [
        _line("01-11-2026", "02-11-2026", "0,025", "0,6", "70,5", "31,2"),
        _line("02-11-2026", "03-11-2026", "0,030", "0,8", "71,0", "30,0"),
        _line("03-11-2026", "04-11-2026", "0,020", "0,4", "69,0", "33,0"),
    ]
    return {
        "AarStart": "01-01-2026",
        "AarSlut": "31-12-2026",
        "ForbrugsLinjer": {"AktuelLinjeNr": "0", "AntLinjer": str(len(lines)), "TForbrugsLinje": lines},
        "IaltLinje": {
            "FraDatoStr": "01-01-2026",
            "TilDatoStr": "31-12-2026",
            "Tempfrem": "70",
            "TempRetur": "31",
            "Forv_Retur": "37",
            "Afkoling": "39",
            "ForventetForbrugM3": "200",
            "ForventetForbrugENG1": "12",
        },
    }


NO_DATA_ERROR = {"response": "TForb: Opslag på årsmærke fejlede(TForbrug.Beregn): 2027"}
NO_LINES = {"ForbrugsLinjer": {"AktuelLinjeNr": "0", "AntLinjer": "0", "Text": "", "Pris": "0"}}
SETTINGS = {"AppServerUri": APP_SERVER, "ForsyningsNavn": "Testværk"}
TOKEN = {"Token": SERVER_TOKEN}
LOGIN_OK = {"Result": 1}
LOGIN_FAIL = {"Result": 0}
USERINFO = {"id": 42, "indflyttet": "01-06-2019"}
INSTALLATIONS = {
    "Installationer": [
        {
            "EjendomNr": 1,
            "Adresse": "Testvej 1",
            "InstallationNr": 1,
            "ForbrugerNr": USERNAME,
            "MålerNr": "999999",
            "By": "Testby",
            "PostNr": "9800",
            "AktivNr": 1,
            "Målertype": "Varme",
        }
    ]
}
YEAR_MARKER = {"aarsmaerke": 2026, "aarsmaerke_start": "01-01-2026", "aarsmaerke_slut": "31-12-2026"}


def billing_response(lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Synthetic api/getberegnregnskab (Beregnet varmeregnskab) payload."""
    default_lines = [
        {
            "ekstra": "kr.",
            "enhedPris": "433,80",
            "linieType": "3",
            "antalEnheder": "3,361",
            "enhed": "MWh",
            "tekst": "999999",
            "prisEnhed": "kr./MWh",
            "ialt": "1.458,00",
        },
        {
            "ekstra": "",
            "enhedPris": "",
            "linieType": "3",
            "antalEnheder": "108,66",
            "enhed": "M3",
            "tekst": "",
            "prisEnhed": "",
            "ialt": "",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "433,80",
            "linieType": "3",
            "antalEnheder": "2,144",
            "enhed": "MWh",
            "tekst": "Prognose: 27-08-2026 til 31-12-2026",
            "prisEnhed": "kr./MWh",
            "ialt": "930,07",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "",
            "linieType": "12",
            "antalEnheder": "",
            "enhed": "",
            "tekst": "Samlet varmeforbrug",
            "prisEnhed": "",
            "ialt": "2.388,07",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "13,14",
            "linieType": "1",
            "antalEnheder": "170,25",
            "enhed": "m3",
            "tekst": "Fastbidrag",
            "prisEnhed": "kr./m3",
            "ialt": "2.237,09",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "4.625,16",
            "linieType": "10",
            "antalEnheder": "25,00",
            "enhed": "%",
            "tekst": "Moms",
            "prisEnhed": "kr.",
            "ialt": "1.156,29",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "",
            "linieType": "12",
            "antalEnheder": "",
            "enhed": "",
            "tekst": "Total (incl.moms)",
            "prisEnhed": "",
            "ialt": "5.781,45",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "",
            "linieType": "18",
            "antalEnheder": "",
            "enhed": "",
            "tekst": "Tidl. opkrævet (incl. moms)",
            "prisEnhed": "",
            "ialt": "-4.770,00",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "",
            "linieType": "18",
            "antalEnheder": "",
            "enhed": "",
            "tekst": "Restance",
            "prisEnhed": "",
            "ialt": "1.590,00",
        },
        {
            "ekstra": "kr.",
            "enhedPris": "",
            "linieType": "12",
            "antalEnheder": "",
            "enhed": "",
            "tekst": "Til indbetaling ",
            "prisEnhed": "",
            "ialt": "1.011,45",
        },
    ]
    return {"faktlini": default_lines if lines is None else lines}


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type=None):  # noqa: ARG002
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Routes requests by URL fragment; records every call."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.routes = {
            "GetVaerkSettings": SETTINGS,
            "getsecuritytoken": TOKEN,
            "system/login": LOGIN_OK,
            "getebrugerinfo": USERINFO,
            "FindInstallationer": INSTALLATIONS,
            "getaktuelaarsmaerke": YEAR_MARKER,
            "getforbrug": daily_response(),
        }
        self.routes.update(routes or {})

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        for frag, body in self.routes.items():
            if frag in url:
                if callable(body):
                    body = body(method, url, kwargs)
                if isinstance(body, tuple):
                    return FakeResponse(*body)
                return FakeResponse(200, body)
        return FakeResponse(404, {})
