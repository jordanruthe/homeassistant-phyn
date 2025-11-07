"""Test the Phyn init."""
from unittest.mock import AsyncMock, patch, MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.phyn.const import DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry

from botocore.exceptions import ClientError
from aiophyn.errors import RequestError


async def test_setup_entry(hass: HomeAssistant, mock_phyn_api_setup) -> None:
    """Test setting up an entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
    )
    entry.add_to_hass(hass)

    # Mock the coordinator setup
    with patch("custom_components.phyn.PhynDataUpdateCoordinator") as mock_coordinator:
        mock_coordinator_instance = MagicMock()
        mock_coordinator_instance.devices = []
        mock_coordinator_instance.add_device = MagicMock()
        mock_coordinator_instance.async_refresh = AsyncMock()
        mock_coordinator_instance.async_setup = AsyncMock()
        mock_coordinator.return_value = mock_coordinator_instance
        
        with patch("custom_components.phyn.phyn_leak_test_service_setup", new=AsyncMock()):
            assert await async_setup_component(hass, DOMAIN, {})
            await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED


async def test_unload_entry(hass: HomeAssistant, mock_phyn_api_setup) -> None:
    """Test unloading an entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
    )
    entry.add_to_hass(hass)

    # Mock the coordinator setup
    with patch("custom_components.phyn.PhynDataUpdateCoordinator") as mock_coordinator:
        mock_coordinator_instance = MagicMock()
        mock_coordinator_instance.devices = []
        mock_coordinator_instance.add_device = MagicMock()
        mock_coordinator_instance.async_refresh = AsyncMock()
        mock_coordinator_instance.async_setup = AsyncMock()
        mock_coordinator.return_value = mock_coordinator_instance
        
        with patch("custom_components.phyn.phyn_leak_test_service_setup", new=AsyncMock()):
            assert await async_setup_component(hass, DOMAIN, {})
            await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.NOT_LOADED


async def test_setup_entry_auth_failed(hass: HomeAssistant, mock_phyn_api_setup) -> None:
    """Test setup fails with authentication error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "wrong-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
    )
    entry.add_to_hass(hass)

    # Mock authentication failure
    mock_phyn_api_setup.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException"}}, "test"
    )

    assert not await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_entry_cannot_connect(hass: HomeAssistant, mock_phyn_api_setup) -> None:
    """Test setup fails with connection error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
    )
    entry.add_to_hass(hass)

    # Mock connection failure
    mock_phyn_api_setup.side_effect = RequestError("Connection error")

    assert not await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.SETUP_RETRY


async def test_migrate_entry_v1_minor1(hass: HomeAssistant) -> None:
    """Test migration from version 1.1 to 1.2."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
        },
        unique_id="test@example.com",
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    from custom_components.phyn import async_migrate_entry
    
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 1
    assert entry.minor_version == 2
    assert entry.data["Brand"] == "phyn"


async def test_migrate_entry_already_migrated(hass: HomeAssistant) -> None:
    """Test migration when already at version 1.2."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    from custom_components.phyn import async_migrate_entry
    
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 1
    assert entry.minor_version == 2
    assert entry.data["Brand"] == "Phyn"


async def test_migrate_entry_future_version(hass: HomeAssistant) -> None:
    """Test migration fails for future version."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
            "Brand": "Phyn",
        },
        unique_id="test@example.com",
        version=2,
        minor_version=0,
    )
    entry.add_to_hass(hass)

    from custom_components.phyn import async_migrate_entry
    
    assert not await async_migrate_entry(hass, entry)
