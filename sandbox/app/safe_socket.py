"""Safe socket module for sandboxed tool execution.

Provides a SOCKS5-routing socket wrapper that enforces per-server
``allowed_hosts`` policy, matching how ``SSRFProtectedAsyncHttpClient``
handles HTTP traffic.

When tool code does ``import socket``, the executor's safe import mechanism
returns the module-like object from ``create_safe_socket_module()`` instead
of the real socket module.

All TCP connections are routed through the SOCKS5 proxy sidecar.  DNS
resolution happens proxy-side (DOMAINNAME address type) to prevent DNS
rebinding attacks.

IP validation ranges mirror socks-proxy/proxy.py — keep in sync.
"""

import ipaddress
import socket as _real_socket
import struct
from types import SimpleNamespace
from typing import Any

# --- IP validation (mirrors socks-proxy/proxy.py and sandbox/app/ssrf.py) ---

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
    """Check if an IP is in a range that can never be overridden by admin approval."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in _ALWAYS_BLOCKED_NETWORKS:
            if ip in network:
                return True
        return False
    except ValueError:
        return False


# SOCKS5 constants
_SOCKS_VERSION = 0x05
_AUTH_NONE = 0x00
_CMD_CONNECT = 0x01
_ATYP_IPV4 = 0x01
_ATYP_DOMAINNAME = 0x03
_REP_SUCCESS = 0x00


class SafeSocket:
    """Drop-in replacement for socket.socket that routes through SOCKS5 proxy.

    Enforces:
    1. allowed_hosts check (per-server network policy)
    2. Always-blocked IP validation (loopback, metadata, link-local)
    3. SOCKS5 proxy routing (all connections go through socks-proxy:1080)
    4. Blocks server-side operations (bind, listen, accept)

    SECURITY: Uses __slots__ and name-mangled attributes to prevent sandbox
    code from accessing the underlying real socket (consistent with
    SSRFProtectedAsyncHttpClient and TimeoutProtectedRegex patterns).
    """

    __slots__ = ("__real_socket", "__allowed_hosts", "__proxy_addr", "__connected")

    def __init__(
        self,
        family: int = _real_socket.AF_INET,
        type: int = _real_socket.SOCK_STREAM,
        proto: int = 0,
        fileno: int | None = None,
        *,
        _allowed_hosts: set[str] | None = None,
        _proxy_addr: tuple[str, int] | None = None,
    ):
        if type != _real_socket.SOCK_STREAM:
            raise ValueError(
                "Only SOCK_STREAM (TCP) is supported in the sandbox. "
                "UDP and raw sockets are not available."
            )
        sock = _real_socket.socket(family, type, proto)
        object.__setattr__(self, "_SafeSocket__real_socket", sock)
        object.__setattr__(self, "_SafeSocket__allowed_hosts", _allowed_hosts)
        object.__setattr__(self, "_SafeSocket__proxy_addr", _proxy_addr)
        object.__setattr__(self, "_SafeSocket__connected", False)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"Access to '{name}' is not allowed on socket objects. "
            f"Use connect(), send(), recv(), close(), etc."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Cannot set attributes on socket objects")

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # --- Connection (SOCKS5 routing) ---

    def connect(self, address: tuple[str, int]) -> None:
        """Connect to target through SOCKS5 proxy.

        Validates against allowed_hosts and blocked IP ranges before
        performing SOCKS5 handshake with the proxy.
        """
        host, port = address

        # 1. Check allowed_hosts (per-server network policy)
        if self.__allowed_hosts is not None:
            if host.lower() not in self.__allowed_hosts:
                raise ConnectionError(
                    f"Network access to '{host}' is not approved for this server. "
                    f"Use mcpbox_request_network_access to request access."
                )

        # 2. Check always-blocked IPs (literal IP addresses only)
        if _is_always_blocked_ip(host):
            raise ConnectionError(
                f"Connection to '{host}' is blocked (reserved IP range). "
                f"Loopback, link-local, and metadata addresses are never allowed."
            )

        # 3. Route through SOCKS5 proxy
        if self.__proxy_addr is None:
            raise ConnectionError(
                "SOCKS5 proxy not configured. Set SOCKS_PROXY environment variable."
            )

        self.__real_socket.connect(self.__proxy_addr)

        # SOCKS5 method negotiation: version 5, 1 method, NO_AUTH
        self.__real_socket.sendall(struct.pack("!BBB", _SOCKS_VERSION, 1, _AUTH_NONE))
        response = self.__real_socket.recv(2)
        if (
            len(response) < 2
            or response[0] != _SOCKS_VERSION
            or response[1] != _AUTH_NONE
        ):
            raise ConnectionError("SOCKS5 proxy rejected authentication method")

        # SOCKS5 CONNECT request using DOMAINNAME type
        # (proxy resolves DNS to prevent DNS rebinding)
        host_bytes = host.encode("ascii")
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
            + struct.pack("!H", port)
        )
        self.__real_socket.sendall(request)

        # Read response: VER(1) + REP(1) + RSV(1) + ATYP(1) + ADDR(variable) + PORT(2)
        resp_header = self.__real_socket.recv(4)
        if len(resp_header) < 4:
            raise ConnectionError("SOCKS5 proxy: incomplete response")

        rep = resp_header[1]
        if rep != _REP_SUCCESS:
            error_messages = {
                0x01: "general SOCKS server failure",
                0x02: "connection not allowed by ruleset",
                0x03: "network unreachable",
                0x04: "host unreachable",
                0x05: "connection refused",
                0x06: "TTL expired",
                0x07: "command not supported",
                0x08: "address type not supported",
            }
            msg = error_messages.get(rep, f"unknown error (0x{rep:02x})")
            raise ConnectionError(f"SOCKS5 proxy: {msg}")

        # Consume remaining response bytes (bind address + port)
        atyp = resp_header[3]
        if atyp == _ATYP_IPV4:
            self.__real_socket.recv(4 + 2)  # 4 bytes IP + 2 bytes port
        elif atyp == _ATYP_DOMAINNAME:
            length = self.__real_socket.recv(1)[0]
            self.__real_socket.recv(length + 2)
        elif atyp == 0x04:  # IPv6
            self.__real_socket.recv(16 + 2)

        object.__setattr__(self, "_SafeSocket__connected", True)

    def connect_ex(self, address: tuple[str, int]) -> int:
        """Connect, returning 0 on success or an errno on failure."""
        try:
            self.connect(address)
            return 0
        except OSError as e:
            return e.errno or -1

    # --- Data transfer (delegate to real socket) ---

    def send(self, data: bytes, flags: int = 0) -> int:
        return self.__real_socket.send(data, flags)

    def sendall(self, data: bytes, flags: int = 0) -> None:
        return self.__real_socket.sendall(data, flags)

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        return self.__real_socket.recv(bufsize, flags)

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        return self.__real_socket.recv_into(buffer, nbytes, flags)

    def makefile(self, mode: str = "r", buffering: int = -1, **kwargs: Any) -> Any:
        return self.__real_socket.makefile(mode, buffering, **kwargs)

    # --- Socket management ---

    def close(self) -> None:
        self.__real_socket.close()

    def shutdown(self, how: int) -> None:
        self.__real_socket.shutdown(how)

    def settimeout(self, timeout: float | None) -> None:
        self.__real_socket.settimeout(timeout)

    def gettimeout(self) -> float | None:
        return self.__real_socket.gettimeout()

    def setblocking(self, flag: bool) -> None:
        self.__real_socket.setblocking(flag)

    def fileno(self) -> int:
        return self.__real_socket.fileno()

    def getpeername(self) -> tuple[str, int]:
        return self.__real_socket.getpeername()

    def getsockname(self) -> tuple[str, int]:
        return self.__real_socket.getsockname()

    def setsockopt(self, level: int, optname: int, value: Any) -> None:
        self.__real_socket.setsockopt(level, optname, value)

    def getsockopt(self, level: int, optname: int, buflen: int = 0) -> Any:
        if buflen:
            return self.__real_socket.getsockopt(level, optname, buflen)
        return self.__real_socket.getsockopt(level, optname)

    def detach(self) -> int:
        return self.__real_socket.detach()

    # --- Blocked server operations ---

    def bind(self, address: tuple[str, int]) -> None:
        raise PermissionError("bind() is not allowed in the sandbox")

    def listen(self, backlog: int = 0) -> None:
        raise PermissionError("listen() is not allowed in the sandbox")

    def accept(self) -> tuple[Any, tuple[str, int]]:
        raise PermissionError("accept() is not allowed in the sandbox")


def create_safe_socket_module(
    allowed_hosts: set[str] | None = None,
    socks_proxy_addr: tuple[str, int] | None = None,
) -> SimpleNamespace:
    """Create a module-like object that replaces the ``socket`` module.

    Tool code that does ``import socket`` gets this instead.  ``socket.socket()``
    returns ``SafeSocket`` instances that route through the SOCKS5 proxy.

    Args:
        allowed_hosts: Per-server network allowlist (None = no restriction).
        socks_proxy_addr: SOCKS5 proxy (host, port) tuple.
    """

    def safe_socket_constructor(
        family: int = _real_socket.AF_INET,
        type: int = _real_socket.SOCK_STREAM,
        proto: int = 0,
        fileno: int | None = None,
    ) -> SafeSocket:
        return SafeSocket(
            family,
            type,
            proto,
            fileno,
            _allowed_hosts=allowed_hosts,
            _proxy_addr=socks_proxy_addr,
        )

    def safe_create_connection(
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> SafeSocket:
        """Create a connected SafeSocket (mirrors socket.create_connection)."""
        host, port = address
        sock = SafeSocket(
            _real_socket.AF_INET,
            _real_socket.SOCK_STREAM,
            _allowed_hosts=allowed_hosts,
            _proxy_addr=socks_proxy_addr,
        )
        if timeout is not None:
            sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except Exception:
            sock.close()
            raise
        return sock

    def safe_getaddrinfo(
        host: str | None,
        port: int | str | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        """Stub getaddrinfo that returns synthetic results.

        DNS resolution happens proxy-side to prevent DNS rebinding.
        This stub satisfies libraries that call getaddrinfo before connecting.
        """
        p = int(port) if port is not None else 0
        h = host if host is not None else "0.0.0.0"
        return [(_real_socket.AF_INET, _real_socket.SOCK_STREAM, 0, "", (h, p))]

    # Build the module-like namespace
    mod = SimpleNamespace(
        # Constructor
        socket=safe_socket_constructor,
        # High-level helpers
        create_connection=safe_create_connection,
        getaddrinfo=safe_getaddrinfo,
        # Constants
        AF_INET=_real_socket.AF_INET,
        AF_INET6=_real_socket.AF_INET6,
        SOCK_STREAM=_real_socket.SOCK_STREAM,
        SOCK_DGRAM=_real_socket.SOCK_DGRAM,
        IPPROTO_TCP=_real_socket.IPPROTO_TCP,
        IPPROTO_UDP=_real_socket.IPPROTO_UDP,
        SOL_SOCKET=_real_socket.SOL_SOCKET,
        SO_REUSEADDR=_real_socket.SO_REUSEADDR,
        SO_KEEPALIVE=_real_socket.SO_KEEPALIVE,
        SHUT_RD=_real_socket.SHUT_RD,
        SHUT_WR=_real_socket.SHUT_WR,
        SHUT_RDWR=_real_socket.SHUT_RDWR,
        TCP_NODELAY=_real_socket.TCP_NODELAY,
        IPPROTO_IP=getattr(_real_socket, "IPPROTO_IP", 0),
        # Exceptions
        error=_real_socket.error,
        timeout=_real_socket.timeout,
        herror=_real_socket.herror,
        gaierror=_real_socket.gaierror,
        # Module name (some libraries check this)
        __name__="socket",
    )

    return mod
