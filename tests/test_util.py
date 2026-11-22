"""Unit tests for privacy, unique_id, and cache helpers."""

from __future__ import annotations

from pathlib import Path

from kmd_easy_energy.util import (
    cache_has_sensor_data,
    delete_legacy_www_cache,
    redact_secret,
    redact_url,
    sanitize_cache,
    unique_id_for,
)


def test_redact_url_oidc_code() -> None:
    url = "https://minvarme.kredslob.dk/min-varme?code=SECRETVALUE123&state=abc"
    out = redact_url(url)
    assert "SECRETVALUE123" not in out
    assert "code=[REDACTED]" in out
    assert "state=abc" in out


def test_redact_url_tokens_and_fragment() -> None:
    url = "https://example/cb#access_token=eyJhbGciOi&id_token=xyz&foo=1"
    out = redact_url(url)
    assert "eyJhbGciOi" not in out
    assert "id_token=[REDACTED]" in out


def test_redact_bearer() -> None:
    out = redact_secret("Authorization: Bearer super-secret-token")
    assert "super-secret-token" not in out
    assert "Bearer [REDACTED]" in out


def test_sanitize_cache_strips_otp_and_token() -> None:
    clean = sanitize_cache(
        {
            "annual": {"2026": 100},
            "mitid_otp_code": "1234",
            "mitid_qr_svg": "<svg />",
            "access_token": "abc",
            "sync_state": "otp_ready",
            "sync_message": "secret",
        }
    )
    assert "mitid_otp_code" not in clean
    assert "mitid_qr_svg" not in clean
    assert "access_token" not in clean
    assert clean["sync_state"] == "idle"
    assert clean["sync_message"] == ""
    assert clean["annual"] == {"2026": 100}


def test_unique_id_for_known_and_custom() -> None:
    assert unique_id_for("kredslob") == "kredslob"
    assert unique_id_for("Kredslob", "https://minvarme.kredslob.dk/") == "kredslob"
    assert unique_id_for("custom", "https://www.example-varme.dk/login") == "custom:example-varme.dk"
    assert unique_id_for("custom", "") == "custom"


def test_cache_has_sensor_data() -> None:
    assert not cache_has_sensor_data({})
    assert not cache_has_sensor_data(None)
    assert cache_has_sensor_data({"annual": {"2026": 1}})
    assert cache_has_sensor_data({"daily": {"total": 12}})
    assert cache_has_sensor_data({"hdd_7d": 8.5})


def test_delete_legacy_www_cache(tmp_path: Path) -> None:
    f = tmp_path / "kmd_easy_energy_cache_kredslob.json"
    f.write_text("{}", encoding="utf-8")
    other = tmp_path / "data.json"
    other.write_text("keep", encoding="utf-8")
    delete_legacy_www_cache([f])
    assert not f.exists()
    assert other.read_text() == "keep"
