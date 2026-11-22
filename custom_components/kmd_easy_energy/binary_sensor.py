"""Binary sensors for motivation penalty and abnormal consumption."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KMDEasyEnergyCoordinator
from .insights import STATUS_PENALTY


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KMD Easy Energy binary sensors."""
    coordinator: KMDEasyEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            KMDMotivationPenaltyBinarySensor(coordinator, entry),
            KMDAbnormalConsumptionBinarySensor(coordinator, entry),
        ]
    )


class KMDBaseBinarySensor(
    CoordinatorEntity[KMDEasyEnergyCoordinator], BinarySensorEntity
):
    """Base binary sensor on the KMD Easy Energy device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "KMD Easy Energy",
            "manufacturer": "KMD",
        }


class KMDMotivationPenaltyBinarySensor(KMDBaseBinarySensor):
    """On when the return temperature is in the motivation-tariff penalty band."""

    _attr_translation_key = "motivation_penalty"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_motivation_penalty"

    @property
    def is_on(self) -> bool:
        return (self.coordinator.data or {}).get("motivation_status") == STATUS_PENALTY


class KMDAbnormalConsumptionBinarySensor(KMDBaseBinarySensor):
    """On when yesterday's kWh is high vs. the same weekday (HDD-adjusted).

    This is a local condition only — the integration does not send
    notifications; the user decides whether to automate on it.
    """

    _attr_translation_key = "abnormal_consumption"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: KMDEasyEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_abnormal_consumption"

    @property
    def is_on(self) -> bool:
        flag = (self.coordinator.data or {}).get("abnormal_consumption") or {}
        return bool(flag.get("abnormal"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = dict((self.coordinator.data or {}).get("abnormal_consumption") or {})
        return data
