"""Pure-Python MitID + OIDC PKCE authenticator for KMD Easy Energy (no Chromium required)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html as html_mod
import http.cookiejar
import io
import json
import logging
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import qrcode
import qrcode.image.svg
from bs4 import BeautifulSoup

from ..mitid_browserclient.BrowserClient import BrowserClient
from ..util import redact_url

_LOGGER = logging.getLogger(__name__)

IDENTITY_BASE = "https://easy-energy-identity.kmd.dk"
PLUGIN_API_BASE = "https://easy-energy-plugin-api.kmd.dk"
NEMLOGIN_URL = "https://nemlog-in.mitid.dk/login/mitid"
DEFAULT_KREDSLOB = {
    "client_id": "48A281C0-95CB-48EE-A018-3F7941E6D46A",
    "redirect_uri": "https://minvarme.kredslob.dk/min-varme",
    "post_logout_uri": "https://minvarme.kredslob.dk",
    "utility_code": "0455000",
}


def _qr_to_svg(qr_obj: qrcode.QRCode) -> str:
    """Render a QR code as a compact SVG that scales crisply in the browser.

    ``shape-rendering="crispEdges"`` avoids hairline gaps between the unit
    squares when the card scales the SVG up, which can make the code hard to
    scan from a tablet or PC screen.
    """
    img = qr_obj.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    if "shape-rendering" not in svg:
        svg = svg.replace("<svg ", '<svg shape-rendering="crispEdges" ', 1)
    return svg


class _CaptureCodeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Strip explicit :443/ from redirects and capture OIDC authorization code."""

    def __init__(self) -> None:
        super().__init__()
        self.oidc_code: str | None = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        clean_url = newurl.replace(":443/", "/")
        parsed = urlparse(clean_url)
        qs = parse_qs(parsed.query)
        if "code" in qs and parsed.hostname not in (
            "easy-energy-identity.kmd.dk",
            "identity.kmd.dk",
            "idpproxy.identity.kmd.dk",
            "nemlog-in.mitid.dk",
        ):
            self.oidc_code = qs["code"][0]
            return None
        return super().redirect_request(req, fp, code, msg, headers, clean_url)


class _Resp:
    """Minimal requests.Response-compatible wrapper for BrowserClient."""

    def __init__(self, status_code: int, content: bytes, url: str, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.url = url
        self.headers = headers

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url[:120]}")


class UrllibSession:
    """Standard-library HTTP session compatible with BrowserClient."""

    def __init__(self) -> None:
        self.cj = http.cookiejar.CookieJar()
        self.redirect_handler = _CaptureCodeRedirectHandler()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            self.redirect_handler,
        )
        self.opener.addheaders = [
            (
                "User-Agent",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            ),
            ("Accept-Language", "da,en-US;q=0.9,en;q=0.8"),
        ]

    def get_cookie(self, name: str, default: str = "") -> str:
        for c in self.cj:
            if c.name == name:
                return str(c.value)
        return default

    def _req(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | bytes | str | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int = 25,
    ) -> _Resp:
        target = url
        if params:
            sep = "&" if "?" in target else "?"
            target = f"{target}{sep}{urllib.parse.urlencode(params)}"
        hdrs = dict(headers or {})
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
            hdrs.setdefault("Accept", "application/json, text/plain, */*")
        elif isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        elif method in ("POST", "PUT") and body is None:
            body = b""
            hdrs.setdefault("Content-Length", "0")

        req = urllib.request.Request(target, data=body, method=method, headers=hdrs)
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return _Resp(r.status, r.read(), r.geturl(), dict(r.headers))
        except urllib.error.HTTPError as e:
            return _Resp(e.code, e.read(), e.geturl(), dict(e.headers))

    def get(self, url: str, **kw: Any) -> _Resp:
        return self._req(
            "GET",
            url,
            params=kw.get("params"),
            headers=kw.get("headers"),
            timeout=kw.get("timeout", 25),
        )

    def post(self, url: str, **kw: Any) -> _Resp:
        return self._req(
            "POST",
            url,
            params=kw.get("params"),
            data=kw.get("data"),
            json_body=kw.get("json"),
            headers=kw.get("headers"),
            timeout=kw.get("timeout", 25),
        )

    def put(self, url: str, **kw: Any) -> _Resp:
        return self._req(
            "PUT",
            url,
            params=kw.get("params"),
            data=kw.get("data"),
            json_body=kw.get("json"),
            headers=kw.get("headers"),
            timeout=kw.get("timeout", 25),
        )


class KMDMitIDAuthenticator:
    """Pure-Python OIDC PKCE + NemLog-in + MitID SRP client for KMD Easy Energy."""

    def __init__(self, timeout: int = 25) -> None:
        self.timeout = timeout
        self.session = UrllibSession()
        self.mitid_client: BrowserClient | None = None
        self._verification_token: str = ""
        self._code_verifier: str = ""
        self._client_id: str = DEFAULT_KREDSLOB["client_id"]
        self._redirect_uri: str = DEFAULT_KREDSLOB["redirect_uri"]

    def _discover_oidc_config(self, portal_url: str) -> dict[str, str]:
        if "minvarme.kredslob.dk" in portal_url:
            return dict(DEFAULT_KREDSLOB)
        try:
            resp = self.session.get(portal_url, timeout=self.timeout)
            html_txt = resp.text
            m_js = re.search(
                r"https://easy-energy-plugin-settings\.kmd\.dk/plugin/js/([0-9a-fA-F-]+)",
                html_txt,
            )
            if m_js:
                js_txt = self.session.get(m_js.group(0), timeout=self.timeout).text
                cid_m = re.search(r'OIDCClientId:"([^"]+)"', js_txt)
                red_m = re.search(r'OIDCRedirectUri:"([^"]+)"', js_txt)
                post_m = re.search(r'OIDCPostLogoutRedirectUri:"([^"]+)"', js_txt)
                if cid_m and red_m:
                    cid = cid_m.group(1)
                    s_resp = self.session.get(
                        f"{PLUGIN_API_BASE}/api/settings/plugins/client/{cid}",
                        timeout=self.timeout,
                    ).json()
                    plant = str(s_resp["PlantNumber"]).zfill(4)
                    util = str(s_resp["UtilityNumber"]).zfill(3)
                    return {
                        "client_id": cid,
                        "redirect_uri": red_m.group(1),
                        "post_logout_uri": post_m.group(1) if post_m else portal_url.rstrip("/"),
                        "utility_code": f"{plant}{util}",
                    }
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Dynamic OIDC discovery failed for %s (%s); using default", portal_url, err)
        return dict(DEFAULT_KREDSLOB)

    def start_session(self, portal_url: str, mitid_username: str) -> None:
        """Start OIDC PKCE + NemLog-in + MitID APP session (blocking, run in executor)."""
        cfg = self._discover_oidc_config(portal_url)
        self._client_id = cfg["client_id"]
        self._redirect_uri = cfg["redirect_uri"]

        self._code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self._code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "openid profile pluginapi_int",
            "nonce": secrets.token_hex(16),
            "state": secrets.token_hex(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "utility": cfg["utility_code"],
            "login_type": "plugin",
            "post_logout_redirect_uri": cfg["post_logout_uri"],
            "app": str(uuid.uuid4()),
        }
        r1 = self.session.get(f"{IDENTITY_BASE}/oidc/authorize", params=params, timeout=self.timeout)
        r1.raise_for_status()
        soup1 = BeautifulSoup(r1.text, "html.parser")
        form1 = soup1.find("form", {"id": "external-account"}) or soup1.find("form")
        if not form1:
            raise RuntimeError("KMD identity ExternalLogin form not found")

        action1 = urljoin(r1.url, html_mod.unescape(str(form1.get("action") or "")))
        rvt1_el = form1.find("input", {"name": "__RequestVerificationToken"})
        prov_el = form1.find("button", {"name": "provider"}) or form1.find("input", {"name": "provider"})
        form_data1 = {
            "provider": (prov_el.get("value") if prov_el else None) or "NemLogIn",
            "__RequestVerificationToken": rvt1_el.get("value", "") if rvt1_el else "",
        }
        r2 = self.session.post(action1, data=form_data1, timeout=self.timeout)
        r2.raise_for_status()

        soup2 = BeautifulSoup(r2.text, "html.parser")
        rvt2_el = soup2.find("input", {"name": "__RequestVerificationToken"})
        if not rvt2_el or not rvt2_el.get("value"):
            raise RuntimeError("NemLog-in RequestVerificationToken not found")
        self._verification_token = str(rvt2_el["value"])

        init_headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://nemlog-in.mitid.dk",
            "Referer": NEMLOGIN_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        r_init = self.session.post(
            f"{NEMLOGIN_URL}/initialize",
            headers=init_headers,
            data={"__RequestVerificationToken": self._verification_token},
            timeout=self.timeout,
        )
        r_init.raise_for_status()
        init_json = r_init.json()
        if isinstance(init_json, str):
            init_json = json.loads(init_json)
        aux_b64 = init_json.get("Aux")
        if not aux_b64:
            raise RuntimeError("MitID Aux missing from NemLog-in initialize response")
        aux = json.loads(base64.b64decode(aux_b64).decode())
        client_hash = binascii.hexlify(base64.b64decode(aux["coreClient"]["checksum"])).decode("ascii")
        auth_session_id = aux["parameters"]["authenticationSessionId"]

        self.mitid_client = BrowserClient(client_hash, auth_session_id, self.session)
        authenticators = self.mitid_client.identify_as_user_and_get_available_authenticators(
            mitid_username.strip()
        )
        if "APP" not in authenticators:
            raise RuntimeError(f"MitID APP authenticator not available for user ({authenticators})")
        self.mitid_client.start_app_authentication()

    def poll_once(self) -> dict[str, Any]:
        """Poll MitID APP status once (blocking, run in executor)."""
        if not self.mitid_client:
            raise RuntimeError("MitID session not started")
        res = self.mitid_client.poll_app_authentication_status()
        if res.get("status") == "qr_ready":
            qrs = self.mitid_client.get_current_qr_codes()
            if qrs and all(qrs):
                # MitID's animated QR is two frames (p=1 / p=2) that each carry
                # half of the channel binding. The MitID app must see BOTH, so
                # deliver both and let the card alternate them every second,
                # independent of how long MitID's long-poll takes to answer.
                frames = [_qr_to_svg(qr) for qr in qrs]
                res["qr_frames"] = frames
                res["qr_svg"] = frames[0]
        return res

    def finalize_and_exchange_token(self) -> str:
        """Complete MitID SRP, submit SAML/OIDC forms, and exchange OIDC code for JWT."""
        if not self.mitid_client:
            raise RuntimeError("MitID session not started")
        _LOGGER.info("Post-MitID: completing APP SRP authentication")
        self.mitid_client.complete_app_authentication()
        _LOGGER.info("Post-MitID: finalizing authentication for authorization code")
        auth_code = self.mitid_client.finalize_authentication_and_get_authorization_code()

        params = {
            "__RequestVerificationToken": self._verification_token,
            "NewCulture": "",
            "MitIDUseConfirmed": "True",
            "MitIDAuthCode": auth_code,
            "MitIDAuthenticationCancelled": "",
            "MitIDCoreClientError": "",
            "SessionStorageActiveSessionUuid": self.session.get_cookie("SessionUuid", ""),
            "SessionStorageActiveChallenge": self.session.get_cookie("Challenge", ""),
        }
        _LOGGER.info("Post-MitID: posting completion to NemLog-in")
        r_comp = self.session.post(NEMLOGIN_URL, data=params, timeout=self.timeout)
        r_comp.raise_for_status()
        _LOGGER.debug(
            "Post-MitID: NemLog-in response status=%s url=%s",
            r_comp.status_code,
            redact_url(r_comp.url)[:160],
        )

        # Handle multiple identities if NemLog-in presents /loginoption
        if "/loginoption" in r_comp.url:
            _LOGGER.info("Post-MitID: handling /loginoption multiple identity selection")
            soup_opt = BeautifulSoup(r_comp.text, "html.parser")
            data = {}
            for inp in soup_opt.select("form input"):
                key = inp.get("name") or inp.get("id")
                if key:
                    data[key] = inp.get("value", "")
            session_uuid = self.session.get_cookie("SessionUuid", "")
            challenge = self.session.get_cookie("Challenge", "")
            if session_uuid:
                data["SessionStorageActiveSessionUuid"] = session_uuid
            if challenge:
                data["SessionStorageActiveChallenge"] = challenge
            opts = soup_opt.select("a.list-link")
            if opts and opts[0].get("data-loginoptions"):
                data["ChosenOptionJson"] = opts[0]["data-loginoptions"]
            r_comp = self.session.post(
                r_comp.url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": r_comp.url},
                timeout=self.timeout,
            )
            r_comp.raise_for_status()
            _LOGGER.debug(
                "Post-MitID: /loginoption response status=%s url=%s",
                r_comp.status_code,
                redact_url(r_comp.url)[:160],
            )

        # Multi-hop <form> submission loop (NemLog-in -> idpproxy -> identity.kmd.dk -> easy-energy-identity)
        cur = r_comp
        for hop in range(8):
            if self.session.redirect_handler.oidc_code:
                break
            qs = parse_qs(urlparse(cur.url).query)
            if "code" in qs:
                self.session.redirect_handler.oidc_code = qs["code"][0]
                break
            soup = BeautifulSoup(cur.text, "html.parser")
            form = soup.find("form")
            if not form or not form.get("action"):
                break
            action_url = urljoin(cur.url, html_mod.unescape(str(form["action"]))).replace(":443/", "/")
            payload = {
                inp.get("name"): inp.get("value", "")
                for inp in form.find_all("input")
                if inp.get("name")
            }
            cur = self.session.post(action_url, data=payload, timeout=self.timeout)
            _LOGGER.debug(
                "Post-MitID form hop %d -> %s (status=%s)",
                hop + 1,
                redact_url(action_url)[:160],
                cur.status_code,
            )
            if not self.session.redirect_handler.oidc_code and cur.status_code >= 400:
                cur.raise_for_status()

        oidc_code = self.session.redirect_handler.oidc_code
        if not oidc_code:
            raise RuntimeError(
                f"OIDC authorization code not returned (last url={redact_url(cur.url)[:160]})"
            )

        tok_resp = self.session.post(
            f"{IDENTITY_BASE}/oidc/token",
            data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "code_verifier": self._code_verifier,
                "code": oidc_code,
                "redirect_uri": self._redirect_uri,
            },
            timeout=self.timeout,
        )
        tok_resp.raise_for_status()
        tok_data = tok_resp.json()
        access_token = tok_data.get("access_token")
        if not access_token:
            raise RuntimeError("No access_token in OIDC token response")
        return str(access_token)
