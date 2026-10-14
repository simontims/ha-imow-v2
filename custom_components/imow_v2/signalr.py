"""Minimal SignalR client for the STIHL iMow ``deviceevents`` hub.

The myimow web app receives every mower change through this hub: each message
is a partial JSON document (only the fields that changed) for one of the
targets ``mowerStatus``, ``mowerSettings``, ``mowingPlan`` or ``advices``.
A ``force-status-update`` command makes the mower resend its whole state as a
burst of these messages.

Only the JSON hub protocol over WebSockets is implemented; that is all the
Azure SignalR service needs for receive-only use.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .api import ImowApi, ImowApiError
from .auth import ImowAuth, ImowAuthError

_LOGGER = logging.getLogger(__name__)

_RS = "\x1e"  # SignalR record separator
_MSG_INVOCATION = 1
_MSG_PING = 6
_MSG_CLOSE = 7
_KEEPALIVE_S = 15
_SERVER_TIMEOUT_S = 60
_BACKOFF_S = (5, 15, 30, 60, 120, 300)

MessageCallback = Callable[[str, dict[str, Any]], None]


class ImowSignalR:
    """Keeps a hub connection open, reconnecting with backoff."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: ImowAuth,
        api: ImowApi,
        on_message: MessageCallback,
        ensure_token: Callable[[], Awaitable[None]],
        on_connect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._auth = auth
        self._api = api
        self._on_message = on_message
        self._ensure_token = ensure_token
        self._on_connect = on_connect
        self._task: asyncio.Task | None = None
        self.connected = False

    def start(self, hass) -> None:
        if self._task is None:
            self._task = hass.async_create_background_task(
                self._run(), "imow_v2 signalr"
            )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.connected = False

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                await self._connect_and_listen()
                attempt = 0  # clean close after a working session
            except asyncio.CancelledError:
                raise
            except (ImowAuthError, ImowApiError, aiohttp.ClientError,
                    asyncio.TimeoutError, ValueError) as err:
                _LOGGER.debug("SignalR connection failed: %r", err)
            except Exception:  # noqa: BLE001 — never let the loop die
                _LOGGER.exception("Unexpected SignalR error")
            self.connected = False
            delay = _BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)]
            attempt += 1
            _LOGGER.debug("SignalR reconnecting in %ss", delay)
            await asyncio.sleep(delay)

    async def _connect_and_listen(self) -> None:
        await self._ensure_token()
        neg = await self._api.negotiate_signalr()
        hub_url, hub_token = neg.get("url"), neg.get("accessToken")
        if not hub_url or not hub_token:
            raise ValueError(f"unexpected negotiate response keys: {sorted(neg)}")
        hub_headers = {"Authorization": f"Bearer {hub_token}"}

        # Second negotiate, against the Azure SignalR service itself
        neg_url = hub_url.replace("/client/?", "/client/negotiate?", 1)
        async with self._session.post(
            f"{neg_url}&negotiateVersion=1",
            headers=hub_headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            conn = await resp.json(content_type=None)
        conn_token = conn.get("connectionToken") or conn.get("connectionId")
        if not conn_token:
            raise ValueError("service negotiate returned no connection token")

        ws_url = hub_url.replace("https://", "wss://", 1) + f"&id={conn_token}"
        async with self._session.ws_connect(
            ws_url, headers=hub_headers, heartbeat=None,
            timeout=aiohttp.ClientWSTimeout(ws_close=10),
        ) as ws:
            await ws.send_str(json.dumps({"protocol": "json", "version": 1}) + _RS)
            handshake = await ws.receive(timeout=15)
            if handshake.type != aiohttp.WSMsgType.TEXT:
                raise ValueError(f"no handshake reply ({handshake.type})")
            reply = json.loads(handshake.data.split(_RS)[0] or "{}")
            if reply.get("error"):
                raise ValueError(f"handshake rejected: {reply['error']}")

            self.connected = True
            _LOGGER.info("SignalR connected to iMow device events")
            if self._on_connect:
                await self._on_connect()
            keepalive = asyncio.create_task(self._keepalive(ws))
            try:
                await self._listen(ws)
            finally:
                keepalive.cancel()
                self.connected = False

    async def _keepalive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        ping = json.dumps({"type": _MSG_PING}) + _RS
        while not ws.closed:
            await asyncio.sleep(_KEEPALIVE_S)
            await ws.send_str(ping)

    async def _listen(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            msg = await ws.receive(timeout=_SERVER_TIMEOUT_S)
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                _LOGGER.debug("SignalR socket closed (%s)", msg.type)
                return
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            for record in filter(None, msg.data.split(_RS)):
                frame = json.loads(record)
                kind = frame.get("type")
                if kind == _MSG_CLOSE:
                    _LOGGER.debug("SignalR server closed: %s", frame.get("error"))
                    return
                if kind != _MSG_INVOCATION:
                    continue
                target = frame.get("target", "")
                for arg in frame.get("arguments") or []:
                    try:
                        payload = json.loads(arg) if isinstance(arg, str) else arg
                    except ValueError:
                        _LOGGER.debug("Unparseable %s payload: %.200s", target, arg)
                        continue
                    if isinstance(payload, dict):
                        self._on_message(target, payload)
