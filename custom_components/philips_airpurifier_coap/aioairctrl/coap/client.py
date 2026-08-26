"""CoAP client for Philips air purifiers."""

import json
import logging
import os
import random

from aiocoap import (
    NON,
    Context,
    Message,
)
from aiocoap.numbers.codes import (
    GET,
    POST,
)

from .encryption import (
    EncryptionContext,
    decrypt_prekey,
    derive_tls_secret,
    generate_rsa_keypair,
)

logger = logging.getLogger(__name__)

TLS_PATH = "/sys/dev/info/tls"


class StaleStatusError(ConnectionError):
    """Raised when the first status packet fails the freshness check."""


def is_tls_option(option: int | str | None) -> bool:
    """Return True when the discovery "option" field advertises TLS (bit 6)."""
    if option is None or option == "":
        return False
    try:
        value = int(option)
    except (TypeError, ValueError):
        return False
    return ((value >> 6) & 1) == 1


class Client:
    STATUS_PATH = "/sys/dev/status"
    CONTROL_PATH = "/sys/dev/control"
    SYNC_PATH = "/sys/dev/sync"

    def __init__(self, host, port=5683, option=None):
        self.host = host
        self.port = port
        self._option = option
        # Both are set together in _init; kept as None so shutdown() is safe to
        # call even if _init never completed.
        self._client_context: Context | None = None
        self._encryption_context: EncryptionContext | None = None

    @property
    def _tls(self) -> bool:
        return is_tls_option(self._option)

    @property
    def _ctx(self) -> Context:
        if self._client_context is None:
            raise RuntimeError("Client not initialized; use Client.create()")
        return self._client_context

    @property
    def _enc(self) -> EncryptionContext:
        if self._encryption_context is None:
            raise RuntimeError("Client not initialized; use Client.create()")
        return self._encryption_context

    async def _init(self):
        self._client_context = await Context.create_client_context(transports=["simple6"])
        self._encryption_context = EncryptionContext()
        try:
            if self._tls:
                await self._tls_handshake()
            await self._sync()
        except BaseException:
            # Ensure the aiocoap context is always cleaned up, even on
            # cancellation (asyncio.CancelledError is a BaseException).
            await self._client_context.shutdown()
            raise

    async def _tls_handshake(self):
        """Negotiate the session secret with a TLS-capable device.

        Mirrors the app's flow on /sys/dev/info/tls: we post an RSA-1024
        public key plus random2; the device answers with random1 and an
        RSA-encrypted prekey. Both sides derive the same secret from the sum.
        """
        logger.debug("running TLS key exchange with %s", self.host)
        pem, private_key = generate_rsa_keypair()
        random2 = random.randint(1000, 9999)  # nosec B311  # nosec B311
        payload = json.dumps({"type": "config_encrypt", "random2": random2, "pk": pem})
        request = Message(
            code=POST,
            mtype=NON,
            uri=f"coap://{self.host}:{self.port}{TLS_PATH}",
            payload=payload.encode(),
        )
        request.opt.content_format = 50  # application/json
        response = await self._ctx.request(request).response
        data = json.loads(response.payload.decode())
        prekey_plaintext = decrypt_prekey(private_key, data["prekey"])
        secret = derive_tls_secret(int(data["random1"]), random2, prekey_plaintext)
        logger.debug("TLS secret negotiated")
        self._enc.set_tls_secret(secret)

    @classmethod
    async def create(cls, *args, **kwargs):
        """Async factory — use instead of the constructor."""
        obj = cls(*args, **kwargs)
        await obj._init()
        return obj

    async def shutdown(self) -> None:
        if self._client_context:
            await self._client_context.shutdown()

    async def _sync(self):
        """Exchange a nonce with the device to obtain the initial client key.

        The client sends a random 4-byte hex string; the device responds with
        the client key that must be used for all subsequent encrypted messages.
        """
        logger.debug("syncing")
        sync_request = os.urandom(4).hex().upper()
        request = Message(
            code=POST,
            mtype=NON,
            uri=f"coap://{self.host}:{self.port}{self.SYNC_PATH}",
            payload=sync_request.encode(),
        )
        response = await self._ctx.request(request).response
        client_key = response.payload.decode()
        logger.debug("synced: %s", client_key)
        self._enc.set_client_key(client_key)

    async def get_status(self):
        """Return (state_reported, max_age) for the current device status."""
        logger.debug("retrieving status")
        request = Message(
            code=GET,
            mtype=NON,
            uri=f"coap://{self.host}:{self.port}{self.STATUS_PATH}",
        )
        # observe=0 registers a CoAP observation; the first response carries
        # the current state, which is all we consume here.
        request.opt.observe = 0
        response = await self._ctx.request(request).response
        payload_encrypted = response.payload.decode()
        payload = self._enc.decrypt(payload_encrypted)
        if payload is None:
            raise StaleStatusError("initial status dropped by freshness check")
        logger.debug("status: %s", payload)
        state_reported = json.loads(payload)
        max_age = 60
        if response.opt.max_age is not None:
            max_age = response.opt.max_age
            logger.debug("max age = %s", max_age)
        return state_reported["state"]["reported"], max_age

    async def observe_status(self):
        """Async generator that yields state_reported dicts as the device pushes updates."""

        def decrypt_status(response):
            payload_encrypted = response.payload.decode()
            payload = self._enc.decrypt(payload_encrypted)
            if payload is None:
                # Replay-window reject: silently drop, like the official app.
                logger.debug("dropped stale status packet")
                return None
            logger.debug("observation status: %s", payload)
            return json.loads(payload)["state"]["reported"]

        logger.debug("observing status")
        request = Message(
            code=GET,
            mtype=NON,
            uri=f"coap://{self.host}:{self.port}{self.STATUS_PATH}",
        )
        request.opt.observe = 0
        requester = self._ctx.request(request)
        observation = requester.observation
        try:
            response = await requester.response
            first = decrypt_status(response)
            if first is not None:
                yield first
            if observation is not None:
                async for response in observation:
                    status = decrypt_status(response)
                    if status is not None:
                        yield status
        finally:
            # Cancel the observation when the caller stops iterating, so the
            # device stops sending notifications and aiocoap frees its resources.
            if observation is not None:
                observation.cancel()

    async def set_control_value(self, key, value, retry_count=5, resync=True) -> bool:
        return await self.set_control_values(
            data={key: value}, retry_count=retry_count, resync=resync
        )

    async def set_control_values(self, data: dict, retry_count=5, resync=True) -> bool:
        """Send a control command to the device, retrying on failure.

        On the first failure, if resync=True, the client re-syncs the
        encryption key before retrying. Subsequent failures retry without
        re-syncing (stale key is unlikely to be the cause after one resync).
        """
        state_desired = {
            "state": {
                "desired": {
                    "CommandType": "app",
                    "DeviceId": "",
                    "EnduserId": "",
                    **data,
                }
            }
        }
        payload = json.dumps(state_desired)
        logger.debug("REQUEST: %s", payload)
        for attempt in range(retry_count + 1):
            payload_encrypted = self._enc.encrypt(payload)
            request = Message(
                code=POST,
                mtype=NON,
                uri=f"coap://{self.host}:{self.port}{self.CONTROL_PATH}",
                payload=payload_encrypted.encode(),
            )
            response = await self._ctx.request(request).response
            logger.debug("RESPONSE: %s", response.payload)
            result = json.loads(response.payload)
            if result.get("status") == "success":
                return True
            if attempt == 0 and resync:
                logger.debug("set_control_value failed, resyncing...")
                await self._sync()
            else:
                logger.debug(
                    "set_control_value failed, retrying (attempt %d/%d)...",
                    attempt + 1,
                    retry_count,
                )
        logger.error("set_control_value failed: %s", data)
        return False
