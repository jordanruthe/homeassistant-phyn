"""The phyn integration."""
import asyncio
import logging

from aiophyn import async_get_api
from aiophyn.errors import RequestError
from botocore.exceptions import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLIENT, DOMAIN
from .update_coordinator import PhynDataUpdateCoordinator
from .exceptions import HaAuthError, HaCannotConnect
from .services import phyn_leak_test_service_setup

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.UPDATE, Platform.VALVE]

async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > 1:
      # This means the user has downgraded from a future version
      return False

    if config_entry.version == 1:
        new = {**config_entry.data}
        if config_entry.minor_version < 2:
            if "Brand" not in new:
                new['Brand'] = "phyn"

        config_entry.version = 1
        config_entry.minor_version = 2
        hass.config_entries.async_update_entry(config_entry, data=new)

    _LOGGER.debug("Migration to version %s.%s successful", config_entry.version, config_entry.minor_version)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up flo from a config entry."""
    session = async_get_clientsession(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN] = {}
    client_id = f"homeassistant-{hass.data['core.uuid']}"
    try:
        hass.data[DOMAIN][CLIENT] = client = await async_get_api(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD],
            phyn_brand=entry.data["Brand"].lower(), session=session,
            client_id=client_id
        )
    except RequestError as error:
        raise ConfigEntryNotReady from error
    except ClientError as error:
        if error.response['Error']['Code'] == "NotAuthorizedException":
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed"
            )
        else:
            raise error

    homes = await client.home.get_homes(entry.data[CONF_USERNAME])

    _LOGGER.debug("Phyn homes: %s", homes)

    try:
        await client.mqtt.connect()

        coordinator = PhynDataUpdateCoordinator(hass, client)
        for home in homes:
            for device in home["devices"]:
                coordinator.add_device(home["id"], device["device_id"], device["product_code"])
        hass.data[DOMAIN]["coordinator"] = coordinator

        await coordinator.async_refresh()
        await coordinator.async_setup()

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await phyn_leak_test_service_setup(hass)

        return True
    except Exception:
        # Ensure MQTT is disconnected on any setup failure to avoid leaking
        # open connections across repeated failed setups.
        try:
            await client.mqtt.disconnect_and_wait()
        except Exception as err:
            _LOGGER.debug("Error disconnecting MQTT after setup failure: %s", err)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client = hass.data[DOMAIN][CLIENT]
    await client.mqtt.disconnect_and_wait()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        del hass.data[DOMAIN][CLIENT]
        del hass.data[DOMAIN]["coordinator"]
    return unload_ok