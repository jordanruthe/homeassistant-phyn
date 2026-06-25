"""Phyn device object."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

MQTT_DOWN_RELOAD_THRESHOLD = 10
STATE_FETCH_FAILURE_THRESHOLD = 3  # ~3 min at 60s polls before surfacing UpdateFailed

from aiophyn.api import API
from aiophyn.errors import AuthenticationError, RequestError
from asyncio import timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed


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
        self._alert_initial_fetch_done: bool = False
        self._mqtt_down_cycles: int = 0
        self._reload_in_progress: bool = False
        self._state_fetch_failures: int = 0

        super().__init__(
            hass,
            LOGGER,
            name=f"{PHYN_DOMAIN}-coordinator",
            update_interval=update_interval,
        )
    
    def add_device(self, home_id: str, device_id: str, product_code: str, home_name: str = "") -> None:
        """Add a device to the coordinator."""
        if product_code in ["PP1","PP2"]:
            self._devices.append(
                PhynPlusDevice(self, home_id, device_id, product_code, home_name)
            )
        elif product_code in ["PC1"]:
            self._devices.append(
                PhynClassicDevice(self, home_id, device_id, product_code, home_name)
            )
        elif product_code in ["PW1"]:
            self._devices.append(
                PhynWaterSensorDevice(self, home_id, device_id, product_code, home_name)
            )

    @property
    def devices(self) -> list[PhynDevice]:
        """Return list of devices."""
        return self._devices

    async def _async_update_data(self) -> None:
        """Update data via library."""
        try:
            self._alert_active_summary = await self.api_client.alert.get_active_summary(
                self.api_client.username, "unresolved"
            )
        except AuthenticationError:
            raise
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Could not fetch alert active summary: %s", err)

        # On the first poll use a large limit to seed _seen_alert_ids so that
        # historical alerts are never replayed as "new" events on startup.
        # On subsequent polls a small limit is sufficient — any alert created
        # in the last 60 s will be at the top of the most-recent list.
        alert_limit = 50 if not self._alert_initial_fetch_done else 20

        home_ids = {device.home_id for device in self._devices}
        for home_id in home_ids:
            # Request only the union of alert types declared by devices in this
            # home.  Homes with no alert-consuming devices skip the call entirely.
            types = sorted({
                t
                for device in self._devices
                if device.home_id == home_id
                for t in device.ALERT_EVENT_TYPES
            })
            if not types:
                continue
            try:
                self._alert_latest_by_home[home_id] = await self.api_client.alert.get_latest(
                    self.api_client.username,
                    home_id,
                    alert_type=types,
                    limit=alert_limit,
                )
            except AuthenticationError:
                raise
            except Exception as err:  # noqa: BLE001
                LOGGER.warning("Could not fetch latest alerts for home %s: %s", home_id, err)

        self._alert_initial_fetch_done = True

        last_state_error: RequestError | None = None
        for device in self._devices:
            try:
                async with timeout(20):
                    await device.async_update_data()
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed(
                    translation_domain="phyn",
                    translation_key="auth_failed",
                ) from error
            except RequestError as error:
                last_state_error = error
                break

        if last_state_error is not None:
            self._state_fetch_failures += 1
            if self._state_fetch_failures >= STATE_FETCH_FAILURE_THRESHOLD:
                raise UpdateFailed(last_state_error) from last_state_error
            LOGGER.warning(
                "Transient error fetching Phyn device state (%s/%s): %s",
                self._state_fetch_failures,
                STATE_FETCH_FAILURE_THRESHOLD,
                last_state_error,
            )
            return

        self._state_fetch_failures = 0

        # As a last-resort, reload the config entry to rebuild the MQTT client from
        # scratch.
        # The threshold is intentionally high (~10 min at 60s intervals) because the
        # reconnect loop should recover on its own well before this fires.
        mqtt = self.api_client.mqtt
        if mqtt.topics and not mqtt.is_connected():
            self._mqtt_down_cycles += 1

            # Snapshot aiophyn reconnect state-machine internals for diagnostics.
            # Read defensively (getattr) since these are private aiophyn attributes.
            connect_task = getattr(mqtt, "connect_task", None)
            reconnect_evt = getattr(mqtt, "reconnect_evt", None)
            disconnect_evt = getattr(mqtt, "disconnect_evt", None)
            task_state = (
                "none" if connect_task is None
                else "done" if connect_task.done()
                else "cancelled" if connect_task.cancelled()
                else "running"
            )
            LOGGER.warning(
                "Phyn MQTT disconnected while API is reachable (%s/%s cycles) — "
                "topics=%s task=%s reconnect_evt=%s disconnect_evt=%s pending_acks=%s",
                self._mqtt_down_cycles,
                MQTT_DOWN_RELOAD_THRESHOLD,
                len(getattr(mqtt, "topics", [])),
                task_state,
                reconnect_evt.is_set() if reconnect_evt is not None else "n/a",
                disconnect_evt is not None,
                len(getattr(mqtt, "pending_acks", {})),
            )
            if (
                self._mqtt_down_cycles >= MQTT_DOWN_RELOAD_THRESHOLD
                and not self._reload_in_progress
            ):
                self._reload_in_progress = True
                # Reset the cycle counter now so that if this reload attempt fails
                # the watchdog backs off a full threshold before retrying, instead
                # of staying stuck at ≥ threshold forever.
                self._mqtt_down_cycles = 0
                LOGGER.warning(
                    "Reloading Phyn integration to recover MQTT connection"
                )
                reload_task = self.hass.async_create_task(
                    self.hass.config_entries.async_reload(
                        self.config_entry.entry_id
                    )
                )

                def _on_reload_done(task: Any) -> None:
                    """Clear the reload flag so a future threshold can retry."""
                    self._reload_in_progress = False
                    exc = None
                    try:
                        exc = task.exception()
                    except Exception:  # noqa: BLE001
                        pass
                    if exc is not None:
                        LOGGER.warning(
                            "Phyn integration reload failed: %s — will retry after %s cycles",
                            exc,
                            MQTT_DOWN_RELOAD_THRESHOLD,
                        )

                reload_task.add_done_callback(_on_reload_done)
        else:
            self._mqtt_down_cycles = 0
    
    async def async_setup(self) -> None:
        """Setup devices."""
        for device in self._devices:
            await device.async_setup()
