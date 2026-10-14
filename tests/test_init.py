"""Setup tests: a rejected password starts re-authentication."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.imow_v2.auth import ImowAuthError, ImowInvalidCredentials
from custom_components.imow_v2.const import DOMAIN

from .conftest import USERNAME


def _entry() -> MockConfigEntry:
    # No refresh token, so setup goes straight to a password login
    return MockConfigEntry(
        domain=DOMAIN, title=USERNAME, unique_id=USERNAME,
        data={"username": USERNAME, "password": "changed-elsewhere"},
    )


async def test_rejected_password_starts_reauth(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.imow_v2.ImowAuth.login",
        AsyncMock(side_effect=ImowInvalidCredentials("rejected")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_network_error_retries(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.imow_v2.ImowAuth.login",
        AsyncMock(side_effect=ImowAuthError("network")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
