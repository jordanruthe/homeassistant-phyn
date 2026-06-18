"""The phyn integration."""
import asyncio
import logging

from aiophyn import async_get_api
from aiophyn.errors import AuthenticationError, RequestError
from botocore.exceptions import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLIENT, DOMAIN, CONF_HOME_ID, CONF_DEVICE_IDS
from .update_coordinator import PhynDataUpdateCoordinator
from .exceptions import HaAuthError, HaCannotConnect
from .services import phyn_leak_test_service_setup

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR, Platform.SWITCH, Platform.UPDATE, Platform.VALVE]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to the current schema version."""
    _LOGGER.debug("Migrating from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > 1:
        # Downgraded from a future version.
        return False

    if config_entry.version == 1:
        new_data = {**config_entry.data}

        if config_entry.minor_version < 3:
            # Remove the now-obsolete Brand field.
            new_data.pop("Brand", None)

        if config_entry.minor_version < 4:
            # Migrate to account-scoped entry (one entry per account, no CONF_HOME_ID).
            username = new_data.get(CONF_USERNAME, "")
            all_entries = [
                e for e in hass.config_entries.async_entries(DOMAIN)
                if e.data.get(CONF_USERNAME) == username
            ]
            primary = min(all_entries, key=lambda e: e.entry_id) if all_entries else config_entry
            is_primary = primary.entry_id == config_entry.entry_id

            if is_primary:
                all_device_ids: list[str] = []
                seen: set[str] = set()
                for sibling in all_entries:
                    for did in sibling.data.get(CONF_DEVICE_IDS, []):
                        if did not in seen:
                            seen.add(did)
                            all_device_ids.append(did)

                new_data.pop(CONF_HOME_ID, None)
                new_data[CONF_DEVICE_IDS] = all_device_ids

                hass.config_entries.async_update_entry(
                    config_entry,
                    title=username,
                    data=new_data,
                    unique_id=username,
                    version=1,
                    minor_version=4,
                )
            else:
                new_data.pop(CONF_HOME_ID, None)
                hass.config_entries.async_update_entry(
                    config_entry,
                    data=new_data,
                    version=1,
                    minor_version=4,
                )

            _LOGGER.debug(
                "Migration to version 1.4 complete for entry %s (is_primary=%s)",
                config_entry.entry_id,
                is_primary,
            )
            return True

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=1, minor_version=4
        )

    _LOGGER.debug("Migration to version %s.%s successful", config_entry.version, config_entry.minor_version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Phyn from a config entry."""

    username = entry.data.get(CONF_USERNAME, "")
    same_account = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_USERNAME) == username
    ]
    primary = min(same_account, key=lambda e: e.entry_id) if same_account else entry
    if entry.entry_id != primary.entry_id:
        _LOGGER.debug(
            "Removing redundant Phyn entry %s; primary is %s",
            entry.entry_id, primary.entry_id,
        )
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return True

    session = async_get_clientsession(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN] = {}
    client_id = f"homeassistant-{hass.data['core.uuid']}-{entry.entry_id}"
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

    device_ids: list[str] = entry.data.get(CONF_DEVICE_IDS, [])

    if not device_ids:
        # Primary entry has no selected devices.
        _LOGGER.debug("Entry %s has no devices; skipping setup", entry.entry_id)
        return True

    all_account_devices: dict[str, dict] = {}
    for home in homes:
        for device in home.get("devices", []):
            all_account_devices[device["device_id"]] = {
                "home_id": home["id"],
                "home_name": home.get("name", home["id"]),
                "product_code": device["product_code"],
            }

    selected_home_ids = {
        all_account_devices[d]["home_id"]
        for d in device_ids
        if d in all_account_devices
    }
    multi_home = len(selected_home_ids) > 1

    device_registry = dr.async_get(hass)
    for dev_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        phyn_ids = {identifier[1] for identifier in dev_entry.identifiers if identifier[0] == DOMAIN}
        if phyn_ids and not phyn_ids.intersection(device_ids):
            device_registry.async_remove_device(dev_entry.id)
            _LOGGER.debug("Removed stale device %s", phyn_ids)

    try:
        await client.mqtt.connect()

        coordinator = PhynDataUpdateCoordinator(hass, client, entry)
        for device_id in device_ids:
            if device_id in all_account_devices:
                info = all_account_devices[device_id]
                home_name = info["home_name"] if multi_home else ""
                coordinator.add_device(info["home_id"], device_id, info["product_code"], home_name)
            else:
                _LOGGER.warning(
                    "Selected device %s not found in account; skipping", device_id
                )
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
    if CLIENT not in hass.data.get(DOMAIN, {}):
        return True
    client = hass.data[DOMAIN][CLIENT]
    await client.mqtt.disconnect_and_wait()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        del hass.data[DOMAIN][CLIENT]
        del hass.data[DOMAIN]["coordinator"]
    return unload_ok
