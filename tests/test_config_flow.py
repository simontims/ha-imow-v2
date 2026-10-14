"""Config flow tests: sign-in, re-authentication, reconfigure and options."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.imow_v2.auth import ImowAuthError, ImowInvalidCredentials
from custom_components.imow_v2.const import DOMAIN

from .conftest import ACCOUNT_ID, PASSWORD, USERNAME

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


async def test_user_flow(hass: HomeAssistant, mock_auth: MagicMock) -> None:
    """A good sign-in creates the entry, keyed by the STIHL account ID."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": f"  {USERNAME} ", "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == USERNAME
    assert result["data"] == {
        "username": USERNAME,
        "password": PASSWORD,
        "refresh_token": "new-refresh-token",
    }
    assert result["result"].unique_id == ACCOUNT_ID
    mock_auth.login.assert_awaited_once_with(USERNAME, PASSWORD)


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ImowInvalidCredentials("rejected"), "invalid_auth"),
        (ImowAuthError("timeout"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_recover(
    hass: HomeAssistant, mock_auth: MagicMock, side_effect: Exception, error: str
) -> None:
    """Each failure shows the right message, keeps the email, and a retry can succeed."""
    mock_auth.login.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_auth.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_falls_back_to_email(hass: HomeAssistant, mock_auth: MagicMock) -> None:
    """Without an account ID in the token, the lower-cased email is the unique ID."""
    mock_auth.account_id = None
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "Owner@Example.com", "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "owner@example.com"


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_auth: MagicMock, config_entry: MockConfigEntry
) -> None:
    """The same STIHL account can't be added twice, even under a new email."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "new-address@example.com", "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, mock_auth: MagicMock, config_entry: MockConfigEntry) -> None:
    """Re-authentication asks only for the password and stores the new one."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["username"] == USERNAME

    mock_auth.login.side_effect = ImowInvalidCredentials("rejected")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "still-wrong"})
    assert result["errors"] == {"base": "invalid_auth"}

    mock_auth.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == PASSWORD
    assert config_entry.data["refresh_token"] == "new-refresh-token"
    mock_auth.login.assert_awaited_with(USERNAME, PASSWORD)


async def test_reauth_wrong_account(
    hass: HomeAssistant, mock_auth: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Re-authentication can't swap the entry over to another account."""
    config_entry.add_to_hass(hass)
    mock_auth.account_id = "some-other-account"
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data["password"] == "old-password"


async def test_reconfigure(hass: HomeAssistant, mock_auth: MagicMock, config_entry: MockConfigEntry) -> None:
    """Reconfigure changes the email and password of the same account."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "new-address@example.com", "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.title == "new-address@example.com"
    assert config_entry.data["username"] == "new-address@example.com"
    assert config_entry.data["password"] == PASSWORD


async def test_reconfigure_wrong_account(
    hass: HomeAssistant, mock_auth: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Reconfigure refuses details for a different account."""
    config_entry.add_to_hass(hass)
    mock_auth.account_id = "some-other-account"
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "someone-else@example.com", "password": PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data["username"] == USERNAME


async def test_options_flow(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Options are saved as whole numbers."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15.0, "tracking_interval": 30.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {"scan_interval": 15, "tracking_interval": 30}
