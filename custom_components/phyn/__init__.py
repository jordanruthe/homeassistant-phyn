"""The phyn integration."""
import asyncio
import logging

from aiophyn import async_get_api
from aiophyn.errors import AuthenticationError, RequestError
from botocore.exceptions import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLIENT, DOMAIN, CONF_HOME_ID, CONF_DEVICE_IDS
from .update_coordinator import PhynDataUpdateCoordinator
from .exceptions import HaAuthError, HaCannotConnect
from .services import phyn_leak_test_service_setup

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR, Platform.SWITCH, Platform.UPDATE, Platform.VALVE]

async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > 1:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 1:
        new = {**config_entry.data}
        if config_entry.minor_version < 3:
            # Remove the now-obsolete Brand field.
            new.pop("Brand", None)
            # home_id and device_ids will be resolved in async_setup_entry
            # once the API client is available.

        hass.config_entries.async_update_entry(
            config_entry, data=new, version=1, minor_version=3
        )

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
            phyn_brand="phyn", session=session,
            client_id=client_id
        )
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
        ) from error
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

    # --- Resolve home and device selection ---
    home_id = entry.data.get(CONF_HOME_ID)
    device_ids = entry.data.get(CONF_DEVICE_IDS)

    if home_id is None:
        # Legacy entry that hasn't been through the new flow yet.
        if len(homes) == 1:
            # Safe to auto-migrate: use the single home and all its devices.
            home_id = homes[0]["id"]
            device_ids = [d["device_id"] for d in homes[0].get("devices", [])]
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_HOME_ID: home_id, CONF_DEVICE_IDS: device_ids},
            )
            _LOGGER.debug("Auto-migrated single home %s with devices %s", home_id, device_ids)
        else:
            # Multiple homes — the user must pick one via reconfigure.
            ir.async_create_issue(
                hass,
                DOMAIN,
                "reconfigure_required",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="reconfigure_required",
            )
            raise ConfigEntryError(
                "Your Phyn account has multiple homes. Please reconfigure the integration to select a home."
            )

    ir.async_delete_issue(hass, DOMAIN, "reconfigure_required")

    selected_home = next((h for h in homes if h["id"] == home_id), None)
    if selected_home is None:
        _LOGGER.error("Configured home %s not found in account homes", home_id)
        raise ConfigEntryNotReady("Configured home not found")

    # Remove any devices from a previous setup that are no longer selected.
    device_registry = dr.async_get(hass)
    for dev_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        phyn_ids = {identifier[1] for identifier in dev_entry.identifiers if identifier[0] == DOMAIN}
        if phyn_ids and not phyn_ids.intersection(device_ids):
            device_registry.async_remove_device(dev_entry.id)
            _LOGGER.debug("Removed stale device %s", phyn_ids)

    try:
        await client.mqtt.connect()

        coordinator = PhynDataUpdateCoordinator(hass, client, entry)
        for device in selected_home.get("devices", []):
            if device["device_id"] in device_ids:
                coordinator.add_device(home_id, device["device_id"], device["product_code"])
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