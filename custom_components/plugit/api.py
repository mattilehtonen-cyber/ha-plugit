"""Plugit API client."""
from __future__ import annotations

import aiohttp
from datetime import datetime

from .const import ORY_BASE, API_BASE


class PlugitApiError(Exception):
    """Plugit API error."""


class PlugitApi:
    """Plugit API client."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._access_token: str | None = None

    async def authenticate(self) -> None:
        """Authenticate with Ory and register session."""
        async with self._session.get(
            f"{ORY_BASE}/self-service/login/api"
        ) as resp:
            resp.raise_for_status()
            flow = await resp.json()
            flow_id = flow["id"]

        async with self._session.post(
            f"{ORY_BASE}/self-service/login?flow={flow_id}",
            json={
                "method": "password",
                "identifier": self._email,
                "password": self._password,
            },
        ) as resp:
            if resp.status != 200:
                raise PlugitApiError(f"Login failed: {resp.status}")
            data = await resp.json()
            session_token = data["session_token"]

        async with self._session.post(
            f"{API_BASE}/users/register-session",
            json={"token": session_token},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._access_token = data["accessToken"]

    def _headers(self) -> dict:
        return {
            "authorization": self._access_token,
            "content-type": "application/json",
            "user-agent": "Dart/3.8 (dart:io)",
        }

    async def _get(self, url: str) -> any:
        """Make authenticated GET request with token refresh."""
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 401:
                await self.authenticate()
                async with self._session.get(url, headers=self._headers()) as resp2:
                    resp2.raise_for_status()
                    return await resp2.json()
            resp.raise_for_status()
            return await resp.json()

    async def get_chargers(self) -> list:
        """Get user chargers."""
        return await self._get(f"{API_BASE}/charge-points/user-charge-points")

    async def get_active_transaction(self) -> dict | None:
        """Get active charging transaction."""
        if not self._access_token:
            await self.authenticate()
        data = await self._get(f"{API_BASE}/transactions/active")
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return None

    async def get_monthly_stats(self) -> dict | None:
        """Get current month statistics."""
        if not self._access_token:
            await self.authenticate()
        now = datetime.now()
        data = await self._get(
            f"{API_BASE}/v2/monthly-transactions"
            f"?country=FI&year={now.year}&month={now.month}&currency=EUR"
        )
        return data.get("report") if isinstance(data, dict) else None

    async def get_yearly_stats(self) -> list:
        """Get yearly statistics."""
        if not self._access_token:
            await self.authenticate()
        now = datetime.now()
        return await self._get(f"{API_BASE}/yearly-transactions?year={now.year}")

    async def get_leasing_refunds(self) -> list:
        """Get leasing refund history."""
        if not self._access_token:
            await self.authenticate()
        return await self._get(f"{API_BASE}/leasing/refunds")

    async def start_charging(self, charge_box_id: str, charge_box_group_id: str) -> bool:
        """Start charging session."""
        if not self._access_token:
            await self.authenticate()
        async with self._session.post(
            f"{API_BASE}/remote-start-transaction",
            headers=self._headers(),
            json={
                "chargeBoxId": charge_box_id,
                "chargeBoxGroupId": charge_box_group_id,
            },
        ) as resp:
            return resp.status == 200

    async def stop_charging(self, charge_point_id: str, charge_box_id: str) -> bool:
        """Stop charging session."""
        if not self._access_token:
            await self.authenticate()
        async with self._session.post(
            f"{API_BASE}/remote-stop-transaction",
            headers=self._headers(),
            json={
                "chargePointId": charge_point_id,
                "chargeBoxId": charge_box_id,
            },
        ) as resp:
            return resp.status == 200
