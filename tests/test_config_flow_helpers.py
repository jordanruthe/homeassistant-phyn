"""Unit tests for pure helper functions in config_flow.py."""
import sys
from pathlib import Path

import pytest

# Ensure project root is importable without a full HA install for these helpers.
sys.path.insert(0, str(Path(__file__).parent.parent))

# config_flow imports voluptuous and homeassistant — skip gracefully when absent.
pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("voluptuous", reason="voluptuous package required")

# Import the helpers directly — they have no HA runtime dependencies.
from custom_components.phyn.config_flow import (
    _build_device_schema,
    _device_label,
    _extract_device_ids,
)


# ---------------------------------------------------------------------------
# _device_label
# ---------------------------------------------------------------------------

class TestDeviceLabel:
    def test_uses_device_name_when_present(self):
        device = {"device_id": "abc123", "device_name": "Kitchen Sensor", "product_code": "PW1"}
        assert _device_label(device) == "Kitchen Sensor (abc123)"

    def test_falls_back_to_product_code(self):
        device = {"device_id": "abc123", "product_code": "PW1"}
        assert _device_label(device) == "PW1 (abc123)"

    def test_falls_back_to_device_id_when_no_name_or_code(self):
        device = {"device_id": "abc123"}
        assert _device_label(device) == "abc123"

    def test_empty_device_name_falls_back_to_product_code(self):
        """An empty string device_name is falsy; should fall back to product_code."""
        device = {"device_id": "abc123", "device_name": "", "product_code": "PP1"}
        assert _device_label(device) == "PP1 (abc123)"


# ---------------------------------------------------------------------------
# _extract_device_ids
# ---------------------------------------------------------------------------

def _make_homes():
    return [
        {
            "id": "home1",
            "name": "Main House",
            "devices": [
                {"device_id": "d1", "product_code": "PP1"},
                {"device_id": "d2", "product_code": "PW1"},
            ],
        },
        {
            "id": "home2",
            "name": "Cabin",
            "devices": [
                {"device_id": "d3", "product_code": "PC1"},
            ],
        },
    ]


class TestExtractDeviceIds:
    def test_extracts_selected_ids_by_home_name(self):
        homes = _make_homes()
        user_input = {"Main House": ["d1"], "Cabin": ["d3"]}
        result = _extract_device_ids(user_input, homes)
        assert result == ["d1", "d3"]

    def test_returns_empty_when_nothing_selected(self):
        homes = _make_homes()
        result = _extract_device_ids({}, homes)
        assert result == []

    def test_deduplicates_ids_that_appear_in_multiple_homes(self):
        """If the same device_id somehow appears across two homes it's only included once."""
        homes = [
            {"id": "h1", "name": "A", "devices": [{"device_id": "shared"}]},
            {"id": "h2", "name": "B", "devices": [{"device_id": "shared"}]},
        ]
        user_input = {"A": ["shared"], "B": ["shared"]}
        result = _extract_device_ids(user_input, homes)
        assert result == ["shared"]

    def test_skips_homes_without_devices_key(self):
        homes = [{"id": "empty_home", "name": "Ghost"}]
        result = _extract_device_ids({"Ghost": ["dx"]}, homes)
        assert result == []

    def test_preserves_selection_order(self):
        homes = _make_homes()
        user_input = {"Cabin": ["d3"], "Main House": ["d2", "d1"]}
        result = _extract_device_ids(user_input, homes)
        # Order follows the homes list, not the user_input dict order.
        assert result == ["d2", "d1", "d3"]


# ---------------------------------------------------------------------------
# _build_device_schema
# ---------------------------------------------------------------------------

class TestBuildDeviceSchema:
    def test_schema_has_a_key_per_home(self):
        homes = _make_homes()
        schema = _build_device_schema(homes)
        keys = [str(k) for k in schema.schema.keys()]
        assert "Main House" in keys
        assert "Cabin" in keys

    def test_schema_defaults_to_all_devices_when_no_current(self):
        homes = _make_homes()
        schema = _build_device_schema(homes)
        # vol.Optional stores the default on the marker object.
        for key in schema.schema.keys():
            if str(key) == "Main House":
                assert set(key.default()) == {"d1", "d2"}
            if str(key) == "Cabin":
                assert set(key.default()) == {"d3"}

    def test_schema_pre_populates_current_devices(self):
        homes = _make_homes()
        schema = _build_device_schema(homes, current_device_ids=["d1"])
        for key in schema.schema.keys():
            if str(key) == "Main House":
                # Only d1 is currently selected; d2 should not be pre-selected.
                assert key.default() == ["d1"]
            if str(key) == "Cabin":
                # No current selection for Cabin → falls back to all.
                assert key.default() == ["d3"]

    def test_skips_homes_without_devices(self):
        homes = [{"id": "empty", "name": "Empty Home"}]
        schema = _build_device_schema(homes)
        assert len(schema.schema) == 0
