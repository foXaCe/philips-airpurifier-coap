"""Tests for the diagnostics."""

from syrupy.assertion import SnapshotAssertion

from custom_components.philips_airpurifier_coap.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant


async def test_diagnostics(hass: HomeAssistant, make_runtime, snapshot: SnapshotAssertion) -> None:
    """Diagnostics expose device info while redacting sensitive data."""
    entry, _ = make_runtime("AC3033")

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Guard the security-critical redaction explicitly: a snapshot alone would
    # silently bake in a leaked host if --snapshot-update ran on a regression.
    assert diagnostics["entry"]["data"]["host"] == "**REDACTED**"
    assert diagnostics["device_info"]["host"] == "**REDACTED**"
    assert diagnostics == snapshot
