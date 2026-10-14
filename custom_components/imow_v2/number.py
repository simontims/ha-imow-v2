"""Number platform for STIHL iMow v2 — duration used by Start commands from HA."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import ImowCoordinator
from .entity import ImowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ImowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ImowMowingDurationNumber(coordinator, mower_id) for mower_id in coordinator.data
    )


class ImowMowingDurationNumber(ImowEntity, NumberEntity, RestoreEntity):
    """How long a Start from HA mows for (minutes).

    Local to HA: it starts at the mower's own default manual mowing duration
    and is not written back to the mower.
    """

    _attr_name = "Default Mowing Duration"
    _attr_icon = "mdi:timer-edit"
    _attr_native_min_value = 5
    _attr_native_max_value = 480
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImowCoordinator, mower_id: str) -> None:
        super().__init__(coordinator, mower_id, "default_mowing_duration")
        self._current_value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state not in (
            None, "unknown", "unavailable"
        ):
            try:
                self._current_value = float(last.state)
                return
            except ValueError:
                pass
        self._current_value = round(self.coordinator.default_duration_s(self._mower_id) / 60)

    @property
    def native_value(self) -> float | None:
        return self._current_value

    async def async_set_native_value(self, value: float) -> None:
        self._current_value = value
        self.async_write_ha_state()

    @property
    def duration_s(self) -> int:
        if self._current_value is None:
            return self.coordinator.default_duration_s(self._mower_id)
        return int(self._current_value * 60)
