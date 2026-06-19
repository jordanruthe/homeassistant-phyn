"""PP-specific entity classes for Phyn Plus devices."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    ValveEntityFeature,
)
from homeassistant.const import UnitOfVolume, UnitOfVolumeFlowRate

from .base import PhynEntity, PhynSwitchEntity, WATER_ICON

if TYPE_CHECKING:
    from ..devices.pp import PhynPlusDevice

NAME_FLOW_RATE = "Current water flow rate"


class PhynAutoShutoffModeSwitch(PhynSwitchEntity):
    """Switch class for the Phyn Away Mode."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__("autoshutoff_enabled", "Autoshutoff Enabled", device)
        self._preference_name: str | None = "autoshutoff_enabled"

    @property
    def _state(self) -> bool | None:
        return self._device.autoshutoff_enabled

    @property
    def icon(self) -> str:
        """Return the icon to use for the away mode."""
        if self.is_on:
            return "mdi:bag-suitcase"
        return "mdi:home-circle"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the preference."""
        await self._device.set_autoshutoff_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the preference."""
        await self._device.set_autoshutoff_enabled(False)
        self.async_write_ha_state()


class PhynAwayModeSwitch(PhynSwitchEntity):
    """Switch class for the Phyn Away Mode."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__("away_mode", "Away Mode", device)
        self._preference_name: str | None = "leak_sensitivity_away_mode"

    @property
    def _state(self) -> bool | None:
        return self._device.away_mode

    @property
    def icon(self) -> str:
        """Return the icon to use for the away mode."""
        if self.is_on:
            return "mdi:bag-suitcase"
        return "mdi:home-circle"


class PhynFlowState(PhynEntity, SensorEntity):
    """Flow State for Water Sensor"""
    _attr_icon = WATER_ICON
    #_attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    #_attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    #_attr_device_class = SensorDeviceClass.WATER

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the daily water usage sensor."""
        super().__init__("water_flow_state", "Water Flowing", device)
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        if "flow_state" in self._device._rt_device_state:
            return self._device._rt_device_state['flow_state']['v']
        return None


class PhynLeakTestSensor(PhynEntity, BinarySensorEntity):
    """Leak Test Sensor"""
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the leak test sensor."""
        super().__init__("leak_test_running", "Leak Test Running", device)

    @property
    def is_on(self) -> bool:
        return self._device.leak_test_running


class PhynLeakTestWarning(PhynEntity, BinarySensorEntity):
    """Leak Test Sensor"""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the leak test warning sensor."""
        super().__init__("leak_test_warning", "Leak Test Warning", device)

    @property
    def is_on(self) -> bool | None:
        if self._device._latest_health_test is None:
            return None
        return self._device._latest_health_test.get('is_warn', False)


class PhynLeakTestLeakDetected(PhynEntity, BinarySensorEntity):
    """Leak Test Sensor"""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the leak test leak sensor."""
        super().__init__("leak_test_leak", "Leak Detected", device)

    @property
    def is_on(self) -> bool | None:
        if self._device._latest_health_test is None:
            return None
        return self._device._latest_health_test.get('is_leak', False)


class PhynScheduledLeakTestEnabledSwitch(PhynSwitchEntity):
    """Switch class for the Phyn Away Mode."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__("scheduled_leak_test_enabled", "Scheduled Leak Test Enabled", device)
        self._preference_name: str | None = "scheduler_enable"

    @property
    def _state(self) -> bool | None:
        return self._device.scheduled_leak_test_enabled

    @property
    def icon(self) -> str:
        """Return the icon to use for the away mode."""
        if self.is_on:
            return "mdi:bag-suitcase"
        return "mdi:home-circle"


class PhynConsumptionSensor(PhynEntity, SensorEntity):
    """Monitors the amount of water usage."""

    _attr_icon = WATER_ICON
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.WATER

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the daily water usage sensor."""
        super().__init__("consumption", "Total Water Usage", device)
        self._state: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current daily usage."""
        if self._device.consumption is None:
            return None
        return self._device.consumption


class PhynCurrentFlowRateSensor(PhynEntity, SensorEntity):
    """Monitors the current water flow rate."""

    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key = "current_flow_rate"
    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.GALLONS_PER_MINUTE

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the flow rate sensor."""
        super().__init__("current_flow_rate", NAME_FLOW_RATE, device)
        self._state: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current flow rate."""
        if self._device.current_flow_rate is None:
            return None
        rate = round(self._device.current_flow_rate, 1)
        return 0 if rate == 0 else rate


class PhynValve(PhynEntity, ValveEntity):
    """ValveEntity for the Phyn valve."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Valve."""
        super().__init__("shutoff_valve", "Shutoff valve", device)
        self._attr_supported_features = ValveEntityFeature(ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE)
        self._attr_device_class = ValveDeviceClass.WATER
        self._attr_reports_position = False
        self._last_known_state: bool = False

    async def async_open_valve(self) -> None:
        """Open the valve."""
        await self._device.coordinator.api_client.device.open_valve(self._device.id)

    def open_valve(self) -> None:
        """Open the valve."""
        raise NotImplementedError()

    async def async_close_valve(self) -> None:
        """Close the valve."""
        await self._device.coordinator.api_client.device.close_valve(self._device.id)

    def close_valve(self) -> None:
        """Close valve."""
        raise NotImplementedError()

    @property
    def _attr_is_closed(self) -> bool | None:
        """ Is the valve closed """
        if self._device.valve_open is None:
            return None
        self._last_known_state = self._device.valve_open
        return not self._device.valve_open

    @property
    def _attr_is_opening(self) -> bool:
        """ Is the valve opening """
        if self._device.valve_changing and self._device._last_known_valve_state is False:
            return True
        return False

    @property
    def _attr_is_closing(self) -> bool:
        """ Is the valve closing """
        if self._device.valve_changing and self._device._last_known_valve_state is True:
            return True
        return False
