"""Support for Phyn Classic Water Monitor sensors."""
from __future__ import annotations
from typing import Any

from aiophyn.errors import RequestError
from asyncio import timeout

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature
)
from homeassistant.const import (
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfVolume,
)

from homeassistant.helpers.update_coordinator import UpdateFailed
import homeassistant.util.dt as dt_util

from ..const import LOGGER
from ..entities.base import (
    PhynDailyUsageSensor,
    PhynFirmwareUpdateAvailableSensor,
    PhynFirwmwareUpdateEntity,
    PhynTemperatureSensor,
    PhynPressureSensor,
)
from .base import PhynDevice

class PhynClassicDevice(PhynDevice):
    """Phyn device object."""

    def __init__(
        self, coordinator, home_id: str, device_id: str, product_code: str
    ) -> None:
        """Initialize the device."""
        super().__init__ (coordinator, home_id, device_id, product_code)
        self._device_state: dict[str, Any] = {
            "cold_line_num": None,
            "hot_line_num": None,
        }
        self._away_mode: dict[str, Any] = {}
        self._water_usage: dict[str, Any] = {}
        self._last_known_valve_state: bool = True

        self.entities = [
            PhynDailyUsageSensor(self),
            PhynFirmwareUpdateAvailableSensor(self),
            PhynFirwmwareUpdateEntity(self),
            PhynTemperatureSensor(self, "temperature1", "Average hot water temperature", "temperature1"),
            PhynTemperatureSensor(self, "temperature2", "Average cold water temperature", "temperature2"),
            PhynPressureSensor(self, "pressure1", "Average hot water pressure", "current_psi1"),
            PhynPressureSensor(self, "pressure2", "Average cold water pressure", "current_psi2"),
        ]

    async def async_update_data(self):
        """Update data via library."""
        try:
            async with timeout(20):
                await self._update_device_state()
                await self._update_consumption_data()

                #Update every hour
                if self._update_count % 60 == 0:
                    await self._update_firmware_information()

                self._update_count += 1
        except (RequestError) as error:
            raise UpdateFailed(error) from error

    @property
    def cold_line_num(self) -> int | None:
        """Return cold line number"""
        return self._device_state['cold_line_num']

    @property
    def consumption_today(self) -> float:
        """Return the current consumption for today in gallons."""
        return self._water_usage["water_consumption"]

    @property
    def current_flow_rate(self) -> float:
        """Return current flow rate in gpm."""
        if "v" not in self._device_state["flow"]:
            return None
        return round(self._device_state["flow"]["v"], 3)

    @property
    def current_psi1(self) -> float:
        """Return the current pressure in psi."""
        if "v" in self._device_state["pressure1"]:
            return round(self._device_state["pressure1"]["v"], 2)
        return round(self._device_state["pressure1"]["mean"], 2)

    @property
    def current_psi2(self) -> float:
        """Return the current pressure in psi."""
        if "v" in self._device_state["pressure2"]:
            return round(self._device_state["pressure2"]["v"], 2)
        return round(self._device_state["pressure2"]["mean"], 2)

    @property
    def hot_line_num(self) -> int | None:
        """Return hot line number"""
        return self._device_state['hot_line_num']

    @property
    def leak_test_running(self) -> bool:
        """Check if a leak test is running"""
        return self._device_state["sov_status"]["v"] == "LeakExp"

    @property
    def temperature1(self) -> float:
        """Return the current temperature in degrees F."""
        if "v" in self._device_state["temperature1"]:
            return round(self._device_state["temperature1"]["v"], 2)
        return round(self._device_state["temperature1"]["mean"], 2)

    @property
    def temperature2(self) -> float:
        """Return the current temperature in degrees F."""
        if "v" in self._device_state["temperature2"]:
            return round(self._device_state["temperature2"]["v"], 2)
        return round(self._device_state["temperature2"]["mean"], 2)

    async def _update_consumption_data(self, *_) -> None:
        """Update water consumption data from the API."""
        today = dt_util.now().date()
        duration = today.strftime("%Y/%m/%d")
        self._water_usage = await self._coordinator.api_client.device.get_consumption(
            self._phyn_device_id, duration
        )
        LOGGER.debug("Updated Phyn consumption data: %s", self._water_usage)

    async def async_setup(self):
        """Async setup not needed"""
        return None
