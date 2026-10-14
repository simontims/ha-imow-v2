"""HA services for STIHL iMow v2.

Service: imow_v2.intent
  action (required): start-mowing | pause | resume | end-job-and-return-to-dock |
                     clear-errors | force-status-update (plus friendly aliases)
  mower_device (optional): device_id from device registry
  mower_name   (optional): friendly name of the mower device
  duration     (optional): minutes, for start-mowing
  zone         (optional): mowing zone id (0 = from dock), for start-mowing
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CMD_CLEAR_ERRORS,
    CMD_DOCK,
    CMD_FORCE_UPDATE,
    CMD_PAUSE,
    CMD_RESUME,
    CMD_START,
    DOMAIN,
)

# Accepted action names → command names used by the myimow web app
_ACTION_MAP = {
    CMD_START: CMD_START,
    CMD_PAUSE: CMD_PAUSE,
    CMD_RESUME: CMD_RESUME,
    CMD_DOCK: CMD_DOCK,
    CMD_CLEAR_ERRORS: CMD_CLEAR_ERRORS,
    CMD_FORCE_UPDATE: CMD_FORCE_UPDATE,
    # Friendly aliases (incl. names older versions of this integration accepted)
    "startMowing": CMD_START,
    "start_mowing": CMD_START,
    "stop": CMD_DOCK,
    "stop_mowing": CMD_DOCK,
    "park": CMD_DOCK,
    "dock": CMD_DOCK,
    "toDocking": CMD_DOCK,
    "refresh": CMD_FORCE_UPDATE,
}

INTENT_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("mower_device"): cv.string,
            vol.Optional("mower_name"): cv.string,
            vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
            vol.Optional("zone"): vol.Coerce(int),
            vol.Required("action"): vol.In(list(_ACTION_MAP)),
        },
        cv.has_at_least_one_key("mower_device", "mower_name"),
    )
)


async def async_setup_services(hass, entry) -> None:
    """Register iMow services."""
    if hass.services.has_service(DOMAIN, "intent"):
        return

    async def _intent(service_call):
        await _handle_intent(hass, service_call)

    hass.services.async_register(DOMAIN, "intent", _intent, schema=INTENT_SCHEMA)


async def _handle_intent(hass, service_call) -> None:
    data = service_call.data
    cmd = _ACTION_MAP[data["action"]]
    mower_id = await _resolve_mower_id(hass, data)

    coordinator = next(
        (c for c in hass.data[DOMAIN].values() if mower_id in (c.data or {})), None
    )
    if coordinator is None:
        raise HomeAssistantError(f"Mower '{mower_id}' is not available from any loaded iMow config entry")

    payload = None
    if cmd == CMD_START:
        duration_s = (
            data["duration"] * 60 if "duration" in data
            else coordinator.start_duration_s(mower_id)
        )
        payload = {"durationInSeconds": duration_s}
        if "zone" in data:
            payload["mowingZoneId"] = data["zone"]

    await coordinator.async_send_command(mower_id, cmd, payload)


async def _resolve_mower_id(hass, data: dict) -> str:
    domain_data = hass.data.get(DOMAIN, {})

    all_ids: set[str] = set()
    for coordinator in domain_data.values():
        all_ids.update((coordinator.data or {}).keys())

    if "mower_device" in data:
        registry = dr.async_get(hass)
        device = registry.async_get(data["mower_device"])
        if device:
            for domain, identifier in device.identifiers:
                if domain == DOMAIN and identifier in all_ids:
                    return identifier
        raise HomeAssistantError(f"Device '{data['mower_device']}' not found in iMow devices")

    name_query = data["mower_name"].lower()
    name_matches = list(dict.fromkeys(
        mid
        for coordinator in domain_data.values()
        for mid, mdata in (coordinator.data or {}).items()
        if name_query in (mdata.get("_deviceName") or "").lower()
    ))

    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        raise HomeAssistantError(
            f"Mower name '{data.get('mower_name')}' matches multiple iMow devices {name_matches}; "
            "use mower_device to disambiguate."
        )
    if len(all_ids) == 1:
        return next(iter(all_ids))
    raise HomeAssistantError(
        f"Could not find mower matching '{data.get('mower_name')}'. "
        f"Available mowers: {sorted(all_ids)}"
    )
