"""Unit tests for PhynPlusDevice.consumption (lifetime meter, PR #69).

The REST get_state() payload stores consumption as {"v": ..., "ts": ...} while
on_device_update stores a floored scalar. The property must accept both and
must not drop to None when a realtime message arrives without the key.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from custom_components.phyn.devices.pp import PhynPlusDevice


def _make_device(device_state=None) -> PhynPlusDevice:
    coordinator = MagicMock()
    coordinator._alert_active_summary = {}
    coordinator._alert_latest_by_home = {}
    device = PhynPlusDevice(coordinator, "home1", "device1", "PP1")
    if device_state:
        device._device_state.update(device_state)
    return device


class TestConsumptionProperty:
    def test_rest_dict_shape(self):
        d = _make_device({"consumption": {"v": 1234.5678, "ts": 1}})
        assert d.consumption == 1234.56

    def test_realtime_scalar_shape(self):
        d = _make_device({"consumption": 1234.56})
        assert d.consumption == 1234.56

    def test_missing_returns_none(self):
        d = _make_device()
        assert d.consumption is None

    def test_dict_without_v_returns_none(self):
        d = _make_device({"consumption": {"ts": 1}})
        assert d.consumption is None


class TestConsumptionSurvivesRealtimeUpdates:
    def test_realtime_message_without_consumption_keeps_value(self):
        d = _make_device({"consumption": {"v": 100.0, "ts": 1}})
        asyncio.run(d.on_device_update("device1", {"flow": {"v": 0.5}}))
        assert d.consumption == 100.0

    def test_realtime_message_with_consumption_updates_value(self):
        d = _make_device({"consumption": {"v": 100.0, "ts": 1}})
        asyncio.run(d.on_device_update("device1", {"consumption": {"v": 101.239}}))
        assert d.consumption == 101.23

    def test_other_device_message_ignored(self):
        d = _make_device({"consumption": {"v": 100.0, "ts": 1}})
        asyncio.run(d.on_device_update("other", {"consumption": {"v": 5.0}}))
        assert d.consumption == 100.0
