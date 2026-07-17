"""Tests for the push DataUpdateCoordinator."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.philips_airpurifier_coap.coordinator import (
    MISSED_PACKAGE_COUNT,
    Coordinator,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util


class FakeClient:
    """Minimal stand-in for ``aioairctrl.CoAPClient``."""

    def __init__(self, status: dict, timeout: int = 60) -> None:
        """Initialize the fake client."""
        self.initial_status = status
        self.timeout = timeout
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.shutdown = AsyncMock()
        self.set_control_value = AsyncMock()
        self.set_control_values = AsyncMock()

    async def get_status(self) -> tuple[dict, int]:
        """Return a copy of the initial status and the reporting interval."""
        return dict(self.initial_status), self.timeout

    async def observe_status(self):
        """Yield every status pushed onto the queue (a live stream).

        Pushing an ``Exception`` onto the queue raises it, mimicking the
        library's generator dying on a corrupt or dropped packet.
        """
        while True:
            item = await self.queue.get()
            if isinstance(item, Exception):
                raise item
            yield item


def _make_coordinator(hass: HomeAssistant, client: FakeClient, status: dict | None):
    """Create a coordinator instance for tests."""
    return Coordinator(hass, client, "1.2.3.4", status)


async def test_is_data_update_coordinator(hass: HomeAssistant) -> None:
    """The coordinator must be a proper DataUpdateCoordinator."""
    coord = _make_coordinator(hass, FakeClient({"pwr": "1"}), {"pwr": "1"})
    assert isinstance(coord, DataUpdateCoordinator)
    assert coord.status == {"pwr": "1"}


async def test_first_refresh_sets_data_and_timeout(hass: HomeAssistant) -> None:
    """async_first_refresh should populate data and learn the interval."""
    client = FakeClient({"pwr": "1"}, timeout=30)
    coord = _make_coordinator(hass, client, None)

    await coord.async_first_refresh()

    assert coord.data == {"pwr": "1"}
    assert coord.status == {"pwr": "1"}
    assert coord._timeout == 30


async def test_first_refresh_failure_raises_not_ready(hass: HomeAssistant) -> None:
    """A failing first refresh must raise ConfigEntryNotReady."""
    client = FakeClient({})
    client.get_status = AsyncMock(side_effect=OSError("boom"))
    coord = _make_coordinator(hass, client, None)

    with pytest.raises(ConfigEntryNotReady):
        await coord.async_first_refresh()


async def test_push_update_propagates(hass: HomeAssistant) -> None:
    """A pushed status update should reach the listeners via the coordinator."""
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})

    updates: list[dict] = []

    @callback
    def _listener() -> None:
        updates.append(dict(coord.data))

    remove = coord.async_add_listener(_listener)
    await hass.async_block_till_done()

    await client.queue.put({"pwr": "0", "pm25": 12})
    await hass.async_block_till_done()

    assert coord.data == {"pwr": "0", "pm25": 12}
    assert coord.last_update_success
    assert {"pwr": "0", "pm25": 12} in updates

    remove()
    await coord.async_shutdown()


async def test_observing_stops_without_listeners(hass: HomeAssistant) -> None:
    """Removing the last listener should stop the observation task."""
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})

    remove = coord.async_add_listener(lambda: None)
    await hass.async_block_till_done()
    assert coord._observe_task is not None

    remove()
    assert coord._observe_task is None

    await coord.async_shutdown()


async def test_watchdog_triggers_reconnect(hass: HomeAssistant) -> None:
    """When no update arrives in time, the watchdog reconnects the client."""
    client = FakeClient({"pwr": "1"}, timeout=1)
    coord = _make_coordinator(hass, client, None)
    await coord.async_first_refresh()  # learns the 1s reporting interval
    new_client = FakeClient({"pwr": "1"}, timeout=1)

    coord.async_add_listener(lambda: None)
    await hass.async_block_till_done()

    with patch(
        "custom_components.philips_airpurifier_coap.coordinator.CoAPClient.create",
        AsyncMock(return_value=new_client),
    ) as mock_create:
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=MISSED_PACKAGE_COUNT + 2)
        )
        await hass.async_block_till_done()
        mock_create.assert_awaited_once()

    assert coord.client is new_client
    client.shutdown.assert_awaited()

    await coord.async_shutdown()


async def test_corrupt_packet_reconnects_silently(hass: HomeAssistant) -> None:
    """A corrupt status packet reconnects silently without flagging an error."""
    client = FakeClient({"pwr": "1"}, timeout=1)
    coord = _make_coordinator(hass, client, {"pwr": "1"})
    await coord.async_first_refresh()
    new_client = FakeClient({"pwr": "1"}, timeout=1)

    coord.async_add_listener(lambda: None)
    await hass.async_block_till_done()

    with patch(
        "custom_components.philips_airpurifier_coap.coordinator.CoAPClient.create",
        AsyncMock(return_value=new_client),
    ) as mock_create:
        # Mimic the library raising on a truncated UDP datagram.
        await client.queue.put(
            ValueError("non-hexadecimal number found in fromhex() arg at position 220")
        )
        await hass.async_block_till_done()
        mock_create.assert_awaited_once()

    # The device stays available and keeps its last known state.
    assert coord.last_update_success is True
    assert coord.data == {"pwr": "1"}
    assert coord.client is new_client

    await coord.async_shutdown()


async def test_corrupt_packet_during_reconnect_does_not_reschedule(
    hass: HomeAssistant,
) -> None:
    """A corrupt packet while a reconnect is already in flight schedules nothing."""
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})
    coord._reconnecting = True  # a reconnect is already tearing the client down

    with patch(
        "custom_components.philips_airpurifier_coap.coordinator.CoAPClient.create",
        AsyncMock(),
    ) as mock_create:
        coord.async_add_listener(lambda: None)
        await hass.async_block_till_done()
        await client.queue.put(
            ValueError("non-hexadecimal number found in fromhex() arg at position 42")
        )
        await hass.async_block_till_done()

    # Already reconnecting → no second reconnect, device keeps its state.
    assert mock_create.await_count == 0
    assert coord.last_update_success is True

    coord._reconnecting = False
    await coord.async_shutdown()


async def test_reconnect_hang_times_out_and_retries(hass: HomeAssistant) -> None:
    """A reconnect that hangs (lost CoAP sync packet) times out and retries.

    aioairctrl uses non-confirmable messages without timeouts, so a lost
    datagram used to hang CoAPClient.create forever: the watchdog was never
    re-armed and only a Home Assistant restart recovered the device.
    """
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})

    async def _hang(host):
        await asyncio.Event().wait()

    with (
        patch(
            "custom_components.philips_airpurifier_coap.coordinator.CONNECT_TIMEOUT",
            0,
        ),
        patch(
            "custom_components.philips_airpurifier_coap.coordinator.CoAPClient.create",
            _hang,
        ),
    ):
        coord._schedule_reconnect()
        assert coord._reconnect_task is not None
        # block_till_done does not wait for background tasks; await it directly.
        await coord._reconnect_task

    # The hang degraded into a failure: device unavailable, but the watchdog is
    # re-armed so the coordinator keeps retrying instead of wedging forever.
    assert coord.last_update_success is False
    assert coord._reconnecting is False
    assert coord._cancel_watchdog is not None

    await coord.async_shutdown()


async def test_command_timeout_raises_and_schedules_reconnect(
    hass: HomeAssistant,
) -> None:
    """A control command that hangs times out and triggers a reconnect."""
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})

    async def _hang(*args, **kwargs):
        await asyncio.Event().wait()

    client.set_control_value = _hang
    client.set_control_values = _hang

    new_client = FakeClient({"pwr": "1"})
    # The reconnect triggered by the first timeout swaps the client in; make
    # the replacement hang too so the second command also exercises the timeout.
    new_client.set_control_value = _hang
    new_client.set_control_values = _hang
    with (
        patch(
            "custom_components.philips_airpurifier_coap.coordinator.COMMAND_TIMEOUT",
            0,
        ),
        patch(
            "custom_components.philips_airpurifier_coap.coordinator.CoAPClient.create",
            AsyncMock(return_value=new_client),
        ),
    ):
        with pytest.raises(TimeoutError):
            await coord.async_set_control_value("pwr", "0")
        with pytest.raises(TimeoutError):
            await coord.async_set_control_values({"pwr": "0"})
        assert coord._reconnect_task is not None
        # block_till_done does not wait for background tasks; await it directly.
        await coord._reconnect_task

    # The reconnect recovered the connection with a fresh client.
    assert coord.client is new_client

    await coord.async_shutdown()


async def test_commands_pass_through_to_client(hass: HomeAssistant) -> None:
    """The command helpers forward to the client within the timeout."""
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})

    await coord.async_set_control_value("pwr", "0")
    client.set_control_value.assert_awaited_once_with("pwr", "0")

    await coord.async_set_control_values({"pwr": "0", "om": "1"})
    client.set_control_values.assert_awaited_once_with(data={"pwr": "0", "om": "1"})

    await coord.async_shutdown()


async def test_reconnect_failure_marks_unavailable(hass: HomeAssistant) -> None:
    """A failed reconnect marks the coordinator as unavailable and retries."""
    client = FakeClient({"pwr": "1"}, timeout=1)
    coord = _make_coordinator(hass, client, None)
    await coord.async_first_refresh()
    coord.async_add_listener(lambda: None)
    await hass.async_block_till_done()

    with patch(
        "custom_components.philips_airpurifier_coap.coordinator.CoAPClient.create",
        AsyncMock(side_effect=OSError("boom")),
    ):
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=MISSED_PACKAGE_COUNT + 2)
        )
        await hass.async_block_till_done()

    assert coord.last_update_success is False

    await coord.async_shutdown()


async def test_shutdown_cancels_and_closes(hass: HomeAssistant) -> None:
    """async_shutdown must stop the tasks and close the client."""
    client = FakeClient({"pwr": "1"})
    coord = _make_coordinator(hass, client, {"pwr": "1"})

    coord.async_add_listener(lambda: None)
    await hass.async_block_till_done()

    await coord.async_shutdown()

    assert coord._observe_task is None
    client.shutdown.assert_awaited()
