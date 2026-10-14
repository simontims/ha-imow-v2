"""STIHL iMow REST API client."""
from __future__ import annotations

import asyncio
import json
import logging
from json import JSONDecodeError
from typing import Any

import aiohttp

from .auth import ImowAuth, ImowAuthError
from .const import (
    APIM_KEY,
    API_ADVICES,
    API_COMMAND,
    API_EVENT_HISTORY,
    API_MOWER_SETTINGS,
    API_MOWERS,
    API_MOWING_PLAN,
    API_SIGNALR_NEG,
    CMD_FORCE_UPDATE,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

_COMMON_HEADERS = {
    "Ocp-Apim-Subscription-Key": APIM_KEY,
    "Accept": "application/json",
    "User-Agent": USER_AGENT,
}


class ImowApiError(Exception):
    """Raised for non-auth API errors."""


class ImowApi:
    """Thin wrapper around the STIHL APIM REST endpoints."""

    def __init__(self, session: aiohttp.ClientSession, auth: ImowAuth) -> None:
        self._session = session
        self._auth = auth

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_mowers(self) -> list[dict[str, Any]]:
        """Return the account's mowers with their full status (the cloud twin)."""
        data = await self._get(API_MOWERS)
        if isinstance(data, list):
            return data
        return data.get("mowers", [data]) if isinstance(data, dict) else []

    async def get_mower_settings(self, mower_id: str) -> dict[str, Any]:
        """Return settings, GPS location, Wi-Fi/cellular info and cutting height."""
        return await self._get(API_MOWER_SETTINGS.format(id=mower_id)) or {}

    async def get_mowing_plan(self, mower_id: str) -> dict[str, Any]:
        """Return the mowing plan / calendar for the mower."""
        return await self._get(API_MOWING_PLAN.format(id=mower_id)) or {}

    async def get_event_history(self, mower_id: str) -> list[dict[str, Any]]:
        """Return the mower's event log, newest first."""
        data = await self._get(API_EVENT_HISTORY.format(id=mower_id))
        return data if isinstance(data, list) else []

    async def get_advices(self, mower_id: str) -> list[dict[str, Any]]:
        """Return the advice notices the app shows for this mower."""
        data = await self._get(API_ADVICES.format(id=mower_id)) or {}
        return data.get("advices", []) if isinstance(data, dict) else []

    async def send_command(
        self, mower_id: str, command: str, payload: dict | None = None
    ) -> Any:
        """Send a mower command (start-mowing, pause, resume, end-job-and-return-to-dock, …)."""
        url = API_COMMAND.format(id=mower_id, cmd=command)
        return await self._post(url, payload)

    async def force_status_update(self, mower_id: str) -> None:
        """Ask the mower to report its full state now.

        The fresh state arrives over SignalR (and in the cloud twin a few
        seconds later). Unlike the dashboard ``force-status-update-mode`` query
        parameter, this returns straight away instead of waiting for the mower.
        """
        await self.send_command(mower_id, CMD_FORCE_UPDATE)

    async def negotiate_signalr(self) -> dict[str, Any]:
        """Return {url, accessToken} for the Azure SignalR ``deviceevents`` hub."""
        return await self._post(API_SIGNALR_NEG, None) or {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, url: str) -> Any:
        headers = {**_COMMON_HEADERS, "Authorization": f"Bearer {self._auth.access_token}"}
        try:
            async with self._session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise ImowAuthError("401 from API — token expired")
                if resp.status >= 400:
                    raise ImowApiError(f"GET {url} → {resp.status}: {text[:200]}")
                if not text.strip():
                    return None
                try:
                    return json.loads(text)
                except JSONDecodeError as err:
                    raise ImowApiError(
                        f"GET {url}: invalid JSON response: {text[:200]}"
                    ) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ImowApiError(f"GET {url}: network error: {err!r}") from err

    async def _post(self, url: str, payload: dict | None) -> Any:
        headers = {**_COMMON_HEADERS, "Authorization": f"Bearer {self._auth.access_token}"}
        kwargs: dict[str, Any] = {}
        if payload is not None:
            kwargs["json"] = payload
        try:
            async with self._session.post(
                url, headers=headers, timeout=_REQUEST_TIMEOUT, **kwargs
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise ImowAuthError("401 from API — token expired")
                if resp.status >= 400:
                    raise ImowApiError(f"POST {url} → {resp.status}: {text[:200]}")
                if text.strip():
                    try:
                        return json.loads(text)
                    except JSONDecodeError:
                        pass
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ImowApiError(f"POST {url}: network error: {err!r}") from err
