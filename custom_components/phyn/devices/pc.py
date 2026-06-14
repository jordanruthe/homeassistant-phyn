"""Support for Phyn Classic Water Monitor sensors."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

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
    PhynAlertEvent,
    PhynAlertSensor,
    PhynDailyUsageSensor,
    PhynFirmwareUpdateAvailableSensor,
    PhynFirwmwareUpdateEntity,
    PhynTemperatureSensor,
    PhynPressureSensor,
)
from .base import PhynDevice

if TYPE_CHECKING:
    from ..update_coordinator import PhynDataUpdateCoordinator

class PhynClassicDevice(PhynDevice):
    """Phyn device object."""

    ALERT_EVENT_TYPES: list[str] = [
        "battery",
        "freeze_warn",
        "high_pressure",
        "leak",
        "offline_leak",
        "periodic_leak",
        "pinhole_leak",
        "temperature",
    ]

    def __init__(
        self,
        coordinator: PhynDataUpdateCoordinator,
        home_id: str,
        device_id: str,
        product_code: str
    ) -> None:
        """Initialize the device."""
        super().__init__(coordinator, home_id, device_id, product_code)
        self._device_state: dict[str, Any] = {
            "cold_line_num": None,
            "hot_line_num": None,
        }
        self._away_mode: dict[str, Any] = {}
        self._water_usage: dict[str, Any] = {}
        self._last_known_valve_state: bool = True

        self.entities = [
            PhynAlertEvent(self),
            PhynAlertSensor(self, "alert_battery", "Battery Alert", "alert_battery"),
            PhynAlertSensor(self, "alert_freeze_warn", "Freeze Warning Alert", "alert_freeze_warn"),
            PhynAlertSensor(self, "alert_high_pressure", "High Pressure Alert", "alert_high_pressure"),
            PhynAlertSensor(self, "alert_leak", "Leak Alert", "alert_leak"),
            PhynAlertSensor(self, "alert_offline_leak", "Offline Leak Shutoff Alert", "alert_offline_leak"),
            PhynAlertSensor(self, "alert_periodic_leak", "Recurring Flow Alert", "alert_periodic_leak"),
            PhynAlertSensor(self, "alert_pinhole_leak", "Pinhole Leak Alert", "alert_pinhole_leak"),
            PhynAlertSensor(self, "alert_temperature", "Temperature Alert", "alert_temperature"),
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
                await self._update_alerts()
                await self._update_alert_events()
                await self._update_consumption_data()

                #Update every hour
                if self._update_count % 60 == 0:
                    await self._update_firmware_information()

                self._update_count += 1
        except (RequestError) as error:
            raise UpdateFailed(error) from error

    @property
    def alert_battery(self) -> bool:
        return self.has_active_alert("battery")

    @property
    def alert_freeze_warn(self) -> bool:
        return self.has_active_alert("freeze_warn")

    @property
    def alert_high_pressure(self) -> bool:
        return self.has_active_alert("high_pressure")

    @property
    def alert_leak(self) -> bool:
        return self.has_active_alert("leak")

    @property
    def alert_offline_leak(self) -> bool:
        return self.has_active_alert("offline_leak")

    @property
    def alert_periodic_leak(self) -> bool:
        return self.has_active_alert("periodic_leak")

    @property
    def alert_pinhole_leak(self) -> bool:
        return self.has_active_alert("pinhole_leak")

    @property
    def alert_temperature(self) -> bool:
        return self.has_active_alert("temperature")

    @property
    def cold_line_num(self) -> int | None:
        """Return cold line number"""
        return self._device_state.get('cold_line_num')

    @property
    def consumption_today(self) -> float | None:
        """Return the current consumption for today in gallons."""
        return self._water_usage.get("water_consumption")

    @property
    def current_flow_rate(self) -> float | None:
        """Return current flow rate in gpm."""
        flow = self._device_state.get("flow", {})
        if "v" not in flow:
            return None
        return round(flow["v"], 3)

    @property
    def current_psi1(self) -> float:
        """Return the current pressure in psi."""
        pressure1 = self._device_state.get("pressure1", {})
        if "v" in pressure1:
            return round(pressure1["v"], 2)
        return round(pressure1.get("mean", 0), 2)

    @property
    def current_psi2(self) -> float:
        """Return the current pressure in psi."""
        pressure2 = self._device_state.get("pressure2", {})
        if "v" in pressure2:
            return round(pressure2["v"], 2)
        return round(pressure2.get("mean", 0), 2)

    @property
    def hot_line_num(self) -> int | None:
        """Return hot line number"""
        return self._device_state.get('hot_line_num')

    @property
    def leak_test_running(self) -> bool:
        """Check if a leak test is running"""
        sov_status = self._device_state.get("sov_status", {})
        return sov_status.get("v") == "LeakExp"

    @property
    def temperature1(self) -> float:
        """Return the current temperature in degrees F."""
        temp1 = self._device_state.get("temperature1", {})
        if "v" in temp1:
            return round(temp1["v"], 2)
        return round(temp1.get("mean", 0), 2)

    @property
    def temperature2(self) -> float:
        """Return the current temperature in degrees F."""
        temp2 = self._device_state.get("temperature2", {})
        if "v" in temp2:
            return round(temp2["v"], 2)
        return round(temp2.get("mean", 0), 2)

    async def _update_consumption_data(self, *_) -> None:
        """Update water consumption data from the API."""
        today = dt_util.now().date()
        duration = today.strftime("%Y/%m/%d")
        self._water_usage = await self._coordinator.api_client.device.get_consumption(
            self._phyn_device_id, duration
        )
        LOGGER.debug("Updated Phyn consumption data: %s", self._water_usage)

    async def async_setup(self) -> None:
        """Async setup not needed"""
        pass
