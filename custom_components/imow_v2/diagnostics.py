"""Diagnostics for STIHL iMow v2 (Settings → Devices & services → … → Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Account details, and anything in the mower data that identifies the mower,
# the owner's network or where the lawn is
TO_REDACT_ENTRY = {"username", "password", "refresh_token", "title", "unique_id"}
TO_REDACT_DATA = {
    "deviceId",
    "uniqueId",
    "serialNumber",
    "signalPCBSerialNumber",
    "cellularIMEI",
    "cellularIMSI",
    "bluetoothMacAddress",
    "bluetoothTrustedDevices",
    "wifiMacAddress",
    "wifiCredentials",
    "ssid",
    "currentlySeenWifiNetworks",
    "ownIPAddress",
    "publicIPAddress",
    "gateway",
    "subNetMask",
    "latitude",
    "longitude",
    "location",
    "deviceTimeZoneLocation",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted entry, options and the latest data for each mower."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    mowers: dict[str, Any] = {}
    if coordinator is not None and coordinator.data:
        # The mower ID is also the dict key, so number the mowers instead
        for index, mower in enumerate(coordinator.data.values(), start=1):
            mowers[f"mower_{index}"] = async_redact_data(mower, TO_REDACT_DATA)
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT_ENTRY),
        "signalr_connected": bool(
            coordinator is not None and coordinator.signalr is not None and coordinator.signalr.connected
        ),
        "last_update_success": coordinator.last_update_success if coordinator is not None else None,
        "mowers": mowers,
    }
