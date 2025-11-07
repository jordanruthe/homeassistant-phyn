"""Common fixtures for Phyn tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.phyn.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


@pytest.fixture(name="mock_phyn_api")
def mock_phyn_api_fixture():
    """Mock the Phyn API for config flow tests."""
    with patch("aiophyn.async_get_api", new=AsyncMock()) as mock_api:
        mock_api_instance = MagicMock()
        
        # Mock the home.get_homes method as async
        mock_api_instance.home.get_homes = AsyncMock(return_value=[
            {
                "id": "test-home-id",
                "alias_name": "Test Home",
                "devices": [
                    {
                        "device_id": "test-device-id",
                        "product_code": "PP1",
                    }
                ],
            }
        ])
        
        # Make async_get_api return the instance
        mock_api.return_value = mock_api_instance
        
        yield mock_api


@pytest.fixture(name="mock_phyn_api_setup")
def mock_phyn_api_setup_fixture():
    """Mock the Phyn API for setup tests."""
    with patch("aiophyn.async_get_api", new=AsyncMock()) as mock_api:
        mock_api_instance = MagicMock()
        
        # Mock the home.get_homes method as async
        mock_api_instance.home.get_homes = AsyncMock(return_value=[
            {
                "id": "test-home-id",
                "alias_name": "Test Home",
                "devices": [
                    {
                        "device_id": "test-device-id",
                        "product_code": "PP1",
                    }
                ],
            }
        ])
        
        # Mock MQTT
        mock_api_instance.mqtt.connect = AsyncMock()
        mock_api_instance.mqtt.disconnect_and_wait = AsyncMock()
        
        # Make async_get_api return the instance
        mock_api.return_value = mock_api_instance
        
        yield mock_api


@pytest.fixture(name="mock_config_entry")
def mock_config_entry_fixture():
    """Create a mock config entry."""
    return {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "test-password",
        "Brand": "Phyn",
    }
