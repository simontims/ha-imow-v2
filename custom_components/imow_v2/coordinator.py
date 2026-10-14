"""DataUpdateCoordinator for STIHL iMow v2.

Polling fetches the full picture (cloud twin, settings incl. GPS, mowing plan,
event history, advices) and asks the mower for a fresh report. Between polls,
SignalR pushes partial updates which are merged into the same data and pushed
to entities straight away.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ImowApi, ImowApiError
from .auth import ImowAuth, ImowAuthError, ImowInvalidCredentials, ImowTokenRejected
from .const import (
    DOMAIN,
    ERROR_TEXT_LOCALES,
    OVERALL_STATE_GROUPS,
    SIGNALR_ADVICES,
    SIGNALR_PLAN,
    SIGNALR_SETTINGS,
    SIGNALR_STATUS,
)

_LOGGER = logging.getLogger(__name__)

_HISTORY_KEEP = 25          # events kept in memory / exposed as attributes
_PUSH_DEBOUNCE_S = 1.0      # SignalR bursts arrive as dozens of tiny messages
_FORCE_SETTLE_S = 6         # cloud twin lag after force-status-update (no SignalR)
# Categories in which the mower is out on the lawn and worth tracking
_AWAY_CATEGORIES = frozenset({"mowing", "driving", "returning", "paused", "error", "locked"})


def _deep_merge(target: dict, patch: dict) -> None:
    """Merge a SignalR partial document into target (lists are replaced)."""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


_UNKNOWN_STATES_LOGGED: set[str] = set()


def overall_category(state: str | None) -> str | None:
    """Group a raw overallState into the categories the myimow app uses."""
    if not state:
        return None
    for category, members in OVERALL_STATE_GROUPS.items():
        if state in members:
            return category
    if state not in _UNKNOWN_STATES_LOGGED:
        _UNKNOWN_STATES_LOGGED.add(state)
        _LOGGER.info("Unmapped iMow overallState '%s'; please report it", state)
    return None


class ImowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches data for all mowers and merges live SignalR updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth: ImowAuth,
        api: ImowApi,
        scan_interval_minutes: int,
        tracking_interval_s: int,
        username: str,
        password: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self._auth = auth
        self._api = api
        self._username = username
        self._password = password
        self._entry = entry
        self._auth_lock = asyncio.Lock()
        self._push_unsub: CALLBACK_TYPE | None = None
        self._history_unsub: dict[str, CALLBACK_TYPE] = {}
        self.signalr = None  # set by __init__.py once created
        self._tracking_interval_s = tracking_interval_s
        self._tracking: dict[str, asyncio.Task] = {}
        self.error_texts: dict[str, dict[str, str]] = {}  # code → {headline, description}

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def async_ensure_token(self) -> None:
        """Have a valid access token, re-logging in only if STIHL rejected ours."""
        async with self._auth_lock:
            if self._auth.access_token and not self._auth.token_needs_refresh:
                return
            await self._refresh_or_login()

    async def _refresh_or_login(self) -> None:
        try:
            await self._auth.refresh()
        except ImowTokenRejected as err:
            _LOGGER.warning("Refresh token rejected (%s), logging in again", err)
            await self._auth.login(self._username, self._password)
            _LOGGER.info("Re-login successful")
        self._persist_auth_tokens()

    async def _force_reauth(self) -> None:
        """Refresh after an API 401, even if the token looked valid."""
        async with self._auth_lock:
            await self._refresh_or_login()

    def _persist_auth_tokens(self) -> None:
        rt = self._auth.refresh_token
        if rt and rt != self._entry.data.get("refresh_token"):
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, "refresh_token": rt},
            )

    async def _call(self, func, *args):
        """Call an API method, re-authenticating once on a 401."""
        await self.async_ensure_token()
        try:
            return await func(*args)
        except ImowAuthError:
            await self._force_reauth()
            return await func(*args)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_all()
        except ImowInvalidCredentials as err:
            # The refresh token was rejected and the stored password no longer works
            raise ConfigEntryAuthFailed("STIHL rejected the email or password") from err
        except (ImowAuthError, ImowApiError) as err:
            raise UpdateFailed(str(err)) from err

    def _error_text_locale(self) -> str:
        """HA's language as a myimow locale ("en" → "en-GB"), else en-GB."""
        lang = self.hass.config.language or "en"
        if lang in ERROR_TEXT_LOCALES:
            return lang
        return next((loc for loc in ERROR_TEXT_LOCALES if loc.startswith(f"{lang.split('-')[0]}-")),
                    "en-GB")

    async def _load_error_texts(self) -> None:
        """Fetch the error texts once; retried on each poll until it works."""
        try:
            self.error_texts = await self._api.get_error_texts(self._error_text_locale())
        except ImowApiError as err:
            _LOGGER.debug("Error texts not loaded (will retry): %s", err)

    async def _fetch_all(self) -> dict[str, Any]:
        if not self.error_texts:
            await self._load_error_texts()
        mowers = await self._call(self._api.get_mowers)
        live = self.signalr is not None and self.signalr.connected

        ids = [str(m.get("deviceId") or m.get("id") or "") for m in mowers]
        ids = [i for i in ids if i]
        # Ask every mower for a fresh report. Over SignalR the answer arrives as
        # a push burst; without it, give the cloud twin a moment and re-read.
        forced = await asyncio.gather(
            *(self._call(self._api.force_status_update, i) for i in ids),
            return_exceptions=True,
        )
        for mower_id, res in zip(ids, forced):
            if isinstance(res, Exception):
                _LOGGER.debug("force-status-update failed for %s: %s", mower_id, res)
        if ids and not live and not all(isinstance(r, Exception) for r in forced):
            await asyncio.sleep(_FORCE_SETTLE_S)
            mowers = await self._call(self._api.get_mowers)

        result: dict[str, Any] = {}
        for mower in mowers:
            mower_id = str(mower.get("deviceId") or mower.get("id") or "")
            if not mower_id:
                continue
            settings, plan, history, advices = await asyncio.gather(
                self._call(self._api.get_mower_settings, mower_id),
                self._call(self._api.get_mowing_plan, mower_id),
                self._call(self._api.get_event_history, mower_id),
                self._call(self._api.get_advices, mower_id),
                return_exceptions=True,
            )
            previous = (self.data or {}).get(mower_id, {})
            merged = copy.deepcopy(mower)
            # Optional extras: on failure keep what we had rather than blanking entities
            for key, value in (("_settings", settings), ("_plan", plan),
                               ("_history", history), ("_advices", advices)):
                if isinstance(value, Exception):
                    _LOGGER.debug("Fetching %s for %s failed: %s", key, mower_id, value)
                    if key in previous:
                        merged[key] = previous[key]
                else:
                    merged[key] = value[:_HISTORY_KEEP] if key == "_history" else value
            self._derive(merged, mower_id)
            result[mower_id] = merged

        for mower_id in result:
            self._update_tracking(mower_id, result)
        return result

    # ------------------------------------------------------------------
    # SignalR push
    # ------------------------------------------------------------------

    @callback
    def handle_push(self, target: str, payload: dict[str, Any]) -> None:
        """Merge one SignalR partial update into the current data."""
        mower_id = payload.get("deviceId")
        if not self.data or mower_id not in self.data:
            return
        mower = self.data[mower_id]
        patch = {k: v for k, v in payload.items() if k != "deviceId"}
        if target == SIGNALR_STATUS:
            _deep_merge(mower, patch)
            # A state or job change usually means a new event-log entry
            if ("job" in patch or "overallState" in (patch.get("device") or {})) \
                    and mower_id not in self._history_unsub:
                self._history_unsub[mower_id] = async_call_later(
                    self.hass, 10, partial(self._history_timer_fired, mower_id)
                )
        elif target == SIGNALR_SETTINGS:
            _deep_merge(mower.setdefault("_settings", {}), patch)
        elif target == SIGNALR_PLAN:
            _deep_merge(mower.setdefault("_plan", {}), patch)
        elif target == SIGNALR_ADVICES:
            mower["_advices"] = patch.get("advices", [])
        else:
            _LOGGER.debug("Ignoring SignalR target %s", target)
            return
        self._derive(mower, mower_id)
        self._update_tracking(mower_id)
        # Not async_set_updated_data(): that would keep postponing the poll
        if self._push_unsub is None:
            self._push_unsub = async_call_later(
                self.hass, _PUSH_DEBOUNCE_S, self._flush_push
            )

    @callback
    def _flush_push(self, _now) -> None:
        self._push_unsub = None
        self.async_update_listeners()

    @callback
    def _history_timer_fired(self, mower_id: str, _now) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self._async_refresh_history(mower_id), "imow_v2 history refresh"
        )

    async def _async_refresh_history(self, mower_id: str) -> None:
        self._history_unsub.pop(mower_id, None)
        try:
            history = await self._call(self._api.get_event_history, mower_id)
        except (ImowAuthError, ImowApiError) as err:
            _LOGGER.debug("Event history refresh failed: %s", err)
            return
        mower = (self.data or {}).get(mower_id)
        if mower is not None:
            mower["_history"] = history[:_HISTORY_KEEP]
            self._derive(mower, mower_id)
            self.async_update_listeners()

    # ------------------------------------------------------------------
    # GPS tracking while away from the dock
    # ------------------------------------------------------------------

    def _is_away(self, mower: dict[str, Any]) -> bool:
        activity = mower.get("_activity")
        docked = bool((mower.get("device") or {}).get("isDocked"))
        # An error or lock on the dock (e.g. a wire fault) isn't worth tracking; out on the lawn
        # it is. isDocked is only trusted here: it can lag while a job is running.
        if activity in ("error", "locked"):
            return not docked
        if activity in _AWAY_CATEGORIES:
            return True
        return activity == "busy" and not docked

    @callback
    def _update_tracking(self, mower_id: str, data: dict[str, Any] | None = None) -> None:
        """Start a tracking loop when the mower leaves the dock.

        The mower only uploads its GPS position in reply to force-status-update,
        and the position is never pushed over SignalR, so it has to be polled.
        """
        mower = (data or self.data or {}).get(mower_id) or {}
        if self._tracking_interval_s <= 0 or mower_id in self._tracking:
            return
        if self._is_away(mower):
            self._tracking[mower_id] = self.config_entry.async_create_background_task(
                self.hass, self._async_track(mower_id), f"imow_v2 tracking {mower_id}"
            )

    async def _async_track(self, mower_id: str) -> None:
        _LOGGER.info("Mower away from dock: GPS tracking every %ss", self._tracking_interval_s)
        try:
            # Check at the end of each round: when started from a poll, self.data
            # does not hold that poll's result yet
            while True:
                try:
                    await self._call(self._api.force_status_update, mower_id)
                    await asyncio.sleep(_FORCE_SETTLE_S)
                    settings = await self._call(self._api.get_mower_settings, mower_id)
                except (ImowAuthError, ImowApiError) as err:
                    _LOGGER.debug("GPS tracking poll failed: %s", err)
                else:
                    mower = (self.data or {}).get(mower_id)
                    if mower is not None and settings:
                        mower["_settings"] = settings
                        self._derive(mower, mower_id)
                        self.async_update_listeners()
                await asyncio.sleep(max(self._tracking_interval_s - _FORCE_SETTLE_S, 5))
                if not self._is_away((self.data or {}).get(mower_id) or {}):
                    break
        finally:
            self._tracking.pop(mower_id, None)
            _LOGGER.info("GPS tracking stopped")

    @callback
    def async_cancel_timers(self) -> None:
        if self._push_unsub:
            self._push_unsub()
            self._push_unsub = None
        for unsub in self._history_unsub.values():
            unsub()
        self._history_unsub.clear()
        for task in self._tracking.values():
            task.cancel()
        self._tracking.clear()

    async def async_on_signalr_connect(self) -> None:
        """After (re)connecting, request a burst so nothing missed stays stale."""
        for mower_id in list(self.data or {}):
            try:
                await self._call(self._api.force_status_update, mower_id)
            except (ImowAuthError, ImowApiError) as err:
                _LOGGER.debug("force-status-update on connect failed: %s", err)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_send_command(
        self, mower_id: str, command: str, payload: dict | None = None
    ) -> None:
        try:
            reply = await self._call(self._api.send_command, mower_id, command, payload)
        except (ImowAuthError, ImowApiError) as err:
            raise HomeAssistantError(f"iMow command '{command}' failed: {err}") from err
        # 201 replies say whether the cloud reached the mower; 204 (force) has no body
        if isinstance(reply, dict) and reply.get("commandExecutionState") not in (
            None, "commandDelivered"
        ):
            raise HomeAssistantError(
                f"iMow command '{command}' not delivered to the mower: "
                f"{reply.get('commandExecutionState')}"
            )
        _LOGGER.info("iMow command '%s' sent to mower %s", command, mower_id)
        if not (self.signalr and self.signalr.connected):
            await self.async_request_refresh()

    def default_duration_s(self, mower_id: str) -> int:
        """The mower's own default manual mowing duration, in seconds."""
        setting = (self.data or {}).get(mower_id, {}).get("setting") or {}
        try:
            return int(setting.get("defaultManualMowingDuration") or 3600)
        except (TypeError, ValueError):
            return 3600

    def start_duration_s(self, mower_id: str) -> int:
        """Duration for a Start from HA: the duration number, else the mower default."""
        entity_id = er.async_get(self.hass).async_get_entity_id(
            Platform.NUMBER, DOMAIN, f"{mower_id}_default_mowing_duration"
        )
        state = self.hass.states.get(entity_id) if entity_id else None
        try:
            return int(float(state.state) * 60)
        except (AttributeError, TypeError, ValueError):
            return self.default_duration_s(mower_id)

    # ------------------------------------------------------------------
    # Derived fields
    # ------------------------------------------------------------------

    @staticmethod
    def _derive(mower: dict[str, Any], mower_id: str) -> None:
        device = mower.get("device") or {}
        # Job times come as naive device-local time; convert to UTC once
        tz_offset_s = device.get("deviceTimeZoneOffsetInSeconds") or 0
        job = mower.get("job") or {}
        for key in ("startTime", "endTime"):
            val = job.get(key)
            if tz_offset_s and isinstance(val, str) and val and "Z" not in val \
                    and "+" not in val[10:] and len(val) <= 20:
                try:
                    local = datetime.fromisoformat(val)
                    job[key] = (local - timedelta(seconds=tz_offset_s)).replace(
                        tzinfo=timezone.utc
                    ).isoformat()
                except ValueError:
                    pass
        mower["_nextStart"] = job.get("startTime")
        # Zone of the running manual job, by name ("Back"), from the mowing plan
        mower["_jobZone"] = None
        if str(job.get("state") or "").endswith("JobRunning"):
            manual = (mower.get("_plan") or {}).get("mowingPlanManualJob") or {}
            zone_id = manual.get("mowingZoneId")
            zones = (mower.get("setting") or {}).get("mowingZones") or []
            mower["_jobZone"] = next(
                (z.get("name") for z in zones if z.get("mowingZoneId") == zone_id),
                None if zone_id is None else f"Zone {zone_id}",
            )
        mower["_activity"] = overall_category(
            (device.get("overallState") or {}).get("state")
        )
        history = mower.get("_history") or []
        mower["_lastEvent"] = history[0] if history else None
        mower["_deviceName"] = (
            (mower.get("setting") or {}).get("deviceNickname")
            or device.get("type")
            or f"iMow {mower_id[-6:]}"
        )
