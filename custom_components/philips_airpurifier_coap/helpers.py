"""Helper functions for Philips air purifier status."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import struct
import time
from typing import Any, cast

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

from .aioairctrl import CoAPClient
from .const import PhilipsApi

_LOGGER = logging.getLogger(__name__)

# Logger name of the vendored aioairctrl package (see aioairctrl/VENDORED.md).
VENDORED_LOGGER = __package__ + ".aioairctrl"

# Multicast discovery parameters reverse-engineered from the Philips Air+ app:
# devices listen on CoAP port 5683 in group 224.0.1.187 and answer a CoAP GET
# on /sys/dev/info (legacy) or /sys/dev/info/encryption (encrypted models).
DISCOVERY_GROUP = "224.0.1.187"
DISCOVERY_PORT = 5683
DISCOVERY_INFO_PATH = ("sys", "dev", "info")
DISCOVERY_ENCRYPTED_PATH = ("sys", "dev", "info", "encryption")
# Default shared secret used to derive the AES key/IV that protect the
# "didt" field of encrypted discovery responses.
DISCOVERY_SECRET = "JiangPan"  # nosec B105  # nosec B105


def extract_name(status: dict[str, Any]) -> str:
    """Extract the name from the status."""
    for name_key in [PhilipsApi.NAME, PhilipsApi.NEW_NAME, PhilipsApi.NEW2_NAME]:
        name = status.get(name_key)
        if name:
            return cast(str, name)
    return ""


def extract_model(status: dict[str, Any]) -> str:
    """Extract the model from the status."""
    for model_key in [
        PhilipsApi.MODEL_ID,
        PhilipsApi.NEW_MODEL_ID,
        PhilipsApi.NEW2_MODEL_ID,
    ]:
        model = status.get(model_key)
        if model:
            return cast(str, model[:9])
    return ""


def get_local_ip() -> str | None:
    """Get the local IP address of this machine."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
        sock.close()
        return cast(str, local_ip)
    except Exception:
        return None


def get_active_ips_from_arp() -> list[str]:
    """Get list of active IPs from ARP table."""
    active_ips = []
    try:
        with open("/proc/net/arp") as f:
            lines = f.readlines()[1:]  # Skip header
            for line in lines:
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "0x2":  # Valid entry
                    active_ips.append(parts[0])
    except Exception as ex:
        _LOGGER.debug("Could not read ARP table: %s", ex)
    return active_ips


async def ping_sweep(network_prefix: str) -> None:
    """Send UDP probes across the subnet to populate the ARP table."""
    _LOGGER.debug("Ping sweep on %s.0/24 to discover active hosts", network_prefix)

    async def probe(ip: str, port: int) -> None:
        """Send a single UDP packet to trigger an ARP entry."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            sock.sendto(b"\x00", (ip, port))
            sock.close()
        except OSError:
            pass

    # Send UDP packets to common ports to trigger ARP resolution.
    tasks = []
    for i in range(1, 255):
        ip = f"{network_prefix}.{i}"
        tasks.append(probe(ip, 5683))  # CoAP
        tasks.append(probe(ip, 80))  # HTTP

    await asyncio.gather(*tasks)
    await asyncio.sleep(1)  # Wait for ARP responses


def _build_coap_get(path: tuple[str, ...], message_id: int, token: bytes = b"") -> bytes:
    """Build a minimal non-confirmable CoAP GET request for a URI path."""
    # Header: version 1, type NON (1), token length, code 0.01 (GET), message id
    header = struct.pack("!BBH", 0x50 | len(token), 0x01, message_id)
    options = b""
    last_option = 0
    for segment in path:
        delta = 11 - last_option  # Uri-Path option number is 11
        last_option = 11
        encoded = segment.encode()
        assert delta <= 12 and len(encoded) <= 12
        options += struct.pack("!B", (delta << 4) | len(encoded)) + encoded
    return header + token + options


def decrypt_didt(didt: str, local_ip: str) -> tuple[str, str] | None:
    """Decrypt the encrypted discovery payload ("didt").

    Encrypted devices answer the multicast probe with an AES-CBC blob holding
    "deviceId&deviceToken". The key and IV are the two halves of the uppercase
    hex MD5 of the shared secret concatenated with our local IP address.
    """
    digest = hashlib.md5((DISCOVERY_SECRET + local_ip).encode()).hexdigest().upper()  # nosec B324  # nosec B324
    half = len(digest) // 2
    key, iv = digest[:half], digest[half:]
    try:
        cipher = AES.new(key=key.encode(), mode=AES.MODE_CBC, iv=iv.encode())
        plain = unpad(cipher.decrypt(bytes.fromhex(didt)), 16, style="pkcs7")
        device_id, _, device_token = plain.decode().partition("&")
    except (ValueError, KeyError):  # noqa: BLE001
        return None
    if not device_id:
        return None
    return device_id, device_token


def _extract_payload(data: bytes) -> dict[str, Any] | None:
    """Extract the JSON payload from a raw CoAP response datagram."""
    raw = data[4:]
    marker = raw.find(b"\xff")
    if marker != -1:
        raw = raw[marker + 1 :]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_discovery_reply(
    data: bytes,
    ip: str,
    local_ip: str | None,
) -> dict[str, Any] | None:
    """Turn one discovery reply into a candidate entry, or None if unusable."""
    payload = _extract_payload(data)
    if not isinstance(payload, dict):
        return None
    didt = payload.get("didt")
    if didt and local_ip:
        decrypted = decrypt_didt(str(didt), local_ip)
        if decrypted:
            payload["device_id"], payload["device_token"] = decrypted
        else:
            _LOGGER.debug("Could not decrypt discovery reply from %s", ip)
            return None
    elif not payload.get("device_id"):
        return None
    _LOGGER.debug("CoAP discovery reply from %s: %s", ip, payload)
    return {
        "ip": ip,
        "device_id": payload.get("device_id"),
        "option": payload.get("option", ""),
    }


async def coap_discovery(timeout: float = 3.0) -> list[dict[str, Any]]:
    """Discover Philips devices via CoAP multicast, as the official app does.

    Sends CoAP GET requests to the 224.0.1.187 group on port 5683 and collects
    the unicast JSON replies. This is dramatically cheaper than probing every
    candidate IP with a full CoAP client handshake.

    Returns a list of dicts with 'ip', 'device_id' and 'option' keys.
    """
    loop = asyncio.get_running_loop()
    local_ip = await loop.run_in_executor(None, get_local_ip)
    responses: dict[str, dict[str, Any]] = {}

    def _discover() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.25)
        try:
            sock.bind(("", 0))
            paths = (DISCOVERY_INFO_PATH, DISCOVERY_ENCRYPTED_PATH)
            start = time.monotonic()
            deadline = start + timeout
            # Re-emit the probe every second: the first multicast burst can be
            # swallowed by IGMP snooping on some switches.
            next_send = 0.0
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_send:
                    for path in paths:
                        request = _build_coap_get(path, message_id=0x1234)
                        sock.sendto(request, (DISCOVERY_GROUP, DISCOVERY_PORT))
                    next_send = now + 1.0
                try:
                    data, addr = sock.recvfrom(2048)
                except TimeoutError:  # noqa: PERF203
                    continue
                ip = addr[0]
                if ip in responses or not data:
                    continue
                parsed = _parse_discovery_reply(data, ip, local_ip)
                if parsed:
                    responses[ip] = parsed
        finally:
            sock.close()

    await loop.run_in_executor(None, _discover)
    _LOGGER.info("CoAP multicast discovery found %d device(s)", len(responses))
    return list(responses.values())


async def _check_single_ip(
    ip: str,
    semaphore: asyncio.Semaphore,
    timeout: float,
) -> dict[str, Any] | None:
    """Check a single IP for a Philips device."""
    async with semaphore:
        client = None
        try:
            # Quick connection timeout - CoAP devices respond fast
            client = await asyncio.wait_for(CoAPClient.create(ip), timeout=3)
            status, _ = await asyncio.wait_for(client.get_status(), timeout=timeout)
            if status:
                model = extract_model(status)
                name = extract_name(status)
                _LOGGER.info("Found Philips device at %s: %s %s", ip, model, name)
                return {"ip": ip, "model": model, "name": name, "status": status}
        except TimeoutError:
            pass  # Expected for non-Philips devices
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled checking %s", ip)
        except Exception:  # noqa: S110
            pass  # Silently ignore non-Philips devices
        finally:
            if client:
                try:
                    await asyncio.wait_for(client.shutdown(), timeout=1)
                except Exception:  # noqa: S110
                    pass  # Best effort shutdown
        return None


async def scan_for_devices(timeout: float = 8.0) -> list[dict[str, Any]]:
    """Scan the local network for Philips air purifiers.

    Optimized scan strategy:
    1. CoAP multicast discovery (single round-trip, as the official app does)
    2. If nothing answered, fall back to ARP-table IPs, then the DHCP range

    Returns a list of dicts with 'ip', 'model', 'name' keys.
    """
    # Suppress noisy CoAP logs during scan
    logging.getLogger("coap").setLevel(logging.ERROR)
    logging.getLogger(VENDORED_LOGGER).setLevel(logging.WARNING)

    loop = asyncio.get_running_loop()
    semaphore = asyncio.Semaphore(50)  # High parallelism for speed
    found_devices: list[dict[str, Any]] = []

    # Step 1: multicast discovery, then full status only for discovered IPs
    try:
        candidates = await asyncio.wait_for(coap_discovery(), timeout=timeout)
    except TimeoutError:
        candidates = []
    candidate_ips = [c["ip"] for c in candidates]
    if candidate_ips:
        _LOGGER.info("Fast scan: checking %d CoAP-discovered IP(s)...", len(candidate_ips))
        tasks = [_check_single_ip(ip, semaphore, timeout) for ip in candidate_ips]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        found_devices = [r for r in results if isinstance(r, dict)]

    if not found_devices:
        local_ip = await loop.run_in_executor(None, get_local_ip)
        if not local_ip:
            _LOGGER.warning("Could not determine local IP address")
            return []

        network_prefix = ".".join(local_ip.split(".")[:3])

        # Step 2: Quick ping sweep to populate ARP table
        await ping_sweep(network_prefix)

        arp_ips = await loop.run_in_executor(None, get_active_ips_from_arp)
        arp_ips = [ip for ip in arp_ips if ip.startswith(network_prefix + ".")]

        if arp_ips:
            _LOGGER.info("Fallback scan: checking %d IPs from ARP table...", len(arp_ips))
            tasks = [_check_single_ip(ip, semaphore, timeout) for ip in arp_ips]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            found_devices = [r for r in results if isinstance(r, dict)]

        # Step 3: If nothing found, scan common DHCP range as last resort
        if not found_devices:
            common_ips = [f"{network_prefix}.{i}" for i in range(1, 101)]
            # Exclude already scanned IPs
            common_ips = [ip for ip in common_ips if ip not in arp_ips]
            _LOGGER.info("Last resort scan: checking %d common IPs...", len(common_ips))
            tasks = [_check_single_ip(ip, semaphore, timeout) for ip in common_ips]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            found_devices = [r for r in results if isinstance(r, dict)]

    # Restore log levels
    logging.getLogger("coap").setLevel(logging.WARNING)
    logging.getLogger(VENDORED_LOGGER).setLevel(logging.INFO)

    _LOGGER.info("Scan complete. Found %d device(s)", len(found_devices))
    return found_devices
