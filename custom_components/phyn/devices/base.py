""" Generic Phyn Device"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable
import math
import time

from ..const import LOGGER

if TYPE_CHECKING:
    from ..update_coordinator import PhynDataUpdateCoordinator

class PhynDevice:
    """Generic Phyn Device"""
    def __init__(
        self,
        coordinator: PhynDataUpdateCoordinator,
        home_id: str,
        device_id: str,
        product_code: str
    ) -> None:
        """Initialize the Phyn device."""
        self._coordinator: PhynDataUpdateCoordinator = coordinator
        self._phyn_home_id: str = home_id
        self._phyn_device_id: str = device_id
        self._product_code: str = product_code
        self._manufacturer: str = "Phyn"
        self._device_state: dict[str, Any] = {}
        self._device_preferences: dict[str, dict[str, Any]] = {}
        self._firmware_info: dict[str, Any] = {}
        self._active_alerts: dict[str, int] = {}
        self._latest_device_alerts: list[dict] = []
        self._update_count: int = 0
        self._alert_listeners: list[Callable[[dict], None]] = []
        self._seen_alert_ids: set[str] = set()
        self._alert_seed_done: bool = False
    
    @property
    def available(self) -> bool:
        """Return True if device is available."""
        online_status = self._device_state.get("online_status", {})
        return online_status.get("v") == "online"
    
    @property
    def coordinator(self) -> PhynDataUpdateCoordinator:
        """Return update coordinator"""
        return self._coordinator

    @property
    def device_name(self) -> str:
        """Return device name."""
        return f"{self.manufacturer} {self.model}"

    @property
    def firmware_has_update(self) -> bool | None:
        """Return if the firmware has an update"""
        if "fw_version" not in self._firmware_info:
            return None
        fw_version = self._firmware_info.get("fw_version")
        device_fw = self._device_state.get("fw_version")
        if fw_version and device_fw:
            return int(fw_version) > int(device_fw)
        return False

    @property
    def firmware_latest_version(self) -> str | None:
        """Return the latest available firmware version"""
        if "fw_version" not in self._firmware_info:
            return None
        return self._firmware_info["fw_version"]

    @property
    def firmware_release_url(self) -> str | None:
        """Return the URL for the latest release notes"""
        if "release_notes" not in self._firmware_info:
            return None
        return self._firmware_info["release_notes"]

    @property
    def firmware_version(self) -> str:
        """Return the firmware version for the device."""
        return self._device_state.get("fw_version", "")

    @property
    def home_id(self) -> str:
        """Return Phyn home id."""
        return self._phyn_home_id

    @property
    def id(self) -> str:
        """Return Phyn device id."""
        return self._phyn_device_id

    @property
    def manufacturer(self) -> str:
        """Return manufacturer for device."""
        return self._manufacturer

    @property
    def model(self) -> str:
        """Return model for device."""
        return self._device_state.get("product_code", "")

    @property
    def rssi(self) -> float | None:
        """Return rssi for device."""
        return self._device_state.get("signal_strength")

    @property
    def serial_number(self) -> str:
        """Return the serial number for the device."""
        return self._device_state.get("serial_number", "")
    
    async def async_setup(self) -> None:
        """Setup the device. Override in subclasses if needed."""
        pass

    async def async_update_data(self) -> None:
        """Update device data. Must be overridden by subclasses."""
        pass

    async def _update_firmware_information(self, *_) -> None:
        self._firmware_info.update(
            (await self._coordinator.api_client.device.get_latest_firmware_info(self._phyn_device_id))[0]
        )
        LOGGER.debug("%s firmware: %s", self.device_name, self._firmware_info)

    def has_active_alert(self, alert_type: str) -> bool:
        """Return True if the given alert type is currently active."""
        return self._active_alerts.get(alert_type, 0) > 0

    def has_ongoing_alert(self, alert_type: str) -> bool:
        """Return True if an active/ongoing alert of the given type is present
        in the most recently fetched alerts for this device.

        Uses ``_latest_device_alerts`` populated by ``_update_alert_events``.
        Handles both ``alert_type`` (PW1 API shape) and ``type`` field names.
        """
        for alert in self._latest_device_alerts:
            a_type = alert.get("alert_type") or alert.get("type")
            if a_type != alert_type:
                continue
            if alert.get("active") == "Y" or alert.get("ongoing") is True:
                return True
        return False

    def add_alert_listener(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        """Register a callback invoked for each new (unseen, non-excluded) alert.

        Returns a removal function suitable for use with ``async_on_remove``.
        """
        self._alert_listeners.append(cb)
        def remove() -> None:
            try:
                self._alert_listeners.remove(cb)
            except ValueError:
                pass
        return remove

    async def _update_alerts(self, *_) -> None:
        """Read active alerts for this device from the coordinator's cached summary."""
        self._active_alerts = self._coordinator._alert_active_summary.get(self._phyn_device_id, {})
        LOGGER.debug("Active alerts for %s: %s", self._phyn_device_id, self._active_alerts)

    async def _update_alert_events(self, *_) -> None:
        """Detect new Phyn alerts and dispatch them to registered listeners.

        Uses the ``/alerts/latest`` endpoint (returning rich per-alert objects)
        rather than the active-summary, so each discrete alert occurrence is
        caught exactly once.  On the very first run the existing alert IDs are
        seeded into the seen-set to prevent a notification storm on startup.
        """
        from ..const import CONF_EXCLUDED_ALERT_TYPES
        excluded: set[str] = set(
            self._coordinator.config_entry.options.get(CONF_EXCLUDED_ALERT_TYPES, [])
        )

        alerts: list[dict] = self._coordinator._alert_latest_by_home.get(self._phyn_home_id, [])
        LOGGER.debug("Latest alerts (home %s): %s", self._phyn_home_id, alerts)

        # Filter to alerts that belong to this device.
        # The Phyn API returns a list of dicts — field names are confirmed via
        # the debug log above on first run; common candidates: "id", "device_id",
        # "type", "message", "created_at".
        device_alerts = [
            a for a in alerts
            if a.get("device_id") == self._phyn_device_id
        ]

        # Keep the latest snapshot so has_ongoing_alert() can query current state.
        self._latest_device_alerts = device_alerts

        if not self._alert_seed_done:
            # Record all current IDs so we don't replay history on restart.
            for alert in device_alerts:
                alert_id = alert.get("id")
                if alert_id is not None:
                    self._seen_alert_ids.add(alert_id)
            self._alert_seed_done = True
            LOGGER.debug(
                "Seeded %d existing alert IDs for %s",
                len(self._seen_alert_ids),
                self._phyn_device_id,
            )
            return

        for alert in device_alerts:
            alert_id = alert.get("id")
            if alert_id is None or alert_id in self._seen_alert_ids:
                continue
            self._seen_alert_ids.add(alert_id)

            alert_type = alert.get("alert_type") or alert.get("type") or ""
            if alert_type in excluded:
                LOGGER.debug("Skipping excluded alert type %r for %s", alert_type, self._phyn_device_id)
                continue

            LOGGER.debug("New alert for %s: %s", self._phyn_device_id, alert)
            for cb in list(self._alert_listeners):
                try:
                    cb(alert)
                except Exception as err:  # noqa: BLE001
                    LOGGER.error("Alert listener error for %s: %s", self._phyn_device_id, err)

    async def _update_device_state(self, *_) -> None:
        """Update the device state from the API."""
        if 'last_updated' not in self._device_state or self._device_state['last_updated'] <= (math.floor(time.time()) - 60):
            self._device_state.update(await self._coordinator.api_client.device.get_state( 
                self._phyn_device_id
            ))
            self._device_state['last_updated'] = math.floor(time.time())
