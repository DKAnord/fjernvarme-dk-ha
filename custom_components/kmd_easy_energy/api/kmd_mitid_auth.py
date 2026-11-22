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
    "login_type": "plugin",
}

# Shared Min Forsyning 2 (minforsyning-2.kmd.dk) OIDC client, published in the
# public SPA bundle. Tenants are selected with utility=PPPPUUU (plant+utility).
DEFAULT_MINFORSYNING2 = {
    "client_id": "1DA5CFAF-F67F-4DA1-A1A6-513A7768F994",
    "redirect_uri": "https://minforsyning-2.kmd.dk/login",
    "post_logout_uri": "https://minforsyning-2.kmd.dk/login",
    "login_type": "mf",
}

MAX_DISCOVERY_FETCHES = 6
MAX_FORM_HOPS = 8

_PLUGIN_JS_RE = re.compile(
    r"https://easy-energy-plugin-settings\.kmd\.dk/plugin/js/([0-9a-fA-F-]+)",
    re.I,
)
_IDENTITY_URL_RE = re.compile(
    r"https://easy-energy-identity\.kmd\.dk[^\s<>]+",
    re.I,
)
_MF2_URL_RE = re.compile(
    r"https://minforsyning-2\.kmd\.dk[^\s<>]+",
    re.I,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_TOKENISH_RE = re.compile(r"\b[A-Za-z0-9_\-]{28,}\b")
_CPR_RE = re.compile(r"\b\d{6}-?\d{4}\b")
_INTERACTIVE_TEXT_RE = re.compile(
    r"opret\s+(bruger|konto)|registrer|register|vilk[aå]r|terms of (use|service)|"
    r"associate your|confirm your (account|email)|accepter vilk[aå]r|"
    r"create (a new )?account|første gang",
    re.I,
)
_DISCOVERY_PATH_RE = re.compile(
    r"minforsyning|min-forsyning|selvbetjening|min-varme|minvarme|min-forsyning",
    re.I,
)

MSG_PORTAL_FIRST = (
    "MitID lykkedes, men værkets portal kræver, at du logger ind én gang "
    "i en almindelig browser først og accepterer vilkår. Prøv derefter igen her."
)
MSG_OIDC_GENERIC = (
    "MitID lykkedes, men login hos værket stoppede før adgangskoden blev givet. "
    "Se HA-loggen (kmd_easy_energy) for detaljer."
)
MSG_DISCOVERY_FAILED = (
    "Kunne ikke finde login-oplysningerne for denne portal. "
    "Tjek at du har valgt det rigtige værk, og send gerne en fejlrapport (uden MitID-id)."
)


def _decode_href(url: str) -> str:
    """Unescape HTML entities in a crawled href or raw URL."""
    return html_mod.unescape(str(url).replace("&#038;", "&")).strip()


def _parse_oidc_from_js(text: str) -> dict[str, str] | None:
    """Extract OIDCClientId / redirect URIs from plugin JS or the MF2 SPA bundle."""
    cid = re.search(r'OIDCClientId:"([^"]+)"', text)
    red = re.search(r'OIDCRedirectUri:"([^"]+)"', text)
    post = re.search(r'OIDCPostLogoutRedirectUri:"([^"]+)"', text)
    if not (cid and red):
        return None
    return {
        "client_id": cid.group(1),
        "redirect_uri": red.group(1),
        "post_logout_uri": post.group(1) if post else red.group(1),
    }


def _parse_mf2_utility_code(url: str) -> str | None:
    """Build KMD utility_code PPPPUUU from a minforsyning-2.kmd.dk URL."""
    qs = parse_qs(urlparse(_decode_href(url)).query)
    if "plant" not in qs or not qs["plant"][0]:
        return None
    plant = str(qs["plant"][0]).zfill(4)
    util = str((qs.get("utility") or ["0"])[0]).zfill(3)
    return f"{plant}{util}"


def _parse_oidc_from_url(url: str) -> dict[str, str] | None:
    """Parse client_id / redirect_uri / utility / login_type from an identity or authorize URL."""
    raw = _decode_href(url)
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    for key in ("ReturnUrl", "returnUrl", "returnurl"):
        if key not in qs:
            continue
        inner = qs[key][0]
        if inner.startswith("/"):
            inner = f"{IDENTITY_BASE}{inner}"
        inner_qs = parse_qs(urlparse(inner).query)
        if "client_id" in inner_qs:
            qs = inner_qs
            break
    if "client_id" not in qs:
        return None
    redirect = (qs.get("redirect_uri") or [""])[0]
    if not redirect:
        return None
    login_type = (qs.get("login_type") or [""])[0]
    if not login_type:
        login_type = "mf" if "minforsyning-2.kmd.dk" in redirect else "plugin"
    post = (qs.get("post_logout_redirect_uri") or [redirect])[0]
    utility = (qs.get("utility") or [""])[0]
    cfg = {
        "client_id": qs["client_id"][0],
        "redirect_uri": redirect,
        "post_logout_uri": post,
        "login_type": login_type,
    }
    if utility:
        cfg["utility_code"] = utility
    mf2_util = _parse_mf2_utility_code(raw)
    if mf2_util and "utility_code" not in cfg:
        cfg["utility_code"] = mf2_util
    return cfg


def _urls_in_html(html: str) -> list[str]:
    """Collect href/src and raw KMD portal URLs from a page."""
    found: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"""(?:href|src)=["']([^"']+)["']""", html, re.I):
        url = _decode_href(match.group(1))
        if url and url not in seen:
            seen.add(url)
            found.append(url)
    for rex in (_PLUGIN_JS_RE, _IDENTITY_URL_RE, _MF2_URL_RE):
        for match in rex.finditer(html):
            url = _decode_href(match.group(0))
            if url and url not in seen:
                seen.add(url)
                found.append(url)
    return found


def _is_discovery_follow_url(base_url: str, candidate: str) -> bool:
    """Whether a link from a portal page is worth fetching for OIDC discovery."""
    url = urljoin(base_url, candidate)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host == "minforsyning-2.kmd.dk":
        return True
    if host == "easy-energy-plugin-settings.kmd.dk" and "/plugin/js/" in path:
        return True
    if host == "easy-energy-identity.kmd.dk" and (
        "client_id=" in url.lower() or "/oidc/authorize" in url.lower()
    ):
        return True
    base_host = (urlparse(base_url).hostname or "").lower()
    if host == base_host and _DISCOVERY_PATH_RE.search(path):
        return True
    return False


def _sanitize_feedback(text: str, limit: int = 180) -> str:
    """Collapse whitespace and strip emails, CPR-like numbers and token-ish strings."""
    cleaned = _EMAIL_RE.sub("[email]", text)
    cleaned = _CPR_RE.sub("[id]", cleaned)
    cleaned = _TOKENISH_RE.sub("[redacted]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _extract_page_feedback(html: str, url: str) -> str:
    """Best-effort, PII-free heading or error text from a KMD identity page."""
    bits: list[str] = []
    qs = parse_qs(urlparse(url).query)
    for key in ("error", "error_description", "remoteError", "RemoteError", "ErrorMessage"):
        if key in qs and qs[key][0].strip():
            bits.append(qs[key][0].strip())
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for sel in ("title", "h1", "h2", ".validation-summary-errors", ".text-danger", ".alert", "#ErrorMessage"):
        el = soup.select_one(sel)
        if el:
            txt = " ".join(el.stripped_strings)
            if txt and txt not in bits:
                bits.append(txt)
    return _sanitize_feedback(" — ".join(bits)) if bits else ""


def _form_action_url(form: Any, current_url: str) -> str:
    """Resolve a form action, treating a missing or empty action as the current URL."""
    action = html_mod.unescape(str(form.get("action") or "")).strip()
    return urljoin(current_url, action).replace(":443/", "/")


def _form_payload(form: Any) -> dict[str, str]:
    """Collect input values plus a single default submit button (ASP.NET provider buttons)."""
    payload: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        typ = (inp.get("type") or "text").lower()
        if typ in ("submit", "button", "image", "reset"):
            continue
        if typ in ("checkbox", "radio") and not inp.has_attr("checked"):
            continue
        payload[name] = inp.get("value") or ""
    submits: list[tuple[str, str]] = []
    for el in form.find_all(["input", "button"]):
        name = el.get("name")
        typ = (el.get("type") or ("submit" if el.name == "button" else "")).lower()
        if name and typ == "submit":
            submits.append((name, el.get("value") or ""))
    if not submits:
        return payload
    chosen = None
    for name, val in submits:
        low = f"{name} {val}".lower()
        if "cancel" in low or "annuller" in low:
            continue
        chosen = (name, val)
        break
    if chosen is None:
        chosen = submits[0]
    payload[chosen[0]] = chosen[1]
    return payload


def _is_auto_post_form(form: Any) -> bool:
    """True when the form has no fields a human would have to fill in."""
    for inp in form.find_all("input"):
        typ = (inp.get("type") or "text").lower()
        if typ in {"text", "email", "password", "tel", "number", "search", "url"}:
            return False
        if typ in {"checkbox", "radio"}:
            return False
    if form.find("select") is not None or form.find("textarea") is not None:
        return False
    return True


def _is_external_provider_form(form: Any) -> bool:
    """The ASP.NET Identity 'choose external provider' form (start of login, not a callback)."""
    if (form.get("id") or "") == "external-account":
        return True
    names = {
        el.get("name")
        for el in form.find_all(["input", "button"])
        if el.get("name")
    }
    if "provider" in names and "SAMLResponse" not in names and "MitIDAuthCode" not in names:
        return True
    return False


def _is_interactive_account_page(url: str, form: Any, html: str) -> bool:
    """First-time / register / terms page after MitID, which we must not auto-submit."""
    path = urlparse(url).path.lower()
    visible = " ".join(BeautifulSoup(html or "", "html.parser").stripped_strings)
    looks_new = bool(_INTERACTIVE_TEXT_RE.search(visible) or _INTERACTIVE_TEXT_RE.search(html or ""))
    has_email = False
    if form:
        has_email = bool(
            form.find("input", {"type": "email"})
            or form.find("input", attrs={"name": re.compile(r"email|Input\.Email", re.I)})
            or form.find("input", attrs={"type": re.compile(r"^(text|password)$", re.I)})
        )
    if "externallogin" in path and form and not _is_auto_post_form(form):
        return True
    if looks_new and (has_email or "externallogin" in path or "register" in path):
        return True
    return False


def oidc_code_missing_error(url: str, html: str) -> RuntimeError:
    """User-facing Danish error when the OIDC code never appears after MitID."""
    path = urlparse(url).path.lower()
    feedback = _extract_page_feedback(html, url)
    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form")
    if form and (
        _is_interactive_account_page(url, form, html)
        or ("externallogin" in path and _is_external_provider_form(form))
        or ("externallogin" in path and not _is_auto_post_form(form))
    ):
        msg = MSG_PORTAL_FIRST
    else:
        msg = MSG_OIDC_GENERIC
        if feedback:
            msg = f"{MSG_OIDC_GENERIC} ({feedback})"
    _LOGGER.error(
        "OIDC authorization code not returned (last url=%s feedback=%s)",
        redact_url(url)[:300],
        feedback or "(none)",
    )
    return RuntimeError(msg)


def discovery_failed_error(portal_url: str, err: Exception | None = None) -> RuntimeError:
    """User-facing Danish error when OIDC client settings cannot be discovered."""
    _LOGGER.error("OIDC discovery failed for %s: %s", portal_url, err or "no client settings found")
    return RuntimeError(MSG_DISCOVERY_FAILED)


def _qr_to_svg(qr_obj: qrcode.QRCode) -> str:
    """Render a QR code as a crisp pixel-sized SVG with an opaque white background.

    ``shape-rendering="crispEdges"`` avoids hairline gaps between modules,
    pixel dimensions avoid ``mm``-unit scaling quirks, and the white ``<rect>``
    keeps the quiet zone readable even on dark-mode dashboards.
    """
    img = qr_obj.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    size = (qr_obj.modules_count + 2 * qr_obj.border) * 10
    svg = re.sub(r'width="[^"]*"', f'width="{size}"', svg, count=1)
    svg = re.sub(r'height="[^"]*"', f'height="{size}"', svg, count=1)
    if "shape-rendering" not in svg:
        svg = svg.replace("<svg ", '<svg shape-rendering="crispEdges" ', 1)
    if '<rect width="100%"' not in svg:
        svg = re.sub(
            r"(<svg\b[^>]*>)",
            r'\1<rect width="100%" height="100%" fill="#ffffff"/>',
            svg,
            count=1,
        )
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
        """Resolve OIDC client settings for a utility portal.

        Kredsløb (and Galten, which shares minvarme.kredslob.dk) use the
        Easy Energy *plugin* client. Many other KMD utilities — including
        Energi Ikast — use Min Forsyning 2 (minforsyning-2.kmd.dk) with a
        different client_id, redirect_uri and login_type=mf. Falling back
        to Kredsløb's client silently makes MitID succeed and then fail on
        /Identity/Account/ExternalLogin, so discovery failure is an error.
        """
        if "minvarme.kredslob.dk" in portal_url:
            return dict(DEFAULT_KREDSLOB)
        try:
            return self._discover_oidc_config_uncached(portal_url)
        except RuntimeError:
            raise
        except Exception as err:  # noqa: BLE001
            raise discovery_failed_error(portal_url, err) from err

    def _discover_oidc_config_uncached(self, portal_url: str) -> dict[str, str]:
        """Breadth-first crawl (max MAX_DISCOVERY_FETCHES public GETs) for OIDC settings.

        Order of evidence:
        1. A direct easy-energy-identity link with client_id/redirect_uri/utility.
        2. An Easy Energy plugin JS (plugin client + settings API for plant/utility).
        3. A minforsyning-2.kmd.dk?plant=… link -> shared Min Forsyning 2 client.
        """
        queue: list[str] = [portal_url]
        seen: set[str] = set()
        mf2_utility: str | None = None
        plugin_js_url: str | None = None
        fetches = 0

        while queue and fetches < MAX_DISCOVERY_FETCHES:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            resp = self.session.get(url, timeout=self.timeout)
            fetches += 1
            base = getattr(resp, "url", None) or url
            seen.add(base)
            html_txt = getattr(resp, "text", "") or ""

            # A redirect straight onto an MF2 tenant URL (e.g. minforsyning.beof.dk).
            mf2_utility = mf2_utility or _parse_mf2_utility_code(base)

            for found in _urls_in_html(html_txt):
                abs_url = urljoin(base, found)
                direct = _parse_oidc_from_url(abs_url)
                if direct and direct.get("utility_code"):
                    return direct
                mf2_utility = mf2_utility or _parse_mf2_utility_code(abs_url)
                m_js = _PLUGIN_JS_RE.search(abs_url)
                if m_js and not plugin_js_url:
                    plugin_js_url = m_js.group(0)
                host = (urlparse(abs_url).hostname or "").lower()
                # Never GET identity authorize/login URLs (that starts a login)
                # or the MF2 SPA / plugin JS — those are parsed from the URL or fetched later.
                if (
                    abs_url not in seen
                    and abs_url not in queue
                    and host
                    not in {
                        "minforsyning-2.kmd.dk",
                        "easy-energy-identity.kmd.dk",
                        "easy-energy-plugin-settings.kmd.dk",
                        "easy-energy-plugin-api.kmd.dk",
                    }
                    and _is_discovery_follow_url(portal_url, abs_url)
                ):
                    queue.append(abs_url)
            if plugin_js_url or mf2_utility:
                break

        if plugin_js_url:
            parsed = _parse_oidc_from_js(self.session.get(plugin_js_url, timeout=self.timeout).text)
            if parsed:
                cid = parsed["client_id"]
                s_resp = self.session.get(
                    f"{PLUGIN_API_BASE}/api/settings/plugins/client/{cid}",
                    timeout=self.timeout,
                ).json()
                plant = str(s_resp["PlantNumber"]).zfill(4)
                util = str(s_resp["UtilityNumber"]).zfill(3)
                return {
                    "client_id": cid,
                    "redirect_uri": parsed["redirect_uri"],
                    "post_logout_uri": parsed["post_logout_uri"],
                    "utility_code": f"{plant}{util}",
                    "login_type": "plugin",
                }

        if mf2_utility:
            cfg = dict(DEFAULT_MINFORSYNING2)
            cfg["utility_code"] = mf2_utility
            _LOGGER.info(
                "OIDC discovery: Min Forsyning 2 utility=%s (shared MF2 client)", mf2_utility
            )
            return cfg

        raise discovery_failed_error(portal_url)

    def start_session(self, portal_url: str, mitid_username: str) -> None:
        """Start OIDC PKCE + NemLog-in + MitID APP session (blocking, run in executor)."""
        cfg = self._discover_oidc_config(portal_url)
        self._client_id = cfg["client_id"]
        self._redirect_uri = cfg["redirect_uri"]
        _LOGGER.info(
            "OIDC start: portal=%s client_id=%s login_type=%s utility=%s",
            portal_url,
            self._client_id,
            cfg.get("login_type") or "plugin",
            cfg.get("utility_code"),
        )

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
            "login_type": cfg.get("login_type") or "plugin",
            "post_logout_redirect_uri": cfg["post_logout_uri"],
            "app": str(uuid.uuid4()),
        }
        r1 = self.session.get(f"{IDENTITY_BASE}/oidc/authorize", params=params, timeout=self.timeout)
        r1.raise_for_status()
        # Min Forsyning 2 may already redirect to NemLog-in; Kredsløb shows ExternalLogin first.
        if "nemlog-in.mitid.dk" in (r1.url or ""):
            r2 = r1
        else:
            soup1 = BeautifulSoup(r1.text, "html.parser")
            form1 = soup1.find("form", {"id": "external-account"}) or soup1.find("form")
            if not form1:
                raise RuntimeError("KMD identity ExternalLogin form not found")

            action1 = _form_action_url(form1, r1.url)
            rvt1_el = form1.find("input", {"name": "__RequestVerificationToken"})
            prov_el = form1.find("button", {"name": "provider"}) or form1.find("input", {"name": "provider"})
            form_data1 = _form_payload(form1)
            if "provider" not in form_data1:
                form_data1["provider"] = (prov_el.get("value") if prov_el else None) or "NemLogIn"
            if rvt1_el and rvt1_el.get("value"):
                form_data1["__RequestVerificationToken"] = rvt1_el.get("value", "")
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
        for hop in range(MAX_FORM_HOPS):
            if self.session.redirect_handler.oidc_code:
                break
            qs = parse_qs(urlparse(cur.url).query)
            if "code" in qs:
                self.session.redirect_handler.oidc_code = qs["code"][0]
                break
            soup = BeautifulSoup(cur.text, "html.parser")
            form = soup.find("form")
            if not form:
                break
            if _is_interactive_account_page(cur.url, form, cur.text):
                raise oidc_code_missing_error(cur.url, cur.text)
            # Do not restart login by re-posting the ExternalLogin provider form.
            if _is_external_provider_form(form) and not _is_auto_post_form(form):
                raise oidc_code_missing_error(cur.url, cur.text)
            if _is_external_provider_form(form) and "SAMLResponse" not in _form_payload(form):
                raise oidc_code_missing_error(cur.url, cur.text)
            if not _is_auto_post_form(form):
                raise oidc_code_missing_error(cur.url, cur.text)
            action_url = _form_action_url(form, cur.url)
            payload = _form_payload(form)
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
            raise oidc_code_missing_error(cur.url, getattr(cur, "text", "") or "")

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
