"""Support for Phyn Water Sensors."""
from __future__ import annotations

from datetime import datetime
from aiophyn.errors import RequestError

from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
)
from asyncio import timeout

from .base import PhynDevice
from ..entities.base import (
    PhynEntity,
    PhynAlertSensor,
    PhynFirwmwareUpdateEntity,
    PhynHumiditySensor,
    PhynTemperatureSensor,
)
from ..const import LOGGER

class PhynWaterSensorDevice(PhynDevice):
    """Phyn Water Sensor Device"""
    def __init__ (self, coordinator, home_id: str, device_id: str, product_code: str) -> None:
        self._water_statistics = {}
        super().__init__ (coordinator, home_id, device_id, product_code)

        self.entities = [
            PhynAlertSensor(self, "high_humidity_alert", "High Humidity Alert", "high_humidity"),
            PhynAlertSensor(self, "low_humidity_alert", "Low Humidity Alert", "low_humidity"),
            PhynAlertSensor(self, "low_temperature_alert", "Low Temperature Alert", "low_temperature"),
            PhynAlertSensor(self, "water_detected_alert", "Water Detected Alert", "water_detected"),
            PhynBatterySensor(self, "battery", "Battery"),
            PhynFirwmwareUpdateEntity(self),
            PhynHumiditySensor(self, "humidity","Humidity"),
            PhynTemperatureSensor(self,"air_temperature","Air Temperature"),
        ]

    @property
    def battery(self) -> int | None:
        """Return battery percentage"""
        if "battery_level" not in self._water_statistics:
            return None
        return self._water_statistics.get("battery_level")

    @property
    def device_name(self) -> str:
        """Return device name."""
        if "name" not in self._device_state:
            return f"{self.manufacturer} {self.model}"
        return f"{self.manufacturer} {self.model} - {self._device_state.get('name', '')}"

    @property
    def high_humidity(self) -> bool | None:
        """High humidity detected"""
        key = "high_humidity"
        alerts = self._water_statistics.get("alerts", {})
        if key in alerts:
            return alerts.get(key)
        return None

    @property
    def humidity(self) -> str | None:
        """Humidity percentage"""
        if "humidity" not in self._water_statistics:
            return None
        humidity_data = self._water_statistics.get("humidity", [])
        if humidity_data and len(humidity_data) > 0:
            return humidity_data[0].get("value")
        return None

    @property
    def low_humidity(self) -> bool | None:
        """Low humidity detected"""
        key = "low_humidity"
        alerts = self._water_statistics.get("alerts", {})
        if key in alerts:
            return alerts.get(key)
        return None

    @property
    def low_temperature(self) -> bool | None:
        """Low temperature detected"""
        key = "low_temperature"
        alerts = self._water_statistics.get("alerts", {})
        if key in alerts:
            return alerts.get(key)
        return None

    @property
    def temperature(self) -> str | None:
        """Current temperature"""
        if "temperature" not in self._water_statistics:
            return None
        temperature_data = self._water_statistics.get("temperature", [])
        if temperature_data and len(temperature_data) > 0:
            return temperature_data[0].get("value")
        return None

    @property
    def water_detected(self) -> bool | None:
        """Water detected"""
        key = "water"
        alerts = self._water_statistics.get("alerts", {})
        if key in alerts:
            return alerts.get(key)
        return None

    async def async_update_data(self):
        """Update data via library."""
        try:
            async with timeout(20):
                if "product_code" not in self._device_state:
                    await self._update_device_state()
                await self._update_device()

                #Update every hour
                if self._update_count % 60 == 0:
                    await self._update_firmware_information()

                self._update_count += 1
        except (RequestError) as error:
            raise UpdateFailed(error) from error

    async def _update_device(self, *_) -> None:
        """Update the device state from the API."""
        to_ts = int(datetime.timestamp(datetime.now()) * 1000)
        from_ts = to_ts - (3600 * 72 * 1000)
        data = await self._coordinator.api_client.device.get_water_statistics(self._phyn_device_id, from_ts, to_ts)
        LOGGER.debug("PW1 data (%s): %s", (self._phyn_device_id, data))

        item = None
        for entry in data:
            if item is None:
                item = entry
                continue
            if entry.get('ts', 0) > item.get('ts', 0):
                item = entry

        if item:
            self._water_statistics.update(item)

        LOGGER.debug("Phyn Water device state (%s): %s", (self._phyn_device_id, self._device_state))

    async def async_setup(self):
        """Async setup not needed"""
        return None

class PhynBatterySensor(PhynEntity, SensorEntity):
    """Monitors the battery level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    def __init__(self, device, name, readable_name):
        """Initialize the battery sensor."""
        super().__init__(name, readable_name, device)
        self._state: float = None
        self._device_property = "battery"

    @property
    def native_value(self) -> float | None:
        """Return the current battery."""
        if not hasattr(self._device, self._device_property) or self._device.battery is None:
            return None
        return round(self._device.battery, 1)
