"""Plugit WebSocket client for real-time updates."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

SOCKET_URL = "wss://socket.plugitcloud.com/socket.io/?EIO=3&transport=websocket"


class PlugitWebSocket:
    """Socket.IO WebSocket client for Plugit real-time data."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        charge_box_id: str,
        on_status: Callable[[str], None],
        on_meter: Callable[[dict], None],
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._charge_box_id = charge_box_id
        self._on_status = on_status
        self._on_meter = on_meter
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start WebSocket connection."""
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        """Main WebSocket loop with reconnect."""
        while self._running:
            try:
                await self._connect()
            except Exception as err:
                _LOGGER.warning("Plugit WebSocket error: %s, reconnecting in 30s", err)
                await asyncio.sleep(30)

    async def _connect(self) -> None:
        """Connect and handle messages."""
        _LOGGER.debug("Connecting to Plugit WebSocket")
        async with self._session.ws_connect(
            SOCKET_URL,
            headers={"user-agent": "Dart/3.8 (dart:io)"},
        ) as ws:
            self._ws = ws
            _LOGGER.debug("Plugit WebSocket connected")

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break

    async def _handle_message(self, raw: str) -> None:
        """Handle Socket.IO message."""
        # Socket.IO protocol:
        # "0{...}" = connect handshake
        # "40" = connected to namespace
        # "2" = ping
        # "3" = pong
        # "42[...]" = event message

        if raw == "2":
            # Ping — respond with pong
            if self._ws:
                await self._ws.send_str("3")
            return

        if raw.startswith("0"):
            # Handshake received — subscribe to charge box
            _LOGGER.debug("Socket.IO handshake received")
            await self._subscribe()
            return

        if raw.startswith("42"):
            # Event message
            import json
            try:
                payload = json.loads(raw[2:])
                if isinstance(payload, list) and len(payload) == 2:
                    token = payload[0]
                    data = payload[1]

                    if not isinstance(data, dict):
                        return

                    msg_type = data.get("messageType")

                    if msg_type == "StatusNotification":
                        status = data.get("data", {}).get("status", "Unknown")
                        _LOGGER.debug("Plugit status: %s", status)
                        self._on_status(status)

                    elif msg_type == "MeterValues":
                        meter_data = data.get("data", {})
                        _LOGGER.debug("Plugit meter values: %s", meter_data)
                        self._on_meter(meter_data)

                    elif msg_type == "Alert":
                        # Token expiring warning — re-authenticate would be needed
                        _LOGGER.debug("Plugit socket alert: %s", data.get("message"))

            except (json.JSONDecodeError, IndexError) as err:
                _LOGGER.debug("Could not parse WebSocket message: %s", err)

    async def _subscribe(self) -> None:
        """Subscribe to charge box events."""
        if not self._ws:
            return
        # Socket.IO subscribe format: 42["token", data]
        import json
        msg = json.dumps([self._access_token, {
            "chargeBoxId": self._charge_box_id,
        }])
        await self._ws.send_str(f"42{msg}")
        _LOGGER.debug("Subscribed to Plugit WebSocket for chargeBoxId: %s", self._charge_box_id)
