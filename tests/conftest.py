"""Shared fixtures."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.imow_v2.const import DOMAIN

ACCOUNT_ID = "6f2c1d3e-0000-4000-8000-123456789abc"
USERNAME = "owner@example.com"
PASSWORD = "correct-horse"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    yield


@pytest.fixture
def mock_auth() -> Generator[MagicMock]:
    """A successful STIHL login, as seen by the config flow."""
    with patch("custom_components.imow_v2.config_flow.ImowAuth", autospec=True) as cls:
        auth = cls.return_value
        auth.login = AsyncMock(return_value=None)
        auth.account_id = ACCOUNT_ID
        auth.refresh_token = "new-refresh-token"
        yield auth


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Don't really set up the integration after a flow finishes."""
    with patch("custom_components.imow_v2.async_setup_entry", return_value=True) as mock:
        yield mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """An existing entry for the account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=ACCOUNT_ID,
        data={"username": USERNAME, "password": "old-password", "refresh_token": "old-refresh-token"},
        options={"scan_interval": 10, "tracking_interval": 60},
    )
