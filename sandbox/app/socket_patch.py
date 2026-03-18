"""Context-aware socket monkey-patch for sandboxed tool execution.

Patches ``socket.socket``, ``socket.getaddrinfo``, and
``socket.create_connection`` in the **real** socket module so that ALL
code — including third-party libraries and stdlib modules like asyncio
that hold cached references to the real socket — routes TCP through the
SOCKS5 proxy when running inside a tool execution context.

**Why this is needed:**  The executor's ``safe_import("socket")`` only
intercepts ``import socket`` written directly in tool code.  Libraries
imported via ``real_import`` (e.g. paho-mqtt, asyncio) use the real
socket module and bypass SafeSocket entirely.  Since the sandbox
container has no direct route to external hosts (not on the external
Docker network), those connections fail immediately.

**Safety for framework code (uvicorn / FastAPI):**  A
``contextvars.ContextVar`` tracks whether the current execution context
is a tool invocation.  When the ContextVar is unset (framework code),
all patched functions delegate to the originals — zero behaviour change.

**Concurrency:**  ContextVars are per-``asyncio.Task``, so concurrent
tool executions each have isolated ``allowed_hosts`` / proxy configs.
On Python 3.12+ (sandbox uses 3.14), ``loop.run_in_executor``
automatically copies context to the worker thread.
"""

from __future__ import annotations

import contextvars
import ipaddress
import socket as _real_socket_module
import struct
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# IP validation (mirrors safe_socket.py and socks-proxy/proxy.py — keep in sync)
# ---------------------------------------------------------------------------

_ALWAYS_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def _is_always_blocked_ip(ip_str: str) -> bool:
    """Check if an IP is in a range that can never be overridden."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in _ALWAYS_BLOCKED_NETWORKS:
            if ip in network:
                return True
        return False
    except ValueError:
        return False


def _is_loopback(host: str) -> bool:
    """Return True if *host* is a loopback address (127.0.0.0/8, ::1, localhost)."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# SOCKS5 constants
# ---------------------------------------------------------------------------

_SOCKS_VERSION = 0x05
_AUTH_NONE = 0x00
_CMD_CONNECT = 0x01
_ATYP_IPV4 = 0x01
_ATYP_DOMAINNAME = 0x03
_REP_SUCCESS = 0x00

_SOCKS5_ERRORS = {
    0x01: "general SOCKS server failure",
    0x02: "connection not allowed by ruleset",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
}

# ---------------------------------------------------------------------------
# Per-execution context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ExecutionContext:
    """Immutable snapshot of per-execution socket config."""

    allowed_hosts: frozenset[str] | None  # None = no restriction
    proxy_addr: tuple[str, int]


_execution_context: contextvars.ContextVar[_ExecutionContext | None] = (
    contextvars.ContextVar("_execution_context", default=None)
)

# ---------------------------------------------------------------------------
# Save originals before patching
# ---------------------------------------------------------------------------

_OriginalSocket = _real_socket_module.socket
_original_getaddrinfo = _real_socket_module.getaddrinfo
_original_create_connection = _real_socket_module.create_connection
_original_gethostbyname = _real_socket_module.gethostbyname
_original_gethostbyname_ex = _real_socket_module.gethostbyname_ex

# ---------------------------------------------------------------------------
# SOCKS5 handshake helper (shared by PatchedSocket.connect)
# ---------------------------------------------------------------------------


def _socks5_handshake(
    sock: _OriginalSocket,  # type: ignore[type-arg]
    proxy_addr: tuple[str, int],
    target_host: str,
    target_port: int,
) -> None:
    """Perform SOCKS5 CONNECT through *proxy_addr* to *target_host:target_port*.

    Mirrors ``SafeSocket.connect()`` from ``safe_socket.py`` — keep in sync.
    DNS resolution happens proxy-side (DOMAINNAME address type).
    """
    # Connect to the SOCKS5 proxy itself
    _OriginalSocket.connect(sock, proxy_addr)

    # Method negotiation: version 5, 1 method, NO_AUTH
    _OriginalSocket.sendall(sock, struct.pack("!BBB", _SOCKS_VERSION, 1, _AUTH_NONE))
    response = _OriginalSocket.recv(sock, 2)
    if len(response) < 2 or response[0] != _SOCKS_VERSION or response[1] != _AUTH_NONE:
        raise ConnectionError("SOCKS5 proxy rejected authentication method")

    # CONNECT request using DOMAINNAME type (proxy resolves DNS)
    host_bytes = target_host.encode("ascii")
    request = (
        struct.pack(
            "!BBBBB",
            _SOCKS_VERSION,
            _CMD_CONNECT,
            0x00,
            _ATYP_DOMAINNAME,
            len(host_bytes),
        )
        + host_bytes
        + struct.pack("!H", target_port)
    )
    _OriginalSocket.sendall(sock, request)

    # Read response header: VER(1) + REP(1) + RSV(1) + ATYP(1)
    resp_header = _OriginalSocket.recv(sock, 4)
    if len(resp_header) < 4:
        raise ConnectionError("SOCKS5 proxy: incomplete response")

    rep = resp_header[1]
    if rep != _REP_SUCCESS:
        msg = _SOCKS5_ERRORS.get(rep, f"unknown error (0x{rep:02x})")
        raise ConnectionError(f"SOCKS5 proxy: {msg}")

    # Consume remaining response bytes (bind address + port)
    atyp = resp_header[3]
    if atyp == _ATYP_IPV4:
        _OriginalSocket.recv(sock, 4 + 2)
    elif atyp == _ATYP_DOMAINNAME:
        length = _OriginalSocket.recv(sock, 1)[0]
        _OriginalSocket.recv(sock, length + 2)
    elif atyp == 0x04:  # IPv6
        _OriginalSocket.recv(sock, 16 + 2)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_for_tool_context(host: str, port: int, ctx: _ExecutionContext) -> None:
    """Raise ConnectionError if *host:port* is not allowed in *ctx*.

    Checks both ``"host:port"`` and ``"host"`` entries in ``allowed_hosts``,
    consistent with SafeSocket and the SSRF client.
    """
    if ctx.allowed_hosts is not None:
        host_lower = host.lower()
        host_port = f"{host_lower}:{port}"
        if host_port not in ctx.allowed_hosts and host_lower not in ctx.allowed_hosts:
            raise ConnectionError(
                f"Network access to '{host_port}' is not approved for this server. "
                f"Use mcpbox_request_network_access to request access."
            )
    if _is_always_blocked_ip(host):
        raise ConnectionError(
            f"Connection to '{host}' is blocked (reserved IP range). "
            f"Loopback, link-local, and metadata addresses are never allowed."
        )


# ---------------------------------------------------------------------------
# PatchedSocket — subclass of the real socket (not a wrapper)
# ---------------------------------------------------------------------------


class PatchedSocket(_OriginalSocket):  # type: ignore[type-arg]
    """``socket.socket`` subclass that routes through SOCKS5 in tool context.

    When ``_execution_context`` is set (tool execution), ``connect()``
    performs a SOCKS5 handshake instead of a direct connection.  When
    unset (framework code), behaviour is identical to the original class.

    Subclassing (rather than wrapping) is required because asyncio's
    internals do ``isinstance(sock, socket.socket)`` checks and
    ``selector.register()`` needs a real file descriptor.
    """

    def connect(self, address: Any) -> None:
        ctx = _execution_context.get()
        if ctx is None:
            # Framework code — passthrough
            return _OriginalSocket.connect(self, address)

        host, port = address
        # Loopback is container-local and cannot be meaningfully proxied
        # through SOCKS5 (the proxy would reach its own loopback, not ours).
        # SafeSocket independently blocks loopback for tool-authored code;
        # the SOCKS5 proxy also blocks it.  Sandbox API requires auth.
        if _is_loopback(host):
            return _OriginalSocket.connect(self, address)
        # Connection to the SOCKS proxy itself must pass through directly.
        # httpx/httpcore already handle SOCKS5 proxying via HTTPS_PROXY;
        # intercepting their connection to the proxy would create a loop.
        if (host, port) == ctx.proxy_addr:
            return _OriginalSocket.connect(self, address)
        _validate_for_tool_context(host, port, ctx)
        _socks5_handshake(self, ctx.proxy_addr, host, port)

    def connect_ex(self, address: Any) -> int:
        try:
            self.connect(address)
            return 0
        except OSError as e:
            return e.errno or -1


# ---------------------------------------------------------------------------
# Patched module-level functions
# ---------------------------------------------------------------------------


def _patched_getaddrinfo(
    host: str | None,
    port: int | str | None,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    """In tool context, return synthetic results (DNS resolves proxy-side)."""
    ctx = _execution_context.get()
    if ctx is None:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    p = int(port) if port is not None else 0
    h = host if host is not None else "0.0.0.0"
    return [
        (_real_socket_module.AF_INET, _real_socket_module.SOCK_STREAM, 0, "", (h, p))
    ]


def _patched_create_connection(
    address: tuple[str, int],
    timeout: float | object = _real_socket_module._GLOBAL_DEFAULT_TIMEOUT,  # type: ignore[attr-defined]
    source_address: tuple[str, int] | None = None,
) -> _real_socket_module.socket:
    """In tool context, create a PatchedSocket that SOCKS5-routes on connect."""
    ctx = _execution_context.get()
    if ctx is None:
        return _original_create_connection(address, timeout, source_address)

    host, port = address
    sock = PatchedSocket(_real_socket_module.AF_INET, _real_socket_module.SOCK_STREAM)
    if timeout is not _real_socket_module._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
        sock.settimeout(timeout)  # type: ignore[arg-type]
    try:
        sock.connect((host, port))
    except Exception:
        sock.close()
        raise
    return sock


def _patched_gethostbyname(hostname: str) -> str:
    """In tool context, delegate to patched getaddrinfo (single DNS code path)."""
    ctx = _execution_context.get()
    if ctx is None:
        return _original_gethostbyname(hostname)
    # Delegate to getaddrinfo so all DNS goes through one code path.
    # In tool context this returns the hostname as-is (DNS resolves proxy-side).
    results = _patched_getaddrinfo(hostname, 0)
    return results[0][4][0]


def _patched_gethostbyname_ex(hostname: str) -> tuple[str, list[str], list[str]]:
    """In tool context, delegate to patched getaddrinfo (single DNS code path)."""
    ctx = _execution_context.get()
    if ctx is None:
        return _original_gethostbyname_ex(hostname)
    results = _patched_getaddrinfo(hostname, 0)
    addresses = [r[4][0] for r in results]
    return (hostname, [], addresses)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch_socket() -> None:
    """Monkey-patch the real ``socket`` module.  Call once at startup.

    Must be called **after** framework imports (FastAPI, uvicorn, httpx)
    so their module-level socket references are unaffected for bind/listen.
    The patch only changes the *class* used for new ``socket.socket()``
    calls and the behaviour of ``getaddrinfo`` / ``create_connection``.
    """
    _real_socket_module.socket = PatchedSocket  # type: ignore[misc]
    _real_socket_module.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]
    _real_socket_module.create_connection = _patched_create_connection  # type: ignore[assignment]
    _real_socket_module.gethostbyname = _patched_gethostbyname  # type: ignore[assignment]
    _real_socket_module.gethostbyname_ex = _patched_gethostbyname_ex  # type: ignore[assignment]


@asynccontextmanager
async def execution_socket_context(
    allowed_hosts: set[str] | None,
    socks_proxy_addr: tuple[str, int] | None,
):
    """Activate SOCKS5 routing for the duration of a tool execution.

    Args:
        allowed_hosts: Per-server network allowlist (None = no restriction).
        socks_proxy_addr: ``(host, port)`` of the SOCKS5 proxy.
            If None, tool code that uses third-party TCP will get a
            ``ConnectionError`` explaining the proxy is not configured.
    """
    if socks_proxy_addr is None:
        # No proxy configured — don't activate context so sockets pass through.
        # Direct connections will still fail (no route), which is correct.
        yield
        return

    frozen_hosts = frozenset(allowed_hosts) if allowed_hosts is not None else None
    ctx = _ExecutionContext(allowed_hosts=frozen_hosts, proxy_addr=socks_proxy_addr)
    token = _execution_context.set(ctx)
    try:
        yield
    finally:
        _execution_context.reset(token)
