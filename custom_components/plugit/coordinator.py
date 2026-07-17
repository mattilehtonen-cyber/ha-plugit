"""Plugit data coordinator with WebSocket real-time updates."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PlugitApi, PlugitApiError
from .const import DOMAIN, STATS_UPDATE_INTERVAL, CONF_EMAIL, CONF_PASSWORD, CONF_CHARGE_BOX_ID, CONF_CHARGE_POINT_ID
from .websocket import PlugitWebSocket

_LOGGER = logging.getLogger(__name__)

INTERVAL_ACTIVE = timedelta(seconds=30)
INTERVAL_IDLE = timedelta(minutes=60)
ACTIVE_STATUSES = {"Preparing", "Charging", "Finishing", "SuspendedEV", "SuspendedEVSE"}


class PlugitCoordinator(DataUpdateCoordinator):
    """Plugit data coordinator with WebSocket real-time updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=INTERVAL_IDLE,
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
        self._ws_transaction: dict | None = None  # WebSocket transaction data
        self._monthly_stats: dict | None = None
        self._yearly_stats: list = []
        self._leasing_refunds: list = []
        self._last_stats_update: datetime | None = None
        self._initial_rest_update_done = False

    def _update_poll_interval(self) -> None:
        """Adjust polling interval based on charger status."""
        new_interval = INTERVAL_ACTIVE if self._charger_status in ACTIVE_STATUSES else INTERVAL_IDLE
        if self.update_interval != new_interval:
            _LOGGER.debug("Plugit polling interval changed to %s", new_interval)
            self.update_interval = new_interval

    async def _async_update_data(self) -> dict:
        """Fetch data from Plugit API."""
        try:
            # Hae REST-data — käytetään jos WebSocket-data puuttuu
            if self._ws is None and self.api._access_token:
                await self._start_websocket()

            # REST is used only for the initial state and while WebSocket is
            # unavailable. Normal real-time updates arrive via WebSocket.
            use_rest = not self._initial_rest_update_done or not (
                self._ws and self._ws.connected
            )
            rest_transaction = None
            if use_rest:
                rest_transaction = await self.api.get_active_transaction()
                self._initial_rest_update_done = True

            if (
                self._last_stats_update is None
                or datetime.now() - self._last_stats_update
                >= timedelta(seconds=STATS_UPDATE_INTERVAL)
            ):
                await self._update_stats()

            # Käytä WebSocket-dataa jos saatavilla, muuten REST
            transaction = self._ws_transaction if self._ws_transaction else rest_transaction

            return {
                "transaction": transaction,
                "charger_status": self._charger_status,
                "monthly_stats": self._monthly_stats,
                "yearly_stats": self._yearly_stats,
                "leasing_refunds": self._leasing_refunds,
                "ws_active": self._ws_transaction is not None,
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
            self._last_stats_update = datetime.now()
        except Exception as err:
            _LOGGER.warning("Failed to update stats: %s", err)

    async def _start_websocket(self) -> None:
        """Start WebSocket connection."""
        charge_box_id = self.entry.data[CONF_CHARGE_BOX_ID]
        charge_point_id = self.entry.data.get(CONF_CHARGE_POINT_ID)
        self._ws = PlugitWebSocket(
            session=self._session,
            access_token=self.api._access_token,
            charge_box_id=charge_box_id,
            charge_point_id=charge_point_id,
            on_status=self._on_status_update,
            on_transaction_update=self._on_transaction_update,
            on_token_expiring=self._on_token_expiring,
            on_connection_change=self._on_websocket_connection_change,
        )
        await self._ws.start()
        _LOGGER.info("Plugit WebSocket started")

    def _on_status_update(self, status: str) -> None:
        """Handle real-time status update."""
        self._charger_status = status
        self._update_poll_interval()

        # Jos laturi vapautuu, tyhjennä WS-data
        if status == "Available":
            self._ws_transaction = None

        self.hass.async_create_task(self.async_request_refresh())

    def _on_transaction_update(self, data: dict) -> None:
        """Handle real-time transaction update from WebSocket."""
        self._ws_transaction = data
        # Jos lataus päättyy, tyhjennä WS-data hetken kuluttua
        if data.get("state") == "finished":
            self._ws_transaction = None
        self.hass.async_create_task(self.async_request_refresh())

    def _on_websocket_connection_change(self, connected: bool) -> None:
        """Refresh state when WebSocket availability changes."""
        _LOGGER.info("Plugit WebSocket %s", "connected" if connected else "disconnected")
        self.hass.async_create_task(self.async_request_refresh())

    def _on_token_expiring(self) -> None:
        """Handle token expiring — re-authenticate and update WebSocket token."""
        async def _refresh():
            try:
                await self.api.authenticate()
                if self._ws and self.api._access_token:
                    self._ws.update_token(self.api._access_token)
                    _LOGGER.info("Plugit WebSocket token renewed")
            except Exception as err:
                _LOGGER.warning("Failed to renew token: %s", err)
        self.hass.async_create_task(_refresh())

    async def async_shutdown(self) -> None:
        if self._ws:
            await self._ws.stop()
        await super().async_shutdown()
