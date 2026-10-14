"""Shared base entity for STIHL iMow v2."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ImowCoordinator


def deep_get(data: Any, path: tuple[str, ...]) -> Any:
    """Follow a key path through nested dicts; None if any step is missing."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class ImowEntity(CoordinatorEntity[ImowCoordinator]):
    """An entity belonging to one mower."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ImowCoordinator, mower_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._mower_id = mower_id
        self._attr_unique_id = f"{mower_id}_{key}"
        mower = coordinator.data.get(mower_id, {})
        device = mower.get("device") or {}
        settings = mower.get("_settings") or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mower_id)},
            name=mower.get("_deviceName") or f"iMow {mower_id[-6:]}",
            manufacturer=MANUFACTURER,
            model=device.get("type") or "STIHL iMow Gen5+",
            model_id=settings.get("deviceModel"),
            serial_number=settings.get("serialNumber"),
            sw_version=(mower.get("setting") or {}).get(
                "deviceSoftwarePackageVersionInstalled"
            ),
        )

    @property
    def mower(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(self._mower_id, {})

    @property
    def available(self) -> bool:
        return super().available and self._mower_id in (self.coordinator.data or {})
