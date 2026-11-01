"""Unit tests for PhynDataUpdateCoordinator.add_device dispatch logic."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Coordinator and devices depend on homeassistant and aiophyn — skip when absent.
pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from custom_components.phyn.devices.pc import PhynClassicDevice
from custom_components.phyn.devices.pp import PhynPlusDevice
from custom_components.phyn.devices.pw import PhynWaterSensorDevice


def _make_coordinator():
    """Build a minimal coordinator-like object to test add_device dispatch.

    We avoid constructing a real DataUpdateCoordinator (which requires a live
    HomeAssistant instance) by patching the parent __init__ and creating the
    object directly.
    """
    from custom_components.phyn.update_coordinator import PhynDataUpdateCoordinator

    hass = MagicMock()
    api_client = MagicMock()
    config_entry = MagicMock()

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
        coordinator.logger = MagicMock()
        coordinator.name = "test-coordinator"
        coordinator.update_interval = None
        coordinator._listeners = {}
        coordinator._unsub_refresh = None

    return coordinator


class TestAddDeviceDispatch:
    def test_pp1_creates_phyn_plus_device(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "PP1")
        assert len(coord._devices) == 1
        assert isinstance(coord._devices[0], PhynPlusDevice)

    def test_pp2_creates_phyn_plus_device(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "PP2")
        assert len(coord._devices) == 1
        assert isinstance(coord._devices[0], PhynPlusDevice)

    def test_pc1_creates_phyn_classic_device(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "PC1")
        assert len(coord._devices) == 1
        assert isinstance(coord._devices[0], PhynClassicDevice)

    def test_pw1_creates_phyn_water_sensor_device(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "PW1")
        assert len(coord._devices) == 1
        assert isinstance(coord._devices[0], PhynWaterSensorDevice)

    def test_unknown_product_code_adds_nothing(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "XX9")
        assert len(coord._devices) == 0

    def test_home_name_passed_to_device(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "PP1", home_name="Cabin")
        assert coord._devices[0]._phyn_home_name == "Cabin"

    def test_multiple_devices_can_be_added(self):
        coord = _make_coordinator()
        coord.add_device("home1", "dev1", "PP1")
        coord.add_device("home1", "dev2", "PW1")
        coord.add_device("home2", "dev3", "PC1")
        assert len(coord._devices) == 3
        types = [type(d).__name__ for d in coord._devices]
        assert types == ["PhynPlusDevice", "PhynWaterSensorDevice", "PhynClassicDevice"]
