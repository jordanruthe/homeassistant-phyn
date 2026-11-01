"""Tests for async_unload_entry disconnect timeout guard (issues #56 / #60).

Verifies that async_unload_entry does not hang forever when
mqtt.disconnect_and_wait stalls — e.g. because MQTT is already down and a
buggy or old aiophyn version never fires the _on_disconnect callback.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from custom_components.phyn.const import CLIENT, DOMAIN


async def _make_hass_data(*, disconnect_hangs: bool = False, disconnect_raises: bool = False):
    """Return a minimal hass mock and a pre-populated hass.data[DOMAIN] dict."""
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    mqtt = MagicMock()
    if disconnect_hangs:
        # Simulate a disconnect_and_wait that never resolves
        async def _hang():
            await asyncio.sleep(9999)

        mqtt.disconnect_and_wait = _hang
    elif disconnect_raises:
        mqtt.disconnect_and_wait = AsyncMock(side_effect=OSError("connection reset"))
    else:
        mqtt.disconnect_and_wait = AsyncMock()

    client = MagicMock()
    client.mqtt = mqtt

    hass.data = {DOMAIN: {CLIENT: client, "coordinator": MagicMock()}}
    return hass, client


class TestUnloadDisconnectTimeout:
    @pytest.mark.asyncio
    async def test_unload_completes_when_disconnect_hangs(self):
        """async_unload_entry must complete even when disconnect_and_wait hangs."""
        from custom_components.phyn import async_unload_entry

        hass, client = await _make_hass_data(disconnect_hangs=True)
        entry = MagicMock()
        entry.entry_id = "test-entry"

        with patch("custom_components.phyn.MQTT_DISCONNECT_TIMEOUT", 0.05):
            result = await asyncio.wait_for(
                async_unload_entry(hass, entry), timeout=3.0
            )

        assert result is True
        hass.config_entries.async_unload_platforms.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_completes_when_disconnect_raises(self):
        """A disconnect error must not abort the platform unload."""
        from custom_components.phyn import async_unload_entry

        hass, client = await _make_hass_data(disconnect_raises=True)
        entry = MagicMock()
        entry.entry_id = "test-entry"

        result = await asyncio.wait_for(async_unload_entry(hass, entry), timeout=3.0)

        assert result is True
        hass.config_entries.async_unload_platforms.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_completes_when_disconnect_succeeds(self):
        """Happy path: disconnect_and_wait resolves quickly, unload proceeds."""
        from custom_components.phyn import async_unload_entry

        hass, client = await _make_hass_data(disconnect_hangs=False)
        entry = MagicMock()
        entry.entry_id = "test-entry"

        result = await asyncio.wait_for(async_unload_entry(hass, entry), timeout=3.0)

        assert result is True
        client.mqtt.disconnect_and_wait.assert_called_once()
        hass.config_entries.async_unload_platforms.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_completes_when_no_client(self):
        """If there is no client in hass.data, unload returns True immediately."""
        from custom_components.phyn import async_unload_entry

        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        entry = MagicMock()

        result = await async_unload_entry(hass, entry)
        assert result is True
