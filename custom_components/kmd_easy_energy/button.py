"""Button platform for KMD Easy Energy."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KMDEasyEnergyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KMD Easy Energy button entities."""
    coordinator: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KMDSyncButton(coordinator, entry)])


class KMDSyncButton(CoordinatorEntity[KMDEasyEnergyCoordinator], ButtonEntity):
    """1-tap native MitID sync button for KMD Easy Energy."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync"
    _attr_icon = "mdi:cloud-refresh"

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync"
        # E|Forsyning / Watts On need no MitID: "Synkroniser nu" instead of
        # "Synkroniser (MitID)".
        no_mitid = getattr(coordinator, "uses_mitid", True) is False
        if no_mitid:
            self._attr_translation_key = "sync_now"
        source = getattr(coordinator, "data_source", None)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "KMD Easy Energy",
            "manufacturer": source if no_mitid and isinstance(source, str) else "KMD",
        }

    async def async_press(self) -> None:
        """Sync now: MitID login (KMD) or forbrugernummer login (E|Forsyning)."""
        await self.coordinator.async_start_sync()
