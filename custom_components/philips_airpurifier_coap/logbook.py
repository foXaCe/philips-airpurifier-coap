"""Logbook descriptions for Philips AirPurifier events."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_ICON,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_FILTER_ALERT


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the integration's logbook events."""

    @callback
    def async_describe_filter_alert(event: Event) -> dict[str, str]:
        """Render a human-readable logbook entry for the filter-alert event."""
        data = event.data
        name = data.get("device_name") or "Philips AirPurifier"
        filter_name = data.get("filter_name") or "A filter"
        percentage = data.get("percentage")

        if percentage is not None:
            message = f"{filter_name} needs attention ({percentage}%)"
        else:
            message = f"{filter_name} needs attention"

        described: dict[str, str] = {
            LOGBOOK_ENTRY_NAME: name,
            LOGBOOK_ENTRY_MESSAGE: message,
            LOGBOOK_ENTRY_ICON: "mdi:air-filter",
        }

        # Attach the entry to the originating entity when available.
        if entity_id := data.get("entity_id"):
            described[LOGBOOK_ENTRY_ENTITY_ID] = entity_id

        return described

    async_describe_event(DOMAIN, EVENT_FILTER_ALERT, async_describe_filter_alert)
