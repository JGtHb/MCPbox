"""Tests for the SOCKS5 proxy server."""

import asyncio
import ipaddress
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Import from the proxy module (add parent to path for standalone test runs)
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from proxy import (
    ACLReader,
    handle_client,
    is_always_blocked,
    is_lan_hostname,
    is_private,
    validate_connection,
)


# --- IP validation tests ---


class TestIsAlwaysBlocked:
    """Test always-blocked IP ranges (loopback, metadata, link-local)."""

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "127.255.255.255",
            "0.0.0.0",
            "0.255.255.255",
            "169.254.0.1",
            "169.254.169.254",  # AWS metadata
            "::1",
            "fe80::1",
        ],
    )
    def test_blocked_ips(self, ip):
        assert is_always_blocked(ipaddress.ip_address(ip)) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "192.168.1.1",
            "10.0.0.1",
            "172.16.0.1",
        ],
    )
    def test_allowed_ips(self, ip):
        assert is_always_blocked(ipaddress.ip_address(ip)) is False


class TestIsPrivate:
    """Test private IP range detection (RFC 1918 + shared address space)."""

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.255",
            "100.64.0.1",
            "100.127.255.255",
        ],
    )
    def test_private_ips(self, ip):
        assert is_private(ipaddress.ip_address(ip)) is True

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "203.0.113.1"])
    def test_public_ips(self, ip):
        assert is_private(ipaddress.ip_address(ip)) is False


class TestIsLanHostname:
    """Test LAN hostname detection."""

    @pytest.mark.parametrize(
        "hostname",
        ["mynas.local", "printer.lan", "router.home", "server.internal", "myhost"],
    )
    def test_lan_hostnames(self, hostname):
        assert is_lan_hostname(hostname) is True

    @pytest.mark.parametrize("hostname", ["api.example.com", "github.com"])
    def test_public_hostnames(self, hostname):
        assert is_lan_hostname(hostname) is False


# --- ACL reader tests ---


class TestACLReader:
    """Test the ACL file reader with caching."""

    def test_reads_approved_hosts(self, tmp_path):
        acl_file = tmp_path / "approved-private.txt"
        acl_file.write_text("192.168.1.2\nmynas.local\n10.0.0.5\n")

        reader = ACLReader(acl_file, ttl=0)  # TTL=0 forces re-read each time
        assert reader.is_approved("192.168.1.2") is True
        assert reader.is_approved("mynas.local") is True
        assert reader.is_approved("10.0.0.5") is True
        assert reader.is_approved("10.0.0.6") is False

    def test_case_insensitive(self, tmp_path):
        acl_file = tmp_path / "approved-private.txt"
        acl_file.write_text("MyNas.Local\n")

        reader = ACLReader(acl_file, ttl=0)
        assert reader.is_approved("mynas.local") is True
        assert reader.is_approved("MYNAS.LOCAL") is True

    def test_missing_file(self, tmp_path):
        reader = ACLReader(tmp_path / "nonexistent.txt", ttl=0)
        assert reader.is_approved("anything") is False

    def test_empty_file(self, tmp_path):
        acl_file = tmp_path / "approved-private.txt"
        acl_file.write_text("")

        reader = ACLReader(acl_file, ttl=0)
        assert reader.is_approved("192.168.1.1") is False

    def test_ignores_blank_lines(self, tmp_path):
        acl_file = tmp_path / "approved-private.txt"
        acl_file.write_text("192.168.1.1\n\n\n10.0.0.1\n\n")

        reader = ACLReader(acl_file, ttl=0)
        assert reader.is_approved("192.168.1.1") is True
        assert reader.is_approved("10.0.0.1") is True
        assert reader.is_approved("") is False

    def test_ttl_caching(self, tmp_path):
        acl_file = tmp_path / "approved-private.txt"
        acl_file.write_text("192.168.1.1\n")

        reader = ACLReader(acl_file, ttl=999)  # Very long TTL
        assert reader.is_approved("192.168.1.1") is True

        # Update file — should still see cached version
        acl_file.write_text("10.0.0.1\n")
        assert reader.is_approved("192.168.1.1") is True
        assert reader.is_approved("10.0.0.1") is False


# --- Connection validation tests ---


class TestValidateConnection:
    """Test the validate_connection function."""

    def test_public_ip_allowed(self):
        result = validate_connection(
            "example.com", ipaddress.ip_address("93.184.216.34")
        )
        assert result is None

    def test_loopback_always_blocked(self):
        result = validate_connection("localhost", ipaddress.ip_address("127.0.0.1"))
        assert result is not None
        assert "always-blocked" in result

    def test_metadata_always_blocked(self):
        result = validate_connection(
            "metadata", ipaddress.ip_address("169.254.169.254")
        )
        assert result is not None
        assert "always-blocked" in result

    def test_private_ip_blocked_without_approval(self):
        with patch("proxy.acl_reader") as mock_reader:
            mock_reader.is_approved.return_value = False
            result = validate_connection("myhost", ipaddress.ip_address("192.168.1.1"))
            assert result is not None
            assert "not in the approved" in result

    def test_private_ip_allowed_with_hostname_approval(self):
        with patch("proxy.acl_reader") as mock_reader:
            mock_reader.is_approved.side_effect = lambda h: h == "myhost"
            result = validate_connection("myhost", ipaddress.ip_address("192.168.1.1"))
            assert result is None

    def test_private_ip_allowed_with_ip_approval(self):
        with patch("proxy.acl_reader") as mock_reader:
            mock_reader.is_approved.side_effect = lambda h: h == "192.168.1.1"
            result = validate_connection("myhost", ipaddress.ip_address("192.168.1.1"))
            assert result is None

    def test_dns_rebinding_blocked(self):
        """Hostname resolving to private IP is blocked unless approved."""
        with patch("proxy.acl_reader") as mock_reader:
            mock_reader.is_approved.return_value = False
            result = validate_connection(
                "evil.example.com", ipaddress.ip_address("10.0.0.1")
            )
            assert result is not None
            assert "private IP" in result


# --- SOCKS5 protocol tests ---


class TestSOCKS5Protocol:
    """Test SOCKS5 protocol handling via handle_client."""

    @pytest.mark.asyncio
    async def test_invalid_version_rejected(self):
        """Non-SOCKS5 version is rejected."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info.return_value = ("127.0.0.1", 12345)

        # Send SOCKS4 version
        reader.readexactly = AsyncMock(side_effect=[b"\x04\x01"])

        await handle_client(reader, writer)
        writer.close.assert_called()

    @pytest.mark.asyncio
    async def test_no_acceptable_auth_rejected(self):
        """Request with only unsupported auth methods is rejected."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info.return_value = ("127.0.0.1", 12345)
        writer.drain = AsyncMock()

        # Version 5, 1 method, USER/PASS (0x02) only — NO_AUTH not offered
        reader.readexactly = AsyncMock(side_effect=[b"\x05\x01", b"\x02"])

        await handle_client(reader, writer)
        # Should respond with 0xFF (no acceptable method)
        writer.write.assert_called()
        written = writer.write.call_args_list[0][0][0]
        assert written == b"\x05\xff"

    @pytest.mark.asyncio
    async def test_unsupported_command_rejected(self):
        """Non-CONNECT command is rejected."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info.return_value = ("127.0.0.1", 12345)
        writer.drain = AsyncMock()

        # Method negotiation: OK
        # Command: BIND (0x02) instead of CONNECT (0x01)
        reader.readexactly = AsyncMock(
            side_effect=[
                b"\x05\x01",  # version, 1 method
                b"\x00",  # NO_AUTH
                b"\x05\x02\x00\x01",  # VER, BIND, RSV, IPv4
                b"\x01\x01\x01\x01",  # target IP
                b"\x00\x50",  # port 80
            ]
        )

        await handle_client(reader, writer)
        # Check reply code is 0x07 (command not supported)
        calls = writer.write.call_args_list
        # First write: method selection, second write: reply
        reply = calls[1][0][0]
        assert reply[1] == 0x07

    @pytest.mark.asyncio
    async def test_blocked_ip_returns_not_allowed(self):
        """Connection to always-blocked IP returns NOT_ALLOWED reply."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info.return_value = ("127.0.0.1", 12345)
        writer.drain = AsyncMock()

        # Connect to 127.0.0.1:80
        reader.readexactly = AsyncMock(
            side_effect=[
                b"\x05\x01",  # version, 1 method
                b"\x00",  # NO_AUTH
                b"\x05\x01\x00\x03",  # VER, CONNECT, RSV, DOMAINNAME
                b"\x09",  # hostname length
                b"localhost",  # hostname
                b"\x00\x50",  # port 80
            ]
        )

        with patch("proxy.resolve_hostname", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = ("127.0.0.1", ipaddress.ip_address("127.0.0.1"))
            await handle_client(reader, writer)

        # Check reply code is 0x02 (not allowed)
        calls = writer.write.call_args_list
        reply = calls[1][0][0]
        assert reply[1] == 0x02
