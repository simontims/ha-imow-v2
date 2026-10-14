"""Device tracker platform — shows the mower on the HA map."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ImowCoordinator
from .entity import ImowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ImowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ImowTrackerEntity(coordinator, mower_id) for mower_id in coordinator.data)


class ImowTrackerEntity(ImowEntity, TrackerEntity):
    """The mower's GPS position, from mower-settings → location."""

    _attr_translation_key = "location"
    _attr_icon = "mdi:robot-mower"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: ImowCoordinator, mower_id: str) -> None:
        super().__init__(coordinator, mower_id, "tracker")

    @property
    def _location(self) -> dict[str, Any]:
        settings = self.mower.get("_settings") or {}
        if not (settings.get("locationValidity") or {}).get("isValid", True):
            return {}
        return settings.get("location") or {}

    def _coord(self, key: str) -> float | None:
        try:
            return float(self._location[key])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def latitude(self) -> float | None:
        return self._coord("latitude")

    @property
    def longitude(self) -> float | None:
        return self._coord("longitude")

    @property
    def location_accuracy(self) -> float:
        return self._coord("accuracy") or 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        settings = self.mower.get("_settings") or {}
        return {
            "heading": settings.get("courseAngle"),
            "last_updated": self._location.get("lastUpdated"),
        }
