"""Diagnostics support for Philips AirPurifier."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .config_entry_data import ConfigEntryData
from .const import CONF_DEVICE_ID, DOMAIN

TO_REDACT = {
    CONF_HOST,
    CONF_DEVICE_ID,
    "DeviceId",
    "ProductId",
    "serial_number",
    "mac",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    config_entry_data: ConfigEntryData = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "device_info": {
            "model": config_entry_data.device_information.model,
            "name": config_entry_data.device_information.name,
            "host": "**REDACTED**",
            "mac": "**REDACTED**" if config_entry_data.device_information.mac else None,
        },
        "coordinator": {
            "status": async_redact_data(config_entry_data.coordinator.status or {}, TO_REDACT),
        },
    }
