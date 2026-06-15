"""Tests for the logbook event descriptions."""

from types import SimpleNamespace

from custom_components.philips_airpurifier_coap import logbook
from custom_components.philips_airpurifier_coap.const import DOMAIN, EVENT_FILTER_ALERT
from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_ICON,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import HomeAssistant


def _register(hass: HomeAssistant) -> dict:
    """Run async_describe_events and capture the registered describer."""
    captured: dict = {}

    def capture(domain, event_name, describe_callback):
        captured.update(domain=domain, event=event_name, callback=describe_callback)

    logbook.async_describe_events(hass, capture)
    return captured


async def test_filter_alert_described_with_entity(hass: HomeAssistant) -> None:
    """The filter-alert event renders a message and attaches to its entity."""
    captured = _register(hass)
    assert captured["domain"] == DOMAIN
    assert captured["event"] == EVENT_FILTER_ALERT

    event = SimpleNamespace(
        data={
            "entity_id": "binary_sensor.living_room_filter",
            "device_name": "Living Room",
            "filter_name": "HEPA filter",
            "percentage": 5,
        }
    )
    described = captured["callback"](event)
    assert described[LOGBOOK_ENTRY_NAME] == "Living Room"
    assert described[LOGBOOK_ENTRY_MESSAGE] == "HEPA filter needs attention (5%)"
    assert described[LOGBOOK_ENTRY_ICON] == "mdi:air-filter"
    assert described[LOGBOOK_ENTRY_ENTITY_ID] == "binary_sensor.living_room_filter"


async def test_filter_alert_described_without_entity_or_percentage(hass: HomeAssistant) -> None:
    """A bare event still renders, with sensible fallbacks and no entity attachment."""
    captured = _register(hass)
    described = captured["callback"](SimpleNamespace(data={}))
    assert described[LOGBOOK_ENTRY_NAME] == "Philips AirPurifier"
    assert described[LOGBOOK_ENTRY_MESSAGE] == "A filter needs attention"
    assert LOGBOOK_ENTRY_ENTITY_ID not in described
