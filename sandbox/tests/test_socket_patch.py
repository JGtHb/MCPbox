"""Tests for the context-aware socket monkey-patch (socket_patch.py).

Verifies that PatchedSocket routes through SOCKS5 only during tool execution
(when the ContextVar is set) and passes through to the original socket for
framework code (when the ContextVar is unset).
"""

import asyncio
import socket as real_socket_module
import struct
from unittest.mock import patch

import pytest

from app.socket_patch import (
    PatchedSocket,
    _ExecutionContext,
    _OriginalSocket,
    _execution_context,
    _is_always_blocked_ip,
    _is_loopback,
    _patched_create_connection,
    _patched_getaddrinfo,
    _patched_gethostbyname,
    _patched_gethostbyname_ex,
    _socks5_handshake,
    _validate_for_tool_context,
    execution_socket_context,
    patch_socket,
)


# ---------------------------------------------------------------------------
# IP validation (mirrors safe_socket tests — keep in sync)
# ---------------------------------------------------------------------------


class TestIsAlwaysBlockedIP:
    @pytest.mark.parametrize("ip", ["127.0.0.1", "0.0.0.0", "169.254.169.254", "::1"])
    def test_blocked_ips(self, ip):
        assert _is_always_blocked_ip(ip) is True

    @pytest.mark.parametrize("ip", ["8.8.8.8", "192.168.1.1", "10.0.0.1", "not-an-ip"])
    def test_allowed_ips(self, ip):
        assert _is_always_blocked_ip(ip) is False


class TestIsLoopback:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "127.0.0.2", "127.255.255.255", "::1", "localhost", "LOCALHOST"],
    )
    def test_loopback_hosts(self, host):
        assert _is_loopback(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "8.8.8.8",
            "192.168.1.1",
            "10.0.0.1",
            "169.254.169.254",
            "example.com",
            "not-an-ip",
        ],
    )
    def test_non_loopback_hosts(self, host):
        assert _is_loopback(host) is False


# ---------------------------------------------------------------------------
# _validate_for_tool_context
# ---------------------------------------------------------------------------


class TestValidateForToolContext:
    def test_host_not_in_allowlist(self):
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"approved.local"}),
            proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="not approved"):
            _validate_for_tool_context("unapproved.local", 80, ctx)

    def test_host_in_allowlist_passes(self):
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"approved.local"}),
            proxy_addr=("proxy", 1080),
        )
        _validate_for_tool_context("approved.local", 80, ctx)  # should not raise

    def test_no_allowlist_passes_any_host(self):
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        _validate_for_tool_context("anything.com", 80, ctx)  # should not raise

    def test_always_blocked_ip_rejected(self):
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        with pytest.raises(ConnectionError, match="reserved IP range"):
            _validate_for_tool_context("127.0.0.1", 80, ctx)

    def test_blocked_ip_rejected_even_if_in_allowlist(self):
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"127.0.0.1"}),
            proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="reserved IP range"):
            _validate_for_tool_context("127.0.0.1", 80, ctx)

    def test_case_insensitive(self):
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"myhost.local"}),
            proxy_addr=("proxy", 1080),
        )
        _validate_for_tool_context("MYHOST.LOCAL", 80, ctx)  # should not raise

    def test_port_scoped_entry_matches(self):
        """host:port entry matches connection to that exact port."""
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"192.168.1.2:1883"}),
            proxy_addr=("proxy", 1080),
        )
        _validate_for_tool_context("192.168.1.2", 1883, ctx)  # should not raise

    def test_port_scoped_entry_rejects_wrong_port(self):
        """host:port entry does NOT match a different port."""
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"192.168.1.2:1883"}),
            proxy_addr=("proxy", 1080),
        )
        with pytest.raises(ConnectionError, match="not approved"):
            _validate_for_tool_context("192.168.1.2", 8080, ctx)

    def test_host_only_entry_matches_any_port(self):
        """Plain host entry matches any port."""
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"192.168.1.2"}),
            proxy_addr=("proxy", 1080),
        )
        _validate_for_tool_context("192.168.1.2", 1883, ctx)  # should not raise
        _validate_for_tool_context("192.168.1.2", 8080, ctx)  # should not raise


# ---------------------------------------------------------------------------
# SOCKS5 handshake
# ---------------------------------------------------------------------------


class TestSocks5Handshake:
    def test_successful_handshake(self):
        """Verify correct SOCKS5 bytes are sent and response consumed."""
        sent_data = []
        recv_responses = [
            b"\x05\x00",  # method: NO_AUTH accepted
            b"\x05\x00\x00\x01",  # reply: success, ATYP=IPv4
            b"\x00\x00\x00\x00\x00\x00",  # bind addr (4 IP + 2 port)
        ]
        recv_idx = [0]
        connected_to = [None]

        # Create real PatchedSocket and monkey-patch its underlying methods
        sock = PatchedSocket(real_socket_module.AF_INET, real_socket_module.SOCK_STREAM)

        def mock_connect(self, addr):
            connected_to[0] = addr

        def mock_sendall(self, data, flags=0):
            sent_data.append(data)

        def mock_recv(self, size, flags=0):
            idx = recv_idx[0]
            recv_idx[0] += 1
            return recv_responses[idx]

        with (
            patch.object(_OriginalSocket, "connect", mock_connect),
            patch.object(_OriginalSocket, "sendall", mock_sendall),
            patch.object(_OriginalSocket, "recv", mock_recv),
        ):
            _socks5_handshake(sock, ("proxy", 1080), "example.com", 443)

        # Verify connect to proxy
        assert connected_to[0] == ("proxy", 1080)

        # Verify method negotiation
        assert sent_data[0] == b"\x05\x01\x00"

        # Verify CONNECT request
        connect_data = sent_data[1]
        assert connect_data[0:4] == b"\x05\x01\x00\x03"  # VER, CONNECT, RSV, DOMAINNAME
        assert connect_data[4] == len("example.com")
        assert connect_data[5 : 5 + len("example.com")] == b"example.com"
        assert struct.unpack("!H", connect_data[-2:])[0] == 443
        sock.close()

    def test_auth_rejected(self):
        sock = PatchedSocket(real_socket_module.AF_INET, real_socket_module.SOCK_STREAM)

        def mock_connect(self, addr):
            pass

        def mock_sendall(self, data, flags=0):
            pass

        def mock_recv(self, size, flags=0):
            return b"\x05\xff"

        with (
            patch.object(_OriginalSocket, "connect", mock_connect),
            patch.object(_OriginalSocket, "sendall", mock_sendall),
            patch.object(_OriginalSocket, "recv", mock_recv),
        ):
            with pytest.raises(ConnectionError, match="rejected authentication"):
                _socks5_handshake(sock, ("proxy", 1080), "example.com", 80)
        sock.close()

    def test_connect_refused(self):
        sock = PatchedSocket(real_socket_module.AF_INET, real_socket_module.SOCK_STREAM)
        recv_responses = [
            b"\x05\x00",  # method OK
            b"\x05\x05\x00\x01",  # reply: connection refused (0x05)
            b"\x00\x00\x00\x00\x00\x00",
        ]
        recv_idx = [0]

        def mock_connect(self, addr):
            pass

        def mock_sendall(self, data, flags=0):
            pass

        def mock_recv(self, size, flags=0):
            idx = recv_idx[0]
            recv_idx[0] += 1
            return recv_responses[idx]

        with (
            patch.object(_OriginalSocket, "connect", mock_connect),
            patch.object(_OriginalSocket, "sendall", mock_sendall),
            patch.object(_OriginalSocket, "recv", mock_recv),
        ):
            with pytest.raises(ConnectionError, match="connection refused"):
                _socks5_handshake(sock, ("proxy", 1080), "example.com", 80)
        sock.close()


# ---------------------------------------------------------------------------
# PatchedSocket
# ---------------------------------------------------------------------------


class TestPatchedSocket:
    def test_isinstance_check(self):
        """PatchedSocket is a real socket subclass (needed by asyncio)."""
        sock = PatchedSocket(real_socket_module.AF_INET, real_socket_module.SOCK_STREAM)
        assert isinstance(sock, _OriginalSocket)
        sock.close()

    def test_passthrough_without_context(self):
        """Without execution context, connect delegates to original."""
        assert _execution_context.get() is None
        connected_to = [None]

        def mock_connect(self, addr):
            connected_to[0] = addr

        sock = PatchedSocket(real_socket_module.AF_INET, real_socket_module.SOCK_STREAM)
        # Verify it calls the original connect directly (not SOCKS5)
        with patch.object(_OriginalSocket, "connect", mock_connect):
            sock.connect(("example.com", 80))
        # Should have connected directly, not to a SOCKS proxy
        assert connected_to[0] == ("example.com", 80)
        sock.close()

    def test_socks5_routing_with_context(self):
        """With execution context, connect goes through SOCKS5."""
        ctx = _ExecutionContext(
            allowed_hosts=None, proxy_addr=("nonexistent-socks-proxy", 1080)
        )
        token = _execution_context.set(ctx)
        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            # Should try to connect to the SOCKS proxy first → OSError
            # (the proxy doesn't exist, but we're verifying it TRIES the proxy)
            with pytest.raises(OSError):
                sock.connect(("example.com", 80))
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_blocked_host_in_context(self):
        """Blocked host raises ConnectionError before proxy attempt."""
        ctx = _ExecutionContext(
            allowed_hosts=frozenset({"approved.local"}),
            proxy_addr=("proxy", 1080),
        )
        token = _execution_context.set(ctx)
        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            with pytest.raises(ConnectionError, match="not approved"):
                sock.connect(("unapproved.local", 80))
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_loopback_ipv4_passthrough_in_context(self):
        """Loopback passes through directly — not proxied, not blocked."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        connected_to = [None]

        def mock_connect(self, addr):
            connected_to[0] = addr

        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            with patch.object(_OriginalSocket, "connect", mock_connect):
                sock.connect(("127.0.0.1", 8888))
            assert connected_to[0] == ("127.0.0.1", 8888)
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_loopback_ipv6_passthrough_in_context(self):
        """IPv6 loopback (::1) also passes through directly."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        connected_to = [None]

        def mock_connect(self, addr):
            connected_to[0] = addr

        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET6, real_socket_module.SOCK_STREAM
            )
            with patch.object(_OriginalSocket, "connect", mock_connect):
                sock.connect(("::1", 8888))
            assert connected_to[0] == ("::1", 8888)
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_loopback_localhost_passthrough_in_context(self):
        """'localhost' hostname passes through directly."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        connected_to = [None]

        def mock_connect(self, addr):
            connected_to[0] = addr

        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            with patch.object(_OriginalSocket, "connect", mock_connect):
                sock.connect(("localhost", 9999))
            assert connected_to[0] == ("localhost", 9999)
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_proxy_address_passthrough_in_context(self):
        """Connection to the SOCKS proxy itself passes through directly (avoids double-proxy)."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("socks-proxy", 1080))
        token = _execution_context.set(ctx)
        connected_to = [None]

        def mock_connect(self, addr):
            connected_to[0] = addr

        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            with patch.object(_OriginalSocket, "connect", mock_connect):
                sock.connect(("socks-proxy", 1080))
            # Should connect directly to the proxy, not SOCKS5-wrap it
            assert connected_to[0] == ("socks-proxy", 1080)
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_non_loopback_blocked_ip_still_rejected(self):
        """Non-loopback blocked IPs (e.g. 169.254.x.x) are still rejected."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            with pytest.raises(ConnectionError, match="reserved IP range"):
                sock.connect(("169.254.169.254", 80))
            sock.close()
        finally:
            _execution_context.reset(token)

    def test_connect_ex_returns_errno_in_context(self):
        ctx = _ExecutionContext(
            allowed_hosts=frozenset(),  # empty = all blocked
            proxy_addr=("proxy", 1080),
        )
        token = _execution_context.set(ctx)
        try:
            sock = PatchedSocket(
                real_socket_module.AF_INET, real_socket_module.SOCK_STREAM
            )
            result = sock.connect_ex(("example.com", 80))
            assert result != 0
            sock.close()
        finally:
            _execution_context.reset(token)


# ---------------------------------------------------------------------------
# Patched getaddrinfo
# ---------------------------------------------------------------------------


class TestPatchedGetaddrinfo:
    def test_synthetic_in_context(self):
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        try:
            result = _patched_getaddrinfo("example.com", 80)
            assert len(result) == 1
            family, socktype, proto, canonname, sockaddr = result[0]
            assert family == real_socket_module.AF_INET
            assert socktype == real_socket_module.SOCK_STREAM
            assert sockaddr == ("example.com", 80)
        finally:
            _execution_context.reset(token)

    def test_real_without_context(self):
        """Without context, delegates to real getaddrinfo."""
        assert _execution_context.get() is None
        result = _patched_getaddrinfo("localhost", 80)
        # Real getaddrinfo returns multiple entries (IPv4/IPv6)
        assert len(result) >= 1
        # Should contain actual resolved addresses
        assert any(entry[4][0] in ("127.0.0.1", "::1") for entry in result)

    def test_none_host_in_context(self):
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        try:
            result = _patched_getaddrinfo(None, 80)
            assert result[0][4] == ("0.0.0.0", 80)
        finally:
            _execution_context.reset(token)


# ---------------------------------------------------------------------------
# Patched create_connection
# ---------------------------------------------------------------------------


class TestPatchedCreateConnection:
    def test_real_without_context(self):
        """Without context, delegates to real create_connection."""
        assert _execution_context.get() is None
        with pytest.raises(OSError):
            _patched_create_connection(
                ("nonexistent-host.invalid", 12345), timeout=0.01
            )

    def test_socks5_with_context(self):
        """With context, creates PatchedSocket and connects via SOCKS5."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("socks-proxy", 1080))
        recv_responses = [
            b"\x05\x00",  # method OK
            b"\x05\x00\x00\x01",  # reply: success
            b"\x00\x00\x00\x00\x00\x00",  # bind addr
        ]
        recv_idx = [0]
        connected_to = [None]

        def mock_connect(self, addr):
            connected_to[0] = addr

        def mock_sendall(self, data, flags=0):
            pass

        def mock_recv(self, size, flags=0):
            idx = recv_idx[0]
            recv_idx[0] += 1
            return recv_responses[idx]

        token = _execution_context.set(ctx)
        try:
            with (
                patch.object(_OriginalSocket, "connect", mock_connect),
                patch.object(_OriginalSocket, "sendall", mock_sendall),
                patch.object(_OriginalSocket, "recv", mock_recv),
            ):
                sock = _patched_create_connection(("example.com", 80))
                # Should have connected to the SOCKS proxy, not the target
                assert connected_to[0] == ("socks-proxy", 1080)
                sock.close()
        finally:
            _execution_context.reset(token)


# ---------------------------------------------------------------------------
# Patched gethostbyname / gethostbyname_ex
# ---------------------------------------------------------------------------


class TestPatchedGethostbyname:
    def test_synthetic_in_context(self):
        """In tool context, returns hostname as-is (DNS resolves proxy-side)."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        try:
            result = _patched_gethostbyname("mqtt.local")
            assert result == "mqtt.local"
        finally:
            _execution_context.reset(token)

    def test_real_without_context(self):
        """Without context, delegates to real gethostbyname."""
        assert _execution_context.get() is None
        result = _patched_gethostbyname("localhost")
        assert result == "127.0.0.1"


class TestPatchedGethostbynameEx:
    def test_synthetic_in_context(self):
        """In tool context, returns hostname in address list (DNS resolves proxy-side)."""
        ctx = _ExecutionContext(allowed_hosts=None, proxy_addr=("proxy", 1080))
        token = _execution_context.set(ctx)
        try:
            hostname, aliases, addresses = _patched_gethostbyname_ex("mqtt.local")
            assert hostname == "mqtt.local"
            assert aliases == []
            assert addresses == ["mqtt.local"]
        finally:
            _execution_context.reset(token)

    def test_real_without_context(self):
        """Without context, delegates to real gethostbyname_ex."""
        assert _execution_context.get() is None
        hostname, aliases, addresses = _patched_gethostbyname_ex("localhost")
        assert "127.0.0.1" in addresses


# ---------------------------------------------------------------------------
# execution_socket_context
# ---------------------------------------------------------------------------


class TestExecutionSocketContext:
    @pytest.mark.asyncio
    async def test_sets_and_resets_context(self):
        assert _execution_context.get() is None
        async with execution_socket_context({"host.local"}, ("proxy", 1080)):
            ctx = _execution_context.get()
            assert ctx is not None
            assert ctx.proxy_addr == ("proxy", 1080)
            assert "host.local" in ctx.allowed_hosts
        assert _execution_context.get() is None

    @pytest.mark.asyncio
    async def test_resets_on_exception(self):
        assert _execution_context.get() is None
        with pytest.raises(ValueError):
            async with execution_socket_context(None, ("proxy", 1080)):
                assert _execution_context.get() is not None
                raise ValueError("test")
        assert _execution_context.get() is None

    @pytest.mark.asyncio
    async def test_no_proxy_skips_context(self):
        """When socks_proxy_addr is None, context is not set."""
        assert _execution_context.get() is None
        async with execution_socket_context(None, None):
            assert _execution_context.get() is None

    @pytest.mark.asyncio
    async def test_concurrent_isolation(self):
        """Two concurrent tasks have isolated contexts."""
        results = {}

        async def tool_exec(name: str, hosts: set[str]):
            async with execution_socket_context(hosts, ("proxy", 1080)):
                ctx = _execution_context.get()
                # Yield to let other tasks run
                await asyncio.sleep(0)
                results[name] = ctx.allowed_hosts

        t1 = asyncio.create_task(tool_exec("a", {"host-a.local"}))
        t2 = asyncio.create_task(tool_exec("b", {"host-b.local"}))
        await asyncio.gather(t1, t2)

        assert results["a"] == frozenset({"host-a.local"})
        assert results["b"] == frozenset({"host-b.local"})

    @pytest.mark.asyncio
    async def test_none_allowed_hosts(self):
        """allowed_hosts=None means no restriction."""
        async with execution_socket_context(None, ("proxy", 1080)):
            ctx = _execution_context.get()
            assert ctx.allowed_hosts is None


# ---------------------------------------------------------------------------
# patch_socket
# ---------------------------------------------------------------------------


class TestPatchSocket:
    def test_patches_socket_module(self):
        """patch_socket replaces socket.socket with PatchedSocket."""
        # Save originals
        orig_socket = real_socket_module.socket
        orig_gai = real_socket_module.getaddrinfo
        orig_cc = real_socket_module.create_connection
        orig_ghbn = real_socket_module.gethostbyname
        orig_ghbn_ex = real_socket_module.gethostbyname_ex

        try:
            patch_socket()
            assert real_socket_module.socket is PatchedSocket
            assert real_socket_module.getaddrinfo is _patched_getaddrinfo
            assert real_socket_module.create_connection is _patched_create_connection
            assert real_socket_module.gethostbyname is _patched_gethostbyname
            assert real_socket_module.gethostbyname_ex is _patched_gethostbyname_ex
        finally:
            # Restore originals to avoid affecting other tests
            real_socket_module.socket = orig_socket
            real_socket_module.getaddrinfo = orig_gai
            real_socket_module.create_connection = orig_cc
            real_socket_module.gethostbyname = orig_ghbn
            real_socket_module.gethostbyname_ex = orig_ghbn_ex
