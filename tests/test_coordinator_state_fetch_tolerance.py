"""Unit tests for transient device-state fetch failure tolerance (issue #46).

Verifies that the coordinator suppresses RequestError below the threshold,
only raising UpdateFailed once STATE_FETCH_FAILURE_THRESHOLD consecutive
failures have been seen, and resets the counter on a successful update.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from aiophyn.errors import AuthenticationError, RequestError
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.phyn.update_coordinator import (
    STATE_FETCH_FAILURE_THRESHOLD,
    PhynDataUpdateCoordinator,
)


def _make_coordinator(device_mock=None):
    """Build a minimal coordinator for testing _async_update_data.

    Bypasses DataUpdateCoordinator.__init__ and provides fakes for all the
    attributes that _async_update_data touches.
    """
    hass = MagicMock()
    hass.async_create_task = MagicMock()

    api_client = MagicMock()
    # Alert calls succeed silently by default.
    api_client.alert.get_active_summary = AsyncMock(return_value={})
    api_client.alert.get_latest = AsyncMock(return_value=[])
    api_client.username = "test@example.com"
    # MQTT looks healthy so the MQTT-reload branch is not triggered.
    api_client.mqtt.topics = []
    api_client.mqtt.is_connected = MagicMock(return_value=True)

    config_entry = MagicMock()
    config_entry.entry_id = "test-entry"

    with patch.object(
        PhynDataUpdateCoordinator.__bases__[0], "__init__", return_value=None
    ):
        coordinator = PhynDataUpdateCoordinator.__new__(PhynDataUpdateCoordinator)
        coordinator.hass = hass
        coordinator.api_client = api_client
        coordinator.config_entry = config_entry
        coordinator._devices = []
        coordinator._alert_active_summary = {}
        coordinator._alert_latest_by_home = {}
        coordinator._alert_initial_fetch_done = False
        coordinator._mqtt_down_cycles = 0
        coordinator._reload_in_progress = False
        coordinator._state_fetch_failures = 0
        coordinator.logger = MagicMock()
        coordinator.name = "test-coordinator"
        coordinator.update_interval = None
        coordinator._listeners = {}
        coordinator._unsub_refresh = None

    if device_mock is not None:
        coordinator._devices = [device_mock]

    return coordinator


def _device_that_raises(exc):
    """Return a device mock whose async_update_data raises *exc*."""
    device = MagicMock()
    device.home_id = "home1"
    device.ALERT_EVENT_TYPES = []
    device.async_update_data = AsyncMock(side_effect=exc)
    return device


def _device_that_succeeds():
    """Return a device mock whose async_update_data returns successfully."""
    device = MagicMock()
    device.home_id = "home1"
    device.ALERT_EVENT_TYPES = []
    device.async_update_data = AsyncMock(return_value=None)
    return device


class TestStateFetchFailureTolerance:
    @pytest.mark.asyncio
    async def test_first_failure_does_not_raise(self):
        """A single RequestError should log a warning but not raise."""
        coord = _make_coordinator(_device_that_raises(RequestError("blip")))
        # Should not raise
        await coord._async_update_data()
        assert coord._state_fetch_failures == 1

    @pytest.mark.asyncio
    async def test_failures_below_threshold_do_not_raise(self):
        """Failures below the threshold are suppressed (warn + continue)."""
        coord = _make_coordinator(_device_that_raises(RequestError("blip")))
        for i in range(STATE_FETCH_FAILURE_THRESHOLD - 1):
            await coord._async_update_data()  # must not raise
        assert coord._state_fetch_failures == STATE_FETCH_FAILURE_THRESHOLD - 1

    @pytest.mark.asyncio
    async def test_threshold_failure_raises_update_failed(self):
        """The Nth consecutive failure should raise UpdateFailed."""
        coord = _make_coordinator(_device_that_raises(RequestError("persistent")))
        for _ in range(STATE_FETCH_FAILURE_THRESHOLD - 1):
            await coord._async_update_data()

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        """A successful update resets the failure counter to 0."""
        coord = _make_coordinator(_device_that_raises(RequestError("blip")))
        # Accumulate some failures (below threshold)
        for _ in range(STATE_FETCH_FAILURE_THRESHOLD - 1):
            await coord._async_update_data()
        assert coord._state_fetch_failures > 0

        # Swap to a succeeding device and run once
        coord._devices = [_device_that_succeeds()]
        await coord._async_update_data()
        assert coord._state_fetch_failures == 0

    @pytest.mark.asyncio
    async def test_success_then_single_failure_does_not_raise(self):
        """After a reset, a new isolated failure should again be suppressed."""
        coord = _make_coordinator(_device_that_succeeds())
        await coord._async_update_data()  # success, counter is 0

        coord._devices = [_device_that_raises(RequestError("blip"))]
        await coord._async_update_data()  # single failure, suppressed
        assert coord._state_fetch_failures == 1

    @pytest.mark.asyncio
    async def test_auth_error_raises_immediately(self):
        """AuthenticationError must still raise ConfigEntryAuthFailed immediately."""
        coord = _make_coordinator(_device_that_raises(AuthenticationError("bad creds")))
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_auth_error_does_not_increment_state_counter(self):
        """Auth failures should not increment the state-fetch failure counter."""
        coord = _make_coordinator(_device_that_raises(AuthenticationError("bad creds")))
        try:
            await coord._async_update_data()
        except ConfigEntryAuthFailed:
            pass
        assert coord._state_fetch_failures == 0
