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
    with patch("custom_components.phyn.config_flow.async_get_api") as mock_api:
        # Create an async function that returns the mock API instance
        mock_api_instance = AsyncMock()
        
        # Mock the home object and its methods
        mock_api_instance.home = AsyncMock()
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
        
        # Make async_get_api an async function that returns the instance
        # This fixes: TypeError: object AsyncMock can't be used in 'await' expression
        async def _async_get_api(*args, **kwargs):
            return mock_api_instance
        
        mock_api.side_effect = _async_get_api
        
        yield mock_api


@pytest.fixture(name="mock_phyn_api_setup")
def mock_phyn_api_setup_fixture():
    """Mock the Phyn API for setup tests."""
    with patch("custom_components.phyn.async_get_api") as mock_api:
        mock_api_instance = AsyncMock()
        
        # Mock the home object and its methods
        mock_api_instance.home = AsyncMock()
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
        
        # Mock MQTT with proper async methods
        mock_api_instance.mqtt = AsyncMock()
        mock_api_instance.mqtt.connect = AsyncMock()
        mock_api_instance.mqtt.disconnect_and_wait = AsyncMock()
        mock_api_instance.mqtt.add_event_handler = AsyncMock()
        mock_api_instance.mqtt.subscribe = AsyncMock()
        
        # Mock device API
        mock_api_instance.device = AsyncMock()
        mock_api_instance.device.get_state = AsyncMock(return_value={
            "sov_status": {"v": "Open"},
            "online_status": {"v": "online"},
            "fw_version": "1.0.0",
            "product_code": "PP1",
            "serial_number": "TEST123",
        })
        mock_api_instance.device.get_consumption = AsyncMock(return_value={
            "water_consumption": 0.0
        })
        mock_api_instance.device.get_autoshuftoff_status = AsyncMock(return_value={
            "auto_shutoff_enable": False
        })
        mock_api_instance.device.get_device_preferences = AsyncMock(return_value=[])
        mock_api_instance.device.get_latest_firmware_info = AsyncMock(return_value=[{
            "fw_version": "1.0.0",
            "release_notes": "https://example.com/release-notes"
        }])
        mock_api_instance.device.run_leak_test = AsyncMock(return_value={"code": "success"})
        
        # Make async_get_api an async function that returns the instance
        # This fixes: TypeError: object AsyncMock can't be used in 'await' expression
        async def _async_get_api(*args, **kwargs):
            return mock_api_instance
        
        mock_api.side_effect = _async_get_api
        
        yield mock_api


@pytest.fixture(name="mock_coordinator")
def mock_coordinator_fixture():
    """Mock coordinator for setup tests."""
    with patch("custom_components.phyn.PhynDataUpdateCoordinator") as mock_coord:
        mock_instance = AsyncMock()
        mock_instance.devices = []
        mock_instance.add_device = MagicMock()
        mock_instance.async_refresh = AsyncMock()
        mock_instance.async_setup = AsyncMock()
        mock_instance.async_config_entry_first_refresh = AsyncMock()
        mock_instance.async_add_listener = MagicMock(return_value=MagicMock())
        mock_coord.return_value = mock_instance
        yield mock_coord


@pytest.fixture(name="mock_config_entry")
def mock_config_entry_fixture():
    """Create a mock config entry."""
    return {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "test-password",
        "Brand": "Phyn",
    }
