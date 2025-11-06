"""Base entity class for Phyn entities."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfVolume,
)

from ..const import DOMAIN as PHYN_DOMAIN

WATER_ICON = "mdi:water"
NAME_DAILY_USAGE = "Daily water usage"

class PhynEntity(Entity):
    """A base class for Phyn entities."""

    _attr_force_update = False
    _attr_has_entity_name = True
    _attr_should_poll = False

    #TEMPORARY: Typing disabled due to circular dependencies
    def __init__(
        self,
        entity_type: str,
        name: str,
        device, #: PhynDeviceDataUpdateCoordinator,
        **kwargs,
    ) -> None:
        """Init Phyn entity."""
        self._attr_name = name
        self._attr_unique_id = f"{device.id}_{entity_type}"
        self._device = device #: PhynDeviceDataUpdateCoordinator = device

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        return DeviceInfo(
            identifiers={(PHYN_DOMAIN, self._device.id)},
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            name=self._device.device_name.capitalize(),
            sw_version=self._device.firmware_version,
            connections={(CONNECTION_NETWORK_MAC, self._device.id)},
            serial_number=self._device.serial_number
        )

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        return self._device.available

    async def async_update(self):
        """Update Phyn entity."""
        await self._device.async_request_refresh()

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        try:
            # Prefer coordinator listener when available
            self.async_on_remove(self._device.coordinator.async_add_listener(self.async_write_ha_state))
        except AttributeError:
            # Fallback for older device structure that exposes async_add_listener directly
            self.async_on_remove(self._device.async_add_listener(self.async_write_ha_state))

class PhynAlertSensor(PhynEntity, BinarySensorEntity):
    """Alert sensor"""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, device, name, readable_name, device_property):
        """Intialize Firmware Update Sensor."""
        super().__init__(name, readable_name, device)
        self._device_property = device_property

    @property
    def is_on(self) -> bool | None:
        if self._device_property is not None and hasattr(self._device, self._device_property):
            return getattr(self._device, self._device_property)
        return None

class PhynDailyUsageSensor(PhynEntity, SensorEntity):
    """Monitors the daily water usage."""

    _attr_icon = WATER_ICON
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.WATER

    def __init__(self, device):
        """Initialize the daily water usage sensor."""
        super().__init__("daily_consumption", NAME_DAILY_USAGE, device)
        self._state: float = None

    @property
    def native_value(self) -> float | None:
        """Return the current daily usage."""
        if self._device.consumption_today is None:
            return None
        return round(self._device.consumption_today, 1)

class PhynFirmwareUpdateAvailableSensor(PhynEntity, BinarySensorEntity):
    """Firmware Update Available Sensor"""
    _attr_device_class = BinarySensorDeviceClass.UPDATE

    def __init__(self, device):
        """Intialize Firmware Update Sensor."""
        super().__init__("firmware_update_available", "Firmware Update Available", device)

    @property
    def is_on(self) -> bool:
        return self._device.firmware_has_update

class PhynFirwmwareUpdateEntity(PhynEntity, UpdateEntity):
    """Update entity for Phyn Plus"""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, device):
        super().__init__("firmware_update", "Firmware Update", device)

    @property
    def installed_version(self) -> str | None:
        return self._device.firmware_version

    @property
    def latest_version(self) -> str | None:
        return self._device.firmware_latest_version

    @property
    def release_url(self) -> str | None:
        return self._device.firmware_release_url

    async def async_install(self, **kwargs: Any) -> None:
        return None

    def release_notes(self) -> str | None:
        return "Upgrade can take up to five minutes"

class PhynSwitchEntity(PhynEntity, SwitchEntity):
    """Switch class for the Phyn Away Mode."""

    def __init__(
        self,
        entity_type: str,
        name: str,
        device,
        **kwargs,
    ) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__(entity_type, name, device)
        self._preference_name = None

    @property
    def _state(self) -> bool:
        """Switch State"""
        raise NotImplementedError()

    @property
    def is_on(self) -> bool:
        """Return True if away mode is on."""
        return self._state

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the preference."""
        await self._device.set_device_preference(self._preference_name, "true")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the preference."""
        await self._device.set_device_preference(self._preference_name, "false")
        self.async_write_ha_state()

class PhynHumiditySensor(PhynEntity, SensorEntity):
    """Monitors the humidty."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    def __init__(self, device, name, readable_name, device_property = None):
        """Initialize the temperature sensor."""
        super().__init__(name, readable_name, device)
        self._state: float = None
        self._device_property = device_property

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        if self._device_property is not None and hasattr(self._device, self._device_property):
            return getattr(self._device, self._device_property)
        if not hasattr(self._device, "humidity") or self._device.humidity is None:
            return None
        return round(self._device.humidity, 1)

class PhynPressureSensor(PhynEntity, SensorEntity):
    """Monitors the water pressure."""

    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_native_unit_of_measurement = UnitOfPressure.PSI
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    def __init__(self, device, name, readable_name, device_property = None):
        """Initialize the pressure sensor."""
        super().__init__(name, readable_name, device)
        self._state: float = None
        self._device_property = device_property

    @property
    def native_value(self) -> float | None:
        """Return the current water pressure."""
        if self._device_property is not None and hasattr(self._device, self._device_property):
            return getattr(self._device, self._device_property)
        if not hasattr(self._device, "current_psi") or self._device.current_psi is None:
            return None
        return round(self._device.current_psi, 1)

class PhynTemperatureSensor(PhynEntity, SensorEntity):
    """Monitors the temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    def __init__(self, device, name, readable_name, device_property = None):
        """Initialize the temperature sensor."""
        super().__init__(name, readable_name, device)
        self._state: float = None
        self._device_property = device_property

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        if self._device_property is not None and hasattr(self._device, self._device_property):
            return getattr(self._device, self._device_property)
        if not hasattr(self._device, "temperature") or self._device.temperature is None:
            return None
        return round(self._device.temperature, 1)

