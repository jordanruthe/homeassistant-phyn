"""Test the Phyn config flow."""
import pytest
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.phyn.const import DOMAIN

from botocore.exceptions import ClientError
from aiophyn.errors import RequestError


async def test_form(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Test Home"
    assert result2["data"] == {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "test-password",
        "Brand": "Phyn",
    }


async def test_form_invalid_auth(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test we handle invalid auth."""
    mock_phyn_api.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException"}}, "test"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "wrong-password",
            "Brand": "Phyn",
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test we handle cannot connect error."""
    mock_phyn_api.side_effect = RequestError("Connection error")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_already_configured(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test we handle already configured."""
    # Create an existing entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY

    # Try to configure the same username again
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )

    assert result4["type"] == FlowResultType.ABORT
    assert result4["reason"] == "already_configured"


async def test_form_other_client_error(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test we handle other client errors."""
    mock_phyn_api.side_effect = ClientError(
        {"Error": {"Code": "SomeOtherError"}}, "test"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test reauth flow."""
    # First create an entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    entry = result2["result"]

    # Start reauth flow
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == "reauth_confirm"

    # Complete reauth with new credentials
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "new-password",
        },
    )
    await hass.async_block_till_done()

    assert result4["type"] == FlowResultType.ABORT
    assert result4["reason"] == "reauth_successful"


async def test_reauth_flow_invalid_auth(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test reauth flow with invalid auth."""
    # First create an entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    entry = result2["result"]

    # Start reauth flow
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )

    # Try with invalid credentials
    mock_phyn_api.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException"}}, "test"
    )
    
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "wrong-password",
        },
    )

    assert result4["type"] == FlowResultType.FORM
    assert result4["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test reconfigure flow."""
    # First create an entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    entry = result2["result"]

    # Start reconfigure flow
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == "reconfigure"

    # Complete reconfigure with new settings
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "new-password",
            "Brand": "Kohler",
        },
    )
    await hass.async_block_till_done()

    assert result4["type"] == FlowResultType.ABORT
    assert result4["reason"] == "reconfigure_successful"


async def test_reconfigure_flow_invalid_auth(hass: HomeAssistant, mock_phyn_api) -> None:
    """Test reconfigure flow with invalid auth."""
    # First create an entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    entry = result2["result"]

    # Start reconfigure flow
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data=entry.data,
    )

    # Try with invalid credentials
    mock_phyn_api.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException"}}, "test"
    )
    
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "wrong-password",
            "Brand": "Phyn",
        },
    )

    assert result4["type"] == FlowResultType.FORM
    assert result4["errors"] == {"base": "invalid_auth"}
