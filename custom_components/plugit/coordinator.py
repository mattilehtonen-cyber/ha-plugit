"""Plugit data coordinator with merged WebSocket and REST state."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PlugitApi, PlugitApiError
from .const import (
    DOMAIN,
    STATS_UPDATE_INTERVAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_CHARGE_BOX_ID,
    CONF_CHARGE_POINT_ID,
)
from .websocket import PlugitWebSocket

_LOGGER = logging.getLogger(__name__)

INTERVAL_ACTIVE = timedelta(seconds=30)
INTERVAL_FULLY_CHARGED = timedelta(minutes=5)
INTERVAL_IDLE = timedelta(minutes=60)
WEBSOCKET_STALE_AFTER = timedelta(minutes=2)
ACTIVE_STATUSES = {"Preparing", "Charging", "Finishing", "SuspendedEV", "SuspendedEVSE"}


class PlugitCoordinator(DataUpdateCoordinator):
    """Keep one consistent view of the configured Plugit charger."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=INTERVAL_IDLE)
        self.entry = entry
        self._session = async_get_clientsession(hass)
        self.api = PlugitApi(self._session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
        self._ws: PlugitWebSocket | None = None

        self._transaction: dict | None = None
        self._transaction_id: str | int | None = None
        self._meter_values: dict[tuple[str | None, str | None, str | None], dict] = {}
        self._last_ws_transaction_update: datetime | None = None
        self._fully_charged_at: str | None = None

        self._live_status: str | None = None
        self._last_live_status_update: datetime | None = None
        self._rest_status: str | None = None
        self._charger_status = "Unknown"

        self._session_peak_power: float | None = None
        self._peak_transaction_id: str | int | None = None
        self._monthly_stats: dict | None = None
        self._yearly_stats: list = []
        self._leasing_refunds: list = []
        self._home_charging_settings: dict | None = None
        self._charger_info: dict | None = None
        self._last_completed_transaction: dict | None = None
        self._last_stats_update: datetime | None = None
        self._initial_rest_update_done = False

    @staticmethod
    def _transaction_key(transaction: dict | None) -> str | int | None:
        if not transaction:
            return None
        return transaction.get("_id") or transaction.get("transactionId")

    @staticmethod
    def _meter_key(value: dict) -> tuple[str | None, str | None, str | None]:
        return (value.get("measurand"), value.get("phase"), value.get("location"))

    def _clear_session(self) -> None:
        self._transaction = None
        self._transaction_id = None
        self._meter_values = {}
        self._last_ws_transaction_update = None
        self._fully_charged_at = None
        self._session_peak_power = None
        self._peak_transaction_id = None

    def _merge_transaction(self, incoming: dict | None, *, from_websocket: bool = False) -> None:
        """Merge only one session and retain meter values omitted by REST."""
        if not incoming:
            return
        if str(incoming.get("chargeBoxId")) != str(self.entry.data[CONF_CHARGE_BOX_ID]):
            return

        incoming_id = self._transaction_key(incoming)
        incoming_state = incoming.get("state")
        # The server can replay old finished sessions. Do not let one replace
        # a currently active session.
        if (
            incoming_state == "finished"
            and self._transaction_id is not None
            and incoming_id != self._transaction_id
        ):
            return

        if incoming_id is not None and incoming_id != self._transaction_id:
            self._transaction = {}
            self._transaction_id = incoming_id
            self._meter_values = {}
            self._fully_charged_at = None
            self._session_peak_power = None
            self._peak_transaction_id = incoming_id
        elif self._transaction is None:
            self._transaction = {}
            self._transaction_id = incoming_id

        for key, value in incoming.items():
            if key != "latestMeterValues" and value is not None:
                self._transaction[key] = value

        for value in incoming.get("latestMeterValues", []):
            if isinstance(value, dict) and value.get("measurand"):
                self._meter_values[self._meter_key(value)] = value
        self._transaction["latestMeterValues"] = list(self._meter_values.values())

        if timestamp := self._transaction.get("timestampFullyCharged"):
            self._fully_charged_at = timestamp
        if from_websocket:
            self._last_ws_transaction_update = datetime.now()

        if self._transaction.get("state") == "finished":
            self._clear_session()

    def _live_status_is_usable(self) -> bool:
        """OCPP status is event-based, not a periodic measurement.

        Keep the last received status while the socket remains connected.
        It is only superseded by REST after a connection loss.
        """
        return bool(
            self._live_status
            and self._live_status != "Unknown"
            and self._ws
            and self._ws.connected
        )

    def _recompute_status(self) -> None:
        """Publish one status with live OCPP preferred over REST fallback."""
        if self._fully_charged_at:
            self._charger_status = "Fully Charged"
        elif self._live_status_is_usable():
            self._charger_status = self._live_status
        elif self._rest_status:
            self._charger_status = self._rest_status
        elif self._transaction and self._transaction.get("state") == "ongoing":
            self._charger_status = "Charging"
        else:
            self._charger_status = "Unknown"
        self._update_poll_interval()

    def _update_poll_interval(self) -> None:
        if self._charger_status in ACTIVE_STATUSES:
            new_interval = INTERVAL_ACTIVE
        elif self._charger_status == "Fully Charged":
            new_interval = INTERVAL_FULLY_CHARGED
        else:
            new_interval = INTERVAL_IDLE
        if self.update_interval != new_interval:
            self.update_interval = new_interval

    async def _async_update_data(self) -> dict:
        try:
            websocket_stale = (
                self._last_ws_transaction_update is None
                or datetime.now() - self._last_ws_transaction_update >= WEBSOCKET_STALE_AFTER
            )
            use_rest = (
                not self._initial_rest_update_done
                or not (self._ws and self._ws.connected)
                or websocket_stale
            )
            if use_rest:
                rest_transaction = await self.api.get_active_transaction(
                    self.entry.data[CONF_CHARGE_BOX_ID]
                )
                self._charger_info = await self.api.get_charge_box_status(
                    self.entry.data[CONF_CHARGE_POINT_ID], self.entry.data[CONF_CHARGE_BOX_ID]
                )
                self._rest_status = (
                    self._charger_info.get("status") if self._charger_info else None
                )
                self._initial_rest_update_done = True
                if rest_transaction:
                    self._merge_transaction(rest_transaction)
                elif self._rest_status == "Available":
                    self._clear_session()

            if self._ws is None and self.api._access_token:
                await self._start_websocket()
            if (
                self._last_stats_update is None
                or datetime.now() - self._last_stats_update >= timedelta(seconds=STATS_UPDATE_INTERVAL)
            ):
                await self._update_stats()

            self._recompute_status()
            self._update_session_peak_power(self._transaction)
            return {
                "transaction": self._transaction,
                "charger_status": self._charger_status,
                "fully_charged": self._fully_charged_at is not None,
                "fully_charged_at": self._fully_charged_at,
                "monthly_stats": self._monthly_stats,
                "yearly_stats": self._yearly_stats,
                "leasing_refunds": self._leasing_refunds,
                "home_charging_settings": self._home_charging_settings,
                "charger_info": self._charger_info,
                "last_completed_transaction": self._last_completed_transaction,
                "ws_active": self._last_ws_transaction_update is not None,
                "session_peak_power": self._session_peak_power if self._transaction else None,
            }
        except PlugitApiError as err:
            raise UpdateFailed(f"Plugit API error: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

    async def _update_stats(self) -> None:
        try:
            self._monthly_stats = await self.api.get_monthly_stats()
            self._yearly_stats = await self.api.get_yearly_stats()
            self._leasing_refunds = await self.api.get_leasing_refunds()
            self._home_charging_settings = await self.api.get_home_charging_settings()
            recent = await self.api.get_recent_transactions()
            charge_box_id = str(self.entry.data[CONF_CHARGE_BOX_ID])
            self._last_completed_transaction = next(
                (item for item in recent if str(item.get("chargeBoxId")) == charge_box_id and item.get("state") == "finished"),
                None,
            )
            self._last_stats_update = datetime.now()
        except Exception as err:
            _LOGGER.warning("Failed to update stats: %s", err)

    async def _start_websocket(self) -> None:
        self._ws = PlugitWebSocket(
            session=self._session,
            access_token=self.api._access_token,
            charge_box_id=self.entry.data[CONF_CHARGE_BOX_ID],
            charge_point_id=self.entry.data.get(CONF_CHARGE_POINT_ID),
            on_status=self._on_status_update,
            on_transaction_update=self._on_transaction_update,
            on_transaction_stopped=self._on_transaction_stopped,
            on_token_expiring=self._on_token_expiring,
            on_connection_change=self._on_websocket_connection_change,
        )
        await self._ws.start()

    def _on_status_update(self, status: str) -> None:
        self._live_status = status
        self._last_live_status_update = datetime.now()
        if status == "Available":
            self._clear_session()
        self._recompute_status()
        self.hass.async_create_task(self.async_request_refresh())

    def _on_transaction_update(self, data: dict) -> None:
        self._merge_transaction(data, from_websocket=True)
        self._update_device_info(data)
        self._recompute_status()
        self.hass.async_create_task(self.async_request_refresh())

    def _on_transaction_stopped(self) -> None:
        self._clear_session()
        self._live_status = None
        self._last_live_status_update = None
        self._recompute_status()
        self.hass.async_create_task(self.async_request_refresh())

    def _update_device_info(self, transaction: dict) -> None:
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.entry.entry_id)})
        if not device:
            return
        values = {
            "name": transaction.get("chargePointName"),
            "manufacturer": transaction.get("chargePointVendor"),
            "model": transaction.get("chargePointModel"),
            "sw_version": transaction.get("firmwareVersion"),
        }
        updates = {key: value for key, value in values.items() if value and getattr(device, key) != value}
        if updates:
            registry.async_update_device(device.id, **updates)

    def _update_session_peak_power(self, transaction: dict | None) -> None:
        if not transaction:
            return
        transaction_id = self._transaction_key(transaction)
        if transaction_id != self._peak_transaction_id:
            self._peak_transaction_id = transaction_id
            self._session_peak_power = None
        for value in transaction.get("latestMeterValues", []):
            if value.get("measurand") != "Power.Active.Import":
                continue
            try:
                self._session_peak_power = max(self._session_peak_power or 0, float(value.get("value")))
            except (TypeError, ValueError):
                continue

    def _on_websocket_connection_change(self, connected: bool) -> None:
        _LOGGER.info("Plugit WebSocket %s", "connected" if connected else "disconnected")
        if not connected:
            self._last_ws_transaction_update = None
            self._live_status = None
            self._last_live_status_update = None
        self.hass.async_create_task(self.async_request_refresh())

    def _on_token_expiring(self) -> None:
        async def refresh() -> None:
            try:
                await self.api.authenticate()
                if self._ws and self.api._access_token:
                    await self._ws.update_token(self.api._access_token)
            except Exception as err:
                _LOGGER.warning("Failed to renew token: %s", err)
        self.hass.async_create_task(refresh())

    async def async_shutdown(self) -> None:
        if self._ws:
            await self._ws.stop()
        await super().async_shutdown()
