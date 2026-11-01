"""Unit tests for PhynWaterSensorDevice._import_history and _update_device.

Key behaviours under test:
  - Hourly bucketing of sensor readings with correct mean/min/max.
  - Mixed timestamp units: temperature/humidity readings use SECONDS, the
    top-level battery entry ts is in MILLISECONDS (divided by 1000 before
    converting to UTC).
  - None-filtering: readings with missing ts or value are silently skipped.
  - statistic_id format: ``phyn:{device_slug}_{metric}``.
  - Skip-guard in _update_device: when device_reading_ts <= _last_statistics_ts
    the API is not called and _import_history is not called.
  - First-run window: 72 h lookback when _last_statistics_ts == 0.
  - Subsequent-run window: (last_ts - 3600) * 1000 start.
  - newest_ts selection from temperature readings.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# These tests require homeassistant and aiophyn — skip gracefully when absent.
pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from homeassistant.util import dt as dt_util, slugify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(last_statistics_ts: int = 0, device_state: dict | None = None):
    """Build a PhynWaterSensorDevice with a fake coordinator."""
    from custom_components.phyn.devices.pw import PhynWaterSensorDevice

    hass = MagicMock()
    api_client = MagicMock()
    api_client.device.get_water_statistics = AsyncMock(return_value=[])

    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.api_client = api_client

    device = PhynWaterSensorDevice(coordinator, "home1", "device-abc", "PW1")
    device._last_statistics_ts = last_statistics_ts
    if device_state:
        device._device_state.update(device_state)

    return device


def _ts(dt: datetime) -> int:
    """Return UTC epoch seconds for a datetime."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


# A stable base hour for all tests.
_BASE_HOUR = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
_BASE_TS = int(_BASE_HOUR.timestamp())  # seconds


# ---------------------------------------------------------------------------
# _import_history — hourly bucketing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_temperature_reading_creates_one_bucket():
    """One reading → one bucket with mean==min==max==value."""
    device = _make_device()
    data = [
        {
            "ts": _BASE_TS * 1000,  # ms (battery field)
            "battery_level": 80,
            "temperature": [{"ts": _BASE_TS + 300, "value": 21.5}],
            "humidity": [],
        }
    ]

    captured_stats = {}
    captured_meta = {}

    def fake_add(hass, meta, stat_data):
        captured_stats[meta['statistic_id']] = stat_data
        captured_meta[meta['statistic_id']] = meta

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    temp_id = f"phyn:{device_slug}_air_temperature"
    assert temp_id in captured_stats

    bucket = captured_stats[temp_id]
    assert len(bucket) == 1
    assert bucket[0]['mean'] == pytest.approx(21.5)
    assert bucket[0]['min'] == pytest.approx(21.5)
    assert bucket[0]['max'] == pytest.approx(21.5)


@pytest.mark.asyncio
async def test_multiple_readings_same_hour_are_bucketed():
    """Three temperature readings in the same clock-hour collapse into one bucket."""
    device = _make_device()
    data = [
        {
            "ts": _BASE_TS * 1000,
            "battery_level": 70,
            "temperature": [
                {"ts": _BASE_TS + 0, "value": 20.0},
                {"ts": _BASE_TS + 600, "value": 22.0},
                {"ts": _BASE_TS + 1800, "value": 24.0},
            ],
            "humidity": [],
        }
    ]

    captured = {}

    def fake_add(hass, meta, stat_data):
        captured[meta['statistic_id']] = stat_data

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    bucket = captured[f"phyn:{device_slug}_air_temperature"]
    assert len(bucket) == 1
    assert bucket[0]['mean'] == pytest.approx((20.0 + 22.0 + 24.0) / 3)
    assert bucket[0]['min'] == pytest.approx(20.0)
    assert bucket[0]['max'] == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_readings_in_different_hours_create_multiple_buckets():
    """Readings spanning two different hours produce two separate stat buckets."""
    device = _make_device()
    hour2_ts = _BASE_TS + 3600  # one hour later
    data = [
        {
            "ts": _BASE_TS * 1000,
            "battery_level": 60,
            "temperature": [
                {"ts": _BASE_TS + 100, "value": 20.0},
                {"ts": hour2_ts + 100, "value": 25.0},
            ],
            "humidity": [],
        }
    ]

    captured = {}

    def fake_add(hass, meta, stat_data):
        captured[meta['statistic_id']] = stat_data

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    buckets = captured[f"phyn:{device_slug}_air_temperature"]
    assert len(buckets) == 2
    assert buckets[0]['mean'] == pytest.approx(20.0)
    assert buckets[1]['mean'] == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# _import_history — battery timestamp is milliseconds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_battery_timestamp_is_divided_by_1000():
    """Entry-level battery ts is in ms; the code divides by 1000 before converting."""
    device = _make_device()
    # A ts value that would be *wildly* wrong (year ~2554) if treated as seconds.
    battery_ts_ms = _BASE_TS * 1000  # correct: this is _BASE_HOUR in ms
    data = [
        {
            "ts": battery_ts_ms,
            "battery_level": 55,
            "temperature": [],
            "humidity": [],
        }
    ]

    captured = {}

    def fake_add(hass, meta, stat_data):
        captured[meta['statistic_id']] = stat_data

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    battery_id = f"phyn:{device_slug}_battery"
    assert battery_id in captured
    bucket = captured[battery_id]
    assert len(bucket) == 1
    # The bucket's start should be the hour of _BASE_HOUR.
    expected_hour = _BASE_HOUR.replace(minute=0, second=0, microsecond=0)
    assert bucket[0]['start'] == expected_hour


# ---------------------------------------------------------------------------
# _import_history — None filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_readings_with_none_ts_are_skipped():
    device = _make_device()
    data = [
        {
            "ts": _BASE_TS * 1000,
            "battery_level": 80,
            "temperature": [
                {"ts": None, "value": 21.5},  # should be skipped
                {"ts": _BASE_TS + 10, "value": 22.0},
            ],
            "humidity": [],
        }
    ]

    captured = {}

    def fake_add(hass, meta, stat_data):
        captured[meta['statistic_id']] = stat_data

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    bucket = captured[f"phyn:{device_slug}_air_temperature"]
    assert len(bucket) == 1
    assert bucket[0]['mean'] == pytest.approx(22.0)


@pytest.mark.asyncio
async def test_readings_with_none_value_are_skipped():
    device = _make_device()
    data = [
        {
            "ts": _BASE_TS * 1000,
            "battery_level": 80,
            "temperature": [{"ts": _BASE_TS + 10, "value": None}],
            "humidity": [],
        }
    ]

    add_calls = []

    def fake_add(hass, meta, stat_data):
        add_calls.append(meta['statistic_id'])

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    # Temperature metric had only None values, so no call for it.
    assert f"phyn:{device_slug}_air_temperature" not in add_calls


@pytest.mark.asyncio
async def test_empty_data_does_not_call_add_external_statistics():
    device = _make_device()
    add_mock = MagicMock()
    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=add_mock,
    ):
        await device._import_history([])
    add_mock.assert_not_called()


# ---------------------------------------------------------------------------
# _import_history — statistic_id format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_statistic_id_uses_phyn_domain_and_device_slug():
    device = _make_device()
    data = [
        {
            "ts": _BASE_TS * 1000,
            "battery_level": 90,
            "temperature": [{"ts": _BASE_TS, "value": 20.0}],
            "humidity": [{"ts": _BASE_TS, "value": 55.0}],
        }
    ]

    captured_ids = []

    def fake_add(hass, meta, stat_data):
        captured_ids.append(meta['statistic_id'])

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
        side_effect=fake_add,
    ):
        await device._import_history(data)

    device_slug = slugify("device-abc")
    assert f"phyn:{device_slug}_air_temperature" in captured_ids
    assert f"phyn:{device_slug}_humidity" in captured_ids
    assert f"phyn:{device_slug}_battery" in captured_ids


# ---------------------------------------------------------------------------
# _update_device — skip-guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_device_skips_when_no_new_readings():
    """If device_reading_ts <= _last_statistics_ts the API must NOT be called."""
    device = _make_device(
        last_statistics_ts=_BASE_TS,
        device_state={"temperature": {"ts": _BASE_TS}},
    )

    with patch.object(
        device._coordinator.api_client.device,
        "get_water_statistics",
        new_callable=AsyncMock,
    ) as mock_api:
        await device._update_device()

    mock_api.assert_not_called()


@pytest.mark.asyncio
async def test_update_device_calls_api_when_new_reading():
    """New ts > last_statistics_ts → API is called."""
    device = _make_device(
        last_statistics_ts=_BASE_TS - 1000,
        device_state={"temperature": {"ts": _BASE_TS}},
    )

    device._coordinator.api_client.device.get_water_statistics = AsyncMock(return_value=[])

    with patch(
        "custom_components.phyn.devices.pw.async_add_external_statistics",
    ):
        await device._update_device()

    device._coordinator.api_client.device.get_water_statistics.assert_called_once()


# ---------------------------------------------------------------------------
# _update_device — newest_ts tracking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_device_sets_newest_ts_from_temperature_readings():
    """_last_statistics_ts is updated to the max temperature reading ts."""
    device = _make_device(last_statistics_ts=0)
    newer_ts = _BASE_TS + 1800

    device._coordinator.api_client.device.get_water_statistics = AsyncMock(
        return_value=[
            {
                "ts": _BASE_TS * 1000,
                "battery_level": 80,
                "temperature": [
                    {"ts": _BASE_TS, "value": 20.0},
                    {"ts": newer_ts, "value": 22.0},
                ],
                "humidity": [],
            }
        ]
    )

    with patch("custom_components.phyn.devices.pw.async_add_external_statistics"):
        await device._update_device()

    assert device._last_statistics_ts == newer_ts


# ---------------------------------------------------------------------------
# _update_device — first-run vs subsequent window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_device_first_run_uses_72h_window():
    """On first run (_last_statistics_ts == 0) from_ts should be ~72h ago."""
    import time

    device = _make_device(last_statistics_ts=0)
    device._coordinator.api_client.device.get_water_statistics = AsyncMock(return_value=[])

    before = int(time.time() * 1000)
    with patch("custom_components.phyn.devices.pw.async_add_external_statistics"):
        await device._update_device()
    after = int(time.time() * 1000)

    call_args = device._coordinator.api_client.device.get_water_statistics.call_args
    _, from_ts, to_ts = call_args[0]

    expected_window_ms = 3600 * 72 * 1000
    actual_window_ms = to_ts - from_ts
    # Allow a 5-second slop for test execution time.
    assert abs(actual_window_ms - expected_window_ms) < 5_000


@pytest.mark.asyncio
async def test_update_device_subsequent_run_uses_overlap_window():
    """On subsequent runs from_ts = (last_ts - 3600) * 1000."""
    device = _make_device(last_statistics_ts=_BASE_TS)
    device._coordinator.api_client.device.get_water_statistics = AsyncMock(return_value=[])

    with patch("custom_components.phyn.devices.pw.async_add_external_statistics"):
        await device._update_device()

    call_args = device._coordinator.api_client.device.get_water_statistics.call_args
    _, from_ts, _ = call_args[0]

    expected_from = (_BASE_TS - 3600) * 1000
    assert from_ts == expected_from
