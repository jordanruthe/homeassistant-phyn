"""Update platform for the Phyn integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.update import UpdateEntity

from .const import DOMAIN as PHYN_DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Phyn switches from config entry."""
    coordinator = hass.data[PHYN_DOMAIN]["coordinator"]
    entities = []
    for device in coordinator.devices:
        entities.extend([
            entity
            for entity in device.entities
            if isinstance(entity, UpdateEntity)
        ])
    async_add_entities(entities)
