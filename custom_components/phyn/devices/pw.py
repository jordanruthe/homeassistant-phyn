"""Support for Phyn Water Sensors."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiophyn.errors import RequestError

from homeassistant.components.recorder.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
    async_import_statistics,
)
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
)
from homeassistant.util import dt as dt_util
from asyncio import timeout

from .base import PhynDevice
from ..entities.base import (
    PhynAlertEvent,
    PhynEntity,
    PhynAlertSensor,
    PhynFirwmwareUpdateEntity,
    PhynHumiditySensor,
    PhynTemperatureSensor,
)
from ..const import LOGGER

_DEVICE_CLASS_UNIT_CLASS: dict[SensorDeviceClass, str | None] = {
    SensorDeviceClass.TEMPERATURE: "temperature",
    SensorDeviceClass.PRESSURE: "pressure",
    SensorDeviceClass.HUMIDITY: None,
    SensorDeviceClass.BATTERY: None,
}

if TYPE_CHECKING:
    from ..update_coordinator import PhynDataUpdateCoordinator

class PhynWaterSensorDevice(PhynDevice):
    """Phyn Water Sensor Device"""

    ALERT_EVENT_TYPES: list[str] = [
        "battery",
        "freeze_warn",
        "humidity",
        "temperature",
        "water_detected",
    ]

    def __init__(
        self,
        coordinator: PhynDataUpdateCoordinator,
        home_id: str,
        device_id: str,
        product_code: str
    ) -> None:
        """Initialize the Phyn Water Sensor device."""
        self._water_statistics: dict[str, Any] = {}
        self._last_statistics_ts: int = 0
        self._pending_history_data: list[dict] | None = None
        super().__init__(coordinator, home_id, device_id, product_code)

        # Store entity references so _import_history can find entity_ids after registration
        self._battery_entity = PhynBatterySensor(self, "battery", "Battery")
        self._humidity_entity = PhynHumiditySensor(self, "humidity", "Humidity")
        self._temperature_entity = PhynAirTemperatureSensor(self, "air_temperature", "Air Temperature")

        self.entities = [
            PhynAlertEvent(self),
            PhynAlertSensor(self, "battery_alert", "Low Battery Alert", "alert_battery"),
            PhynAlertSensor(self, "high_humidity_alert", "High Humidity Alert", "high_humidity"),
            PhynAlertSensor(self, "low_humidity_alert", "Low Humidity Alert", "low_humidity"),
            PhynAlertSensor(self, "low_temperature_alert", "Low Temperature Alert", "low_temperature"),
            PhynAlertSensor(self, "water_detected_alert", "Water Detected Alert", "water_detected"),
            self._battery_entity,
            PhynFirwmwareUpdateEntity(self),
            self._humidity_entity,
            self._temperature_entity,
        ]

    @property
    def alert_battery(self) -> bool:
        """Return True when the Phyn API reports an active low-battery alert."""
        return self.has_ongoing_alert("battery")

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
                await self._update_device_state()
                await self._update_device()
                await self._update_alerts()
                await self._update_alert_events()

                #Update every hour
                if self._update_count % 60 == 0:
                    await self._update_firmware_information()

                self._update_count += 1
        except (RequestError) as error:
            raise UpdateFailed(error) from error

    async def _update_device(self, *_) -> None:
        """Update the device state from the API."""
        # Retry any import that was skipped on a prior cycle because entity_ids weren't ready
        if self._pending_history_data is not None:
            try:
                if await self._import_history(self._pending_history_data):
                    self._pending_history_data = None
            except Exception as err:  # pylint: disable=broad-except
                LOGGER.warning(
                    "Failed to import pending historical statistics for %s: %s",
                    self._phyn_device_id, err
                )

        device_reading_ts = self._device_state.get("temperature", {}).get("ts", 0)

        if device_reading_ts and device_reading_ts <= self._last_statistics_ts:
            LOGGER.debug(
                "PW1 (%s): no new readings since ts=%d, skipping water_statistics fetch",
                self._phyn_device_id, self._last_statistics_ts,
            )
            return

        to_ts = int(datetime.timestamp(datetime.now()) * 1000)
        if self._last_statistics_ts == 0:
            from_ts = to_ts - (3600 * 72 * 1000)
        else:
            # Fetch from 1h before the last known reading to cover any boundary overlap
            from_ts = (self._last_statistics_ts - 3600) * 1000

        data = await self._coordinator.api_client.device.get_water_statistics(self._phyn_device_id, from_ts, to_ts)
        LOGGER.debug("PW1 data (%s): %s", self._phyn_device_id, data)

        item = None
        for entry in data:
            if item is None:
                item = entry
                continue
            if entry.get('ts', 0) > item.get('ts', 0):
                item = entry

        if item:
            self._water_statistics.update(item)

        newest_ts = max(
            (r["ts"] for entry in data for r in entry.get("temperature", []) if "ts" in r),
            default=0,
        )
        if newest_ts:
            self._last_statistics_ts = newest_ts

        try:
            if not await self._import_history(data):
                self._pending_history_data = data
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning(
                "Failed to import historical statistics for %s: %s",
                self._phyn_device_id, err
            )

        LOGGER.debug("Phyn Water device state (%s): %s", self._phyn_device_id, self._device_state)

    async def _import_history(self, data: list[dict]) -> bool:
        """Import the full timestamped batch into HA long-term statistics.

        Timestamp units:
          - per-reading ts  (humidity/temperature lists): SECONDS (10-digit epoch)
          - entry-level ts  (top-level battery timestamp): MILLISECONDS (13-digit epoch)

        Returns True when all metrics were imported, False if any entity_id was not yet assigned.
        """
        hass = self._coordinator.hass
        all_imported = True

        metrics = [
            (
                self._temperature_entity,
                [
                    (dt_util.utc_from_timestamp(r["ts"]), float(r["value"]))
                    for entry in data
                    for r in entry.get("temperature", [])
                    if r.get("ts") is not None and r.get("value") is not None
                ],
            ),
            (
                self._humidity_entity,
                [
                    (dt_util.utc_from_timestamp(r["ts"]), float(r["value"]))
                    for entry in data
                    for r in entry.get("humidity", [])
                    if r.get("ts") is not None and r.get("value") is not None
                ],
            ),
            (
                self._battery_entity,
                [
                    (dt_util.utc_from_timestamp(entry["ts"] / 1000), float(entry["battery_level"]))
                    for entry in data
                    if entry.get("ts") is not None and entry.get("battery_level") is not None
                ],
            ),
        ]

        for entity, points in metrics:
            if not entity.entity_id:
                LOGGER.debug(
                    "Skipping history import for %s on %s: entity_id not yet assigned",
                    type(entity).__name__, self._phyn_device_id,
                )
                all_imported = False
                continue

            if not points:
                continue

            # Bucket readings into hourly intervals and compute mean/min/max
            hourly: dict[datetime, list[float]] = defaultdict(list)
            for reading_dt, value in points:
                hour_start = reading_dt.replace(minute=0, second=0, microsecond=0)
                hourly[hour_start].append(value)

            stat_data = [
                StatisticData(
                    start=hour_start,
                    mean=sum(vals) / len(vals),
                    min=min(vals),
                    max=max(vals),
                )
                for hour_start, vals in sorted(hourly.items())
            ]

            metadata = StatisticMetaData(
                has_mean=True,
                has_sum=False,
                mean_type=StatisticMeanType.ARITHMETIC,
                name=None,
                source="recorder",
                statistic_id=entity.entity_id,
                unit_of_measurement=entity.native_unit_of_measurement,
                unit_class=_DEVICE_CLASS_UNIT_CLASS.get(entity.device_class),
            )

            async_import_statistics(hass, metadata, stat_data)
            LOGGER.debug(
                "Imported %d hourly statistics buckets for %s (%s)",
                len(stat_data), entity.entity_id, self._phyn_device_id,
            )

        return all_imported

    async def async_setup(self) -> None:
        """Async setup not needed"""
        pass

class PhynAirTemperatureSensor(PhynTemperatureSensor):
    """PW1 air temperature sensor.

    Long-term statistics are imported directly from the Phyn API via
    async_import_statistics (hourly mean/min/max).  state_class is intentionally
    omitted so the recorder never auto-compiles competing statistics from the
    live state, which would overwrite the richer imported history.

    To view historical data use a Statistics Graph card pointed at this entity
    rather than the standard more-info popup (which shows short-term live state).
    See README for a card example and for the optional recorder exclude.entities
    config that removes short-term state recording entirely.
    """

    _attr_state_class = None  # type: ignore[assignment]


class PhynBatterySensor(PhynEntity, SensorEntity):
    """Monitors the battery level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    # state_class intentionally omitted: long-term stats are imported from the Phyn API
    # via async_import_statistics (hourly mean/min/max).  If state_class were set the
    # recorder would auto-compile statistics from the live state and overwrite imported
    # history.  View historical data via a Statistics Graph card — see README.

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
