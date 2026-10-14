"""STIHL iMow Azure B2C PKCE authentication (myimow / Gen5+)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from urllib.parse import parse_qs, quote, urlencode, urlparse

import aiohttp

from .const import (
    B2C_BASE,
    B2C_CLIENT_ID,
    B2C_POLICY_MIXED,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    B2C_TOKEN_URL,
    B2C_AUTHORIZE_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class ImowAuthError(Exception):
    """Raised when authentication fails."""


class ImowTokenRejected(ImowAuthError):
    """Raised when STIHL rejects the refresh token, so a full login is needed.

    Network errors and server hiccups raise plain ImowAuthError instead: those
    are worth retrying later, not a reason to send the password again.
    """


def _pkce_pair() -> tuple[str, str]:
    """Return a fresh (code_verifier, code_challenge) pair for one login."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class ImowAuth:
    """Handles STIHL Azure B2C PKCE login and token refresh."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        # Shared HA session — used only for token refresh (no cookies needed)
        self._session = session
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_in: int = 0
        self._token_acquired_at: float = 0.0
        self._code_verifier: str = ""
        self._code_challenge: str = ""

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def token_needs_refresh(self) -> bool:
        """True when the access token is within 60s of expiry (by monotonic clock)."""
        if not self.access_token or not hasattr(self, "_token_acquired_at"):
            return False
        return (time.monotonic() - self._token_acquired_at) > (self.expires_in - 60)

    # ------------------------------------------------------------------
    # Login (PKCE flow)
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str) -> None:
        """Full Azure B2C PKCE login.  Raises ImowAuthError on failure.

        Step 1 uses a CookieJar to capture B2C session cookies.
        Steps 2-4 inject those cookies manually via the Cookie header to avoid
        path-case-sensitivity issues (B2C uses lowercase path in step 1 but
        mixed-case in step 2, which breaks Python's RFC-6265 path matching).
        """
        self._state = secrets.token_urlsafe(16)
        self._code_verifier, self._code_challenge = _pkce_pair()
        # ── Step 1: capture cookies with a jar ───────────────────────────
        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as s1:
            _LOGGER.debug("B2C login: step 1 — authorize")
            settings = await self._step1_authorize(s1)

        # Extract ALL cookies from the jar, ignoring path/domain constraints
        cookie_header = "; ".join(f"{c.key}={c.value}" for c in jar)
        _LOGGER.debug("step1 cookies captured: keys=%s", [c.key for c in jar])

        # ── Steps 2-4: DummyCookieJar + manual Cookie header ─────────────
        async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as s2:
            _LOGGER.debug("B2C login: step 2 — SelfAsserted (transId=%s)", settings.get("transId", "?")[:20])
            # Step 2 may set/update session cookies — capture and merge them
            cookie_header = await self._step2_self_asserted(s2, settings, username, password, cookie_header)

            _LOGGER.debug("B2C login: step 3 — confirmed / auth code")
            code = await self._step3_confirmed(s2, settings, cookie_header)

            _LOGGER.debug("B2C login: step 4 — token exchange")
            await self._step4_token(s2, code)

        _LOGGER.info("B2C login successful, token expires in %ds", self.expires_in)

    # ------------------------------------------------------------------
    # Token refresh (no cookies needed — uses shared HA session)
    # ------------------------------------------------------------------

    async def refresh(self) -> None:
        """Use stored refresh_token to obtain a new access_token."""
        if not self.refresh_token:
            raise ImowAuthError("No refresh token available")
        try:
            async with self._session.post(
                B2C_TOKEN_URL,
                timeout=aiohttp.ClientTimeout(total=30),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": B2C_CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                text = await resp.text()
                if resp.status in (400, 401):
                    # invalid_grant: expired, revoked or unknown refresh token
                    raise ImowTokenRejected(f"Token refresh rejected (HTTP {resp.status})")
                if resp.status >= 400:
                    raise ImowAuthError(f"Token refresh failed (HTTP {resp.status})")
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as err:
                    # Seen once in the wild; log enough to identify it next time.
                    # Treated as a rejection: a fresh login is what recovered it.
                    _LOGGER.warning(
                        "Token refresh: non-JSON reply (HTTP %s, %s): %.300s",
                        resp.status, resp.content_type, text,
                    )
                    raise ImowTokenRejected("Token refresh failed: non-JSON response") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ImowAuthError(f"Token refresh network error: {err}") from err
        if not data.get("access_token"):
            err_code = data.get("error") if isinstance(data, dict) else None
            raise ImowTokenRejected(
                f"Token refresh failed: {err_code or 'no access_token in response'}"
            )
        self._apply_token(data)
        _LOGGER.debug("Token refreshed, expires in %ds", self.expires_in)

    # ------------------------------------------------------------------
    # Internal steps — each receives the dedicated auth_session
    # ------------------------------------------------------------------

    async def _step1_authorize(self, s: aiohttp.ClientSession) -> dict:
        """GET B2C authorize page, parse var SETTINGS (transId + csrf)."""
        params = {
            "response_type": "code",
            "code_challenge_method": "S256",
            "scope": B2C_SCOPE,
            "code_challenge": self._code_challenge,
            "response_mode": "query",
            "redirect_uri": B2C_REDIRECT_URI,
            "client_id": B2C_CLIENT_ID,
            "state": self._state,
        }
        try:
            async with s.get(
                B2C_AUTHORIZE_URL,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
                allow_redirects=True,
            ) as resp:
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise ImowAuthError(f"B2C authorize network error: {err}") from err

        _LOGGER.debug("step1 status=%s", resp.status)
        m = re.search(r"var SETTINGS\s*=\s*(\{[\s\S]*?\});\s*\n", text)
        if not m:
            _LOGGER.debug("step1 body sample: %s", text[:500])
            raise ImowAuthError("B2C authorize: var SETTINGS not found in response")

        return json.loads(m.group(1))

    async def _step2_self_asserted(
        self, s: aiohttp.ClientSession, settings: dict, username: str, password: str,
        cookie_header: str = "",
    ) -> str:
        """Returns updated cookie_header with any cookies set/updated by step 2."""
        """POST credentials to SelfAsserted endpoint."""
        url = (
            f"{B2C_BASE}/{B2C_POLICY_MIXED}/SelfAsserted"
            f"?tx={settings['transId']}&p={B2C_POLICY_MIXED}"
        )
        # Use quote() not quote_plus() so special chars become %XX, never +
        form_body = urlencode(
            {"request_type": "RESPONSE", "signInName": username, "password": password},
            quote_via=quote,
        )
        headers = {
            "User-Agent": USER_AGENT,
            "X-CSRF-TOKEN": settings["csrf"],
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        try:
            async with s.post(url, data=form_body, headers=headers) as resp:
                raw = await resp.text()
                # Capture any cookies B2C updates in this response
                step2_cookies = {k: v.value for k, v in resp.cookies.items()}
        except aiohttp.ClientError as err:
            raise ImowAuthError(f"B2C SelfAsserted network error: {err}") from err

        _LOGGER.debug("step2 status=%s content-type=%s body=%s new_cookies=%s",
                      resp.status, resp.content_type, raw[:300], list(step2_cookies.keys()))

        try:
            body = json.loads(raw)
        except ValueError:
            raise ImowAuthError(
                f"B2C SelfAsserted returned non-JSON (status {resp.status}). "
                f"Body sample: {raw[:200]}"
            )

        if str(body.get("status", "200")) != "200":
            raise ImowAuthError(
                f"Invalid credentials (B2C SelfAsserted rejected): {body.get('message', body)}"
            )

        # Merge updated cookies into the header string for the next step
        if step2_cookies:
            existing = dict(pair.split("=", 1) for pair in cookie_header.split("; ") if "=" in pair)
            existing.update(step2_cookies)
            cookie_header = "; ".join(f"{k}={v}" for k, v in existing.items())
            _LOGGER.debug("step2 merged cookie header has %d cookies", len(existing))
        return cookie_header

    async def _step3_confirmed(self, s: aiohttp.ClientSession, settings: dict,
                               cookie_header: str = "") -> str:
        """GET confirmed endpoint; extract auth code from imow:// redirect."""
        params = {
            "rememberMe": "true",
            "csrf_token": settings["csrf"],
            "tx": settings["transId"],
            "p": B2C_POLICY_MIXED,
        }
        url = f"{B2C_BASE}/{B2C_POLICY_MIXED}/api/CombinedSigninAndSignup/confirmed"
        headers = {"User-Agent": USER_AGENT}
        if cookie_header:
            headers["Cookie"] = cookie_header
        try:
            async with s.get(url, params=params, headers=headers, allow_redirects=False) as resp:
                location = resp.headers.get("Location", "")
                _LOGGER.debug("step3 status=%s location=%s", resp.status, location[:100] if location else "")
        except aiohttp.ClientError as err:
            raise ImowAuthError(f"B2C confirmed network error: {err}") from err

        if not location:
            raise ImowAuthError("B2C confirmed: no Location header in response")

        parsed = urlparse(location)
        qs = parse_qs(parsed.query)
        if "state" in qs and qs["state"][0] != self._state:
            raise ImowAuthError("B2C redirect state mismatch")
        if "code" in qs:
            return qs["code"][0]
        if "error" in qs:
            raise ImowAuthError(
                f"B2C error: {qs.get('error', ['?'])[0]} — {qs.get('error_description', [''])[0]}"
            )
        raise ImowAuthError(f"B2C confirmed: unexpected Location: {location[:200]}")

    async def _step4_token(self, s: aiohttp.ClientSession, code: str) -> None:
        """Exchange auth code for access + refresh tokens."""
        try:
            async with s.post(
                B2C_TOKEN_URL,
                data={
                    "code": code,
                    "code_verifier": self._code_verifier,
                    "redirect_uri": B2C_REDIRECT_URI,
                    "client_id": B2C_CLIENT_ID,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise ImowAuthError(f"Token exchange failed (HTTP {resp.status})")
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as err:
                    raise ImowAuthError("Token exchange failed: non-JSON response") from err
                _LOGGER.debug("step4 status=%s token_type=%s", resp.status, data.get("token_type"))
                if not data.get("access_token"):
                    err_code = data.get("error")
                    raise ImowAuthError(
                        f"Token exchange failed: {err_code or 'no access_token in response'}"
                    )
                self._apply_token(data)
        except aiohttp.ClientError as err:
            raise ImowAuthError(f"Token exchange network error: {err}") from err

    def _apply_token(self, data: dict) -> None:
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self.expires_in = data.get("expires_in", 3600)
        self._token_acquired_at = time.monotonic()
