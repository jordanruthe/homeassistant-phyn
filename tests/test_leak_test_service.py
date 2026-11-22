"""Tests for the phyn.leak_test service.

aiophyn's run_leak_test() only requests the extended test when it receives a
real ``True`` (``"e" if extended_test is True else "s"``). The service must
therefore pass a bool, not the strings "true"/"false".
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("homeassistant", reason="homeassistant package required")
pytest.importorskip("aiophyn", reason="aiophyn package required")

from custom_components.phyn.const import CLIENT, DOMAIN
from custom_components.phyn.services import phyn_leak_test


async def _call(data: dict) -> AsyncMock:
    run_leak_test = AsyncMock(return_value={"code": "success"})
    client = MagicMock()
    client.device.run_leak_test = run_leak_test

    hass = MagicMock()
    hass.data = {DOMAIN: {CLIENT: client}}
    service = MagicMock()
    service.hass = hass
    service.data = data

    refs = MagicMock()
    refs.referenced = {"valve.test"}
    device = MagicMock()
    device.identifiers = {("phyn", "device-123")}
    ent_reg = MagicMock()
    ent_reg.async_get.return_value = MagicMock(device_id="dev")
    dev_reg = MagicMock()
    dev_reg.async_get.return_value = device

    with (
        patch("custom_components.phyn.services.async_extract_referenced_entity_ids", return_value=refs),
        patch("custom_components.phyn.services.er.async_get", return_value=ent_reg),
        patch("custom_components.phyn.services.dr.async_get", return_value=dev_reg),
    ):
        await phyn_leak_test(service)
    return run_leak_test


async def test_extended_true_passes_real_bool():
    run = await _call({"entity_id": "valve.test", "extended": True})
    run.assert_awaited_once_with("device-123", True)
    assert run.await_args.args[1] is True


async def test_extended_false_passes_real_bool():
    run = await _call({"entity_id": "valve.test", "extended": False})
    assert run.await_args.args[1] is False


async def test_extended_omitted_defaults_to_standard():
    run = await _call({"entity_id": "valve.test"})
    assert run.await_args.args[1] is False
