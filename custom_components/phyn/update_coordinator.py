"""Phyn device object."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

MQTT_DOWN_RELOAD_THRESHOLD = 10

from aiophyn.api import API
from aiophyn.errors import AuthenticationError, RequestError
from asyncio import timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from aiophyn.alert import Alert as PhynAlert

from .const import DOMAIN as PHYN_DOMAIN, LOGGER


from .devices.pc import PhynClassicDevice
from .devices.pp import PhynPlusDevice
from .devices.pw import PhynWaterSensorDevice

if TYPE_CHECKING:
    from .devices.base import PhynDevice

class PhynDataUpdateCoordinator(DataUpdateCoordinator[None]):
    """Update coordinator for Phyn devices"""
    def __init__(
        self,
        hass: HomeAssistant,
        api_client: API,
        config_entry: ConfigEntry,
        update_interval: timedelta = timedelta(seconds=60),
    ) -> None:
        """Initialize the device."""
        self.hass: HomeAssistant = hass
        self.api_client: API = api_client
        self.config_entry: ConfigEntry = config_entry
        self._devices: list[PhynDevice] = []
        self._alert_active_summary: dict = {}
        self._alert_latest_by_home: dict[str, list[dict]] = {}
        self._mqtt_down_cycles: int = 0
        self._reload_in_progress: bool = False

        super().__init__(
            hass,
            LOGGER,
            name=f"{PHYN_DOMAIN}-coordinator",
            update_interval=update_interval,
        )
    
    def add_device(self, home_id: str, device_id: str, product_code: str) -> None:
        """Add a device to the coordinator."""
        if product_code in ["PP1","PP2"]:
            self._devices.append(
                PhynPlusDevice(self, home_id, device_id, product_code)
            )
        elif product_code in ["PC1"]:
            self._devices.append(
                PhynClassicDevice(self, home_id, device_id, product_code)
            )
        elif product_code in ["PW1"]:
            self._devices.append(
                PhynWaterSensorDevice(self, home_id, device_id, product_code)
            )

    @property
    def devices(self) -> list[PhynDevice]:
        """Return list of devices."""
        return self._devices

    async def _async_update_data(self) -> None:
        """Update data via library."""
        try:
            self._alert_active_summary = await self.api_client.alert.get_active_summary(
                self.api_client.username
            )
        except AuthenticationError:
            raise
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Could not fetch alert active summary: %s", err)

        home_ids = {device.home_id for device in self._devices}
        for home_id in home_ids:
            try:
                self._alert_latest_by_home[home_id] = await self.api_client.alert.get_latest(
                    self.api_client.username,
                    home_id,
                    alert_type=PhynAlert.ALERT_TYPES,
                    limit=50,
                )
            except AuthenticationError:
                raise
            except Exception as err:  # noqa: BLE001
                LOGGER.warning("Could not fetch latest alerts for home %s: %s", home_id, err)

        for device in self._devices:
            try:
                async with timeout(20):
                    await device.async_update_data()
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed(
                    translation_domain="phyn",
                    translation_key="auth_failed",
                ) from error
            except (RequestError) as error:
                raise UpdateFailed(error) from error

        # As a last-resort, reload the config entry to rebuild the MQTT client from 
        # scratch. 
        # The threshold is intentionally high (~10 min at 60s intervals) because the
        # reconnect loop should recover on its own well before this fires.
        mqtt = self.api_client.mqtt
        if mqtt.topics and not mqtt.is_connected():
            self._mqtt_down_cycles += 1
            LOGGER.warning(
                "Phyn MQTT disconnected while API is reachable (%s/%s cycles)",
                self._mqtt_down_cycles,
                MQTT_DOWN_RELOAD_THRESHOLD,
            )
            if (
                self._mqtt_down_cycles >= MQTT_DOWN_RELOAD_THRESHOLD
                and not self._reload_in_progress
            ):
                self._reload_in_progress = True
                LOGGER.warning(
                    "Reloading Phyn integration to recover MQTT connection"
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(
                        self.config_entry.entry_id
                    )
                )
        else:
            self._mqtt_down_cycles = 0
    
    async def async_setup(self) -> None:
        """Setup devices."""
        for device in self._devices:
            await device.async_setup()
