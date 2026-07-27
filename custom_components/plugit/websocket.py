"""Plugit WebSocket client for real-time updates."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

SOCKET_URL = "wss://socket.plugitcloud.com/socket.io/?EIO=3&transport=websocket"
API_BASE = "https://app-gw.plugitcloud.com"

REGISTER_ENDPOINTS = [
    "/transactions/socket",
    "/hubject/transactions/socket",
    "/transaction-price/socket",
]


class PlugitWebSocket:
    """Socket.IO WebSocket client for Plugit real-time data."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        charge_box_id: str,
        charge_point_id: str,
        on_status: Callable[[str], None],
        on_transaction_update: Callable[[dict], None],
        on_transaction_stopped: Callable[[], None] | None = None,
        on_token_expiring: Callable[[], None] | None = None,
        on_connection_change: Callable[[bool], None] | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._charge_box_id = charge_box_id
        self._charge_point_id = charge_point_id
        self._on_status = on_status
        self._on_transaction_update = on_transaction_update
        self._on_transaction_stopped = on_transaction_stopped
        self._on_token_expiring = on_token_expiring
        self._on_connection_change = on_connection_change
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._socket_id: str | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._connected = False

    @property
    def connected(self) -> bool:
        """Return whether the socket is registered for updates."""
        return self._connected

    def _set_connected(self, connected: bool) -> None:
        """Update connection state and notify the coordinator."""
        if self._connected == connected:
            return
        self._connected = connected
        if self._on_connection_change:
            self._on_connection_change(connected)

    def _is_selected_charge_box(self, data: dict) -> bool:
        """Return whether an event belongs to the configured connector."""
        charge_box_id = data.get("chargeBoxId")
        if charge_box_id is None:
            _LOGGER.debug("Ignoring Plugit event without chargeBoxId")
            return False
        return str(charge_box_id) == str(self._charge_box_id)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        self._set_connected(False)
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    async def update_token(self, new_token: str) -> None:
        """Renew the token and re-register the current socket channels."""
        self._access_token = new_token
        if self._socket_id:
            await self._register_socket(self._socket_id)

    async def _run(self) -> None:
        while self._running:
            try:
                await self._connect()
            except Exception as err:
                self._set_connected(False)
                _LOGGER.warning("Plugit WebSocket error: %s, reconnecting in 30s", err)
                await asyncio.sleep(30)

    async def _register_socket(self, socket_id: str) -> None:
        """Register this socket connection to all Plugit backend channels."""
        headers = {"authorization": self._access_token}

        endpoints = list(REGISTER_ENDPOINTS)
        # chargePointId (ei chargeBoxId) tähän endpointtiin - antaa StatusNotification-viestit
        if self._charge_point_id:
            endpoints.append(f"/charge-point/{self._charge_point_id}/socket")

        for ep in endpoints:
            try:
                async with self._session.post(
                    f"{API_BASE}{ep}",
                    headers=headers,
                    json={"socketId": socket_id},
                ) as resp:
                    _LOGGER.debug("Registered %s -> %s", ep, resp.status)
            except Exception as err:
                _LOGGER.debug("Failed to register %s: %s", ep, err)

    async def _connect(self) -> None:
        _LOGGER.debug("Connecting to Plugit WebSocket")
        async with self._session.ws_connect(SOCKET_URL) as ws:
            self._ws = ws
            _LOGGER.info("Plugit WebSocket connected")

            # 1. Lue handshake (0{sid,...})
            first = await ws.receive()
            if first.type != aiohttp.WSMsgType.TEXT:
                return
            handshake = json.loads(first.data[1:])
            socket_id = handshake.get("sid")
            self._socket_id = socket_id
            _LOGGER.debug("Got socketId: %s", socket_id)

            # 2. Lue ja skippaa "40" (namespace connect)
            second = await ws.receive()
            if second.type != aiohttp.WSMsgType.TEXT:
                return
            _LOGGER.debug("Namespace connected: %s", second.data)

            # 3. Rekisteröi socket kaikkiin kanaviin VASTA nyt
            if socket_id:
                await self._register_socket(socket_id)
                self._set_connected(True)
                _LOGGER.info("Plugit WebSocket registered, listening for data")

            # 4. Kuuntele viestejä
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.debug("WebSocket closed")
                    break

            self._set_connected(False)
            self._socket_id = None

    async def _handle_message(self, raw: str) -> None:
        # Ping → pong
        if raw == "2":
            if self._ws:
                await self._ws.send_str("3")
            return

        # Event message
        if raw.startswith("42"):
            try:
                payload = json.loads(raw[2:])
                if isinstance(payload, list) and len(payload) == 2:
                    data = payload[1]

                    if not isinstance(data, dict):
                        return

                    msg_type = data.get("messageType")

                    if msg_type == "StatusNotification":
                        if not self._is_selected_charge_box(data):
                            return
                        status = data.get("data", {}).get("status", "Unknown")
                        _LOGGER.debug("Plugit status: %s", status)
                        self._on_status(status)

                    elif msg_type == "Alert":
                        message = data.get("message", "")
                        _LOGGER.debug("Plugit alert: %s", message)
                        if "expiring" in message.lower() and self._on_token_expiring:
                            self._on_token_expiring()

                    elif msg_type == "StartTransaction":
                        _LOGGER.debug("StartTransaction: meterStart=%s", data.get("data", {}).get("meterStart"))

                    elif msg_type == "StopTransaction":
                        if not self._is_selected_charge_box(data):
                            return
                        _LOGGER.debug("StopTransaction received")
                        if self._on_transaction_stopped:
                            self._on_transaction_stopped()

                    elif msg_type is None and (
                        "latestMeterValues" in data
                        or (
                            "state" in data
                            and (
                                "transactionId" in data
                                or "chargeBoxId" in data
                            )
                        )
                    ):
                        if not self._is_selected_charge_box(data):
                            return
                        _LOGGER.debug("Transaction update received via WebSocket")
                        self._on_transaction_update(data)

                    else:
                        _LOGGER.debug("Unhandled WS message type: %s", msg_type)

            except (json.JSONDecodeError, IndexError) as err:
                _LOGGER.debug("Could not parse WebSocket message: %s", err)
