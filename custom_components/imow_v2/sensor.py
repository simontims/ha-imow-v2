"""Sensor platform for STIHL iMow v2."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ImowCoordinator
from .entity import ImowEntity, deep_get

_EVENT_PREFIX = "dB_eventHistory_line01_"


def _parse_dt(v: object) -> datetime | None:
    """Parse an ISO-8601 string to an aware datetime (naive = UTC)."""
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours(v: Any) -> float | None:
    try:
        return round(int(v) / 3600, 1)
    except (TypeError, ValueError):
        return None


def event_text(event: dict[str, Any] | None) -> str | None:
    """'dB_eventHistory_line01_returning_to_dock' → 'Returning to dock'."""
    if not event:
        return None
    key = str(event.get("eventTextKeyLine1") or "")
    text = key.removeprefix(_EVENT_PREFIX).replace("_", " ").strip().capitalize()
    if event.get("parameterValue"):
        text = f"{text} ({event['parameterValue']})"
    return text or None



@dataclass(frozen=True, kw_only=True)
class ImowSensorDescription(SensorEntityDescription):
    """Sensor read from a key path into the merged mower data."""

    value_path: tuple[str, ...]
    transform: Callable[[Any], Any] | None = None
    attrs: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _recent_events(mower: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent": [
            {"time": e.get("dateTime"), "event": event_text(e), "icon": e.get("eventIcon")}
            for e in (mower.get("_history") or [])[:10]
        ]
    }



DIAG = EntityCategory.DIAGNOSTIC

SENSOR_DESCRIPTIONS: tuple[ImowSensorDescription, ...] = (
    # ── Status ──────────────────────────────────────────────────────────
    ImowSensorDescription(
        key="activity", name="Activity", icon="mdi:robot-mower",
        device_class=SensorDeviceClass.ENUM,
        options=["docked", "charging", "returning", "driving", "mowing", "paused",
                 "error", "locked", "offline", "sleeping", "busy"],
        value_path=("_activity",),
    ),
    ImowSensorDescription(
        key="overall_state", name="Overall State", icon="mdi:robot-mower",
        entity_category=DIAG, value_path=("device", "overallState", "state"),
    ),
    ImowSensorDescription(
        key="job_state", name="Job State", icon="mdi:state-machine",
        value_path=("job", "state"),
    ),
    ImowSensorDescription(
        key="last_event", name="Last Event", icon="mdi:history",
        value_path=("_lastEvent",), transform=event_text, attrs=_recent_events,
    ),
    ImowSensorDescription(
        key="last_event_time", name="Last Event Time",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:history",
        value_path=("_lastEvent", "dateTime"), transform=_parse_dt,
    ),
    ImowSensorDescription(
        key="job_zone", name="Job Zone", icon="mdi:map-marker-path",
        value_path=("_jobZone",),
    ),
    ImowSensorDescription(
        key="area", name="Current Area", icon="mdi:map-marker-radius",
        value_path=("device", "currentArea"),
    ),
    ImowSensorDescription(
        key="advice", name="Advice", icon="mdi:lightbulb-on-outline",
        value_path=("_advices",),
        transform=lambda v: ", ".join(a.get("type", "?") for a in v) if v else "none",
    ),
    # ── Battery ─────────────────────────────────────────────────────────
    ImowSensorDescription(
        key="battery", name="Battery", device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
        value_path=("battery", "level"),
        transform=lambda v: round(float(v) * 100),
    ),
    ImowSensorDescription(
        key="charge_sufficient_for", name="Charge Sufficient For",
        icon="mdi:battery-check", value_path=("battery", "sufficientlyChargedForOperation"),
    ),
    ImowSensorDescription(
        key="battery_next_state", name="Battery Next State", icon="mdi:battery-clock",
        value_path=("battery", "stateEvent", "nextState"),
    ),
    ImowSensorDescription(
        key="battery_next_state_time", name="Battery Next State Time",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:battery-clock",
        value_path=("battery", "stateEvent", "forecastedEventTime"), transform=_parse_dt,
    ),
    # ── GPS ─────────────────────────────────────────────────────────────
    ImowSensorDescription(
        key="gps_accuracy", name="GPS Accuracy", icon="mdi:crosshairs-gps",
        native_unit_of_measurement=UnitOfLength.METERS, entity_category=DIAG,
        device_class=SensorDeviceClass.DISTANCE, state_class=SensorStateClass.MEASUREMENT,
        value_path=("_settings", "location", "accuracy"), transform=lambda v: round(float(v), 1),
    ),
    ImowSensorDescription(
        key="gps_updated", name="GPS Updated", device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=DIAG, value_path=("_settings", "location", "lastUpdated"),
        transform=_parse_dt,
    ),
    # ── Job times ───────────────────────────────────────────────────────
    ImowSensorDescription(
        key="job_start_time", name="Job Start Time",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:clock-start",
        value_path=("job", "startTime"), transform=_parse_dt,
    ),
    ImowSensorDescription(
        key="job_end_time", name="Job End Time",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:clock-end",
        value_path=("job", "endTime"), transform=_parse_dt,
    ),
    ImowSensorDescription(
        key="last_seen", name="Last Seen", device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check", value_path=("device", "lastConnectionStateUpdate"),
        transform=_parse_dt,
    ),
    # ── Settings ────────────────────────────────────────────────────────
    ImowSensorDescription(
        key="cutting_height", name="Cutting Height", icon="mdi:grass",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        value_path=("_settings", "cuttingHeight"), transform=lambda v: round(float(v) * 1000),
    ),
    # ── Connectivity ────────────────────────────────────────────────────
    ImowSensorDescription(
        key="wifi_signal", name="Wi-Fi Signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT, entity_category=DIAG,
        value_path=("_settings", "wifiNetworkInformation", "currentSignalStrength"),
    ),
    ImowSensorDescription(
        key="cellular_signal", name="Cellular Signal", icon="mdi:signal",
        state_class=SensorStateClass.MEASUREMENT, entity_category=DIAG,
        value_path=("_settings", "cellularNetworkInformation", "currentSignalStrength"),
    ),
    ImowSensorDescription(
        key="cellular_network", name="Cellular Network", icon="mdi:sim",
        entity_category=DIAG,
        value_path=("_settings", "cellularNetworkInformation"),
        transform=lambda v: " ".join(
            x for x in (v.get("providerId"), v.get("connectionType")) if x
        ) or None,
    ),
    # ── Statistics ──────────────────────────────────────────────────────
    ImowSensorDescription(
        key="stat_total_operating_time", name="Total Operating Time",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_path=("statistics", "totalWorkingSeconds"), transform=_hours,
    ),
    ImowSensorDescription(
        key="stat_total_distance", name="Total Distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_path=("statistics", "totalDrivenDistance"),
        transform=lambda v: round(int(v) / 1000, 1),
    ),
    ImowSensorDescription(
        key="stat_blade_time", name="Blade Operating Time",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL, icon="mdi:knife",
        value_path=("statistics", "totalWorkingTimeOfCurrentCuttingKnifes"), transform=_hours,
    ),
    ImowSensorDescription(
        key="stat_total_jobs", name="Total Mowing Jobs", icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_path=("statistics", "totalStartedMowingJobs"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ImowCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        ImowSensor(coordinator, mower_id, desc)
        for mower_id in coordinator.data
        for desc in SENSOR_DESCRIPTIONS
    ]
    entities += [ImowTimeRemainingSensor(coordinator, mower_id) for mower_id in coordinator.data]
    async_add_entities(entities)


class ImowSensor(ImowEntity, SensorEntity):
    """A single sensor entity for an iMow mower."""

    entity_description: ImowSensorDescription

    def __init__(
        self, coordinator: ImowCoordinator, mower_id: str, description: ImowSensorDescription
    ) -> None:
        super().__init__(coordinator, mower_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        raw = deep_get(self.mower, self.entity_description.value_path)
        if raw is None:
            return None
        if self.entity_description.transform:
            try:
                return self.entity_description.transform(raw)
            except (TypeError, ValueError, AttributeError):
                return None
        return raw

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs:
            return self.entity_description.attrs(self.mower)
        return None


class ImowTimeRemainingSensor(ImowEntity, SensorEntity):
    """Minutes until the running job's end time (includes the drive home)."""

    _attr_name = "Time Remaining"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: ImowCoordinator, mower_id: str) -> None:
        super().__init__(coordinator, mower_id, "time_remaining")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The end time is fixed, so count down between coordinator updates
        self.async_on_remove(
            async_track_time_interval(self.hass, self._tick, timedelta(minutes=1))
        )

    @callback
    def _tick(self, _now) -> None:
        if self.native_value is not None or self.state not in (None, "unknown"):
            self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        job = self.mower.get("job") or {}
        if not job.get("state", "").endswith("JobRunning"):
            return None
        end = _parse_dt(job.get("endTime"))
        if end is None:
            return None
        return max(0, round((end - dt_util.utcnow()).total_seconds() / 60))
