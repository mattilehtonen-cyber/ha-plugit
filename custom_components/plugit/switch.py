"""Plugit switch for charging control."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_CHARGE_BOX_ID, CONF_CHARGE_POINT_ID, CONF_CHARGE_BOX_GROUP_ID
from .coordinator import PlugitCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PlugitCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PlugitChargingSwitch(coordinator, entry)])


class PlugitChargingSwitch(CoordinatorEntity, SwitchEntity):
    _attr_name = "Plugit Charging"

    def __init__(self, coordinator: PlugitCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"plugit_{entry.entry_id}_switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Plugit Charger",
            "manufacturer": "Plugit",
        }

    @property
    def is_on(self) -> bool:
        """Return whether the charger is actively delivering energy.

        An OCPP transaction can remain ``ongoing`` while a car is full or
        unplugged. The switch represents active charging, not merely the
        existence of a transaction.
        """
        transaction = self.coordinator.data.get("transaction")
        return bool(
            transaction
            and transaction.get("state") == "ongoing"
            and not transaction.get("timestampFullyCharged")
            and self.coordinator.data.get("charger_status") == "Charging"
        )

    async def async_turn_on(self, **kwargs) -> None:
        success = await self.coordinator.api.start_charging(
            self._entry.data[CONF_CHARGE_BOX_ID],
            self._entry.data[CONF_CHARGE_BOX_GROUP_ID],
        )
        if not success:
            raise HomeAssistantError("Plugit could not start charging")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        success = await self.coordinator.api.stop_charging(
            self._entry.data[CONF_CHARGE_POINT_ID],
            self._entry.data[CONF_CHARGE_BOX_ID],
        )
        if not success:
            raise HomeAssistantError("Plugit could not stop charging")
        await self.coordinator.async_request_refresh()
