"""Phyn device object."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from aiophyn.api import API
from aiophyn.errors import RequestError
from asyncio import timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN as PHYN_DOMAIN, LOGGER


from .devices.pc import PhynClassicDevice
from .devices.pp import PhynPlusDevice
from .devices.pw import PhynWaterSensorDevice

class PhynDataUpdateCoordinator(DataUpdateCoordinator):
    """Update coordinator for Phyn devices"""
    def __init__(
        self, hass: HomeAssistant, api_client: API, 
        update_interval = timedelta(seconds=60)
    ) -> None:
        """Initialize the device."""
        self.hass: HomeAssistant = hass
        self.api_client: API = api_client
        self._devices = []

        super().__init__(
            hass,
            LOGGER,
            name=f"{PHYN_DOMAIN}-coordinator",
            update_interval=update_interval,
        )
    
    def add_device(self, home_id, device_id, product_code):
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
    def devices(self) -> list:
        return self._devices

    async def _async_update_data(self):
        """Update data via library."""
        for device in self._devices:
            try:
                async with timeout(20):
                    await device.async_update_data()
            except (RequestError) as error:
                raise UpdateFailed(error) from error
    
    async def async_setup(self):
        for device in self._devices:
            await device.async_setup()
        return None
