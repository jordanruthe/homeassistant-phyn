"""Services for the phyn integration"""

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.target import async_extract_referenced_entity_ids, TargetSelection

from .const import CLIENT, DOMAIN, LOGGER

async def phyn_leak_test(service: ServiceCall):
    """Handle the service call."""
    
    tgt = TargetSelection(service.data)
    ref = async_extract_referenced_entity_ids(service.hass, tgt)
    entity_registry = er.async_get(service.hass)
    device_registry = dr.async_get(service.hass)
    
    entity_id = ref.referenced.pop()
    valve = entity_registry.async_get(entity_id)
    device = device_registry.async_get(valve.device_id)
    
    device_id = None
    extended_test = bool(service.data.get("extended", False))
    for x in device.identifiers:
        if x[0] == "phyn":
            device_id = x[1]
            break
    assert device_id is not None
    
    client = service.hass.data[DOMAIN][CLIENT]
    LOGGER.debug("Running leak test for device_id: %s (extended: %s)", device_id, extended_test)
    result = await client.device.run_leak_test(device_id, extended_test)
    assert 'code' in result and result['code'] == 'success'

async def phyn_leak_test_service_setup(hass: HomeAssistant):
    """Setup service for phyn leak test"""
    hass.services.async_register(
        DOMAIN,
        "leak_test",
        phyn_leak_test,
        schema=vol.Schema({
            vol.Optional("entity_id"): str,
            vol.Optional("extended"): bool
        }),
        supports_response=SupportsResponse.NONE
    )