"""Constants for the phyn integration."""
import logging
from enum import StrEnum

LOGGER = logging.getLogger(__package__)

CLIENT = "client"
DOMAIN = "phyn"

# All known alert types across all Phyn device models.
# Used as the event_types list for the HA event entity and in the
# options-flow multi-select for suppressing specific alert types.
ALL_ALERT_TYPES: dict[str, str] = {
    "battery": "Battery",
    "freeze_warn": "Freeze Warning",
    "high_humidity": "High Humidity",
    "high_pressure": "High Pressure",
    "leak": "Leak",
    "low_humidity": "Low Humidity",
    "low_temperature": "Low Temperature",
    "offline_leak": "Offline Leak Shutoff",
    "periodic_leak": "Recurring Flow",
    "pinhole_leak": "Pinhole Leak",
    "temperature": "Temperature",
    "water_detected": "Water Detected",
}

CONF_EXCLUDED_ALERT_TYPES = "excluded_alert_types"
CONF_HOME_ID = "home_id"
CONF_DEVICE_IDS = "device_ids"
