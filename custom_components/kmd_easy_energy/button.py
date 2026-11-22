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
    _attr_name = "Sync"
    _attr_icon = "mdi:cloud-refresh"

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "KMD Easy Energy",
            "manufacturer": "KMD",
        }

    async def async_press(self) -> None:
        """Start pure-Python MitID sync directly inside Home Assistant."""
        await self.coordinator.async_start_mitid_sync()
