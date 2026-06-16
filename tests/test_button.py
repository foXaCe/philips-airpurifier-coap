"""Tests for the filter-reset buttons."""

from custom_components.philips_airpurifier_coap import button
from custom_components.philips_airpurifier_coap.const import PhilipsApi
from homeassistant.core import HomeAssistant

_BASE = {
    PhilipsApi.DEVICE_ID: "ABCD1234567890",
    PhilipsApi.WIFI_VERSION: "AWS_Philips_AIR@1.0.0",
}


async def _setup(hass, make_runtime, model, status):
    """Run the button setup and return the created entities."""
    entry, runtime = make_runtime(model=model, status={**_BASE, **status})
    added: list = []
    await button.async_setup_entry(hass, entry, lambda entities, *_: added.extend(entities))
    return added, runtime


async def test_filter_reset_button_press(hass: HomeAssistant, make_runtime) -> None:
    """Pressing a reset button writes the total life back to the remaining-life key."""
    status = {
        PhilipsApi.FILTER_HEPA: 5,
        PhilipsApi.FILTER_HEPA_TOTAL: 100,
        PhilipsApi.FILTER_HEPA_TYPE: "A3",
    }
    entities, runtime = await _setup(hass, make_runtime, "AC3033", status)
    btn = next(e for e in entities if e._value_key == PhilipsApi.FILTER_HEPA)
    btn.async_write_ha_state = lambda: None
    assert btn.unique_id == "AC3033-ABCD1234567890-hepa_filter_reset"

    await btn.async_press()
    runtime.client.set_control_value.assert_awaited_with(PhilipsApi.FILTER_HEPA, 100)


async def test_filter_reset_no_total_is_noop(hass: HomeAssistant, make_runtime) -> None:
    """A press is a no-op when the total life is no longer known."""
    status = {PhilipsApi.FILTER_HEPA: 5, PhilipsApi.FILTER_HEPA_TOTAL: 100}
    entities, runtime = await _setup(hass, make_runtime, "AC3033", status)
    btn = next(e for e in entities if e._value_key == PhilipsApi.FILTER_HEPA)
    btn.async_write_ha_state = lambda: None

    btn._device_status.pop(PhilipsApi.FILTER_HEPA_TOTAL, None)
    await btn.async_press()
    runtime.client.set_control_value.assert_not_awaited()


async def test_button_unknown_model(hass: HomeAssistant, make_runtime) -> None:
    """An unknown model still exposes reset buttons for the filters in the status."""
    entry, runtime = make_runtime(
        model="AC3033",
        status={**_BASE, PhilipsApi.FILTER_HEPA: 50, PhilipsApi.FILTER_HEPA_TOTAL: 100},
    )
    runtime.device_information.model = "UNKNOWN9999"
    added: list = []
    await button.async_setup_entry(hass, entry, lambda entities, *_: added.extend(entities))
    assert any(e._value_key == PhilipsApi.FILTER_HEPA for e in added)
