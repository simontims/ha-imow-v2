"""STIHL iMow v2 Home Assistant integration (Gen5+)."""
from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .auth import ImowAuth, ImowAuthError, ImowTokenRejected
from .api import ImowApi
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_TRACKING_INTERVAL, DOMAIN
from .coordinator import ImowCoordinator
from .services import async_setup_services
from .signalr import ImowSignalR

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LAWN_MOWER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iMow from a config entry."""
    # Own session without a cookie jar: STIHL's B2C token endpoint sets cookies,
    # and when they are sent back it answers a refresh with an HTML page instead
    # of tokens, so every refresh after the first failed with a shared session
    session = async_create_clientsession(
        hass, auto_cleanup=False, cookie_jar=aiohttp.DummyCookieJar()
    )
    auth = ImowAuth(session)

    # Restore tokens from stored data; only log in with the password when STIHL
    # actually rejects the refresh token (not on a network hiccup)
    try:
        if entry.data.get("refresh_token"):
            auth.refresh_token = entry.data["refresh_token"]
            try:
                await auth.refresh()
            except ImowTokenRejected:
                _LOGGER.warning("Stored refresh token rejected, logging in again")
                await auth.login(entry.data["username"], entry.data["password"])
        else:
            await auth.login(entry.data["username"], entry.data["password"])
    except ImowAuthError as err:
        await session.close()
        raise ConfigEntryNotReady(f"Could not authenticate with STIHL cloud: {err}") from err
    except aiohttp.ClientError as err:
        await session.close()
        raise ConfigEntryNotReady(f"Network not ready: {err}") from err
    entry.async_on_unload(session.close)

    api = ImowApi(session, auth)
    coordinator = ImowCoordinator(
        hass,
        auth,
        api,
        entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL),
        entry.options.get("tracking_interval", DEFAULT_TRACKING_INTERVAL),
        entry.data["username"],
        entry.data["password"],
        entry,
    )
    coordinator._persist_auth_tokens()

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass, entry)

    coordinator.signalr = ImowSignalR(
        session,
        auth,
        api,
        coordinator.handle_push,
        coordinator.async_ensure_token,
        coordinator.async_on_signalr_connect,
    )
    coordinator.signalr.start(hass)

    coordinator.options_snapshot = dict(entry.options)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: ImowCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        if coordinator.signalr:
            await coordinator.signalr.stop()
        coordinator.async_cancel_timers()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            if hass.services.has_service(DOMAIN, "intent"):
                hass.services.async_remove(DOMAIN, "intent")
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change.

    Update listeners also fire when entry.data changes, which happens every
    time a rotated refresh token is persisted; reloading then would restart
    everything (and the SignalR connection) every ~15 minutes.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and coordinator.options_snapshot == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)
