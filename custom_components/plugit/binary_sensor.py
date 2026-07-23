"""Binary sensors for the Plugit integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PlugitCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Plugit binary sensors."""
    coordinator: PlugitCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PlugitChargerOnlineBinarySensor(coordinator, entry)])


class PlugitChargerOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Report whether the charger is connected to the Plugit cloud."""

    _attr_name = "Plugit Charger Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:lan-connect"

    def __init__(self, coordinator: PlugitCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"plugit_{entry.entry_id}_charger_online"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Plugit Charger",
            "manufacturer": "Plugit",
        }

    @property
    def is_on(self) -> bool | None:
        info = self.coordinator.data.get("charger_info")
        return info.get("online") if info else None
