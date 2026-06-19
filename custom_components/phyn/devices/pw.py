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
    async_add_external_statistics,
)
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.util import dt as dt_util, slugify
from asyncio import timeout

from .base import PhynDevice
from ..entities.base import (
    PhynAlertEvent,
    PhynAlertSensor,
    PhynFirwmwareUpdateEntity,
    PhynHumiditySensor,
    PhynTemperatureSensor,
)
from ..entities.pw import PhynBatterySensor
from ..const import DOMAIN, LOGGER

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
        product_code: str,
        home_name: str = "",
    ) -> None:
        """Initialize the Phyn Water Sensor device."""
        self._water_statistics: dict[str, Any] = {}
        self._last_statistics_ts: int = 0
        super().__init__(coordinator, home_id, device_id, product_code, home_name)

        self._battery_entity = PhynBatterySensor(self, "battery", "Battery")
        self._humidity_entity = PhynHumiditySensor(self, "humidity", "Humidity")
        self._temperature_entity = PhynTemperatureSensor(self, "air_temperature", "Air Temperature")

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
    def _base_device_name(self) -> str:
        """Return device name incorporating the app-assigned sensor name if available."""
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
            await self._import_history(data)
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning(
                "Failed to import historical statistics for %s: %s",
                self._phyn_device_id, err
            )

        LOGGER.debug("Phyn Water device state (%s): %s", self._phyn_device_id, self._device_state)

    async def _import_history(self, data: list[dict]) -> None:
        """Import the full timestamped batch as external long-term statistics.

        Statistics are stored under the ``phyn:`` namespace so the HA recorder
        can also compile its own statistics from the entities' live state without
        any conflict.

        Timestamp units:
          - per-reading ts  (humidity/temperature lists): SECONDS (10-digit epoch)
          - entry-level ts  (top-level battery timestamp): MILLISECONDS (13-digit epoch)
        """
        hass = self._coordinator.hass
        device_slug = slugify(self._phyn_device_id)

        metrics = [
            (
                "air_temperature",
                "Air Temperature",
                self._temperature_entity,
                [
                    (dt_util.utc_from_timestamp(r["ts"]), float(r["value"]))
                    for entry in data
                    for r in entry.get("temperature", [])
                    if r.get("ts") is not None and r.get("value") is not None
                ],
            ),
            (
                "humidity",
                "Humidity",
                self._humidity_entity,
                [
                    (dt_util.utc_from_timestamp(r["ts"]), float(r["value"]))
                    for entry in data
                    for r in entry.get("humidity", [])
                    if r.get("ts") is not None and r.get("value") is not None
                ],
            ),
            (
                "battery",
                "Battery",
                self._battery_entity,
                [
                    (dt_util.utc_from_timestamp(entry["ts"] / 1000), float(entry["battery_level"]))
                    for entry in data
                    if entry.get("ts") is not None and entry.get("battery_level") is not None
                ],
            ),
        ]

        for metric_key, metric_label, entity, points in metrics:
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

            statistic_id = f"{DOMAIN}:{device_slug}_{metric_key}"
            metadata = StatisticMetaData(
                has_mean=True,
                has_sum=False,
                mean_type=StatisticMeanType.ARITHMETIC,
                name=f"{self.device_name} {metric_label}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=entity.native_unit_of_measurement,
                unit_class=_DEVICE_CLASS_UNIT_CLASS.get(entity.device_class),
            )

            async_add_external_statistics(hass, metadata, stat_data)
            LOGGER.debug(
                "Imported %d hourly statistics buckets for %s (%s)",
                len(stat_data), statistic_id, self._phyn_device_id,
            )

    async def async_setup(self) -> None:
        """Async setup not needed"""
        pass
