"""Lovelace card install and cache-busting resource URL."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from kmd_easy_energy.const import CARD_JS_FILENAME, CARD_RESOURCE_PATH
from kmd_easy_energy.frontend_card import (
    async_ensure_lovelace_card_resource,
    card_resource_url,
    install_frontend_card,
    integration_version,
    is_our_card_resource_url,
)

ROOT = Path(__file__).resolve().parents[1]


def test_integration_version_matches_manifest() -> None:
    assert integration_version() == "1.0.1"
    assert card_resource_url() == "/local/js/kmd-easy-energy-card.js?v=1.0.1"
    assert card_resource_url("0.3.0") == "/local/js/kmd-easy-energy-card.js?v=0.3.0"


@pytest.mark.parametrize(
    ("url", "ours"),
    [
        ("/local/js/kmd-easy-energy-card.js", True),
        ("/local/js/kmd-easy-energy-card.js?v=0.2.0", True),
        ("/local/js/kmd-easy-energy-card.js?v=0.3.2", True),
        ("http://homeassistant.local:8123/local/js/kmd-easy-energy-card.js?v=1", True),
        ("/local/js/kmd-easy-energy-card.js#frag", True),
        ("/local/js/other-card.js", False),
        ("/hacsfiles/kmd-fjernvarme-ha/kmd-easy-energy-card.js", False),
        ("", False),
    ],
)
def test_is_our_card_resource_url(url: str, ours: bool) -> None:
    assert is_our_card_resource_url(url) is ours


def test_install_frontend_card_copies_and_overwrites(tmp_path: Path) -> None:
    src = ROOT / "custom_components/kmd_easy_energy/frontend" / CARD_JS_FILENAME
    dst_dir = tmp_path / "www" / "js"
    written = install_frontend_card(dst_dir)
    assert written == dst_dir / CARD_JS_FILENAME
    assert written.read_bytes() == src.read_bytes()
    written.write_text("// stale v0.2.0 card\n")
    again = install_frontend_card(dst_dir)
    assert again.read_bytes() == src.read_bytes()


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
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert url == "/local/js/kmd-easy-energy-card.js?v=0.3.2"


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
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert url == "/local/js/kmd-easy-energy-card.js?v=0.3.2"
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
    url = asyncio.run(async_ensure_lovelace_card_resource(hass, "0.3.2"))
    assert store.updated == [("a", {"url": url})]
    assert store.deleted == ["b"]
    assert [item["id"] for item in store.items] == ["a"]


def test_readme_documents_versioned_resource() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "/local/js/kmd-easy-energy-card.js?v=1.0.1" in readme
    assert "31 dage" in readme or "31 days" in readme
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "## [1.0.1]" in changelog
    assert CARD_RESOURCE_PATH in changelog or "kmd-easy-energy-card.js?v=" in changelog
