"""Config flow for STIHL iMow v2."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .auth import ImowAuth, ImowAuthError, ImowInvalidCredentials
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_TRACKING_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TRACKING_INTERVAL = "tracking_interval"

_EMAIL = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username"))
_PASSWORD = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)


async def _async_login(hass, username: str, password: str) -> tuple[ImowAuth | None, dict[str, str]]:
    """Log in to STIHL; return (auth, {}) on success or (None, errors) for the form."""
    # login() opens its own short-lived sessions; this one would only be used for refreshes
    auth = ImowAuth(async_get_clientsession(hass))
    try:
        await auth.login(username, password)
    except ImowInvalidCredentials:
        return None, {"base": "invalid_auth"}
    except (ImowAuthError, aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.warning("Could not reach the STIHL login service: %s", err)
        return None, {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error while logging in to STIHL")
        return None, {"base": "unknown"}
    return auth, {}


def _unique_id(auth: ImowAuth, username: str) -> str:
    """The STIHL account ID, or the lower-cased email if the token has none."""
    return auth.account_id or username.lower()


class ImowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for STIHL iMow v2."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the myimow account, test it, and create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            auth, errors = await _async_login(self.hass, username, password)
            if auth is not None:
                await self.async_set_unique_id(_unique_id(auth, username))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_REFRESH_TOKEN: auth.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_USERNAME): _EMAIL, vol.Required(CONF_PASSWORD): _PASSWORD}),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """STIHL rejected the stored password: ask for it again."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password of the same account."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]
        errors: dict[str, str] = {}
        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            auth, errors = await _async_login(self.hass, username, password)
            if auth is not None:
                await self.async_set_unique_id(_unique_id(auth, username))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: password, CONF_REFRESH_TOKEN: auth.refresh_token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD}),
            description_placeholders={"username": username},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the email address or password of the same STIHL account."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            auth, errors = await _async_login(self.hass, username, password)
            if auth is not None:
                await self.async_set_unique_id(_unique_id(auth, username))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    title=username,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_REFRESH_TOKEN: auth.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_USERNAME): _EMAIL, vol.Required(CONF_PASSWORD): _PASSWORD}),
                {CONF_USERNAME: (user_input or entry.data)[CONF_USERNAME]},
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ImowOptionsFlow:
        """Return the options flow."""
        return ImowOptionsFlow()


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(min=1, max=60, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_TRACKING_INTERVAL, default=DEFAULT_TRACKING_INTERVAL): NumberSelector(
            NumberSelectorConfig(min=0, max=600, step=5, unit_of_measurement="s", mode=NumberSelectorMode.BOX)
        ),
    }
)


class ImowOptionsFlow(OptionsFlowWithReload):
    """Poll and GPS tracking intervals. Saving reloads the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # NumberSelector returns floats; the coordinator wants whole minutes/seconds
            return self.async_create_entry(data={k: int(v) for k, v in user_input.items()})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, self.config_entry.options),
        )
