"""Config flow for Plugit integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PlugitApi, PlugitApiError
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_CHARGE_BOX_ID, CONF_CHARGE_POINT_ID, CONF_CHARGE_BOX_GROUP_ID, API_BASE


class PlugitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Plugit config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = PlugitApi(session, user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
            try:
                await api.authenticate()

                # Fetch charger info automatically
                async with session.get(
                    f"{API_BASE}/charge-points/user-charge-points",
                    headers={
                        "authorization": api._access_token,
                        "user-agent": "Dart/3.8 (dart:io)",
                    },
                ) as resp:
                    resp.raise_for_status()
                    chargers = await resp.json()

                if not chargers:
                    errors["base"] = "no_chargers"
                else:
                    # Use first charger
                    charger = chargers[0]
                    group = charger["chargeBoxGroups"][0]
                    box = group["chargeBoxes"][0]

                    data = {
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_CHARGE_POINT_ID: charger["_id"],
                        CONF_CHARGE_BOX_GROUP_ID: group["_id"],
                        CONF_CHARGE_BOX_ID: box["_id"],
                    }

                    charger_name = charger.get("name", "Plugit Charger")
                    return self.async_create_entry(
                        title=f"Plugit - {charger_name}",
                        data=data,
                    )

            except PlugitApiError:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except (KeyError, IndexError):
                errors["base"] = "no_chargers"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )
