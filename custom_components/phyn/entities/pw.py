"""PW-specific entity classes for Phyn Water Sensors."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE

from .base import PhynEntity, PhynTemperatureSensor

if TYPE_CHECKING:
    from ..devices.pw import PhynWaterSensorDevice


class PhynBatterySensor(PhynEntity, SensorEntity):
    """Monitors the battery level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    _device: PhynWaterSensorDevice

    def __init__(self, device: PhynWaterSensorDevice, name: str, readable_name: str) -> None:
        """Initialize the battery sensor."""
        super().__init__(name, readable_name, device)
        self._state: float | None = None
        self._device_property: str = "battery"

    @property
    def native_value(self) -> float | None:
        """Return the current battery."""
        if not hasattr(self._device, self._device_property) or self._device.battery is None:
            return None
        return round(self._device.battery, 1)
