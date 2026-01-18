"""Pytest configuration and fixtures for Philips AirPurifier CoAP tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from .fixtures.mock_data import SAMPLE_STATUS_AC3033


@pytest.fixture
def mock_coap_client():
    """Create a mock CoAPClient."""
    client = AsyncMock()
    client.get_status = AsyncMock(return_value=(SAMPLE_STATUS_AC3033, None))
    client.set_control_value = AsyncMock()
    client.set_control_values = AsyncMock()
    client.observe_status = AsyncMock()
    client.shutdown = AsyncMock()
    return client


@pytest.fixture
def mock_coordinator(mock_coap_client):
    """Create a mock Coordinator."""
    coordinator = MagicMock()
    coordinator.client = mock_coap_client
    coordinator.status = SAMPLE_STATUS_AC3033
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


@pytest.fixture
def sample_status():
    """Return sample device status."""
    return SAMPLE_STATUS_AC3033.copy()


@pytest.fixture
def mock_config_entry():
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "host": "192.168.1.100",
        "model": "AC3033/10",
        "name": "Living Room",
        "device_id": "ABCD1234567890",
    }
    return entry


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock()
    return hass
