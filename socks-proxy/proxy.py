"""MCPbox SOCKS5 Proxy — egress filter for sandbox.

All sandbox outbound traffic (HTTP via httpx+socksio, raw TCP via SafeSocket)
is forced through this proxy via Docker network isolation.

Policy (defense-in-depth — mirrors app-layer SSRF checks):
  - Always-blocked IPs: loopback, link-local, metadata — never allowed
  - Private IPs (RFC 1918): blocked unless admin-approved via ACL file
  - Public IPs (domain whitelisting):
      * Infrastructure hosts (pypi.org, etc.): always allowed
      * When ACL has entries: only approved hosts allowed (defense-in-depth)
      * When ACL is empty: all public traffic allowed (no servers registered)
  - DNS resolved proxy-side to prevent DNS rebinding attacks

ACL file: /shared/proxy-acl/approved-private.txt
  Written by sandbox registry, one hostname/IP per line, case-insensitive.
  Contains the union of all registered servers' allowed_hosts.

IP validation ranges mirror sandbox/app/ssrf.py — keep in sync.

Protocol: RFC 1928 SOCKS5, CONNECT command only, NO_AUTH method only.
"""

import asyncio
import ipaddress
import logging
import os
import socket
import struct
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("socks-proxy")

# --- Configuration ---

LISTEN_HOST = os.environ.get("SOCKS_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("SOCKS_LISTEN_PORT", "1080"))
ACL_FILE = Path(
    os.environ.get("PROXY_ACL_PATH", "/shared/proxy-acl/approved-private.txt")
)
ACL_CACHE_TTL = float(os.environ.get("ACL_CACHE_TTL", "5"))
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "10"))
RELAY_BUFFER_SIZE = 65536

# --- IP validation ---
# Keep in sync with sandbox/app/ssrf.py _ALWAYS_BLOCKED_NETWORKS and BLOCKED_IP_RANGES

ALWAYS_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]

PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
]

# Common LAN hostname suffixes (matches sandbox/app/registry.py filtering logic)
LAN_SUFFIXES = (".local", ".lan", ".home", ".internal")

# Infrastructure hosts the sandbox always needs (package install, security checks).
# These bypass domain whitelisting so the sandbox can function even when
# servers have restricted allowed_hosts lists.
INFRASTRUCTURE_HOSTS = frozenset(
    {
        "pypi.org",  # Package metadata (pypi_client.py)
        "files.pythonhosted.org",  # pip downloads packages from here
        "api.osv.dev",  # Vulnerability checking (osv_client.py)
        "api.deps.dev",  # Dependency health / OpenSSF Scorecard (deps_client.py)
    }
)

# SOCKS5 constants
SOCKS_VERSION = 0x05
AUTH_NONE = 0x00
CMD_CONNECT = 0x01
ATYP_IPV4 = 0x01
ATYP_DOMAINNAME = 0x03
ATYP_IPV6 = 0x04

# SOCKS5 reply codes
REP_SUCCESS = 0x00
REP_GENERAL_FAILURE = 0x01
REP_NOT_ALLOWED = 0x02
REP_NETWORK_UNREACHABLE = 0x03
REP_HOST_UNREACHABLE = 0x04
REP_CONNECTION_REFUSED = 0x05
REP_COMMAND_NOT_SUPPORTED = 0x07
REP_ADDRESS_NOT_SUPPORTED = 0x08


def is_always_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is in a range that can never be overridden by admin approval."""
    for network in ALWAYS_BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


def is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is in a private range that requires admin approval."""
    for network in PRIVATE_NETWORKS:
        if ip in network:
            return True
    return False


def is_lan_hostname(hostname: str) -> bool:
    """Check if hostname looks like a LAN name (needs ACL approval)."""
    h = hostname.lower()
    if h.endswith(LAN_SUFFIXES):
        return True
    if "." not in h:
        return True
    return False


# --- ACL file reader with caching ---


class ACLReader:
    """Reads approved hosts from the shared ACL file with TTL caching.

    Used for both private-IP gating and public-IP domain whitelisting.
    """

    def __init__(self, path: Path, ttl: float = 5.0):
        self._path = path
        self._ttl = ttl
        self._cache: set[str] = set()
        self._last_read: float = 0.0

    def _ensure_fresh(self) -> None:
        now = time.monotonic()
        if now - self._last_read > self._ttl:
            self._refresh()

    def is_approved(self, hostname: str) -> bool:
        """Check if hostname/IP is in the approved hosts list."""
        self._ensure_fresh()
        return hostname.lower() in self._cache

    def has_entries(self) -> bool:
        """Check if the ACL has any entries (i.e. servers are registered)."""
        self._ensure_fresh()
        return bool(self._cache)

    def _refresh(self) -> None:
        """Re-read the ACL file."""
        self._last_read = time.monotonic()
        try:
            text = self._path.read_text()
            self._cache = {
                line.strip().lower() for line in text.splitlines() if line.strip()
            }
        except FileNotFoundError:
            self._cache = set()
        except OSError as e:
            logger.warning("Failed to read ACL file %s: %s", self._path, e)


acl_reader = ACLReader(ACL_FILE, ACL_CACHE_TTL)


# --- Connection validation ---


def is_infrastructure_host(hostname: str) -> bool:
    """Check if hostname is a sandbox infrastructure host (always allowed)."""
    return hostname.lower() in INFRASTRUCTURE_HOSTS


def validate_connection(
    hostname: str,
    resolved_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str | None:
    """Validate whether a connection should be allowed.

    Returns None if allowed, or an error message string if blocked.

    Defense-in-depth layers:
      1. Always-blocked IPs (loopback, link-local, metadata) — never allowed
      2. Private IPs — require ACL approval
      3. Public IPs — infrastructure hosts always allowed; other hosts
         require ACL approval when servers are registered (ACL non-empty)

    Args:
        hostname: Original hostname from the SOCKS5 request (for ACL lookup).
        resolved_ip: The IP address that the hostname resolved to.
    """
    # Always-blocked ranges cannot be overridden
    if is_always_blocked(resolved_ip):
        return f"blocked: {resolved_ip} is in an always-blocked range (loopback/link-local/metadata)"

    # Private IPs require ACL approval
    if is_private(resolved_ip):
        # Check if the original hostname or the resolved IP is approved
        if acl_reader.is_approved(hostname) or acl_reader.is_approved(str(resolved_ip)):
            return None
        return (
            f"blocked: {resolved_ip} is a private IP and '{hostname}' "
            f"is not in the approved hosts list"
        )

    # Public IPs: domain whitelisting (defense-in-depth)
    # Infrastructure hosts are always allowed (sandbox internals need them)
    if is_infrastructure_host(hostname):
        return None

    # When ACL has entries (servers registered), enforce domain whitelisting.
    # The ACL contains the union of all servers' allowed_hosts — this is a
    # coarse filter. The app-layer SSRF check enforces per-server restrictions.
    if acl_reader.has_entries():
        if acl_reader.is_approved(hostname) or acl_reader.is_approved(str(resolved_ip)):
            return None
        return (
            f"blocked: '{hostname}' ({resolved_ip}) is not in the approved "
            f"hosts list or infrastructure hosts"
        )

    # ACL empty (no servers registered) — allow all public traffic
    return None


async def resolve_hostname(
    hostname: str, port: int
) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname to IP address.

    Returns (ip_string, ip_object) tuple.
    Raises OSError if resolution fails.
    """
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"DNS resolution failed for {hostname}")
    # Use first result
    family, _, _, _, sockaddr = infos[0]
    ip_str = sockaddr[0]
    return ip_str, ipaddress.ip_address(ip_str)


# --- SOCKS5 protocol handling ---


async def read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    """Read exactly n bytes, raising on EOF."""
    data = await reader.readexactly(n)
    return data


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single SOCKS5 client connection."""
    peer = writer.get_extra_info("peername")
    remote_writer: asyncio.StreamWriter | None = None

    try:
        # --- Method negotiation ---
        header = await asyncio.wait_for(read_exact(reader, 2), timeout=10)
        version, nmethods = struct.unpack("!BB", header)

        if version != SOCKS_VERSION:
            logger.warning("[%s] Invalid SOCKS version: %d", peer, version)
            writer.close()
            return

        methods = await asyncio.wait_for(read_exact(reader, nmethods), timeout=10)

        if AUTH_NONE not in methods:
            # No acceptable auth method
            writer.write(struct.pack("!BB", SOCKS_VERSION, 0xFF))
            await writer.drain()
            writer.close()
            return

        # Accept NO_AUTH
        writer.write(struct.pack("!BB", SOCKS_VERSION, AUTH_NONE))
        await writer.drain()

        # --- Connection request ---
        request_header = await asyncio.wait_for(read_exact(reader, 4), timeout=10)
        ver, cmd, _rsv, atyp = struct.unpack("!BBBB", request_header)

        if ver != SOCKS_VERSION:
            await _send_reply(writer, REP_GENERAL_FAILURE)
            return

        if cmd != CMD_CONNECT:
            await _send_reply(writer, REP_COMMAND_NOT_SUPPORTED)
            return

        # Parse address
        if atyp == ATYP_IPV4:
            addr_bytes = await asyncio.wait_for(read_exact(reader, 4), timeout=10)
            target_host = socket.inet_ntoa(addr_bytes)
        elif atyp == ATYP_DOMAINNAME:
            length = (await asyncio.wait_for(read_exact(reader, 1), timeout=10))[0]
            target_host = (
                await asyncio.wait_for(read_exact(reader, length), timeout=10)
            ).decode("ascii")
        elif atyp == ATYP_IPV6:
            addr_bytes = await asyncio.wait_for(read_exact(reader, 16), timeout=10)
            target_host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
        else:
            await _send_reply(writer, REP_ADDRESS_NOT_SUPPORTED)
            return

        port_bytes = await asyncio.wait_for(read_exact(reader, 2), timeout=10)
        target_port = struct.unpack("!H", port_bytes)[0]

        # --- Resolve and validate ---
        try:
            ip_str, ip_obj = await asyncio.wait_for(
                resolve_hostname(target_host, target_port),
                timeout=CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as e:
            logger.info("[%s] DNS resolution failed for %s: %s", peer, target_host, e)
            await _send_reply(writer, REP_HOST_UNREACHABLE)
            return

        error = validate_connection(target_host, ip_obj)
        if error is not None:
            logger.info("[%s] %s:%d -> %s", peer, target_host, target_port, error)
            await _send_reply(writer, REP_NOT_ALLOWED)
            return

        # --- Connect to target ---
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(ip_str, target_port),
                timeout=CONNECT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.info(
                "[%s] Connection to %s:%d timed out", peer, target_host, target_port
            )
            await _send_reply(writer, REP_HOST_UNREACHABLE)
            return
        except ConnectionRefusedError:
            logger.info(
                "[%s] Connection to %s:%d refused", peer, target_host, target_port
            )
            await _send_reply(writer, REP_CONNECTION_REFUSED)
            return
        except OSError as e:
            logger.info(
                "[%s] Connection to %s:%d failed: %s", peer, target_host, target_port, e
            )
            await _send_reply(writer, REP_NETWORK_UNREACHABLE)
            return

        # --- Send success reply ---
        # Bind address: use the connected socket's local address
        local_addr = remote_writer.get_extra_info("sockname")
        await _send_reply(writer, REP_SUCCESS, local_addr[0], local_addr[1])

        logger.info(
            "[%s] CONNECT %s:%d -> %s:%d",
            peer,
            target_host,
            target_port,
            ip_str,
            target_port,
        )

        # --- Relay data bidirectionally ---
        await _relay(reader, writer, remote_reader, remote_writer)

    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
        pass
    except Exception:
        logger.exception("[%s] Unexpected error", peer)
    finally:
        writer.close()
        if remote_writer is not None:
            remote_writer.close()


async def _send_reply(
    writer: asyncio.StreamWriter,
    reply_code: int,
    bind_addr: str = "0.0.0.0",
    bind_port: int = 0,
) -> None:
    """Send a SOCKS5 reply."""
    try:
        ip = ipaddress.ip_address(bind_addr)
        if isinstance(ip, ipaddress.IPv4Address):
            addr_bytes = struct.pack("!B4s", ATYP_IPV4, ip.packed)
        else:
            addr_bytes = struct.pack("!B16s", ATYP_IPV6, ip.packed)
    except ValueError:
        addr_bytes = struct.pack("!B4s", ATYP_IPV4, b"\x00\x00\x00\x00")

    reply = (
        struct.pack("!BBB", SOCKS_VERSION, reply_code, 0x00)
        + addr_bytes
        + struct.pack("!H", bind_port)
    )
    writer.write(reply)
    await writer.drain()


async def _relay(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    remote_reader: asyncio.StreamReader,
    remote_writer: asyncio.StreamWriter,
) -> None:
    """Relay data bidirectionally between client and remote."""

    async def forward(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
        try:
            while True:
                data = await src.read(RELAY_BUFFER_SIZE)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                if dst.can_write_eof():
                    dst.write_eof()
            except (ConnectionError, OSError):
                pass

    task1 = asyncio.create_task(forward(client_reader, remote_writer))
    task2 = asyncio.create_task(forward(remote_reader, client_writer))

    # Wait for either direction to finish, then cancel the other
    done, pending = await asyncio.wait(
        [task1, task2], return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    # Suppress cancellation errors
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("SOCKS5 proxy listening on %s", addrs)
    logger.info("ACL file: %s (TTL: %ss)", ACL_FILE, ACL_CACHE_TTL)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
