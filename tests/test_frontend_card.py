"""Lovelace card install and cache-busting resource URL."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from kmd_easy_energy.const import CARD_JS_FILENAME, CARD_RESOURCE_PATH, LEGACY_CARD_RESOURCE_PATH
from kmd_easy_energy import frontend_card
from kmd_easy_energy.frontend_card import (
    async_ensure_lovelace_card_resource,
    async_register_frontend_card_static_path,
    card_resource_url,
    integration_version,
    is_our_card_resource_url,
)

ROOT = Path(__file__).resolve().parents[1]


def test_integration_version_matches_manifest() -> None:
    assert integration_version() == "1.3.27"
    assert card_resource_url() == "/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27"
    assert card_resource_url("0.3.0") == "/kmd_easy_energy/kmd-easy-energy-card.js?v=0.3.0"


@pytest.mark.parametrize(
    ("url", "ours"),
    [
        ("/kmd_easy_energy/kmd-easy-energy-card.js", True),
        ("/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27", True),
        ("http://homeassistant.local:8123/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27", True),
        ("/local/js/kmd-easy-energy-card.js", True),
        ("/local/js/kmd-easy-energy-card.js?v=0.2.0", True),
        ("/local/js/kmd-easy-energy-card.js?v=1.2.9", True),
        ("http://homeassistant.local:8123/local/js/kmd-easy-energy-card.js?v=1", True),
        ("/local/js/kmd-easy-energy-card.js#frag", True),
        ("/local/js/other-card.js", False),
        ("/kmd_easy_energy/other-card.js", False),
        ("/hacsfiles/kmd-fjernvarme-ha/kmd-easy-energy-card.js", False),
        ("", False),
    ],
)
def test_is_our_card_resource_url(url: str, ours: bool) -> None:
    assert is_our_card_resource_url(url) is ours


def test_does_not_export_install_frontend_card() -> None:
    assert not hasattr(frontend_card, "install_frontend_card")
    assert CARD_RESOURCE_PATH == f"/kmd_easy_energy/{CARD_JS_FILENAME}"
    assert LEGACY_CARD_RESOURCE_PATH == f"/local/js/{CARD_JS_FILENAME}"
    fc_src = (ROOT / "custom_components/kmd_easy_energy/frontend_card.py").read_text()
    init_src = (ROOT / "custom_components/kmd_easy_energy/__init__.py").read_text()
    assert "install_frontend_card" not in fc_src
    assert "install_frontend_card" not in init_src
    assert "www/js" not in init_src


class _FakeStorage:
    """Minimal ResourceStorageCollection stand-in."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = list(items or [])
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    async def async_get_info(self) -> dict[str, int]:
        return {"resources": len(self.items)}

    def async_items(self) -> list[dict]:
        return list(self.items)

    async def async_create_item(self, data: dict) -> dict:
        item = {"id": f"id-{len(self.items) + 1}", "type": data.get("res_type"), "url": data["url"]}
        self.items.append(item)
        self.created.append(data)
        return item

    async def async_update_item(self, item_id: str, updates: dict) -> dict:
        self.updated.append((item_id, updates))
        for item in self.items:
            if item["id"] == item_id:
                if "url" in updates:
                    item["url"] = updates["url"]
                if "res_type" in updates:
                    item["type"] = updates["res_type"]
                return item
        raise KeyError(item_id)

    async def async_delete_item(self, item_id: str) -> None:
        self.deleted.append(item_id)
        self.items = [item for item in self.items if item["id"] != item_id]


def test_ensure_resource_skips_when_lovelace_missing() -> None:
    hass = SimpleNamespace(data={})
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "1.3.27"))
    assert url == "/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27"


def test_ensure_resource_yaml_mode_warns(caplog: pytest.LogCaptureFixture) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    yaml_resources = SimpleNamespace(
        async_items=lambda: [{"url": "/local/js/kmd-easy-energy-card.js", "type": "module"}]
    )
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=yaml_resources)})
    with caplog.at_level(logging.WARNING):
        url = asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert url.endswith("?v=0.3.2")
    assert any("YAML mode" in rec.message for rec in caplog.records)


def test_ensure_resource_yaml_mode_silent_when_current(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    target = card_resource_url("0.3.2")
    yaml_resources = SimpleNamespace(
        async_items=lambda: [{"url": target, "type": "module"}]
    )
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=yaml_resources)})
    with caplog.at_level(logging.WARNING, logger="kmd_easy_energy.frontend_card"):
        asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert not any("YAML mode" in rec.message for rec in caplog.records)


def _patch_storage_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make isinstance(..., ResourceStorageCollection) true for _FakeStorage.

    ``async_ensure_lovelace_card_resource`` imports the class inside the
    function, so patch it on the HA module before the call.
    """
    import homeassistant.components.lovelace.resources as res_mod

    monkeypatch.setattr(res_mod, "ResourceStorageCollection", _FakeStorage)


def test_ensure_resource_creates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    _patch_storage_class(monkeypatch)
    store = _FakeStorage([])
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=store)})
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "1.3.27"))
    assert url == "/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27"
    assert store.created == [{"res_type": "module", "url": url}]
    assert store.items[0]["url"] == url
    assert store.items[0]["type"] == "module"


def test_ensure_resource_updates_unversioned_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    _patch_storage_class(monkeypatch)
    store = _FakeStorage(
        [{"id": "abc", "type": "module", "url": "/local/js/kmd-easy-energy-card.js"}]
    )
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=store)})
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert store.updated == [("abc", {"url": url})]
    assert store.items[0]["url"] == url
    assert not store.created
    assert not store.deleted


def test_ensure_resource_updates_old_version_and_fixes_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    _patch_storage_class(monkeypatch)
    store = _FakeStorage(
        [{"id": "abc", "type": "js", "url": "/local/js/kmd-easy-energy-card.js?v=0.2.0"}]
    )
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=store)})
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert store.updated == [("abc", {"url": url, "res_type": "module"})]
    assert store.items[0]["type"] == "module"


def test_ensure_resource_noop_when_current(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    _patch_storage_class(monkeypatch)
    target = card_resource_url("0.3.2")
    store = _FakeStorage([{"id": "abc", "type": "module", "url": target}])
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=store)})
    asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert store.updated == []
    assert store.created == []
    assert store.deleted == []


def test_ensure_resource_removes_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    _patch_storage_class(monkeypatch)
    store = _FakeStorage(
        [
            {"id": "a", "type": "module", "url": "/local/js/kmd-easy-energy-card.js"},
            {"id": "b", "type": "module", "url": "/local/js/kmd-easy-energy-card.js?v=0.2.0"},
        ]
    )
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=store)})
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "1.3.20"))
    assert store.updated == [("a", {"url": url})]
    assert store.deleted == ["b"]
    assert [item["id"] for item in store.items] == ["a"]


def test_ensure_resource_migrates_legacy_local_path_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.components.lovelace import LOVELACE_DATA

    _patch_storage_class(monkeypatch)
    store = _FakeStorage(
        [
            {"id": "legacy", "type": "module", "url": "/local/js/kmd-easy-energy-card.js?v=1.2.8"},
            {"id": "newer", "type": "module", "url": "/kmd_easy_energy/kmd-easy-energy-card.js?v=1.2.9"},
        ]
    )
    hass = SimpleNamespace(data={LOVELACE_DATA: SimpleNamespace(resources=store)})
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "1.3.27"))
    assert url == "/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27"
    assert store.updated == [("legacy", {"url": url})]
    assert store.deleted == ["newer"]
    assert store.items == [{"id": "legacy", "type": "module", "url": url}]


def test_readme_documents_versioned_resource() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.27" in readme
    assert "31 dage" in readme or "31 days" in readme
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "## [1.3.27]" in changelog
    assert CARD_RESOURCE_PATH in changelog or "kmd-easy-energy-card.js?v=" in changelog


def test_register_frontend_card_static_path_is_idempotent() -> None:
    recorded = []

    async def fake_register(configs):
        recorded.append(list(configs))

    hass = SimpleNamespace(data={}, http=SimpleNamespace(async_register_static_paths=fake_register))
    assert asyncio.run(async_register_frontend_card_static_path(hass)) is True
    assert asyncio.run(async_register_frontend_card_static_path(hass)) is True
    assert len(recorded) == 1
    assert recorded[0][0].url_path == CARD_RESOURCE_PATH
    assert recorded[0][0].cache_headers is True

    hass_no_http = SimpleNamespace(data={})
    assert asyncio.run(async_register_frontend_card_static_path(hass_no_http)) is False
