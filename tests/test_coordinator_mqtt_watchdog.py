"""Unit tests for the MQTT disconnection watchdog in PhynDataUpdateCoordinator.

Covers:
- Stuck _reload_in_progress flag is cleared when the reload task completes,
  allowing the watchdog to retry after another full threshold (issue #60).
- _mqtt_down_cycles resets to 0 immediately when a reload is scheduled.
- _mqtt_down_cycles resets to 0 when MQTT reconnects.
- The diagnostic state-dump warning is emitted every down-cycle.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from custom_components.phyn.update_coordinator import (
    MQTT_DOWN_RELOAD_THRESHOLD,
    PhynDataUpdateCoordinator,
)


def _make_coordinator(*, mqtt_connected: bool = True, mqtt_topics: list | None = None):
    """Build a minimal coordinator for testing the MQTT watchdog.

    Bypasses DataUpdateCoordinator.__init__ and wires up exactly the attributes
    that _async_update_data's MQTT-watchdog branch touches.
    """
    if mqtt_topics is None:
        mqtt_topics = []

    hass = MagicMock()
    # async_create_task must return something with add_done_callback
    reload_task = MagicMock()
    reload_task.done = MagicMock(return_value=False)
    reload_task.cancelled = MagicMock(return_value=False)
    hass.async_create_task = MagicMock(return_value=reload_task)

    api_client = MagicMock()
    api_client.alert.get_active_summary = AsyncMock(return_value={})
    api_client.alert.get_latest = AsyncMock(return_value=[])
    api_client.username = "test@example.com"

    # MQTT mock with the internal attributes we now log diagnostics for.
    mqtt = MagicMock()
    mqtt.topics = list(mqtt_topics)
    mqtt.is_connected = MagicMock(return_value=mqtt_connected)
    mqtt.connect_task = None
    mqtt.reconnect_evt = MagicMock()
    mqtt.reconnect_evt.is_set = MagicMock(return_value=False)
    mqtt.disconnect_evt = None
    mqtt.pending_acks = {}
    api_client.mqtt = mqtt

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

    return coordinator


class TestMqttWatchdogBandAid:
    @pytest.mark.asyncio
    async def test_reload_scheduled_at_threshold(self):
        """A reload task is scheduled exactly when cycles reach the threshold."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1

        await coord._async_update_data()

        coord.hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_cycles_reset_to_zero_when_reload_scheduled(self):
        """Cycles must be reset to 0 right after scheduling a reload.

        Without this fix the counter stays at ≥ threshold and the guard
        ``not self._reload_in_progress`` is the only thing preventing a new
        reload each cycle — so when that flag gets stuck the counter climbs
        unbounded (the 19/10 → 23/10 pattern reported in #60).
        """
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1

        await coord._async_update_data()

        assert coord._mqtt_down_cycles == 0

    @pytest.mark.asyncio
    async def test_reload_in_progress_cleared_after_task_done(self):
        """_reload_in_progress must be False once the reload task's done-callback fires.

        This is the regression test for the core bug in #60: the flag was
        permanently stuck True after the first reload attempt, so the watchdog
        could never schedule a second attempt.
        """
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1

        # Capture the done-callback that the coordinator registers.
        captured_callbacks: list = []
        reload_task = coord.hass.async_create_task.return_value
        reload_task.add_done_callback = MagicMock(
            side_effect=lambda cb: captured_callbacks.append(cb)
        )

        await coord._async_update_data()

        # Flag is True while the task is in flight.
        assert coord._reload_in_progress is True

        # Simulate the reload task completing successfully.
        done_task = MagicMock()
        done_task.exception = MagicMock(return_value=None)
        for cb in captured_callbacks:
            cb(done_task)

        # Flag must be cleared so a future threshold can retry.
        assert coord._reload_in_progress is False

    @pytest.mark.asyncio
    async def test_reload_in_progress_cleared_after_task_failure(self):
        """_reload_in_progress is also cleared when the reload task raises."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1

        captured_callbacks: list = []
        reload_task = coord.hass.async_create_task.return_value
        reload_task.add_done_callback = MagicMock(
            side_effect=lambda cb: captured_callbacks.append(cb)
        )

        await coord._async_update_data()

        done_task = MagicMock()
        done_task.exception = MagicMock(return_value=RuntimeError("reload blew up"))
        for cb in captured_callbacks:
            cb(done_task)

        assert coord._reload_in_progress is False

    @pytest.mark.asyncio
    async def test_second_reload_scheduled_after_first_fails(self):
        """After a failed reload clears the flag, the next threshold fires again."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])

        captured_callbacks: list = []
        reload_task = coord.hass.async_create_task.return_value
        reload_task.add_done_callback = MagicMock(
            side_effect=lambda cb: captured_callbacks.append(cb)
        )

        # Burn through to first reload.
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1
        await coord._async_update_data()
        assert coord.hass.async_create_task.call_count == 1

        # Simulate the reload task failing.
        done_task = MagicMock()
        done_task.exception = MagicMock(return_value=RuntimeError("network down"))
        for cb in captured_callbacks:
            cb(done_task)

        # Burn through to the second threshold — cycles start at 0 again.
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1
        await coord._async_update_data()

        assert coord.hass.async_create_task.call_count == 2

    @pytest.mark.asyncio
    async def test_no_double_reload_while_in_progress(self):
        """A second threshold hit while _reload_in_progress is True is ignored."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord._reload_in_progress = True
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1

        await coord._async_update_data()

        coord.hass.async_create_task.assert_not_called()


class TestMqttWatchdogRecovery:
    @pytest.mark.asyncio
    async def test_connected_resets_down_cycles(self):
        """When MQTT reconnects, the down-cycle counter resets to 0."""
        coord = _make_coordinator(mqtt_connected=True, mqtt_topics=["prd/topic"])
        coord._mqtt_down_cycles = 5

        await coord._async_update_data()

        assert coord._mqtt_down_cycles == 0

    @pytest.mark.asyncio
    async def test_no_topics_resets_down_cycles(self):
        """An empty topics list (MQTT never subscribed) should not count as down."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=[])
        coord._mqtt_down_cycles = 5

        await coord._async_update_data()

        assert coord._mqtt_down_cycles == 0

    @pytest.mark.asyncio
    async def test_no_reload_when_mqtt_reconnects(self):
        """No reload is scheduled when MQTT reconnects before the threshold."""
        coord = _make_coordinator(mqtt_connected=True, mqtt_topics=["prd/topic"])
        coord._mqtt_down_cycles = MQTT_DOWN_RELOAD_THRESHOLD - 1

        await coord._async_update_data()

        coord.hass.async_create_task.assert_not_called()


class TestMqttWatchdogDiagnostics:
    @pytest.mark.asyncio
    async def test_diagnostic_warning_emitted_when_down(self):
        """A WARNING with MQTT state-machine info is logged every down-cycle."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])

        with patch(
            "custom_components.phyn.update_coordinator.LOGGER"
        ) as mock_logger:
            await coord._async_update_data()

        # At least one WARNING call should mention the down-cycle count and
        # one of the diagnostic keys.
        warning_calls = mock_logger.warning.call_args_list
        diag_logged = any(
            "task=" in str(c) or "reconnect_evt=" in str(c)
            for c in warning_calls
        )
        assert diag_logged, (
            f"Expected diagnostic snapshot in WARNING calls; got: {warning_calls}"
        )

    @pytest.mark.asyncio
    async def test_diagnostic_survives_missing_internals(self):
        """Diagnostic logging must not raise even if aiophyn attrs are absent."""
        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        # Strip private internals to simulate an older aiophyn version.
        del coord.api_client.mqtt.connect_task
        del coord.api_client.mqtt.reconnect_evt
        del coord.api_client.mqtt.disconnect_evt
        del coord.api_client.mqtt.pending_acks

        # Should not raise.
        await coord._async_update_data()


class TestMqttWatchdogSoftReconnect:
    """Tier 1: ask aiophyn to reconnect in place before a full reload (#66)."""

    @pytest.mark.asyncio
    async def test_ensure_connected_called_at_soft_threshold(self):
        from custom_components.phyn.update_coordinator import MQTT_DOWN_RECONNECT_THRESHOLD

        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord.api_client.mqtt.ensure_connected = MagicMock(return_value=False)
        coord._mqtt_down_cycles = MQTT_DOWN_RECONNECT_THRESHOLD - 1

        await coord._async_update_data()

        coord.api_client.mqtt.ensure_connected.assert_called_once()
        # Soft step must not trigger the reload.
        coord.hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_connected_called_once_not_every_cycle(self):
        from custom_components.phyn.update_coordinator import (
            MQTT_DOWN_RECONNECT_THRESHOLD,
            MQTT_DOWN_RELOAD_THRESHOLD,
        )

        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord.api_client.mqtt.ensure_connected = MagicMock(return_value=False)

        for _ in range(MQTT_DOWN_RELOAD_THRESHOLD - 1):
            await coord._async_update_data()

        assert coord.api_client.mqtt.ensure_connected.call_count == 1
        coord.hass.async_create_task.assert_not_called()
        assert MQTT_DOWN_RECONNECT_THRESHOLD < MQTT_DOWN_RELOAD_THRESHOLD

    @pytest.mark.asyncio
    async def test_reload_still_fires_if_soft_reconnect_does_not_recover(self):
        from custom_components.phyn.update_coordinator import MQTT_DOWN_RELOAD_THRESHOLD

        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord.api_client.mqtt.ensure_connected = MagicMock(return_value=False)

        for _ in range(MQTT_DOWN_RELOAD_THRESHOLD):
            await coord._async_update_data()

        coord.hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_older_aiophyn_without_ensure_connected_is_tolerated(self):
        from custom_components.phyn.update_coordinator import MQTT_DOWN_RECONNECT_THRESHOLD

        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        del coord.api_client.mqtt.ensure_connected
        coord._mqtt_down_cycles = MQTT_DOWN_RECONNECT_THRESHOLD - 1

        # Must not raise.
        await coord._async_update_data()
        coord.hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_connected_exception_is_swallowed(self):
        from custom_components.phyn.update_coordinator import MQTT_DOWN_RECONNECT_THRESHOLD

        coord = _make_coordinator(mqtt_connected=False, mqtt_topics=["prd/topic"])
        coord.api_client.mqtt.ensure_connected = MagicMock(side_effect=RuntimeError("boom"))
        coord._mqtt_down_cycles = MQTT_DOWN_RECONNECT_THRESHOLD - 1

        await coord._async_update_data()

        assert coord._mqtt_down_cycles == MQTT_DOWN_RECONNECT_THRESHOLD
