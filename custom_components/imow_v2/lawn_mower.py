"""Lawn mower platform for STIHL iMow v2 (start / pause / dock)."""
from __future__ import annotations

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CMD_DOCK, CMD_PAUSE, CMD_RESUME, CMD_START, DOMAIN
from .coordinator import ImowCoordinator
from .entity import ImowEntity

_ACTIVITY = {
    "mowing": LawnMowerActivity.MOWING,
    "driving": LawnMowerActivity.MOWING,
    "returning": LawnMowerActivity.RETURNING,
    "docked": LawnMowerActivity.DOCKED,
    "charging": LawnMowerActivity.DOCKED,
    "paused": LawnMowerActivity.PAUSED,
    "error": LawnMowerActivity.ERROR,
    "locked": LawnMowerActivity.ERROR,
    "sleeping": LawnMowerActivity.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ImowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ImowLawnMower(coordinator, mower_id) for mower_id in coordinator.data)


class ImowLawnMower(ImowEntity, LawnMowerEntity):
    """The mower itself."""

    _attr_name = None  # use the device name
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator: ImowCoordinator, mower_id: str) -> None:
        super().__init__(coordinator, mower_id, "lawn_mower")

    @property
    def activity(self) -> LawnMowerActivity | None:
        category = self.mower.get("_activity")
        if category == "busy":
            # Short internal work; report where the mower physically is
            docked = (self.mower.get("device") or {}).get("isDocked")
            return LawnMowerActivity.DOCKED if docked else LawnMowerActivity.MOWING
        return _ACTIVITY.get(category)

    async def async_start_mowing(self) -> None:
        """Resume a paused job, otherwise start a manual job."""
        if self.mower.get("_activity") == "paused":
            await self.coordinator.async_send_command(self._mower_id, CMD_RESUME)
            return
        await self.coordinator.async_send_command(
            self._mower_id,
            CMD_START,
            {"durationInSeconds": self.coordinator.start_duration_s(self._mower_id)},
        )

    async def async_pause(self) -> None:
        await self.coordinator.async_send_command(self._mower_id, CMD_PAUSE)

    async def async_dock(self) -> None:
        await self.coordinator.async_send_command(self._mower_id, CMD_DOCK)
