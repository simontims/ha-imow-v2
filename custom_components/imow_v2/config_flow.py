"""Config flow for STIHL iMow v2."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .auth import ImowAuth, ImowAuthError
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_TRACKING_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("username"): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required("password"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    }
)


class ImowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for STIHL iMow v2."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input["username"].strip()
            password = user_input["password"]

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            try:
                session = async_get_clientsession(self.hass)
                auth = ImowAuth(session)
                await auth.login(username, password)
            except ImowAuthError as err:
                _LOGGER.warning("B2C login failed: %s", err)
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError as err:
                _LOGGER.warning("Network error during login: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception during login: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=username,
                    data={
                        "username": username,
                        "password": password,
                        "refresh_token": auth.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):  # type: ignore[override]
        return ImowOptionsFlow(config_entry)


class ImowOptionsFlow(OptionsFlow):
    """Handle options (scan interval)."""

    def __init__(self, config_entry) -> None:  # type: ignore[override]
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    "scan_interval",
                    default=self._entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=1, max=60)),
                vol.Optional(
                    "tracking_interval",
                    default=self._entry.options.get(
                        "tracking_interval", DEFAULT_TRACKING_INTERVAL
                    ),
                ): vol.All(int, vol.Range(min=0, max=600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
