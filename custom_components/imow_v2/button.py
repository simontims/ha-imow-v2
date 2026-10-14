"""Button platform for STIHL iMow v2."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CMD_CLEAR_ERRORS, CMD_FORCE_UPDATE, DOMAIN
from .coordinator import ImowCoordinator
from .entity import ImowEntity


@dataclass(frozen=True, kw_only=True)
class ImowButtonDescription(ButtonEntityDescription):
    command: str


BUTTONS: tuple[ImowButtonDescription, ...] = (
    ImowButtonDescription(
        key="refresh_status", name="Refresh Status", icon="mdi:refresh",
        entity_category=EntityCategory.DIAGNOSTIC, command=CMD_FORCE_UPDATE,
    ),
    ImowButtonDescription(
        key="clear_errors", name="Clear Errors", icon="mdi:alert-remove-outline",
        command=CMD_CLEAR_ERRORS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ImowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ImowButton(coordinator, mower_id, desc)
        for mower_id in coordinator.data
        for desc in BUTTONS
    )


class ImowButton(ImowEntity, ButtonEntity):
    entity_description: ImowButtonDescription

    def __init__(
        self, coordinator: ImowCoordinator, mower_id: str, description: ImowButtonDescription
    ) -> None:
        super().__init__(coordinator, mower_id, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.async_send_command(
            self._mower_id, self.entity_description.command
        )
