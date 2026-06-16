"""Snapshot tests covering every entity created across all platforms."""

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .fixtures.mock_data import (
    SAMPLE_STATUS_AC0950,
    SAMPLE_STATUS_AC1715,
    SAMPLE_STATUS_AC3033,
)


@pytest.mark.parametrize(
    ("model", "status"),
    [
        ("AC3033", SAMPLE_STATUS_AC3033),
        ("AC0950", SAMPLE_STATUS_AC0950),
        ("AC1715", SAMPLE_STATUS_AC1715),
    ],
)
async def test_all_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    setup_model,
    model: str,
    status: dict,
) -> None:
    """Snapshot every entity (registry entry + state) for representative models.

    One feature-rich device per device generation (legacy AC3033, new2-gen
    AC0950, humidifier-capable AC1715) exercises all entity platforms at once.
    The integration sets up every platform from a single config entry, so the
    snapshots are keyed by ``entity_id`` rather than using the single-platform
    ``snapshot_platform`` helper.
    """
    entry, _ = await setup_model(model, status)

    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert entity_entries

    for entity_entry in entity_entries:
        assert entity_entry == snapshot(name=f"{entity_entry.entity_id}-entry")
        if entity_entry.disabled_by:
            continue
        state = hass.states.get(entity_entry.entity_id)
        assert state, f"State missing for {entity_entry.entity_id}"
        assert state == snapshot(name=f"{entity_entry.entity_id}-state")
