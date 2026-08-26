"""Tests for the vendored CoAP client.

The client is exercised against a fake device that speaks the real wire format:
it answers ``/sys/dev/sync`` with a counter and seals its status with the same
``EncryptionContext`` the client uses to open it. That keeps the tests honest
about the envelope instead of stubbing the crypto away.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

from Cryptodome.Cipher import PKCS1_v1_5
from Cryptodome.PublicKey import RSA
import pytest

from custom_components.philips_airpurifier_coap.aioairctrl.coap.client import (
    Client,
    StaleStatusError,
    is_tls_option,
)
from custom_components.philips_airpurifier_coap.aioairctrl.coap.encryption import (
    EncryptionContext,
    derive_tls_secret,
)

STATUS = {"state": {"reported": {"pwr": "1", "om": "2"}}}


class FakeResponse:
    """Minimal stand-in for an aiocoap response."""

    def __init__(self, payload: str, max_age: int | None = None) -> None:
        self.payload = payload.encode()
        self.opt = type("Opt", (), {"max_age": max_age})()


class FakeRequester:
    """Result of ``Context.request()``: one response, plus an observation."""

    def __init__(self, response: FakeResponse, observation: Any = None) -> None:
        self._response = response
        self.observation = observation

    @property
    def response(self) -> Any:
        async def _await() -> FakeResponse:
            return self._response

        return _await()


class FakeObservation:
    """Async-iterable observation that records whether it was cancelled."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.cancelled = False

    def __aiter__(self) -> FakeObservation:
        self._iter = iter(self._responses)
        return self

    async def __anext__(self) -> FakeResponse:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None

    def cancel(self) -> None:
        self.cancelled = True


class FakeDevice:
    """Answers the CoAP resources the client talks to."""

    def __init__(self, client_key: str = "00000010") -> None:
        self.client_key = client_key
        self.enc = EncryptionContext()
        self.enc.set_client_key(client_key)
        self.control_results: list[str] = []
        self.control_payloads: list[str] = []
        self.sync_count = 0
        self.observation: FakeObservation | None = None
        self.status_max_age: int | None = None
        # TLS key-exchange state, filled in when the client runs the handshake.
        self.random1 = 4242
        self.random2: int | None = None
        self.prekey = b"\x11\x22\x33\x44"
        self.tls_secret: str | None = None

    def seal(self, payload: dict[str, Any]) -> str:
        return self.enc.encrypt(json.dumps(payload))

    def request(self, message: Any) -> FakeRequester:
        uri = "/" + "/".join(message.opt.uri_path)
        if uri.endswith("/sys/dev/sync"):
            self.sync_count += 1
            return FakeRequester(FakeResponse(self.client_key))
        if uri.endswith("/sys/dev/status"):
            return FakeRequester(
                FakeResponse(self.seal(STATUS), self.status_max_age), self.observation
            )
        if uri.endswith("/sys/dev/info/tls"):
            request = json.loads(message.payload.decode())
            assert request["type"] == "config_encrypt"
            self.random2 = int(request["random2"])
            # Seal a prekey with the public key the client just published.
            sealed = PKCS1_v1_5.new(RSA.import_key(request["pk"])).encrypt(self.prekey)
            self.tls_secret = derive_tls_secret(self.random1, self.random2, self.prekey)
            self.enc.set_tls_secret(self.tls_secret)
            return FakeRequester(
                FakeResponse(json.dumps({"random1": self.random1, "prekey": sealed.hex()}))
            )
        if uri.endswith("/sys/dev/control"):
            self.control_payloads.append(message.payload.decode())
            result = self.control_results.pop(0) if self.control_results else "success"
            return FakeRequester(FakeResponse(json.dumps({"status": result})))
        raise AssertionError(f"unexpected uri {uri}")


class FakeContext:
    def __init__(self, device: FakeDevice) -> None:
        self._device = device
        self.shutdown_calls = 0

    def request(self, message: Any) -> FakeRequester:
        return self._device.request(message)

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.fixture
def device() -> FakeDevice:
    return FakeDevice()


@pytest.fixture
def context(device: FakeDevice) -> FakeContext:
    return FakeContext(device)


async def _make_client(context: FakeContext, **kwargs: Any) -> Client:
    with patch(
        "custom_components.philips_airpurifier_coap.aioairctrl.coap.client.Context.create_client_context",
        AsyncMock(return_value=context),
    ):
        return await Client.create("192.0.2.10", **kwargs)


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        (None, False),
        ("", False),
        ("not-a-number", False),
        (0, False),
        (64, True),  # bit 6
        ("64", True),
        (63, False),
        (65, True),
    ],
)
def test_is_tls_option(option: Any, expected: bool) -> None:
    """Only bit 6 of the discovery option advertises TLS."""
    assert is_tls_option(option) is expected


async def test_create_syncs_and_reads_status(device: FakeDevice, context: FakeContext) -> None:
    """A fresh client syncs, then decrypts the device status."""
    client = await _make_client(context)

    assert device.sync_count == 1
    status, max_age = await client.get_status()
    assert status == STATUS["state"]["reported"]
    assert max_age == 60  # default when the device sends no max-age


async def test_get_status_uses_device_max_age(device: FakeDevice, context: FakeContext) -> None:
    """The device's own max-age wins over the default."""
    device.status_max_age = 15
    client = await _make_client(context)

    assert (await client.get_status())[1] == 15


async def test_get_status_rejects_stale_first_packet(
    device: FakeDevice, context: FakeContext
) -> None:
    """A first status outside the freshness window is an error, not a silent drop."""
    client = await _make_client(context)
    # Push the client's reference far ahead of what the device will send.
    client._enc._last_seen_id = 1_000_000

    with pytest.raises(StaleStatusError):
        await client.get_status()


async def test_observe_status_yields_and_cancels(device: FakeDevice, context: FakeContext) -> None:
    """Every pushed status is yielded, and the observation is cancelled at the end."""

    class LiveObservation(FakeObservation):
        """Seals each push on demand, so ids keep advancing like a real device."""

        def __init__(self, count: int) -> None:
            super().__init__([])
            self._left = count

        def __aiter__(self) -> LiveObservation:
            return self

        async def __anext__(self) -> FakeResponse:
            if self._left == 0:
                raise StopAsyncIteration
            self._left -= 1
            return FakeResponse(device.seal(STATUS))

    observation = LiveObservation(2)
    device.observation = observation
    client = await _make_client(context)

    seen = [status async for status in client.observe_status()]

    assert seen == [STATUS["state"]["reported"]] * 3  # first response + two pushes
    assert observation.cancelled is True


async def test_observe_status_drops_stale_packets(device: FakeDevice, context: FakeContext) -> None:
    """A replayed packet is skipped instead of ending the stream."""
    client = await _make_client(context)
    sealed = device.seal(STATUS)
    # Re-sending an id far behind the reference is a replay.
    device.observation = FakeObservation([FakeResponse(sealed)])
    client._enc._last_seen_id = 500

    device.enc.set_client_key("00000001")
    seen = [status async for status in client.observe_status()]

    assert seen == []


async def test_observe_status_without_observation(device: FakeDevice, context: FakeContext) -> None:
    """A device that refuses to register an observation still yields its status."""
    device.observation = None
    client = await _make_client(context)

    assert [s async for s in client.observe_status()] == [STATUS["state"]["reported"]]


async def test_set_control_value_success(device: FakeDevice, context: FakeContext) -> None:
    """A successful command sends the desired state once."""
    client = await _make_client(context)

    assert await client.set_control_value("pwr", "1") is True
    assert len(device.control_payloads) == 1


async def test_set_control_values_resyncs_once_then_retries(
    device: FakeDevice, context: FakeContext
) -> None:
    """The first failure triggers a re-sync, later ones only retry."""
    device.control_results = ["failed", "failed", "success"]
    client = await _make_client(context)

    assert await client.set_control_values({"pwr": "1"}) is True
    assert device.sync_count == 2  # initial sync plus one re-sync
    assert len(device.control_payloads) == 3


async def test_set_control_values_gives_up(device: FakeDevice, context: FakeContext) -> None:
    """After exhausting its retries the command reports failure."""
    device.control_results = ["failed"] * 5
    client = await _make_client(context)

    assert await client.set_control_values({"pwr": "1"}, retry_count=2, resync=False) is False
    assert device.sync_count == 1  # resync disabled
    assert len(device.control_payloads) == 3  # initial attempt plus two retries


async def test_shutdown_closes_the_context(context: FakeContext) -> None:
    """Shutting the client down releases the aiocoap context."""
    client = await _make_client(context)
    await client.shutdown()

    assert context.shutdown_calls == 1


async def test_shutdown_without_context_is_safe() -> None:
    """A client that never connected can still be shut down."""
    await Client("192.0.2.10").shutdown()


async def test_uninitialised_client_raises() -> None:
    """Using the constructor instead of create() is a programming error."""
    client = Client("192.0.2.10")
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = client._ctx
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = client._enc


async def test_init_failure_closes_the_context(context: FakeContext) -> None:
    """A handshake that blows up must not leak the aiocoap context."""
    with (
        patch(
            "custom_components.philips_airpurifier_coap.aioairctrl.coap.client.Context.create_client_context",
            AsyncMock(return_value=context),
        ),
        patch.object(Client, "_sync", side_effect=OSError("boom")),
        pytest.raises(OSError, match="boom"),
    ):
        await Client.create("192.0.2.10")

    assert context.shutdown_calls == 1


async def test_tls_handshake_negotiates_a_shared_secret(
    device: FakeDevice, context: FakeContext
) -> None:
    """A TLS-capable device runs the key exchange before syncing."""
    client = await _make_client(context, option=64)

    assert client._enc.tls_active is True
    assert client._enc._tls_secret == device.tls_secret
    # The GCM-sealed status opens with the negotiated secret.
    assert (await client.get_status())[0] == STATUS["state"]["reported"]
