"""Encryption used by the Philips air purifier CoAP protocol.

Wire format for an encrypted payload (all hex-encoded, uppercase ASCII):

    [client_key: 8 chars][ciphertext: variable][sha256_digest: 64 chars]

The client_key embedded in the payload is a 4-byte big-endian counter
(incremented before each encrypt call) expressed as 8 hex characters.

Key derivation (plain devices): MD5("JiangPan" + client_key), split into two
equal halves. The first half becomes the AES-128 key, the second half the CBC IV.

TLS-capable devices (discovery option bit 6 set) instead run a key exchange on
/sys/dev/info/tls: the client posts an RSA-1024 public key plus a random, the
device answers with random1 and an RSA-encrypted prekey, and both sides derive
a 16-char secret as SHA256(random1 + random2 + prekey_int, little-endian int).
With that secret the payload is sealed with AES-GCM (the derived AES key is
also used as AAD) instead of AES-CBC. Reverse-engineered from the Philips
Air+ app (com.gaoda.util.TSLKeyPairGenerator / defpackage.v80).
"""

import hashlib
import struct
from typing import Any

from Cryptodome.Cipher import AES, PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from Cryptodome.Util.Padding import pad, unpad


class DigestMismatchException(Exception):
    pass


class StaleMessageException(Exception):
    """Raised when incoming message ids keep falling outside the freshness window."""


# The device wraps its message counter at 2e9 (defpackage.DigitalTrans) and the
# app accepts ids from the last seen one up to +10 (zd.l).
COAP_MESSAGE_ID_MAX = 2000000000
FRESHNESS_WINDOW = 10

# Consecutive rejects tolerated before the stream is declared desynchronised.
# A device that reboots restarts its counter far below the last id we saw, so
# every later packet would be rejected forever; the app handles this by marking
# the device offline and re-running the key exchange. Raising here lets the
# coordinator reconnect (and therefore re-sync) in seconds instead of waiting
# for its missed-update watchdog.
MAX_CONSECUTIVE_STALE = 3


class EncryptionContext:
    # Protocol-defined secret mixed into every plain-mode key derivation.
    SECRET_KEY = "JiangPan"  # nosec B105

    def __init__(self) -> None:
        # Hex-encoded 4-byte counter, e.g. "00A3F1C2". None until set_client_key is called.
        self._client_key: str | None = None
        # 16-char secret established by the TLS key exchange; None in plain mode.
        self._tls_secret: str | None = None
        # Last incoming message id (int) accepted for freshness checking.
        self._last_seen_id: int | None = None
        # Consecutive freshness rejects, reset by any accepted message.
        self._stale_streak: int = 0

    def set_client_key(self, client_key: str) -> None:
        self._client_key = client_key

    @property
    def tls_active(self) -> bool:
        return self._tls_secret is not None

    def set_tls_secret(self, secret: str) -> None:
        """Activate GCM mode with the negotiated 16-char secret."""
        self._tls_secret = secret.upper()

    def _increment_client_key(self) -> str:
        if self._client_key is None:
            raise ValueError("Client key must be set before incrementing")
        # Wrap around at 0xFFFFFFFF so the counter stays within 4 bytes.
        next_int = (int(self._client_key, 16) + 1) % 0x100000000
        client_key_next = next_int.to_bytes(4, byteorder="big").hex().upper()
        self._client_key = client_key_next
        return client_key_next

    def _derive_key_and_iv(self, key: str) -> tuple[str, str]:
        """Split the MD5(key material) digest into AES key and IV halves."""
        if self.tls_active:
            # TLS mode mixes the raw bytes of the negotiated secret (hex-decoded)
            # with the ASCII message id; everything stays uppercase afterwards.
            assert self._tls_secret is not None  # nosec B101 - implied by tls_active
            digest = hashlib.md5(bytes.fromhex(self._tls_secret) + key.encode()).hexdigest().upper()  # nosec B324
        else:
            digest = hashlib.md5((self.SECRET_KEY + key).encode()).hexdigest().upper()  # nosec B324
        half = len(digest) // 2
        return digest[:half], digest[half:]

    def _create_cipher(self, key: str) -> Any:
        secret_key, iv = self._derive_key_and_iv(key)
        if self.tls_active:
            # In GCM mode the derived key doubles as AAD.
            cipher = AES.new(key=secret_key.encode(), mode=AES.MODE_GCM, nonce=iv[:12].encode())
            cipher.update(secret_key.encode())
            return cipher
        return AES.new(
            key=secret_key.encode(),
            mode=AES.MODE_CBC,
            iv=iv.encode(),
        )

    def encrypt(self, payload: str) -> str:
        # Increment first so the key embedded in the output is always ahead of
        # the last key seen by the device, preventing replay of old counters.
        key = self._increment_client_key()
        cipher = self._create_cipher(key)
        plaintext = payload.encode()
        ciphertext: str
        if self.tls_active:
            # AES.new(...).update(aad) sets AAD before sealing; the tag is
            # appended to the ciphertext by digest().
            ciphertext_bytes, tag = cipher.encrypt_and_digest(plaintext)
            ciphertext = (ciphertext_bytes + tag).hex().upper()
        else:
            ciphertext = cipher.encrypt(pad(plaintext, 16, style="pkcs7")).hex().upper()
        # Integrity check: SHA-256 over (key + ciphertext) appended at the end.
        digest = hashlib.sha256((key + ciphertext).encode()).hexdigest().upper()
        return key + ciphertext + digest

    def decrypt(self, payload_encrypted: str) -> str | None:
        """Decrypt an incoming envelope.

        Returns None when the message id fails the freshness check — the app
        silently drops such packets instead of treating them as errors. Raises
        DigestMismatchException when the integrity hash does not match.
        """
        # Parse the fixed-width envelope: 8-char key, 64-char digest at the tail.
        key = payload_encrypted[0:8]
        ciphertext = payload_encrypted[8:-64]
        digest = payload_encrypted[-64:]
        digest_calculated = hashlib.sha256((key + ciphertext).encode()).hexdigest().upper()
        if digest != digest_calculated:
            raise DigestMismatchException
        message_id = int(key, 16)
        if not self._is_fresh(message_id):
            return None
        secret_key, iv = self._derive_key_and_iv(key)
        raw = bytes.fromhex(ciphertext)
        cipher: Any
        plaintext_unpadded: bytes
        if self.tls_active:
            # The trailing 16 bytes of the sealed blob are the GCM tag.
            cipher = AES.new(key=secret_key.encode(), mode=AES.MODE_GCM, nonce=iv[:12].encode())
            cipher.update(secret_key.encode())
            plaintext_unpadded = cipher.decrypt_and_verify(raw[:-16], raw[-16:])
        else:
            cipher = AES.new(key=secret_key.encode(), mode=AES.MODE_CBC, iv=iv.encode())
            plaintext_unpadded = unpad(cipher.decrypt(raw), 16, style="pkcs7")
        return plaintext_unpadded.decode()

    def _is_fresh(self, message_id: int) -> bool:
        """Accept ids from the last seen one up to +FRESHNESS_WINDOW (mod 2e9).

        The app accepts an id equal to the last one it saw: a device answering
        a fresh request with its current counter, or a duplicated UDP datagram,
        is not a replay. Only ids that fall behind, or jump too far ahead, are
        rejected.

        Raises StaleMessageException once MAX_CONSECUTIVE_STALE ids in a row
        have been rejected, which means the two counters no longer agree and
        only a re-sync can recover.
        """
        last = self._last_seen_id
        if last is None or message_id >= COAP_MESSAGE_ID_MAX:
            self._last_seen_id = message_id
            self._stale_streak = 0
            return True

        delta = (message_id - last) % COAP_MESSAGE_ID_MAX
        if delta <= FRESHNESS_WINDOW:
            self._last_seen_id = message_id
            self._stale_streak = 0
            return True

        # Keep the last accepted id: adopting a rejected one would silently
        # resynchronise on a replayed packet.
        self._stale_streak += 1
        if self._stale_streak >= MAX_CONSECUTIVE_STALE:
            raise StaleMessageException(
                f"{self._stale_streak} consecutive stale message ids "
                f"(last accepted {last}, received {message_id})"
            )
        return False


def derive_tls_secret(random1: int, random2: int, prekey_plaintext: bytes) -> str:
    """Derive the 16-char secret from the /sys/dev/info/tls exchange.

    The device sends `prekey`, RSA-encrypted with our public key. Its reversed
    byte content, read little-endian, is added to both randoms; the SHA-256 of
    that sum as a little-endian 32-bit int yields the secret (first 16 hex
    characters, uppercase).
    """
    prekey_int = int.from_bytes(prekey_plaintext, "little")
    total = (random1 + random2 + prekey_int) & 0xFFFFFFFF
    return hashlib.sha256(struct.pack("<I", total)).hexdigest().upper()[:16]


def generate_rsa_keypair() -> tuple[str, RSA.RsaKey]:
    """Generate the RSA-1024 keypair used for the TLS handshake.

    Returns (PEM public key matching the app's X.509 SubjectPublicKeyInfo
    format, private key object).
    """
    private = RSA.generate(1024)  # nosec B505
    pem = private.publickey().export_key(format="PEM").decode()
    return pem, private


def decrypt_prekey(private_key: RSA.RsaKey, prekey_hex: str) -> bytes:
    """Decrypt the device's prekey blob with RSA/ECB/PKCS1Padding."""
    sentinel = b"\x00" * 8
    return PKCS1_v1_5.new(private_key).decrypt(bytes.fromhex(prekey_hex), sentinel)
