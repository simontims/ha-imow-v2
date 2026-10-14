"""Sensor platform for STIHL iMow v2."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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


def _first_error(v: Any) -> Any:
    if not isinstance(v, list) or not v:
        return None
    err = v[0]
    if isinstance(err, dict):
        for k in ("errorCode", "code", "errorId", "id", "dtc"):
            if err.get(k) is not None:
                return str(err[k])
        return str(err)[:250]
    return str(err)


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


def _error_attrs(mower: dict[str, Any]) -> dict[str, Any]:
    return {"errors": (mower.get("device") or {}).get("errorsActive") or []}


DIAG = EntityCategory.DIAGNOSTIC

SENSOR_DESCRIPTIONS: tuple[ImowSensorDescription, ...] = (
    # ── Status ──────────────────────────────────────────────────────────
    ImowSensorDescription(
        key="activity", name="Activity", icon="mdi:robot-mower",
        device_class=SensorDeviceClass.ENUM,
        options=["docked", "charging", "returning", "driving", "mowing", "paused",
                 "error", "locked", "offline", "sleeping"],
        value_path=("_activity",),
    ),
    ImowSensorDescription(
        key="overall_state", name="Overall State", icon="mdi:robot-mower",
        value_path=("device", "overallState", "state"),
    ),
    ImowSensorDescription(
        key="job_state", name="Job State", icon="mdi:state-machine",
        value_path=("job", "state"),
    ),
    ImowSensorDescription(
        key="state_trigger", name="State Trigger", icon="mdi:message-text",
        entity_category=DIAG, value_path=("device", "overallState", "trigger"),
    ),
    ImowSensorDescription(
        key="machine_error", name="Error Code", icon="mdi:alert-circle-outline",
        value_path=("device", "errorsActive"), transform=_first_error,
        attrs=_error_attrs,
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
    ImowSensorDescription(
        key="battery_endurance", name="Battery Endurance",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=DIAG, value_path=("battery", "endurance"),
        transform=lambda v: round(int(v) / 60),
    ),
    # ── GPS ─────────────────────────────────────────────────────────────
    ImowSensorDescription(
        key="gps_latitude", name="GPS Latitude", icon="mdi:latitude",
        entity_category=DIAG, value_path=("_settings", "location", "latitude"),
    ),
    ImowSensorDescription(
        key="gps_longitude", name="GPS Longitude", icon="mdi:longitude",
        entity_category=DIAG, value_path=("_settings", "location", "longitude"),
    ),
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
    ImowSensorDescription(
        key="heading", name="Heading", icon="mdi:compass-outline",
        native_unit_of_measurement=DEGREE, entity_category=DIAG,
        value_path=("_settings", "courseAngle"),
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
        key="next_start", name="Next Scheduled Start",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:calendar-clock",
        value_path=("_nextStart",), transform=_parse_dt,
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
    # ── Device info ─────────────────────────────────────────────────────
    ImowSensorDescription(
        key="model", name="Model", icon="mdi:robot-mower", entity_category=DIAG,
        value_path=("device", "type"),
    ),
    ImowSensorDescription(
        key="timezone", name="Time Zone", icon="mdi:map-clock-outline",
        entity_category=DIAG, value_path=("device", "deviceTimeZone"),
    ),
    ImowSensorDescription(
        key="firmware", name="Firmware", icon="mdi:information-outline",
        entity_category=DIAG,
        value_path=("setting", "deviceSoftwarePackageVersionInstalled"),
    ),
    ImowSensorDescription(
        key="nickname", name="Nickname", icon="mdi:tag", entity_category=DIAG,
        value_path=("setting", "deviceNickname"),
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
    async_add_entities(
        ImowSensor(coordinator, mower_id, desc)
        for mower_id in coordinator.data
        for desc in SENSOR_DESCRIPTIONS
    )


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
