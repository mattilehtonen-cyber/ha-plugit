"""Plugit data coordinator."""
from __future__ import annotations

from datetime import timedelta
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PlugitApi, PlugitApiError
from .const import DOMAIN, UPDATE_INTERVAL, STATS_UPDATE_INTERVAL, CONF_EMAIL, CONF_PASSWORD, CONF_CHARGE_BOX_ID
from .websocket import PlugitWebSocket

_LOGGER = logging.getLogger(__name__)


class PlugitCoordinator(DataUpdateCoordinator):
    """Plugit data coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.entry = entry
        self._session = async_get_clientsession(hass)
        self.api = PlugitApi(
            self._session,
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
        )
        self._ws: PlugitWebSocket | None = None
        self._charger_status: str = "Unknown"
        self._monthly_stats: dict | None = None
        self._yearly_stats: list = []
        self._leasing_refunds: list = []
        self._stats_update_counter: int = 0

    async def _async_update_data(self) -> dict:
        """Fetch data from Plugit API."""
        try:
            transaction = await self.api.get_active_transaction()

            if self._ws is None and self.api._access_token:
                await self._start_websocket()

            self._stats_update_counter += 1
            if self._stats_update_counter >= (STATS_UPDATE_INTERVAL // UPDATE_INTERVAL):
                self._stats_update_counter = 0
                await self._update_stats()

            if not self._monthly_stats:
                await self._update_stats()

            return {
                "transaction": transaction,
                "charger_status": self._charger_status,
                "monthly_stats": self._monthly_stats,
                "yearly_stats": self._yearly_stats,
                "leasing_refunds": self._leasing_refunds,
            }
        except PlugitApiError as err:
            raise UpdateFailed(f"Plugit API error: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

    async def _update_stats(self) -> None:
        """Update statistics data."""
        try:
            self._monthly_stats = await self.api.get_monthly_stats()
            self._yearly_stats = await self.api.get_yearly_stats()
            self._leasing_refunds = await self.api.get_leasing_refunds()
        except Exception as err:
            _LOGGER.warning("Failed to update stats: %s", err)

    async def _start_websocket(self) -> None:
        """Start WebSocket connection."""
        charge_box_id = self.entry.data[CONF_CHARGE_BOX_ID]
        self._ws = PlugitWebSocket(
            session=self._session,
            access_token=self.api._access_token,
            charge_box_id=charge_box_id,
            on_status=self._on_status_update,
            on_meter=self._on_meter_update,
        )
        await self._ws.start()

    def _on_status_update(self, status: str) -> None:
        self._charger_status = status
        self.hass.async_create_task(self.async_request_refresh())

    def _on_meter_update(self, meter_data: dict) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    async def async_shutdown(self) -> None:
        if self._ws:
            await self._ws.stop()
        await super().async_shutdown()
