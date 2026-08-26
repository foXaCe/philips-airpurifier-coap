"""Tests for the CoAP payload encryption and its message freshness rules.

The freshness window is the integration's replay protection. Getting it wrong
in either direction is costly: too strict and legitimate updates are dropped
until the watchdog reconnects, too lax and a replayed packet resynchronises the
counter. These tests pin the accepted range against the behaviour of the
official app.
"""

from __future__ import annotations

from Cryptodome.Cipher import PKCS1_v1_5
from Cryptodome.PublicKey import RSA
import pytest

from custom_components.philips_airpurifier_coap.aioairctrl.coap.encryption import (
    COAP_MESSAGE_ID_MAX,
    FRESHNESS_WINDOW,
    MAX_CONSECUTIVE_STALE,
    DigestMismatchException,
    EncryptionContext,
    StaleMessageException,
    decrypt_prekey,
    derive_tls_secret,
    generate_rsa_keypair,
)


def _context(client_key: str = "00000010") -> EncryptionContext:
    context = EncryptionContext()
    context.set_client_key(client_key)
    return context


def test_encrypt_decrypt_roundtrip() -> None:
    """A payload survives a full encrypt/decrypt cycle."""
    sender = _context()
    receiver = _context()
    envelope = sender.encrypt('{"state": 1}')

    # The envelope is the 8-char counter, the ciphertext, then a 64-char digest.
    assert envelope[:8] == "00000011"  # incremented before use
    assert len(envelope) > 8 + 64
    assert receiver.decrypt(envelope) == '{"state": 1}'


def test_decrypt_rejects_tampered_payload() -> None:
    """A digest that does not match the body is refused."""
    envelope = _context().encrypt("payload")
    tampered = envelope[:-1] + ("0" if envelope[-1] != "0" else "1")
    with pytest.raises(DigestMismatchException):
        _context().decrypt(tampered)


def test_client_key_wraps_at_four_bytes() -> None:
    """The counter stays inside four bytes."""
    context = _context("FFFFFFFF")
    assert context.encrypt("x")[:8] == "00000000"


@pytest.mark.parametrize(
    ("delta", "accepted"),
    [
        (0, True),  # the app accepts a repeat of the last id
        (1, True),
        (FRESHNESS_WINDOW, True),
        (FRESHNESS_WINDOW + 1, False),
        (-1, False),  # an id falling behind is a replay
    ],
)
def test_freshness_window_bounds(delta: int, accepted: bool) -> None:
    """Ids are accepted from the last seen one up to the window size."""
    context = EncryptionContext()
    context._last_seen_id = 1000

    assert context._is_fresh(1000 + delta) is accepted


def test_freshness_keeps_last_accepted_id_on_reject() -> None:
    """A rejected id must not become the new reference."""
    context = EncryptionContext()
    context._last_seen_id = 1000

    assert context._is_fresh(500) is False
    assert context._last_seen_id == 1000
    # The legitimate next id is still accepted.
    assert context._is_fresh(1001) is True


def test_freshness_window_wraps_around_the_counter() -> None:
    """The window spans the counter wrap at 2e9."""
    context = EncryptionContext()
    context._last_seen_id = COAP_MESSAGE_ID_MAX - 2

    assert context._is_fresh(3) is True


def test_first_message_is_always_accepted() -> None:
    """With no reference id yet, anything is fresh."""
    assert EncryptionContext()._is_fresh(123456) is True


def test_repeated_stale_ids_raise() -> None:
    """A restarted device counter is reported instead of silently dropped."""
    context = EncryptionContext()
    context._last_seen_id = 1_000_000

    for _ in range(MAX_CONSECUTIVE_STALE - 1):
        assert context._is_fresh(1) is False

    with pytest.raises(StaleMessageException):
        context._is_fresh(1)


def test_accepted_message_resets_the_stale_streak() -> None:
    """One good packet clears the desynchronisation counter."""
    context = EncryptionContext()
    context._last_seen_id = 1_000_000

    assert context._is_fresh(1) is False
    assert context._is_fresh(1_000_001) is True

    # The streak restarts from zero, so a single reject does not raise.
    for _ in range(MAX_CONSECUTIVE_STALE - 1):
        assert context._is_fresh(1) is False


def test_decrypt_returns_none_for_stale_message() -> None:
    """A stale envelope decrypts to None rather than raising."""
    sender = _context("00000FFF")
    receiver = _context()
    receiver._last_seen_id = 1_000_000

    assert receiver.decrypt(sender.encrypt("payload")) is None


def test_tls_mode_roundtrip() -> None:
    """GCM mode seals and opens a payload with the negotiated secret."""
    secret = "0123456789ABCDEF"
    sender, receiver = _context(), _context()
    sender.set_tls_secret(secret)
    receiver.set_tls_secret(secret)

    assert sender.tls_active is True
    assert receiver.decrypt(sender.encrypt('{"state": 2}')) == '{"state": 2}'


def test_increment_requires_a_client_key() -> None:
    """Encrypting before the sync handshake is a programming error."""
    with pytest.raises(ValueError, match="Client key"):
        EncryptionContext().encrypt("payload")


def test_tls_handshake_helpers_round_trip() -> None:
    """The prekey survives the RSA exchange and both sides derive one secret."""
    pem, private_key = generate_rsa_keypair()
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")

    # Play the device's part: seal a prekey with the public key we published.
    prekey = b"\x01\x02\x03\x04"
    sealed = PKCS1_v1_5.new(RSA.import_key(pem)).encrypt(prekey)

    assert decrypt_prekey(private_key, sealed.hex()) == prekey

    secret = derive_tls_secret(1234, 5678, prekey)
    assert len(secret) == 16
    assert secret == secret.upper()
    # Both sides run the same derivation over the same inputs.
    assert derive_tls_secret(1234, 5678, prekey) == secret
