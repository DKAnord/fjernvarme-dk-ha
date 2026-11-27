"""OIDC discovery and post-MitID form handling — no live MitID or tokens."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from kmd_easy_energy.api.kmd_mitid_auth import (
    DEFAULT_KREDSLOB,
    DEFAULT_MINFORSYNING2,
    KMDMitIDAuthenticator,
    MSG_DISCOVERY_FAILED,
    MSG_MITID_PARALLEL_SESSION,
    MSG_MITID_USER_NOT_FOUND,
    MSG_OIDC_GENERIC,
    MSG_PORTAL_FIRST,
    _extract_page_feedback,
    _form_action_url,
    _form_payload,
    _is_auto_post_form,
    _is_discovery_follow_url,
    _is_external_provider_form,
    _is_interactive_account_page,
    _parse_mf2_utility_code,
    _parse_oidc_from_js,
    _parse_oidc_from_url,
    _sanitize_feedback,
    oidc_code_missing_error,
)

KREDSLOB_CLIENT = "48A281C0-95CB-48EE-A018-3F7941E6D46A"
MF2_CLIENT = "1DA5CFAF-F67F-4DA1-A1A6-513A7768F994"

IKAST_HOME = """<!doctype html><html><body>
<a href="https://energi-ikast.dk/kundeservice/minforsyning/">minForsyning</a>
<a href="https://minforsyning-2.kmd.dk/?plant=464&amp;utility=0&amp;type=71&amp;GUID=58c79f1c-54e9-4c5d-a5d0-eec5f9deb127">Åbn Min Forsyning</a>
</body></html>"""

STRUER_PAGE = """<!doctype html><html><body>
<a href="https://easy-energy-identity.kmd.dk/Identity/Account/Sign/Login?ReturnUrl=%2Foidc%2Fauthorize%3Fclient_id%3D1DA5CFAF-F67F-4DA1-A1A6-513A7768F994%26redirect_uri%3Dhttps%253A%252F%252Fminforsyning-2.kmd.dk%252Flogin%26response_type%3Dcode%26scope%3Dopenid%2520profile%2520pluginapi_int%26utility%3D0460000%26login_type%3Dmf%26post_logout_redirect_uri%3Dhttps%253A%252F%252Fminforsyning-2.kmd.dk%252Flogin">Min Forsyning</a>
</body></html>"""

PLUGIN_PAGE = """<!doctype html><html><body>
<script src="https://easy-energy-plugin-settings.kmd.dk/plugin/js/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"></script>
</body></html>"""

PLUGIN_JS = (
    'OIDCClientId:"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",'
    'OIDCRedirectUri:"https://example-utility.dk/app",'
    'OIDCPostLogoutRedirectUri:"https://example-utility.dk"'
)

SAML_FORM = """
<form method="post" action="https://idpproxy.identity.kmd.dk/SAML">
  <input type="hidden" name="SAMLResponse" value="PHNhbWw+" />
  <input type="hidden" name="RelayState" value="abc" />
</form>
"""

EMPTY_ACTION_AUTOPOST = """
<html><body>
<form method="post">
  <input type="hidden" name="token" value="from-callback" />
  <input type="hidden" name="__RequestVerificationToken" value="rvt" />
</form>
</body></html>
"""

EXTERNAL_REGISTER = """
<html><head><title>Registrer</title></head><body>
<h1>Opret konto</h1>
<form method="post" asp-page-handler="Confirmation">
  <input type="hidden" name="__RequestVerificationToken" value="rvt" />
  <input type="email" name="Input.Email" value="anna@example.com" />
  <button type="submit">Register</button>
  <p>Accepter vilkår for at fortsætte.</p>
</form>
</body></html>
"""

EXTERNAL_PROVIDER = """
<html><body>
<form id="external-account" method="post" action="/Identity/Account/ExternalLogin">
  <input type="hidden" name="__RequestVerificationToken" value="rvt" />
  <button type="submit" name="provider" value="NemLogIn">NemLog-in</button>
</form>
</body></html>
"""


class FakeResp(SimpleNamespace):
    def raise_for_status(self) -> None:
        if getattr(self, "status_code", 200) >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeSession:
    """URL-scripted session; records GETs so tests can assert no fallback crawl of Kredsløb."""

    def __init__(self, pages: dict[str, FakeResp]) -> None:
        self.pages = pages
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict | None]] = []
        self.redirect_handler = SimpleNamespace(oidc_code=None)

    def get(self, url: str, **kw):
        self.gets.append(url)
        for key, resp in self.pages.items():
            if url == key or url.startswith(key):
                return resp
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, **kw):
        self.posts.append((url, kw.get("data")))
        for key, resp in self.pages.items():
            if url == key or url.startswith(key):
                return resp
        raise AssertionError(f"unexpected POST {url}")

    def get_cookie(self, name: str, default: str = "") -> str:
        return default


def _auth_with(session: FakeSession) -> KMDMitIDAuthenticator:
    auth = KMDMitIDAuthenticator.__new__(KMDMitIDAuthenticator)
    auth.timeout = 5
    auth.session = session
    return auth


def test_kredslob_discovery_is_local_and_keeps_plugin_client() -> None:
    session = FakeSession({})
    auth = _auth_with(session)
    cfg = auth._discover_oidc_config("https://minvarme.kredslob.dk/")
    assert cfg["client_id"] == KREDSLOB_CLIENT
    assert cfg["login_type"] == "plugin"
    assert cfg["utility_code"] == "0455000"
    assert session.gets == []


def test_energi_ikast_homepage_discovers_mf2_not_kredslob() -> None:
    session = FakeSession(
        {"https://energi-ikast.dk/": FakeResp(status_code=200, text=IKAST_HOME, url="https://energi-ikast.dk/")}
    )
    cfg = _auth_with(session)._discover_oidc_config("https://energi-ikast.dk/")
    assert cfg["client_id"] == MF2_CLIENT
    assert cfg["client_id"] != KREDSLOB_CLIENT
    assert cfg["login_type"] == "mf"
    assert cfg["utility_code"] == "0464000"
    assert cfg["redirect_uri"] == "https://minforsyning-2.kmd.dk/login"
    # Must not fall back to a Kredsløb portal fetch.
    assert all("kredslob" not in u and KREDSLOB_CLIENT.lower() not in u.lower() for u in session.gets)


def test_struer_authorize_link_is_parsed() -> None:
    session = FakeSession(
        {
            "https://struerenergi.dk/selvbetjening/": FakeResp(
                status_code=200, text=STRUER_PAGE, url="https://struerenergi.dk/selvbetjening/"
            )
        }
    )
    cfg = _auth_with(session)._discover_oidc_config("https://struerenergi.dk/selvbetjening/")
    assert cfg["client_id"] == MF2_CLIENT
    assert cfg["login_type"] == "mf"
    assert cfg["utility_code"] == "0460000"
    assert cfg["redirect_uri"] == "https://minforsyning-2.kmd.dk/login"


def test_beof_redirect_to_mf2_uses_plant_from_final_url() -> None:
    session = FakeSession(
        {
            "https://minforsyning.beof.dk/": FakeResp(
                status_code=200,
                text="<!doctype html><title>Minforsyning</title><app-root></app-root>",
                url="https://minforsyning-2.kmd.dk/?plant=176&utility=0&plus=True",
            )
        }
    )
    cfg = _auth_with(session)._discover_oidc_config("https://minforsyning.beof.dk/")
    assert cfg["utility_code"] == "0176000"
    assert cfg["client_id"] == MF2_CLIENT
    assert cfg["login_type"] == "mf"


def test_albertslund_selvbetjening_discovers_mf2_plant_165() -> None:
    albertslund_page = (
        '<a class="btn" href="https://minforsyning-2.kmd.dk/Login?plant=165&amp;utility=0">Log ind</a>'
    )
    session = FakeSession(
        {
            "https://forsyning.albertslund.dk/selvbetjening": FakeResp(
                status_code=200,
                text=albertslund_page,
                url="https://forsyning.albertslund.dk/selvbetjening",
            )
        }
    )
    cfg = _auth_with(session)._discover_oidc_config("https://forsyning.albertslund.dk/selvbetjening")
    assert cfg["client_id"] == MF2_CLIENT
    assert cfg["login_type"] == "mf"
    assert cfg["utility_code"] == "0165000"


def test_kalundborg_selvbetjening_discovers_mf2_plant_177() -> None:
    kalundborg_page = (
        '<a href="https://minforsyning-2.kmd.dk/?plant=177&amp;utility=1&amp;plus=True">Login Min Forsyning</a>'
    )
    session = FakeSession(
        {
            "https://kalfor.dk/selvbetjening/min-forsyning": FakeResp(
                status_code=200,
                text=kalundborg_page,
                url="https://kalfor.dk/selvbetjening/min-forsyning",
            )
        }
    )
    cfg = _auth_with(session)._discover_oidc_config("https://kalfor.dk/selvbetjening/min-forsyning")
    assert cfg["client_id"] == MF2_CLIENT
    assert cfg["login_type"] == "mf"
    assert cfg["utility_code"] == "0177001"


def test_plugin_js_discovery_still_works() -> None:
    session = FakeSession(
        {
            "https://other-utility.dk/": FakeResp(status_code=200, text=PLUGIN_PAGE, url="https://other-utility.dk/"),
            "https://easy-energy-plugin-settings.kmd.dk/plugin/js/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": FakeResp(
                status_code=200, text=PLUGIN_JS, url="https://easy-energy-plugin-settings.kmd.dk/plugin/js/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            ),
            "https://easy-energy-plugin-api.kmd.dk/api/settings/plugins/client/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": FakeResp(
                status_code=200,
                text="{}",
                url="https://easy-energy-plugin-api.kmd.dk/api/settings/plugins/client/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                _json={"PlantNumber": 12, "UtilityNumber": 0},
            ),
        }
    )
    cfg = _auth_with(session)._discover_oidc_config("https://other-utility.dk/")
    assert cfg["client_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert cfg["utility_code"] == "0012000"
    assert cfg["login_type"] == "plugin"
    assert cfg["redirect_uri"] == "https://example-utility.dk/app"


def test_unknown_portal_does_not_fall_back_to_kredslob() -> None:
    session = FakeSession(
        {
            "https://unknown-varme.dk/": FakeResp(
                status_code=200, text="<html><body>Velkommen</body></html>", url="https://unknown-varme.dk/"
            )
        }
    )
    with pytest.raises(RuntimeError, match="Kunne ikke finde login-oplysningerne") as exc:
        _auth_with(session)._discover_oidc_config("https://unknown-varme.dk/")
    assert str(exc.value) == MSG_DISCOVERY_FAILED
    assert KREDSLOB_CLIENT not in str(exc.value)


def test_parse_helpers_ikast_and_js() -> None:
    assert (
        _parse_mf2_utility_code(
            "https://minforsyning-2.kmd.dk/?plant=464&utility=0&type=71&GUID=58c79f1c-54e9-4c5d-a5d0-eec5f9deb127"
        )
        == "0464000"
    )
    parsed = _parse_oidc_from_js(
        'OIDCClientId:"1DA5CFAF-F67F-4DA1-A1A6-513A7768F994",'
        'OIDCRedirectUri:"https://minforsyning-2.kmd.dk/login",'
        'OIDCPostLogoutRedirectUri:"https://minforsyning-2.kmd.dk/login"'
    )
    assert parsed is not None
    assert parsed["client_id"] == MF2_CLIENT


def test_sanitize_feedback_strips_pii() -> None:
    raw = "Fejl til anna@example.com CPR 010203-1234 token ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"
    out = _sanitize_feedback(raw)
    assert "anna@" not in out and "010203" not in out
    assert "[email]" in out and "[id]" in out and "[redacted]" in out


def test_extract_page_feedback_uses_remote_error_and_heading() -> None:
    html = "<html><head><title>Login</title></head><body><h1>Adgang nægtet</h1></body></html>"
    url = "https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLogin?remoteError=access_denied"
    fb = _extract_page_feedback(html, url)
    assert "access_denied" in fb
    assert "Adgang nægtet" in fb


def test_empty_action_is_auto_post_to_current_url() -> None:
    form = BeautifulSoup(EMPTY_ACTION_AUTOPOST, "html.parser").find("form")
    assert _is_auto_post_form(form)
    assert not _is_external_provider_form(form)
    action = _form_action_url(
        form, "https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLogin?returnUrl=/oidc/authorize"
    )
    assert action.startswith("https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLogin")
    payload = _form_payload(form)
    assert payload["token"] == "from-callback"


def test_saml_form_is_auto_post() -> None:
    form = BeautifulSoup(SAML_FORM, "html.parser").find("form")
    assert _is_auto_post_form(form)
    assert _form_payload(form)["SAMLResponse"] == "PHNhbWw+"
    assert _form_action_url(form, "https://nemlog-in.mitid.dk/") == "https://idpproxy.identity.kmd.dk/SAML"


def test_register_form_is_interactive_and_not_auto_posted() -> None:
    form = BeautifulSoup(EXTERNAL_REGISTER, "html.parser").find("form")
    url = "https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLogin?returnUrl=%2Foidc%2Fauthorize%3Fclient_id%3D48A281C0"
    assert not _is_auto_post_form(form)
    assert _is_interactive_account_page(url, form, EXTERNAL_REGISTER)
    err = oidc_code_missing_error(url, EXTERNAL_REGISTER)
    assert str(err) == MSG_PORTAL_FIRST
    # The card must not be shown the raw OIDC URL or the user's email.
    assert "client_id" not in str(err)
    assert "anna@example.com" not in str(err)


def test_provider_form_after_mitid_is_not_resubmitted() -> None:
    form = BeautifulSoup(EXTERNAL_PROVIDER, "html.parser").find("form")
    url = "https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLogin?returnUrl=%2Foidc%2Fauthorize%3Fclient_id%3D48A281C0-95CB-48EE-A018-3F7941E6D46A"
    assert _is_external_provider_form(form)
    err = oidc_code_missing_error(url, EXTERNAL_PROVIDER)
    assert str(err) == MSG_PORTAL_FIRST
    assert KREDSLOB_CLIENT not in str(err)


def test_generic_missing_code_includes_sanitised_heading() -> None:
    html = "<html><head><title>Der opstod en fejl</title></head><body><p>prøv igen</p></body></html>"
    url = "https://easy-energy-identity.kmd.dk/error"
    err = oidc_code_missing_error(url, html)
    assert MSG_OIDC_GENERIC in str(err)
    assert "Der opstod en fejl" in str(err)


def test_form_payload_includes_named_submit_button() -> None:
    html = """<form action="/go" method="post">
      <input type="hidden" name="x" value="1" />
      <button type="submit" name="provider" value="NemLogIn">Log ind</button>
    </form>"""
    form = BeautifulSoup(html, "html.parser").find("form")
    assert _form_payload(form) == {"x": "1", "provider": "NemLogIn"}


def test_finalize_follows_empty_action_auto_post_then_exchanges_code() -> None:
    """SAML-style hop with empty action, then a redirect-like page that already has ?code=."""
    session = FakeSession({})
    session.redirect_handler.oidc_code = None
    nemlogin = FakeResp(
        status_code=200,
        text=EMPTY_ACTION_AUTOPOST,
        url="https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLoginCallback",
    )
    after_post = FakeResp(
        status_code=200,
        text="<html></html>",
        url="https://minforsyning-2.kmd.dk/login?code=SYNTHETIC_CODE&state=s",
    )
    token = FakeResp(
        status_code=200,
        text='{"access_token":"SYNTHETIC_ACCESS"}',
        url="https://easy-energy-identity.kmd.dk/oidc/token",
        _json={"access_token": "SYNTHETIC_ACCESS"},
    )

    def post(url, **kw):
        session.posts.append((url, kw.get("data")))
        if "nemlog-in.mitid.dk" in url:
            return nemlogin
        if "ExternalLoginCallback" in url:
            return after_post
        if url.endswith("/oidc/token"):
            return token
        raise AssertionError(url)

    session.post = post  # type: ignore[method-assign]
    auth = _auth_with(session)
    auth._client_id = MF2_CLIENT
    auth._redirect_uri = DEFAULT_MINFORSYNING2["redirect_uri"]
    auth._code_verifier = "verifier"
    auth._verification_token = "rvt"
    auth.mitid_client = MagicMock()
    auth.mitid_client.finalize_authentication_and_get_authorization_code.return_value = "mitid-auth"
    access = auth.finalize_and_exchange_token()
    assert access == "SYNTHETIC_ACCESS"
    # First hop posted to the current URL (empty action), not aborted.
    assert any("ExternalLoginCallback" in u for u, _ in session.posts)
    # Token exchange used the captured code (never logged / returned as the error).
    token_post = [data for u, data in session.posts if u.endswith("/oidc/token")][0]
    assert token_post["code"] == "SYNTHETIC_CODE"


def test_finalize_stops_on_external_login_register_page() -> None:
    session = FakeSession({})
    session.redirect_handler.oidc_code = None
    session.post = (  # type: ignore[method-assign]
        lambda url, **kw: FakeResp(
            status_code=200,
            text=EXTERNAL_REGISTER,
            url="https://easy-energy-identity.kmd.dk/Identity/Account/ExternalLogin?returnUrl=%2Foidc%2Fauthorize%3Fclient_id%3D48A281C0",
        )
    )
    auth = _auth_with(session)
    auth._client_id = KREDSLOB_CLIENT
    auth._redirect_uri = DEFAULT_KREDSLOB["redirect_uri"]
    auth._code_verifier = "verifier"
    auth._verification_token = "rvt"
    auth.mitid_client = MagicMock()
    auth.mitid_client.finalize_authentication_and_get_authorization_code.return_value = "mitid-auth"
    with pytest.raises(RuntimeError, match="logger ind én gang") as exc:
        auth.finalize_and_exchange_token()
    assert str(exc.value) == MSG_PORTAL_FIRST
    # Must not POST the register form (that would try to create an account).
    assert session.posts == [] or all("Input.Email" not in str(data) for _, data in session.posts)


def _start_session_with_browser_client(err: Exception) -> None:
    import base64
    import json

    aux = base64.b64encode(
        json.dumps(
            {
                "coreClient": {"checksum": base64.b64encode(b"\x01\x02").decode()},
                "parameters": {"authenticationSessionId": "sid-1"},
            }
        ).encode()
    ).decode()
    session = FakeSession(
        {
            "https://easy-energy-identity.kmd.dk/oidc/authorize": FakeResp(
                status_code=200,
                text='<input name="__RequestVerificationToken" value="rvt2" />',
                url="https://nemlog-in.mitid.dk/login/mitid",
            ),
            "https://nemlog-in.mitid.dk/login/mitid/initialize": FakeResp(
                status_code=200,
                text="{}",
                url="https://nemlog-in.mitid.dk/login/mitid/initialize",
                _json={"Aux": aux},
            ),
        }
    )
    auth = _auth_with(session)
    auth._client_id = KREDSLOB_CLIENT
    auth._redirect_uri = DEFAULT_KREDSLOB["redirect_uri"]
    client = MagicMock()
    if "parallel" in str(err).lower():
        client.identify_as_user_and_get_available_authenticators.return_value = {"APP": "MitID"}
        client.start_app_authentication.side_effect = err
    else:
        client.identify_as_user_and_get_available_authenticators.side_effect = err
    with patch("kmd_easy_energy.api.kmd_mitid_auth.BrowserClient", return_value=client):
        auth.start_session("https://minvarme.kredslob.dk/", "secret-mitid-user-42")


def test_start_session_translates_identity_not_found_without_leaking_username() -> None:
    err = Exception(b'{"errorCode":"control.identity_not_found"}')
    with pytest.raises(RuntimeError) as exc:
        _start_session_with_browser_client(err)
    assert str(exc.value) == MSG_MITID_USER_NOT_FOUND
    assert "secret-mitid-user-42" not in str(exc.value)


def test_start_session_translates_parallel_app_sessions() -> None:
    err = Exception("Parallel app sessions detected")
    with pytest.raises(RuntimeError) as exc:
        _start_session_with_browser_client(err)
    assert str(exc.value) == MSG_MITID_PARALLEL_SESSION


def test_custom_srp_uses_secrets_randbits() -> None:
    """SRP ephemeral secret `a` must use cryptographic `secrets.randbits(256)`."""
    import importlib
    from pathlib import Path

    custom_srp_mod = importlib.import_module("kmd_easy_energy.mitid_browserclient.CustomSRP")

    assert not hasattr(custom_srp_mod, "random")
    src = Path(custom_srp_mod.__file__).read_text()
    assert "secrets.randbits(256)" in src
    assert "random.getrandbits" not in src

    with patch.object(custom_srp_mod.secrets, "randbits", return_value=123456789) as mock_randbits:
        srp = custom_srp_mod.CustomSRP()
        res = srp.SRPStage1()

    mock_randbits.assert_called_once_with(256)
    assert srp.a == 123456789
    assert res == format(pow(2, 123456789, srp.N), "x")


def test_browser_client_never_logs_mitid_user_id(caplog: pytest.LogCaptureFixture) -> None:
    """BrowserClient must never write the MitID user ID to logger output on failure."""
    import logging

    from kmd_easy_energy.mitid_browserclient.BrowserClient import BrowserClient

    secret_uid = "sensitive-mitid-user-98765"

    def _new_client(put_resp=None, post_resp=None) -> BrowserClient:
        client = BrowserClient.__new__(BrowserClient)
        client.authentication_session_id = "sess-1"
        client.current_authenticator_type = "TOKEN"
        client.combination_ids = {}
        client.user_id = secret_uid
        client.session = SimpleNamespace(
            put=lambda *a, **k: put_resp,
            post=lambda *a, **k: post_resp,
        )
        return client

    with caplog.at_level(
        logging.DEBUG,
        logger="kmd_easy_energy.mitid_browserclient.BrowserClient",
    ):
        # 1) PUT fails with control.identity_not_found -> triggers lines 294 & 301
        put_400 = SimpleNamespace(
            status_code=400,
            content=b'{"errorCode":"control.identity_not_found"}',
            json=lambda: {"errorCode": "control.identity_not_found"},
        )
        with pytest.raises(Exception):
            _new_client(put_resp=put_400).identify_as_user_and_get_available_authenticators(secret_uid)

        # 2) PUT succeeds, POST /next fails -> triggers line 319
        put_200 = SimpleNamespace(status_code=200)
        post_500 = SimpleNamespace(status_code=500, content=b"err")
        with pytest.raises(Exception):
            _new_client(put_resp=put_200, post_resp=post_500).identify_as_user_and_get_available_authenticators(
                secret_uid
            )

        # 3) __select_authenticator POST /next fails -> triggers line 433
        with pytest.raises(Exception):
            _new_client(post_resp=post_500)._BrowserClient__select_authenticator("APP")

    error_records = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert len(error_records) >= 4
    assert secret_uid not in caplog.text


def test_direct_mf2_url_discovers_locally_without_http_get() -> None:
    session = FakeSession({})
    cfg = _auth_with(session)._discover_oidc_config(
        "https://minforsyning-2.kmd.dk/?plant=120&utility=0&plus=True"
    )
    assert cfg["client_id"] == MF2_CLIENT
    assert cfg["login_type"] == "mf"
    assert cfg["utility_code"] == "0120000"
    assert session.gets == []


def test_discovery_ignores_invalid_urls_with_whitespace() -> None:
    assert _is_discovery_follow_url("https://www.nfs.as/min-forsyning/", "var K=1") is False

    # Page with an invalid relative href containing whitespace should not be fetched.
    bad_only = FakeSession(
        {
            "https://www.nfs.as/min-forsyning/": FakeResp(
                status_code=200,
                text='<html><body><a href="var K=1">min-forsyning</a></body></html>',
                url="https://www.nfs.as/min-forsyning/",
            )
        }
    )
    with pytest.raises(RuntimeError, match="Kunne ikke finde login-oplysningerne"):
        _auth_with(bad_only)._discover_oidc_config("https://www.nfs.as/min-forsyning/")
    assert bad_only.gets == ["https://www.nfs.as/min-forsyning/"]

    # If a valid MF2 link is also present alongside the invalid href, discovery succeeds.
    with_mf2 = FakeSession(
        {
            "https://www.nfs.as/min-forsyning/": FakeResp(
                status_code=200,
                text=(
                    '<a href="var K=1">min-forsyning</a>'
                    '<a href="https://minforsyning-2.kmd.dk/?plant=120&amp;utility=0&amp;plus=True">Login</a>'
                ),
                url="https://www.nfs.as/min-forsyning/",
            )
        }
    )
    cfg = _auth_with(with_mf2)._discover_oidc_config("https://www.nfs.as/min-forsyning/")
    assert cfg["utility_code"] == "0120000"
    assert cfg["client_id"] == MF2_CLIENT
