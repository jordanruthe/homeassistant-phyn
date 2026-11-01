"""Unit tests for near-pure properties in devices/base.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# The phyn package __init__.py imports homeassistant — skip when absent.
pytest.importorskip("homeassistant", reason="homeassistant package required")

from custom_components.phyn.devices.base import PhynDevice


def _make_device(device_state=None, firmware_info=None, home_name="", alerts=None):
    """Build a PhynDevice with a fake coordinator and optional pre-set state."""
    coordinator = MagicMock()
    coordinator._alert_active_summary = {}
    coordinator._alert_latest_by_home = {}
    device = PhynDevice(coordinator, "home1", "device1", "PP1", home_name=home_name)
    if device_state:
        device._device_state.update(device_state)
    if firmware_info:
        device._firmware_info.update(firmware_info)
    if alerts is not None:
        device._latest_device_alerts = alerts
    return device


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------

class TestAvailable:
    def test_online(self):
        d = _make_device({"online_status": {"v": "online"}})
        assert d.available is True

    def test_offline(self):
        d = _make_device({"online_status": {"v": "offline"}})
        assert d.available is False

    def test_missing_online_status(self):
        d = _make_device()
        assert d.available is False


# ---------------------------------------------------------------------------
# firmware_has_update
# ---------------------------------------------------------------------------

class TestFirmwareHasUpdate:
    def test_returns_none_when_no_firmware_info(self):
        d = _make_device()
        assert d.firmware_has_update is None

    def test_update_available_when_latest_greater(self):
        d = _make_device(
            device_state={"fw_version": "100"},
            firmware_info={"fw_version": "200"},
        )
        assert d.firmware_has_update is True

    def test_no_update_when_versions_equal(self):
        d = _make_device(
            device_state={"fw_version": "100"},
            firmware_info={"fw_version": "100"},
        )
        assert d.firmware_has_update is False

    def test_no_update_when_device_is_newer(self):
        d = _make_device(
            device_state={"fw_version": "200"},
            firmware_info={"fw_version": "100"},
        )
        assert d.firmware_has_update is False

    def test_returns_false_when_device_fw_missing(self):
        d = _make_device(firmware_info={"fw_version": "200"})
        assert d.firmware_has_update is False


# ---------------------------------------------------------------------------
# has_ongoing_alert
# ---------------------------------------------------------------------------

class TestHasOngoingAlert:
    def test_matches_active_Y(self):
        alerts = [{"alert_type": "leak", "active": "Y"}]
        d = _make_device(alerts=alerts)
        assert d.has_ongoing_alert("leak") is True

    def test_matches_ongoing_true(self):
        alerts = [{"alert_type": "battery", "ongoing": True}]
        d = _make_device(alerts=alerts)
        assert d.has_ongoing_alert("battery") is True

    def test_uses_type_alias_when_alert_type_missing(self):
        alerts = [{"type": "freeze_warn", "active": "Y"}]
        d = _make_device(alerts=alerts)
        assert d.has_ongoing_alert("freeze_warn") is True

    def test_no_match_for_different_type(self):
        alerts = [{"alert_type": "leak", "active": "Y"}]
        d = _make_device(alerts=alerts)
        assert d.has_ongoing_alert("battery") is False

    def test_inactive_alert_not_matched(self):
        alerts = [{"alert_type": "leak", "active": "N", "ongoing": False}]
        d = _make_device(alerts=alerts)
        assert d.has_ongoing_alert("leak") is False

    def test_empty_alerts(self):
        d = _make_device(alerts=[])
        assert d.has_ongoing_alert("leak") is False


# ---------------------------------------------------------------------------
# device_name / multi-home suffix
# ---------------------------------------------------------------------------

class TestDeviceName:
    def test_no_suffix_when_single_home(self):
        d = _make_device(device_state={"product_code": "PP1"}, home_name="")
        # manufacturer = "Phyn", model = "PP1"
        assert d.device_name == "Phyn PP1"

    def test_appends_home_name_when_multi_home(self):
        d = _make_device(device_state={"product_code": "PP1"}, home_name="Cabin")
        assert d.device_name == "Phyn PP1 - Cabin"
