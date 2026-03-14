"""Tests for the safe socket module (SafeSocket + create_safe_socket_module)."""

import socket as real_socket
import struct
from unittest.mock import MagicMock

import pytest

from app.safe_socket import (
    SafeSocket,
    _SafeSocketModule,
    _is_always_blocked_ip,
    create_safe_socket_module,
)


# --- _is_always_blocked_ip tests ---


class TestIsAlwaysBlockedIP:
    """Test the IP validation function."""

    @pytest.mark.parametrize(
        "ip",
        ["127.0.0.1", "0.0.0.0", "169.254.169.254", "::1"],
    )
    def test_blocked_ips(self, ip):
        assert _is_always_blocked_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        ["8.8.8.8", "192.168.1.1", "10.0.0.1", "not-an-ip"],
    )
    def test_allowed_ips(self, ip):
        assert _is_always_blocked_ip(ip) is False


# --- SafeSocket tests ---


class TestSafeSocket:
    """Test the SafeSocket wrapper."""

    def test_only_tcp_allowed(self):
        """UDP and raw sockets are rejected."""
        with pytest.raises(ValueError, match="SOCK_STREAM"):
            SafeSocket(type=real_socket.SOCK_DGRAM)

    def test_blocked_host_raises(self):
        """Connection to unapproved host raises ConnectionError."""
        sock = SafeSocket(
            _allowed_hosts={"approved.local"},
            _proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="not approved"):
            sock.connect(("unapproved.local", 80))
        sock.close()

    def test_allowed_host_passes_check(self):
        """Approved host passes the allowed_hosts check (fails at proxy connect)."""
        sock = SafeSocket(
            _allowed_hosts={"approved.local"},
            _proxy_addr=("nonexistent-proxy", 1080),
        )
        # Should pass allowed_hosts check but fail at actual TCP connect
        with pytest.raises(OSError):
            sock.connect(("approved.local", 80))
        sock.close()

    def test_no_allowlist_passes(self):
        """When allowed_hosts is None, any host passes the check."""
        sock = SafeSocket(
            _allowed_hosts=None,
            _proxy_addr=("nonexistent-proxy", 1080),
        )
        with pytest.raises(OSError):
            sock.connect(("any-host.com", 80))
        sock.close()

    def test_always_blocked_ip_rejected(self):
        """Literal always-blocked IPs are rejected before proxy."""
        sock = SafeSocket(
            _allowed_hosts=None,
            _proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="reserved IP range"):
            sock.connect(("127.0.0.1", 80))
        sock.close()

    def test_loopback_rejected_even_if_approved(self):
        """Loopback is blocked even when in allowed_hosts."""
        sock = SafeSocket(
            _allowed_hosts={"127.0.0.1"},
            _proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="reserved IP range"):
            sock.connect(("127.0.0.1", 80))
        sock.close()

    def test_no_proxy_configured_raises(self):
        """Missing SOCKS_PROXY raises clear error."""
        sock = SafeSocket(
            _allowed_hosts=None,
            _proxy_addr=None,
        )
        with pytest.raises(ConnectionError, match="SOCKS5 proxy not configured"):
            sock.connect(("example.com", 80))
        sock.close()

    def test_bind_blocked(self):
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        with pytest.raises(PermissionError, match="bind"):
            sock.bind(("0.0.0.0", 8080))
        sock.close()

    def test_listen_blocked(self):
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        with pytest.raises(PermissionError, match="listen"):
            sock.listen()
        sock.close()

    def test_accept_blocked(self):
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        with pytest.raises(PermissionError, match="accept"):
            sock.accept()
        sock.close()

    def test_getattr_blocked(self):
        """Direct attribute access to internals is blocked."""
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        with pytest.raises(AttributeError, match="not allowed"):
            _ = sock._real_socket
        sock.close()

    def test_setattr_blocked(self):
        """Cannot set arbitrary attributes."""
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        with pytest.raises(AttributeError, match="Cannot set"):
            sock.custom_attr = "value"
        sock.close()

    def test_context_manager(self):
        """SafeSocket supports context manager protocol."""
        with SafeSocket(_proxy_addr=("proxy", 1080)) as sock:
            assert sock is not None

    def test_connect_ex_returns_errno(self):
        """connect_ex returns 0 on success or errno on failure."""
        sock = SafeSocket(
            _allowed_hosts=None,
            _proxy_addr=("nonexistent-proxy", 1080),
        )
        result = sock.connect_ex(("example.com", 80))
        assert result != 0
        sock.close()

    def test_connect_ex_blocked_host(self):
        """connect_ex returns non-zero for blocked hosts."""
        sock = SafeSocket(
            _allowed_hosts=set(),  # empty = all blocked
            _proxy_addr=("proxy", 1080),
        )
        result = sock.connect_ex(("example.com", 80))
        assert result != 0
        sock.close()

    def test_socks5_handshake_bytes(self):
        """Verify correct SOCKS5 handshake is sent to proxy."""
        mock_real = MagicMock()
        # Proxy responses: method selection OK, connect header, bind address
        mock_real.recv.side_effect = [
            b"\x05\x00",  # method: NO_AUTH accepted
            b"\x05\x00\x00\x01",  # CONNECT reply header (VER, REP=success, RSV, ATYP=IPv4)
            b"\x00\x00\x00\x00\x00\x00",  # bind addr: 4 IP bytes + 2 port bytes
        ]

        sock = SafeSocket(
            _allowed_hosts=None,
            _proxy_addr=("proxy", 1080),
        )
        # Replace real socket with mock
        object.__setattr__(sock, "_SafeSocket__real_socket", mock_real)

        sock.connect(("example.com", 443))

        # Check proxy connect
        mock_real.connect.assert_called_once_with(("proxy", 1080))

        # Check method negotiation: VER=5, NMETHODS=1, NO_AUTH=0
        calls = mock_real.sendall.call_args_list
        assert calls[0][0][0] == b"\x05\x01\x00"

        # Check CONNECT request
        connect_data = calls[1][0][0]
        assert connect_data[0:4] == b"\x05\x01\x00\x03"  # VER, CONNECT, RSV, DOMAINNAME
        assert connect_data[4] == len("example.com")
        assert connect_data[5 : 5 + len("example.com")] == b"example.com"
        port_bytes = connect_data[-2:]
        assert struct.unpack("!H", port_bytes)[0] == 443

    def test_socks5_proxy_rejection(self):
        """Proxy rejection (e.g., not allowed) raises ConnectionError."""
        mock_real = MagicMock()
        mock_real.recv.side_effect = [
            b"\x05\x00",  # method OK
            b"\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00",  # reply: NOT_ALLOWED (0x02)
        ]

        sock = SafeSocket(
            _allowed_hosts=None,
            _proxy_addr=("proxy", 1080),
        )
        object.__setattr__(sock, "_SafeSocket__real_socket", mock_real)

        with pytest.raises(ConnectionError, match="not allowed by ruleset"):
            sock.connect(("blocked-host.com", 80))

    def test_case_insensitive_host_check(self):
        """allowed_hosts check is case-insensitive."""
        sock = SafeSocket(
            _allowed_hosts={"myhost.local"},
            _proxy_addr=("nonexistent-proxy", 1080),
        )
        # Should pass allowed_hosts check (case-insensitive)
        # but fail at actual proxy connect
        with pytest.raises(OSError):
            sock.connect(("MYHOST.LOCAL", 80))
        sock.close()

    def test_host_port_format_allowed(self):
        """allowed_hosts entries with host:port format are matched."""
        sock = SafeSocket(
            _allowed_hosts={"192.168.1.2:1883"},
            _proxy_addr=("nonexistent-proxy", 1080),
        )
        # host:port matches — passes allowed_hosts, fails at proxy connect
        with pytest.raises(OSError):
            sock.connect(("192.168.1.2", 1883))
        sock.close()

    def test_host_port_wrong_port_rejected(self):
        """host:port entry doesn't match a different port."""
        sock = SafeSocket(
            _allowed_hosts={"192.168.1.2:1883"},
            _proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="not approved"):
            sock.connect(("192.168.1.2", 8080))
        sock.close()

    def test_host_only_allows_any_port(self):
        """Host-only entry (no port) allows any port."""
        sock = SafeSocket(
            _allowed_hosts={"192.168.1.2"},
            _proxy_addr=("nonexistent-proxy", 1080),
        )
        # Should pass allowed_hosts for any port
        with pytest.raises(OSError):
            sock.connect(("192.168.1.2", 1883))
        sock.close()

    def test_safe_readonly_attrs(self):
        """Safe read-only attributes (family, type, proto) are accessible."""
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        assert sock.family == real_socket.AF_INET
        assert sock.type == real_socket.SOCK_STREAM
        assert sock.proto == 0
        sock.close()

    def test_unsafe_attrs_still_blocked(self):
        """Attributes not in the safe list are still blocked."""
        sock = SafeSocket(_proxy_addr=("proxy", 1080))
        with pytest.raises(AttributeError, match="not allowed"):
            _ = sock.some_random_attr
        sock.close()


# --- create_safe_socket_module tests ---


class TestCreateSafeSocketModule:
    """Test the module-like object returned by create_safe_socket_module."""

    def test_has_socket_constructor(self):
        mod = create_safe_socket_module()
        sock = mod.socket()
        assert isinstance(sock, SafeSocket)
        sock.close()

    def test_has_constants(self):
        mod = create_safe_socket_module()
        assert mod.AF_INET == real_socket.AF_INET
        assert mod.AF_INET6 == real_socket.AF_INET6
        assert mod.SOCK_STREAM == real_socket.SOCK_STREAM
        assert mod.SOCK_DGRAM == real_socket.SOCK_DGRAM
        assert mod.IPPROTO_TCP == real_socket.IPPROTO_TCP
        assert mod.SOL_SOCKET == real_socket.SOL_SOCKET

    def test_has_exceptions(self):
        mod = create_safe_socket_module()
        assert mod.error is real_socket.error
        assert mod.timeout is real_socket.timeout
        assert mod.herror is real_socket.herror
        assert mod.gaierror is real_socket.gaierror

    def test_getaddrinfo_returns_synthetic(self):
        mod = create_safe_socket_module()
        result = mod.getaddrinfo("example.com", 80)
        assert len(result) == 1
        family, socktype, proto, canonname, sockaddr = result[0]
        assert family == real_socket.AF_INET
        assert socktype == real_socket.SOCK_STREAM
        assert sockaddr == ("example.com", 80)

    def test_create_connection_returns_safesocket(self):
        mod = create_safe_socket_module(
            allowed_hosts=None,
            socks_proxy_addr=("nonexistent-proxy", 1080),
        )
        with pytest.raises(OSError):
            mod.create_connection(("example.com", 80), timeout=0.01)

    def test_module_name(self):
        mod = create_safe_socket_module()
        assert mod.__name__ == "socket"

    def test_allowed_hosts_propagated_to_socket(self):
        """allowed_hosts from module creation is passed to SafeSocket instances."""
        mod = create_safe_socket_module(
            allowed_hosts={"approved.local"},
            socks_proxy_addr=("proxy", 1080),
        )
        sock = mod.socket()
        with pytest.raises(ConnectionError, match="not approved"):
            sock.connect(("unapproved.local", 80))
        sock.close()

    def test_proxy_addr_propagated_to_socket(self):
        """socks_proxy_addr from module creation is passed to SafeSocket instances."""
        mod = create_safe_socket_module(
            allowed_hosts=None,
            socks_proxy_addr=None,
        )
        sock = mod.socket()
        with pytest.raises(ConnectionError, match="SOCKS5 proxy not configured"):
            sock.connect(("example.com", 80))
        sock.close()

    def test_is_safe_socket_module_instance(self):
        """create_safe_socket_module returns a _SafeSocketModule."""
        mod = create_safe_socket_module()
        assert isinstance(mod, _SafeSocketModule)

    def test_getattr_fallback_for_constants(self):
        """Constants not explicitly set are accessible via __getattr__."""
        mod = create_safe_socket_module()
        # SOCK_RAW is a valid socket constant but not in the explicit list
        if hasattr(real_socket, "SOCK_RAW"):
            assert mod.SOCK_RAW == real_socket.SOCK_RAW

    def test_getattr_blocks_functions(self):
        """Dangerous functions are not accessible."""
        mod = create_safe_socket_module()
        with pytest.raises(AttributeError, match="not available"):
            _ = mod.fromfd

    def test_getattr_blocks_private_attrs(self):
        """Private attributes are blocked."""
        mod = create_safe_socket_module()
        with pytest.raises(AttributeError, match="not available"):
            _ = mod._realmodule

    def test_getattr_nonexistent(self):
        """Non-existent attributes raise AttributeError."""
        mod = create_safe_socket_module()
        with pytest.raises(AttributeError):
            _ = mod.totally_fake_attribute
