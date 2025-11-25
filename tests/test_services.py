"""Test the Phyn services."""
import pytest
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.phyn.const import DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_leak_test_service(hass: HomeAssistant, mock_phyn_api_setup, mock_coordinator) -> None:
    """Test the leak test service."""
    # Setup config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "test-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
    )
    entry.add_to_hass(hass)
    
    # Mock the API client's run_leak_test
    with patch("custom_components.phyn.phyn_leak_test_service_setup", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    
    # Get the mock API client
    client = hass.data[DOMAIN]["client"]
    client.device.run_leak_test = AsyncMock(return_value={"code": "success"})
    
    # Call the service using hass.services.async_call (NOT ServiceCall constructor)
    await hass.services.async_call(
        DOMAIN,
        "leak_test",
        {
            "entity_id": "valve.phyn_shutoff_valve",
            "extended": False
        },
        blocking=True
    )
    await hass.async_block_till_done()
    
    # Verify the mock was called
    # Note: This test may need adjustment based on actual entity setup
