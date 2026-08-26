"""Tests for helper functions."""

import asyncio
from unittest.mock import AsyncMock, mock_open, patch

from custom_components.philips_airpurifier_coap import helpers
from custom_components.philips_airpurifier_coap.const import PhilipsApi
from custom_components.philips_airpurifier_coap.helpers import extract_model, extract_name


class TestExtractName:
    """Tests for extract_name function."""

    def test_extract_name_legacy(self):
        """Test extracting name from legacy API key."""
        status = {PhilipsApi.NAME: "Living Room"}
        assert extract_name(status) == "Living Room"

    def test_extract_name_new(self):
        """Test extracting name from new API key."""
        status = {PhilipsApi.NEW_NAME: "Bedroom"}
        assert extract_name(status) == "Bedroom"

    def test_extract_name_new2(self):
        """Test extracting name from new2 API key."""
        status = {PhilipsApi.NEW2_NAME: "Office"}
        assert extract_name(status) == "Office"

    def test_extract_name_priority(self):
        """Test that legacy name takes priority over new names."""
        status = {
            PhilipsApi.NAME: "Legacy",
            PhilipsApi.NEW_NAME: "New",
            PhilipsApi.NEW2_NAME: "New2",
        }
        assert extract_name(status) == "Legacy"

    def test_extract_name_fallback_to_new(self):
        """Test fallback to new name when legacy is missing."""
        status = {
            PhilipsApi.NEW_NAME: "New",
            PhilipsApi.NEW2_NAME: "New2",
        }
        assert extract_name(status) == "New"

    def test_extract_name_empty_status(self):
        """Test extracting name from empty status."""
        assert extract_name({}) == ""

    def test_extract_name_none_value(self):
        """Test extracting name when value is None."""
        status = {PhilipsApi.NAME: None}
        assert extract_name(status) == ""

    def test_extract_name_empty_string(self):
        """Test extracting name when value is empty string."""
        status = {PhilipsApi.NAME: ""}
        # Empty string is falsy, should continue to next key or return ""
        assert extract_name(status) == ""


class TestExtractModel:
    """Tests for extract_model function."""

    def test_extract_model_legacy(self):
        """Test extracting model from legacy API key."""
        status = {PhilipsApi.MODEL_ID: "AC3033/10"}
        assert extract_model(status) == "AC3033/10"

    def test_extract_model_new(self):
        """Test extracting model from new API key."""
        status = {PhilipsApi.NEW_MODEL_ID: "AC1715/10"}
        assert extract_model(status) == "AC1715/10"

    def test_extract_model_new2(self):
        """Test extracting model from new2 API key."""
        status = {PhilipsApi.NEW2_MODEL_ID: "AC0950/10"}
        assert extract_model(status) == "AC0950/10"

    def test_extract_model_truncates_to_9_chars(self):
        """Test that model is truncated to 9 characters."""
        status = {PhilipsApi.MODEL_ID: "AC3033/10_EXTRA_LONG_STRING"}
        assert extract_model(status) == "AC3033/10"
        assert len(extract_model(status)) == 9

    def test_extract_model_priority(self):
        """Test that legacy model takes priority over new models."""
        status = {
            PhilipsApi.MODEL_ID: "AC1214/10",
            PhilipsApi.NEW_MODEL_ID: "AC1715/10",
            PhilipsApi.NEW2_MODEL_ID: "AC0950/10",
        }
        assert extract_model(status) == "AC1214/10"

    def test_extract_model_fallback_to_new(self):
        """Test fallback to new model when legacy is missing."""
        status = {
            PhilipsApi.NEW_MODEL_ID: "AC1715/10",
            PhilipsApi.NEW2_MODEL_ID: "AC0950/10",
        }
        assert extract_model(status) == "AC1715/10"

    def test_extract_model_empty_status(self):
        """Test extracting model from empty status."""
        assert extract_model({}) == ""

    def test_extract_model_none_value(self):
        """Test extracting model when value is None."""
        status = {PhilipsApi.MODEL_ID: None}
        assert extract_model(status) == ""

    def test_extract_model_short_string(self):
        """Test extracting model shorter than 9 characters."""
        status = {PhilipsApi.MODEL_ID: "AC3033"}
        assert extract_model(status) == "AC3033"


class TestNetworkScan:
    """Tests for the network discovery helpers."""

    def test_get_local_ip(self):
        """A reachable socket reveals the local IP."""
        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.getsockname.return_value = ("192.168.1.10", 0)
            assert helpers.get_local_ip() == "192.168.1.10"

    def test_get_local_ip_failure(self):
        """A socket error yields None."""
        with patch("socket.socket", side_effect=OSError):
            assert helpers.get_local_ip() is None

    def test_get_active_ips_from_arp(self):
        """Only entries with a valid flag (0x2) are returned."""
        arp = (
            "IP address  HW type  Flags  HW address  Mask  Device\n"
            "192.168.1.50  0x1  0x2  aa:bb:cc:dd:ee:ff  *  eth0\n"
            "192.168.1.51  0x1  0x0  00:00:00:00:00:00  *  eth0\n"
        )
        with patch("builtins.open", mock_open(read_data=arp)):
            ips = helpers.get_active_ips_from_arp()
        assert "192.168.1.50" in ips
        assert "192.168.1.51" not in ips

    async def test_check_single_ip_found(self):
        """A responding Philips device is returned with its model and name."""
        client = AsyncMock()
        client.get_status = AsyncMock(
            return_value=(
                {
                    PhilipsApi.MODEL_ID: "AC3033/10",
                    PhilipsApi.NAME: "Living Room",
                    PhilipsApi.DEVICE_ID: "id",
                },
                60,
            )
        )
        client.shutdown = AsyncMock()
        with patch(
            "custom_components.philips_airpurifier_coap.helpers.CoAPClient.create",
            AsyncMock(return_value=client),
        ):
            result = await helpers._check_single_ip("1.2.3.4", asyncio.Semaphore(1), 1.0)
        assert result["ip"] == "1.2.3.4"
        assert result["model"] == "AC3033/10"

    async def test_check_single_ip_not_philips(self):
        """A non-responding host yields None."""
        with patch(
            "custom_components.philips_airpurifier_coap.helpers.CoAPClient.create",
            AsyncMock(side_effect=TimeoutError),
        ):
            result = await helpers._check_single_ip("1.2.3.4", asyncio.Semaphore(1), 1.0)
        assert result is None

    async def test_ping_sweep(self):
        """The ping sweep sends UDP probes across the subnet."""
        with (
            patch("socket.socket"),
            patch(
                "custom_components.philips_airpurifier_coap.helpers.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            await helpers.ping_sweep("192.168.1")

    async def test_scan_for_devices(self):
        """The scan returns the devices found via the ARP table."""
        device = {"ip": "192.168.1.50", "model": "AC3033/10", "name": "x", "status": {}}
        with (
            patch.object(helpers, "coap_discovery", AsyncMock(return_value=[])),
            patch.object(helpers, "get_local_ip", return_value="192.168.1.10"),
            patch.object(helpers, "ping_sweep", AsyncMock()),
            patch.object(helpers, "get_active_ips_from_arp", return_value=["192.168.1.50"]),
            patch.object(helpers, "_check_single_ip", AsyncMock(return_value=device)),
        ):
            devices = await helpers.scan_for_devices(timeout=0.1)
        assert devices == [device]

    async def test_scan_for_devices_no_local_ip(self):
        """The scan returns nothing when the local IP cannot be determined."""
        with (
            patch.object(helpers, "coap_discovery", AsyncMock(return_value=[])),
            patch.object(helpers, "get_local_ip", return_value=None),
        ):
            assert await helpers.scan_for_devices() == []

    async def test_scan_for_devices_coap_timeout(self):
        """CoAP discovery timeout falls back to ARP scan."""
        device = {"ip": "192.168.1.50", "model": "AC3033/10", "name": "x", "status": {}}
        with (
            patch.object(helpers, "coap_discovery", AsyncMock(side_effect=TimeoutError)),
            patch.object(helpers, "get_local_ip", return_value="192.168.1.10"),
            patch.object(helpers, "ping_sweep", AsyncMock()),
            patch.object(helpers, "get_active_ips_from_arp", return_value=["192.168.1.50"]),
            patch.object(helpers, "_check_single_ip", AsyncMock(return_value=device)),
        ):
            devices = await helpers.scan_for_devices(timeout=0.1)
        assert devices == [device]

    async def test_scan_for_devices_prefers_coap_discovery(self):
        """Discovered CoAP candidates are checked directly, skipping ARP sweep."""
        device = {"ip": "192.168.1.73", "model": "AC3033/10", "name": "x", "status": {}}
        candidate = {"ip": "192.168.1.73", "device_id": "abc", "option": "119"}
        ping_sweep = AsyncMock()
        with (
            patch.object(helpers, "coap_discovery", AsyncMock(return_value=[candidate])),
            patch.object(helpers, "_check_single_ip", AsyncMock(return_value=device)) as check,
            patch.object(helpers, "ping_sweep", ping_sweep),
            patch.object(helpers, "get_local_ip", return_value="192.168.1.10"),
        ):
            devices = await helpers.scan_for_devices(timeout=1.0)
        assert devices == [device]
        check.assert_awaited_once_with("192.168.1.73", check.await_args.args[1], 1.0)
        ping_sweep.assert_not_awaited()


class TestCoapDiscovery:
    """Tests for the multicast discovery primitives."""

    def test_build_coap_get_is_a_valid_coap_message(self):
        """The handcrafted GET decodes to a NON GET on the right URI path."""
        import aiocoap

        raw = helpers._build_coap_get(helpers.DISCOVERY_ENCRYPTED_PATH, 0x1234)
        decoded = aiocoap.Message.decode(raw)
        assert str(decoded.code) == "GET"
        assert decoded.mtype == aiocoap.NON
        assert list(decoded.opt.uri_path) == list(helpers.DISCOVERY_ENCRYPTED_PATH)

    def test_build_coap_get_plain_and_encrypted_paths(self):
        """Both discovery URIs are encoded correctly."""
        plain = helpers._build_coap_get(helpers.DISCOVERY_INFO_PATH, 1)
        encrypted = helpers._build_coap_get(helpers.DISCOVERY_ENCRYPTED_PATH, 2)
        assert b"info" in plain
        assert b"encryption" in encrypted

    def test_decrypt_didt_roundtrip(self):
        """A didt blob encrypts to deviceId&deviceToken and back."""
        import hashlib

        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import pad

        local_ip = "192.168.1.10"
        digest = hashlib.md5((helpers.DISCOVERY_SECRET + local_ip).encode()).hexdigest().upper()
        key, iv = digest[:16], digest[16:]
        cipher = AES.new(key=key.encode(), mode=AES.MODE_CBC, iv=iv.encode())
        didt = cipher.encrypt(pad(b"AB12CD34&tok3n", 16)).hex().upper()

        assert helpers.decrypt_didt(didt, local_ip) == ("AB12CD34", "tok3n")

    def test_decrypt_didt_invalid_blob(self):
        """Garbage input yields None instead of raising."""
        assert helpers.decrypt_didt("not-hex", "192.168.1.10") is None
        assert helpers.decrypt_didt("00" * 16, "192.168.1.10") is None

    @staticmethod
    def _coap_response(payload: bytes) -> bytes:
        """Wrap a payload in a minimal CoAP response envelope."""
        return b"\x70\x45\x00\x01\xff" + payload

    def test_parse_discovery_reply_plain(self):
        """A legacy reply carries its device_id in clear text."""
        import json

        data = self._coap_response(json.dumps({"device_id": "dev1", "modelid": "AC3033"}).encode())
        entry = helpers._parse_discovery_reply(data, "1.2.3.4", None)
        assert entry == {"ip": "1.2.3.4", "device_id": "dev1", "option": ""}

    def test_parse_discovery_reply_encrypted(self):
        """An encrypted reply is decrypted using the local IP."""
        import hashlib
        import json

        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import pad

        local_ip = "192.168.1.10"
        digest = hashlib.md5((helpers.DISCOVERY_SECRET + local_ip).encode()).hexdigest().upper()
        key, iv = digest[:16], digest[16:]
        cipher = AES.new(key=key.encode(), mode=AES.MODE_CBC, iv=iv.encode())
        didt = cipher.encrypt(pad(b"dev2&t0k", 16)).hex().upper()
        data = self._coap_response(json.dumps({"didt": didt, "option": "119"}).encode())

        entry = helpers._parse_discovery_reply(data, "1.2.3.4", local_ip)
        assert entry == {"ip": "1.2.3.4", "device_id": "dev2", "option": "119"}

    def test_parse_discovery_reply_garbage(self):
        """Non-CoAP noise is ignored."""
        assert helpers._parse_discovery_reply(b"\x00\x01\x02", "1.2.3.4", None) is None

    def test_parse_discovery_reply_encrypted_bad_didt(self):
        """An encrypted reply with undecryptable didt is skipped."""
        import json

        data = self._coap_response(json.dumps({"didt": "ZZZZ", "option": "119"}).encode())
        assert helpers._parse_discovery_reply(data, "1.2.3.4", "192.168.1.10") is None

    def test_parse_discovery_reply_no_device_id(self):
        """A reply without device_id and without didt is ignored."""
        import json

        data = self._coap_response(json.dumps({"modelid": "X"}).encode())
        assert helpers._parse_discovery_reply(data, "1.2.3.4", None) is None

    def test_parse_discovery_reply_empty_local_ip(self):
        """Encrypted reply with no local_ip cannot be decrypted."""
        import json

        data = self._coap_response(json.dumps({"didt": "AA", "option": "3"}).encode())
        assert helpers._parse_discovery_reply(data, "1.2.3.4", None) is None

    def test_decrypt_didt_empty_device_id(self):
        """Decryption that yields empty device_id returns None."""
        import hashlib

        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import pad

        local_ip = "192.168.1.10"
        digest = hashlib.md5((helpers.DISCOVERY_SECRET + local_ip).encode()).hexdigest().upper()
        key, iv = digest[:16], digest[16:]
        cipher = AES.new(key=key.encode(), mode=AES.MODE_CBC, iv=iv.encode())
        didt = cipher.encrypt(pad(b"&token", 16)).hex().upper()
        assert helpers.decrypt_didt(didt, local_ip) is None


class TestCoapDiscoveryLive:
    """Tests for coap_discovery with mocked socket."""

    async def test_coap_discovery_finds_device(self):
        """coap_discovery parses a real CoAP reply from the socket."""
        import json

        payload = json.dumps({"device_id": "abc123", "modelid": "AC3033", "option": "1"}).encode()
        coap_reply = b"\x70\x45\x00\x01\xff" + payload

        with patch.object(helpers, "get_local_ip", return_value="192.168.1.10"):
            with patch("socket.socket") as mock_sock:
                instance = mock_sock.return_value
                call_count = 0

                def _recv(*_a, **_kw):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return (coap_reply, ("192.168.1.50", 5683))
                    raise TimeoutError

                instance.recvfrom.side_effect = _recv
                devices = await helpers.coap_discovery(timeout=0.5)
        assert len(devices) == 1
        assert devices[0]["device_id"] == "abc123"

    async def test_coap_discovery_empty_when_no_reply(self):
        """coap_discovery returns [] when no device answers."""
        with patch.object(helpers, "get_local_ip", return_value="192.168.1.10"):
            with patch("socket.socket") as mock_sock:
                instance = mock_sock.return_value
                instance.recvfrom.side_effect = TimeoutError
                devices = await helpers.coap_discovery(timeout=0.1)
        assert devices == []

    async def test_coap_discovery_deduplicates_ip(self):
        """A second reply from the same IP is ignored."""
        import json

        payload = json.dumps({"device_id": "x", "option": "1"}).encode()
        coap_reply = b"\x70\x45\x00\x01\xff" + payload

        with patch.object(helpers, "get_local_ip", return_value="192.168.1.10"):
            with patch("socket.socket") as mock_sock:
                instance = mock_sock.return_value
                call_count = 0

                def _recv(*_a, **_kw):
                    nonlocal call_count
                    call_count += 1
                    if call_count <= 2:
                        return (coap_reply, ("192.168.1.50", 5683))
                    raise TimeoutError

                instance.recvfrom.side_effect = _recv
                devices = await helpers.coap_discovery(timeout=0.5)
        assert len(devices) == 1

    async def test_check_single_ip_shutdown_on_success(self):
        """Client is shut down even after a successful status fetch."""
        client = AsyncMock()
        client.get_status = AsyncMock(
            return_value=(
                {
                    PhilipsApi.DEVICE_ID: "id",
                    PhilipsApi.MODEL_ID: "AC3033/10",
                    PhilipsApi.NAME: "x",
                },
                60,
            )
        )
        with patch(
            "custom_components.philips_airpurifier_coap.helpers.CoAPClient.create",
            AsyncMock(return_value=client),
        ):
            await helpers._check_single_ip("1.2.3.4", asyncio.Semaphore(1), 1.0)
        client.shutdown.assert_awaited_once()
