"""Binary sensor platform for STIHL iMow v2."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ImowCoordinator
from .entity import ImowEntity, deep_get


@dataclass(frozen=True, kw_only=True)
class ImowBinarySensorDescription(BinarySensorEntityDescription):
    value_path: tuple[str, ...]
    transform: Callable[[Any], bool] = bool
    attrs_path: tuple[str, ...] | None = None


DIAG = EntityCategory.DIAGNOSTIC

BINARY_SENSOR_DESCRIPTIONS: tuple[ImowBinarySensorDescription, ...] = (
    ImowBinarySensorDescription(
        key="is_raining", translation_key="is_raining",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_path=("sensor", "sensorIsRaining"),
    ),
    ImowBinarySensorDescription(
        key="online", translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_path=("device", "isCurrentlyConnected"),
    ),
    ImowBinarySensorDescription(
        key="docked", translation_key="docked", icon="mdi:home",
        value_path=("device", "isDocked"),
    ),
    ImowBinarySensorDescription(
        key="problem", translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_path=("device", "errorsActive"),
        attrs_path=("device", "errorsActive"),
    ),
    ImowBinarySensorDescription(
        key="service_required", translation_key="service_required",
        device_class=BinarySensorDeviceClass.PROBLEM, icon="mdi:wrench-clock",
        value_path=("device", "servicesRequired"),
        attrs_path=("device", "servicesRequired"),
    ),
    ImowBinarySensorDescription(
        key="mowing_plan_active", translation_key="mowing_plan_active", icon="mdi:calendar-check",
        value_path=("mowingPlan", "isMowingPlanActive"),
    ),
    ImowBinarySensorDescription(
        key="wifi_connected", translation_key="wifi_connected", icon="mdi:wifi",
        device_class=BinarySensorDeviceClass.CONNECTIVITY, entity_category=DIAG,
        value_path=("wifiIsConnected",),
    ),
    ImowBinarySensorDescription(
        key="cellular_connected", translation_key="cellular_connected", icon="mdi:signal",
        device_class=BinarySensorDeviceClass.CONNECTIVITY, entity_category=DIAG,
        value_path=("cellularIsConnected",),
    ),
    ImowBinarySensorDescription(
        key="software_update", translation_key="software_update",
        device_class=BinarySensorDeviceClass.UPDATE, entity_category=DIAG,
        value_path=("device", "isSoftwareUpdateAvailableForInstallation"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ImowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ImowBinarySensor(coordinator, mower_id, desc)
        for mower_id in coordinator.data
        for desc in BINARY_SENSOR_DESCRIPTIONS
    )


class ImowBinarySensor(ImowEntity, BinarySensorEntity):
    """A binary sensor entity for an iMow mower."""

    entity_description: ImowBinarySensorDescription

    def __init__(
        self, coordinator: ImowCoordinator, mower_id: str,
        description: ImowBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, mower_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        val = deep_get(self.mower, self.entity_description.value_path)
        if val is None:
            return None
        return self.entity_description.transform(val)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_path:
            return {"details": deep_get(self.mower, self.entity_description.attrs_path) or []}
        return None
