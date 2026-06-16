"""Philips Air Purifier filter-reset buttons."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .devices import PhilipsEntity, collect_class_attribute, model_to_class
from .sensor import FILTER_TYPES, PhilipsFilterEntityDescription

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .config_entry_data import ConfigEntryData
    from .const import PhilipsConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PhilipsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform."""
    config_entry_data = entry.runtime_data
    model = config_entry_data.device_information.model
    status = config_entry_data.latest_status or {}

    model_class = model_to_class.get(model)
    unavailable_filters: list[str] = []
    if model_class:
        unavailable_filters = collect_class_attribute(model_class, "UNAVAILABLE_FILTERS")

    async_add_entities(
        PhilipsFilterResetButton(hass, entry, config_entry_data, description)
        for description in FILTER_TYPES
        if description.key in status
        and description.total_key
        and description.total_key in status
        and description.key not in unavailable_filters
    )


class PhilipsFilterResetButton(PhilipsEntity, ButtonEntity):
    """A button that resets a filter's life counter to 100%."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigEntry,
        config_entry_data: ConfigEntryData,
        description: PhilipsFilterEntityDescription,
    ) -> None:
        """Initialize the filter-reset button."""
        super().__init__(hass, config, config_entry_data)
        self._value_key = description.key
        self._total_key = description.total_key

        model = config_entry_data.device_information.model
        device_id = config_entry_data.device_information.device_id
        self._attr_unique_id = f"{model}-{device_id}-{description.translation_key}_reset"
        self._attr_translation_key = f"{description.translation_key}_reset"

    async def async_press(self) -> None:
        """Reset the filter by writing its total life back to the remaining-life key.

        This mirrors what the Philips Air+ app does: the device acknowledges the
        reset (it beeps) and the filter sensor jumps back to 100%.
        """
        total = self._device_status.get(self._total_key)
        if total is None:
            return
        await self._async_set_control_value(self._value_key, total)
