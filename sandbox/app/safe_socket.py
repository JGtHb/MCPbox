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

    __slots__ = (
        "__real_socket",
        "__allowed_hosts",
        "__proxy_addr",
        "__connected",
        "__family",
        "__type",
        "__proto",
    )

    # Read-only attributes that third-party libraries commonly access
    # (e.g., paho-mqtt checks sock.family, sock.type). These are safe to
    # expose — they reveal socket metadata, not the underlying real socket.
    _SAFE_READONLY_ATTRS = frozenset(
        {
            "family",
            "type",
            "proto",
        }
    )

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
        object.__setattr__(self, "_SafeSocket__family", family)
        object.__setattr__(self, "_SafeSocket__type", type)
        object.__setattr__(self, "_SafeSocket__proto", proto)

    def __getattr__(self, name: str) -> Any:
        # Allow read access to safe metadata attributes that third-party
        # libraries need (e.g., paho-mqtt checks sock.family, sock.type).
        if name in SafeSocket._SAFE_READONLY_ATTRS:
            return getattr(self.__real_socket, name)
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
        # Check both "host:port" and "host" entries, consistent with SSRF client.
        if self.__allowed_hosts is not None:
            host_lower = host.lower()
            host_port = f"{host_lower}:{port}"
            if (
                host_port not in self.__allowed_hosts
                and host_lower not in self.__allowed_hosts
            ):
                raise ConnectionError(
                    f"Network access to '{host_port}' is not approved for this server. "
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
) -> "_SafeSocketModule":
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

    # Build a module-like object with __getattr__ fallback for socket
    # constants.  Third-party libraries (paho-mqtt, etc.) access many
    # constants beyond the explicitly listed ones.  Integer/string constants
    # and exception classes are safe; functions and socket class are not.
    mod = _SafeSocketModule(
        safe_socket_constructor,
        safe_create_connection,
        safe_getaddrinfo,
    )

    return mod


class _SafeSocketModule:
    """Module-like object that replaces ``socket`` for sandboxed code.

    Explicitly exposes safe constructors and helpers.  Falls back to the
    real socket module for integer/string constants and exception classes
    that third-party libraries need, while blocking access to dangerous
    functions (``socket.socket``, ``socket.fromfd``, etc.).
    """

    __name__ = "socket"

    # Functions on the real socket module that must NOT be exposed.
    _BLOCKED_ATTRS = frozenset(
        {
            "fromfd",
            "socketpair",
            "dup",
            "if_nameindex",
            "if_nametoindex",
            "if_indextoname",
            "sethostname",
            "setdefaulttimeout",
            "getdefaulttimeout",
            "close",  # os-level fd close
        }
    )

    def __init__(
        self,
        socket_constructor,
        create_connection_fn,
        getaddrinfo_fn,
    ):
        self.socket = socket_constructor
        self.create_connection = create_connection_fn
        self.getaddrinfo = getaddrinfo_fn
        # Eagerly set the most commonly used constants so simple attribute
        # lookups don't need __getattr__ at all.
        self.AF_INET = _real_socket.AF_INET
        self.AF_INET6 = _real_socket.AF_INET6
        self.SOCK_STREAM = _real_socket.SOCK_STREAM
        self.SOCK_DGRAM = _real_socket.SOCK_DGRAM
        self.IPPROTO_TCP = _real_socket.IPPROTO_TCP
        self.IPPROTO_UDP = _real_socket.IPPROTO_UDP
        self.SOL_SOCKET = _real_socket.SOL_SOCKET
        self.SO_REUSEADDR = _real_socket.SO_REUSEADDR
        self.SO_KEEPALIVE = _real_socket.SO_KEEPALIVE
        self.SHUT_RD = _real_socket.SHUT_RD
        self.SHUT_WR = _real_socket.SHUT_WR
        self.SHUT_RDWR = _real_socket.SHUT_RDWR
        self.TCP_NODELAY = _real_socket.TCP_NODELAY
        self.IPPROTO_IP = getattr(_real_socket, "IPPROTO_IP", 0)
        # Exceptions
        self.error = _real_socket.error
        self.timeout = _real_socket.timeout
        self.herror = _real_socket.herror
        self.gaierror = _real_socket.gaierror

    def __getattr__(self, name: str) -> Any:
        """Fallback for socket constants not explicitly set.

        Allows integer/string constants and exception classes from the real
        socket module.  Blocks functions and the raw socket class.
        """
        if name.startswith("_") or name in self._BLOCKED_ATTRS:
            raise AttributeError(f"socket.{name} is not available in the sandbox")

        val = getattr(_real_socket, name, None)
        if val is None:
            raise AttributeError(f"module 'socket' has no attribute '{name}'")

        # Allow constants (int, str, bytes) and exception classes only.
        if isinstance(val, (int, str, bytes)):
            return val
        if isinstance(val, type) and issubclass(val, Exception):
            return val

        raise AttributeError(f"socket.{name} is not available in the sandbox")
