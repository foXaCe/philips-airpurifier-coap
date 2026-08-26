"""DataUpdateCoordinator managing push updates from a Philips device over CoAP."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .aioairctrl import CoAPClient
from .aioairctrl.coap.encryption import DigestMismatchException
from .const import DOMAIN
from .model import DeviceStatus

if TYPE_CHECKING:
    from .const import PhilipsConfigEntry

_LOGGER = logging.getLogger(__name__)

# Number of consecutive missed status reports before we assume the connection
# is dead and trigger a reconnect.
MISSED_PACKAGE_COUNT = 3

# Fallback reporting interval (seconds) until the device tells us its own.
DEFAULT_TIMEOUT = 60

# aioairctrl sends non-confirmable CoAP messages and never times out on its
# own: a single lost UDP datagram would otherwise hang an await forever. Cap
# every client round-trip so a lost packet degrades into a retryable error
# instead of wedging the integration until Home Assistant is restarted.
CONNECT_TIMEOUT = 30
COMMAND_TIMEOUT = 30

# Reconnect backoff after a failed connection attempt. The Philips firmware is
# known to wedge its CoAP server until a power cycle, so a failed reconnect
# should retry quickly at first (the user may be power-cycling the device) and
# back off exponentially to avoid hammering a dead endpoint, capped at the
# watchdog interval. The backoff resets as soon as a status update arrives.
RECONNECT_RETRY_DELAY = 30
RECONNECT_BACKOFF_FACTOR = 2
RECONNECT_BACKOFF_MAX = 180

# Errors raised while decoding a single corrupt status packet. A truncated or
# mangled UDP datagram makes ``bytes.fromhex()``/``json.loads()`` fail (both
# ``ValueError``), the decrypted plaintext may not decode as UTF-8
# (``UnicodeDecodeError``, a ``ValueError`` subclass) or lack the expected keys
# (``KeyError``), or the self-consistent digest check may reject it
# (``DigestMismatchException``). None of these mean the device is unreachable.
DECODE_ERRORS = (ValueError, KeyError, DigestMismatchException)


class Coordinator(DataUpdateCoordinator[DeviceStatus]):
    """Coordinate push updates from a Philips AirPurifier over CoAP.

    The device pushes status updates through a CoAP ``observe`` stream rather
    than being polled, so this coordinator does not implement
    ``_async_update_data``. Instead it forwards every observed status to the
    entities via :meth:`async_set_updated_data` and uses a watchdog timer to
    reconnect when updates stop arriving.
    """

    config_entry: PhilipsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: CoAPClient | None,
        host: str,
        status: DeviceStatus | None = None,
        config_entry: PhilipsConfigEntry | None = None,
    ) -> None:
        """Initialize the coordinator.

        ``client`` may be ``None`` when the connection is deferred to a
        background task (see :meth:`async_connect`) so that setup does not
        block Home Assistant startup on the network round-trip.
        """
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=config_entry)

        self.client = client
        self.host = host
        self.data = status or {}

        self._observe_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._reconnecting = False
        self._timeout: int = DEFAULT_TIMEOUT
        self._cancel_watchdog: CALLBACK_TYPE | None = None
        self._reconnect_delay: float = RECONNECT_RETRY_DELAY
        self._watchdog_delay: float | None = None

    @property
    def status(self) -> DeviceStatus:
        """Return the latest known status (compatibility alias for ``data``)."""
        return self.data or {}

    async def async_connect(self) -> None:
        """Create the CoAP client in the background and start observing.

        Called from ``async_setup_entry`` once the platforms are set up so that
        the connection handshake never blocks Home Assistant startup. Entities
        hold the last known status until the first status report arrives.
        """
        if self.client is not None:
            return
        await self._async_reconnect()

    async def async_first_refresh(self) -> None:
        """Fetch the initial status before the platforms are set up."""
        if self.client is None:
            raise ConfigEntryNotReady(f"No CoAP client for host {self.host}")
        try:
            status, timeout = await self.client.get_status()
        except Exception as ex:
            _LOGGER.error("First refresh failed for host %s", self.host)
            raise ConfigEntryNotReady from ex

        self.data = status
        self._timeout = timeout or DEFAULT_TIMEOUT
        _LOGGER.debug("Finished first refresh for host %s", self.host)

    async def async_shutdown(self) -> None:
        """Cancel all background work and close the client."""
        self._cancel_watchdog_if_needed()
        self._async_delete_unreachable_issue()

        if self._observe_task is not None:
            self._observe_task.cancel()
            self._observe_task = None

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.shutdown()

        await super().async_shutdown()

    @callback
    def async_add_listener(
        self, update_callback: CALLBACK_TYPE, context: Any = None
    ) -> CALLBACK_TYPE:
        """Listen for data updates and start observing on the first listener."""
        start_observing = not self._listeners
        remove_listener = super().async_add_listener(update_callback, context)

        if start_observing:
            self._start_observing()

        @callback
        def remove_and_maybe_stop() -> None:
            remove_listener()
            if not self._listeners:
                self._stop_observing()

        return remove_and_maybe_stop

    @callback
    def _start_observing(self) -> None:
        """Start the CoAP observation task and arm the watchdog."""
        if self.client is None:
            # Connection is still being established in the background; it will
            # call _start_observing again once the client is ready.
            return
        if self._observe_task is not None:
            self._observe_task.cancel()

        self._observe_task = self.hass.async_create_background_task(
            self._async_observe_status(), name=f"{DOMAIN}_observe_{self.host}"
        )
        self._arm_watchdog()

    @callback
    def _stop_observing(self) -> None:
        """Stop the observation task and disarm the watchdog."""
        self._cancel_watchdog_if_needed()

        if self._observe_task is not None:
            self._observe_task.cancel()
            self._observe_task = None

    async def _async_observe_status(self) -> None:
        """Forward every observed status update to the entities."""
        if self.client is None:  # pragma: no cover - guarded by _start_observing
            return
        try:
            async for status in self.client.observe_status():
                self.async_set_updated_data(status)
                self._reconnect_delay = RECONNECT_RETRY_DELAY
                self._arm_watchdog()
        except asyncio.CancelledError:
            raise
        except DECODE_ERRORS as ex:
            # A single CoAP packet arrived corrupt (truncated UDP datagram, bad
            # decrypt). The observe generator dies on it, but the device is
            # healthy and our last known state is still valid. Reconnect
            # silently to resume the stream instead of flagging the device
            # unavailable and logging a spurious "Error requesting data".
            _LOGGER.debug("Discarding corrupt status packet from host %s: %s", self.host, ex)
            if not self._reconnecting:
                self._schedule_reconnect()
        except Exception as ex:  # noqa: BLE001 - the observe subscription died
            if self._reconnecting:
                # The watchdog shut the client down on purpose to reconnect; stay
                # quiet (no spurious "Error requesting data") and let the reconnect
                # restart the observation. The device keeps its last known state.
                _LOGGER.debug("Observation stopped during reconnect for host %s", self.host)
                return
            # Only the observe subscription died; the CoAP client itself stays
            # alive, so commands keep working. Mark the device stale and let the
            # watchdog do a full reconnect. Tearing the client down on every
            # transient observe drop churned it and broke control commands.
            _LOGGER.debug("Observation stopped for host %s: %s", self.host, ex)
            self.async_set_update_error(ex)

    async def async_set_control_value(self, key: str, value: Any) -> None:
        """Send a single control value, bounded by a timeout.

        A lost datagram would otherwise hang the service call forever; on
        timeout the connection is assumed dead and a reconnect is scheduled so
        the next command works without waiting for the watchdog.
        """
        if self.client is None:
            raise HomeAssistantError("Device is not connected")
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self.client.set_control_value(key, value)
        except TimeoutError:
            self._schedule_reconnect()
            raise

    async def async_set_control_values(self, data: dict[str, Any]) -> None:
        """Send several control values, bounded by a timeout (see above)."""
        if self.client is None:
            raise HomeAssistantError("Device is not connected")
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self.client.set_control_values(data=data)
        except TimeoutError:
            self._schedule_reconnect()
            raise

    @callback
    def _arm_watchdog(self, delay: float | None = None) -> None:
        """(Re)arm the watchdog that reconnects when updates stop arriving.

        ``delay`` overrides the default ``timeout * MISSED_PACKAGE_COUNT``
        interval, used for the fast reconnect backoff after a failed attempt.
        """
        self._cancel_watchdog_if_needed()
        self._watchdog_delay = delay if delay is not None else self._timeout * MISSED_PACKAGE_COUNT
        self._cancel_watchdog = async_call_later(
            self.hass,
            self._watchdog_delay,
            self._handle_watchdog_timeout,
        )

    @callback
    def _cancel_watchdog_if_needed(self) -> None:
        """Cancel the watchdog timer if it is armed."""
        if self._cancel_watchdog is not None:
            self._cancel_watchdog()
            self._cancel_watchdog = None

    @callback
    def _handle_watchdog_timeout(self, _now: datetime) -> None:
        """No update arrived in time: schedule a reconnect."""
        _LOGGER.debug(
            "No update from host %s within %ss, reconnecting",
            self.host,
            self._watchdog_delay,
        )
        self._schedule_reconnect()

    @callback
    def _schedule_reconnect(self) -> None:
        """Cancel the watchdog and start (or restart) a reconnect task."""
        self._cancel_watchdog_if_needed()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()

        self._reconnect_task = self.hass.async_create_background_task(
            self._async_reconnect(), name=f"{DOMAIN}_reconnect_{self.host}"
        )

    async def _async_reconnect(self) -> None:
        """Recreate the CoAP client and resume observing."""
        self._reconnecting = True
        # Drop the old client before shutting it down so a failed reconnect
        # leaves ``client`` as None: control methods then raise a clean
        # "Device is not connected" instead of using a closed client.
        old_client = self.client
        self.client = None
        if old_client is not None:
            with contextlib.suppress(Exception):
                await old_client.shutdown()

        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self.client = await CoAPClient.create(self.host)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            self._handle_reconnect_failure(
                TimeoutError(f"CoAP connection to {self.host} timed out after {CONNECT_TIMEOUT}s"),
                "timed out after %ss (no CoAP answer)",
            )
            return
        except Exception as ex:  # noqa: BLE001 - retry on any connection failure
            self._handle_reconnect_failure(ex, "failed")
            return

        self._reconnecting = False
        _LOGGER.debug("Reconnected to host %s", self.host)
        self._reconnect_delay = RECONNECT_RETRY_DELAY
        self._async_delete_unreachable_issue()
        self._start_observing()

    @callback
    def _handle_reconnect_failure(self, error: Exception, reason: str) -> None:
        """Record a failed reconnect and schedule the next attempt.

        The Philips firmware is known to wedge its CoAP server until a power
        cycle, so a failed reconnect retries quickly at first (the user may be
        power-cycling the device) and backs off exponentially to avoid hammering
        a dead endpoint, capped at the watchdog interval.
        """
        self._reconnecting = False
        _LOGGER.warning("Reconnect to host %s %s: %s", self.host, reason, error)
        self.async_set_update_error(error)
        self._async_create_unreachable_issue()
        self._arm_watchdog(self._reconnect_delay)
        self._reconnect_delay = min(
            self._reconnect_delay * RECONNECT_BACKOFF_FACTOR, RECONNECT_BACKOFF_MAX
        )

    @callback
    def _async_create_unreachable_issue(self) -> None:
        """Raise a repair issue while the device stays unreachable."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"device_unreachable_{self.host}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="device_unreachable",
            translation_placeholders={"host": self.host},
        )

    @callback
    def _async_delete_unreachable_issue(self) -> None:
        """Clear the unreachable repair issue once the device responds again."""
        ir.async_delete_issue(self.hass, DOMAIN, f"device_unreachable_{self.host}")
