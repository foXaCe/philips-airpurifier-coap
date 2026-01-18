"""Philips Air Purifier & Humidifier Binary Sensors."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_CLASS, CONF_ENTITY_CATEGORY, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity

from .config_entry_data import ConfigEntryData
from .const import (
    BINARY_SENSOR_TYPES,
    DOMAIN,
    FILTER_ALERT_THRESHOLD,
    FILTER_TYPES,
    FanAttributes,
)
from .devices import PhilipsEntity, model_to_class

_LOGGER = logging.getLogger(__name__)

EVENT_FILTER_ALERT = "philips_filter_alert"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[Entity], bool], None],
) -> None:
    """Set up platform for binary_sensor."""

    config_entry_data: ConfigEntryData = hass.data[DOMAIN][entry.entry_id]

    model = config_entry_data.device_information.model
    status = config_entry_data.latest_status

    model_class = model_to_class.get(model)
    available_binary_sensors = []
    unavailable_filters = []

    if model_class:
        for cls in reversed(model_class.__mro__):
            cls_available_binary_sensors = getattr(cls, "AVAILABLE_BINARY_SENSORS", [])
            available_binary_sensors.extend(cls_available_binary_sensors)
            cls_unavailable_filters = getattr(cls, "UNAVAILABLE_FILTERS", [])
            unavailable_filters.extend(cls_unavailable_filters)

    binary_sensors: list[Entity] = [
        PhilipsBinarySensor(hass, entry, config_entry_data, binary_sensor)
        for binary_sensor in BINARY_SENSOR_TYPES
        if binary_sensor in status and binary_sensor in available_binary_sensors
    ]

    # Check if device has any filter sensors, then add filter alert sensor
    available_filters = [f for f in FILTER_TYPES if f in status and f not in unavailable_filters]
    if available_filters:
        binary_sensors.append(
            PhilipsFilterAlertSensor(hass, entry, config_entry_data, available_filters)
        )

    async_add_entities(binary_sensors, update_before_add=False)


class PhilipsBinarySensor(PhilipsEntity, BinarySensorEntity):
    """Define a Philips AirPurifier binary_sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigEntry,
        config_entry_data: ConfigEntryData,
        kind: str,
    ) -> None:
        """Initialize the binary sensor."""

        super().__init__(hass, config, config_entry_data)

        self._model = config_entry_data.device_information.model

        self._description = BINARY_SENSOR_TYPES[kind]
        self._attr_device_class = self._description.get(ATTR_DEVICE_CLASS)
        self._attr_entity_category = self._description.get(CONF_ENTITY_CATEGORY)
        self._attr_translation_key = self._description.get(FanAttributes.LABEL)

        model = config_entry_data.device_information.model
        device_id = config_entry_data.device_information.device_id
        self._attr_unique_id = f"{model}-{device_id}-{kind.lower()}"

        self._attrs: dict[str, Any] = {}
        self.kind = kind

    @property
    def is_on(self) -> bool:
        """Return the state of the binary sensor."""
        value = self._device_status[self.kind]
        convert = self._description.get(FanAttributes.VALUE)
        if convert:
            value = convert(value)
        return cast(bool, value)


class PhilipsFilterAlertSensor(PhilipsEntity, BinarySensorEntity):
    """Binary sensor that indicates if any filter needs attention."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = FanAttributes.FILTER_NEEDS_ATTENTION

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigEntry,
        config_entry_data: ConfigEntryData,
        filter_keys: list[str],
    ) -> None:
        """Initialize the filter alert sensor."""
        super().__init__(hass, config, config_entry_data)

        self._filter_keys = filter_keys
        self._previous_alert_state: bool | None = None
        self._previous_low_filters: set[str] = set()

        model = config_entry_data.device_information.model
        device_id = config_entry_data.device_information.device_id
        self._attr_unique_id = f"{model}-{device_id}-filter_alert"

    @property
    def is_on(self) -> bool:
        """Return True if any filter needs attention (below threshold)."""
        return bool(self._get_low_filters())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with details about low filters."""
        low_filters = self._get_low_filters()
        attrs: dict[str, Any] = {
            "threshold": FILTER_ALERT_THRESHOLD,
            "low_filters": list(low_filters.keys()),
        }
        # Add individual filter percentages
        for filter_key, percentage in low_filters.items():
            filter_desc = FILTER_TYPES.get(filter_key, {})
            filter_name = filter_desc.get(FanAttributes.LABEL, filter_key)
            attrs[f"{filter_name}_percentage"] = percentage
        return attrs

    def _get_low_filters(self) -> dict[str, float]:
        """Get filters that are below the threshold with their percentages."""
        low_filters: dict[str, float] = {}
        for filter_key in self._filter_keys:
            if filter_key not in self._device_status:
                continue

            filter_desc = FILTER_TYPES.get(filter_key)
            if not filter_desc:
                continue

            total_key = filter_desc.get(FanAttributes.TOTAL)
            if total_key and total_key in self._device_status:
                # Calculate percentage
                value = self._device_status[filter_key]
                total = self._device_status[total_key]
                if total > 0:
                    percentage = round(100.0 * value / total)
                    if percentage < FILTER_ALERT_THRESHOLD:
                        low_filters[filter_key] = percentage
            else:
                # No total available, use raw hours value
                # Consider low if under ~72 hours (3 days)
                value = self._device_status[filter_key]
                if value < 72:
                    low_filters[filter_key] = value
        return low_filters

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator and fire events."""
        current_low_filters = set(self._get_low_filters().keys())
        current_alert = bool(current_low_filters)

        # Fire event when a new filter becomes low (not on initial load)
        if self._previous_alert_state is not None:
            new_low_filters = current_low_filters - self._previous_low_filters
            if new_low_filters:
                for filter_key in new_low_filters:
                    filter_desc = FILTER_TYPES.get(filter_key, {})
                    filter_name = filter_desc.get(FanAttributes.LABEL, filter_key)
                    low_filters_data = self._get_low_filters()

                    device_info = self.config_entry_data.device_information
                    self.hass.bus.fire(
                        EVENT_FILTER_ALERT,
                        {
                            "device_id": device_info.device_id,
                            "device_name": device_info.name,
                            "filter_key": filter_key,
                            "filter_name": filter_name,
                            "percentage": low_filters_data.get(filter_key),
                            "threshold": FILTER_ALERT_THRESHOLD,
                        },
                    )
                    _LOGGER.info(
                        "Filter alert: %s is at %s%% (threshold: %s%%)",
                        filter_name,
                        low_filters_data.get(filter_key),
                        FILTER_ALERT_THRESHOLD,
                    )

        self._previous_alert_state = current_alert
        self._previous_low_filters = current_low_filters
        super()._handle_coordinator_update()
