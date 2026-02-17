"""SSRF Prevention utilities for sandbox code execution.

Provides URL validation and protected HTTP clients to prevent
Server-Side Request Forgery (SSRF) attacks.

Implements IP pinning to prevent DNS rebinding attacks:
- DNS is resolved once during validation
- The resolved IP is used for the actual request
- This prevents attackers from using DNS that changes between validation and request
"""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urlunparse

import httpx

# Blocked IP ranges (private, loopback, link-local, metadata endpoints)
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local (AWS metadata)
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("::/128"),  # IPv6 unspecified
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("ff00::/8"),  # IPv6 multicast
]

BLOCKED_HOSTNAMES = {
    # Loopback addresses
    "localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "ip6-localhost",
    "ip6-loopback",
    # AWS metadata endpoints
    "169.254.169.254",
    "metadata.aws.internal",
    "instance-data.ec2.internal",
    # GCP metadata endpoints
    "metadata.google.internal",
    "metadata.gke.internal",
    # Azure metadata endpoints
    "169.254.169.255",
    "metadata.azure.com",
    # Kubernetes internal DNS
    "kubernetes",
    "kubernetes.default",
    "kubernetes.default.svc",
    "kubernetes.default.svc.cluster.local",
}


class SSRFError(Exception):
    """Raised when a URL is blocked for SSRF prevention.

    This includes private IPs, loopback addresses, cloud metadata endpoints,
    and any URL that resolves to a blocked IP range.
    """


@dataclass
class ValidatedURL:
    """Result of URL validation with IP pinning."""

    original_url: str
    pinned_ip: str
    hostname: str
    port: int
    scheme: str

    def get_pinned_url(self) -> str:
        """Get URL with IP instead of hostname for direct connection."""
        if ":" in self.pinned_ip:
            host = f"[{self.pinned_ip}]"
        else:
            host = self.pinned_ip

        default_port = 443 if self.scheme == "https" else 80
        if self.port != default_port:
            netloc = f"{host}:{self.port}"
        else:
            netloc = host

        parsed = urlparse(self.original_url)
        return urlunparse(
            (
                self.scheme,
                netloc,
                parsed.path or "/",
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/internal range.

    Handles IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1) by extracting
    the embedded IPv4 address and checking it separately.
    """
    try:
        ip = ipaddress.ip_address(ip_str)

        # Handle IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1)
        # These embed an IPv4 address in IPv6 format and could bypass checks
        if isinstance(ip, ipaddress.IPv6Address):
            # Check if it's an IPv4-mapped address
            if ip.ipv4_mapped is not None:
                # Extract the IPv4 address and check it
                ipv4 = ip.ipv4_mapped
                for network in BLOCKED_IP_RANGES:
                    # Only check against IPv4 networks
                    if isinstance(network, ipaddress.IPv4Network) and ipv4 in network:
                        return True
            # Also check for IPv4-compatible addresses (deprecated but possible)
            # These are in the format ::x.x.x.x
            if ip.packed[:12] == b"\x00" * 12:
                ipv4_bytes = ip.packed[12:]
                try:
                    ipv4 = ipaddress.IPv4Address(ipv4_bytes)
                    for network in BLOCKED_IP_RANGES:
                        if (
                            isinstance(network, ipaddress.IPv4Network)
                            and ipv4 in network
                        ):
                            return True
                except ValueError:
                    pass

        # Standard check against all blocked ranges
        for network in BLOCKED_IP_RANGES:
            if ip in network:
                return True
        return False
    except ValueError:
        return False


def validate_url_with_pinning(url: str) -> ValidatedURL:
    """Validate a URL and return pinned IP to prevent DNS rebinding.

    Args:
        url: The URL to validate

    Returns:
        ValidatedURL with pinned IP address

    Raises:
        SSRFError: If the URL targets internal resources
    """
    if not url:
        raise SSRFError("URL cannot be empty")

    try:
        parsed = urlparse(str(url))
    except Exception as e:
        raise SSRFError(f"Invalid URL format: {e}")

    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Invalid scheme: {parsed.scheme}. Only http/https allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL must have a hostname")

    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise SSRFError(f"Blocked hostname: {hostname}")

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    pinned_ip: Optional[str] = None

    # Check if hostname is an IP address in blocked range
    try:
        ip = ipaddress.ip_address(hostname)
        for blocked_range in BLOCKED_IP_RANGES:
            if ip in blocked_range:
                raise SSRFError(f"URL targets blocked IP range: {hostname}")
        pinned_ip = hostname
    except ValueError:
        # Not an IP address, it's a hostname - resolve it
        try:
            addr_info = socket.getaddrinfo(
                hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            for result in addr_info:
                ip_str = result[4][0]
                if _is_private_ip(ip_str):
                    raise SSRFError(
                        f"Hostname {hostname} resolves to blocked IP: {ip_str}"
                    )
                if pinned_ip is None:
                    pinned_ip = ip_str
        except socket.gaierror as e:
            raise SSRFError(f"DNS resolution failed for {hostname}: {e}")

    if pinned_ip is None:
        raise SSRFError(f"No valid IP addresses found for '{hostname}'")

    return ValidatedURL(
        original_url=url,
        pinned_ip=pinned_ip,
        hostname=hostname,
        port=port,
        scheme=parsed.scheme,
    )


def _prepare_pinned_request(url: str, kwargs: dict) -> tuple[str, dict]:
    """Validate URL and prepare request with IP pinning.

    Returns the pinned URL and updated kwargs with Host header and SNI hostname.
    """
    validated = validate_url_with_pinning(str(url))
    pinned_url = validated.get_pinned_url()

    # Set Host header to original hostname
    headers = kwargs.get("headers", {})
    if isinstance(headers, dict):
        headers = dict(headers)  # Don't modify original
    headers["Host"] = validated.hostname
    kwargs["headers"] = headers

    # Set SNI hostname for HTTPS connections with IP pinning.
    # When we rewrite the URL to use the resolved IP, TLS SNI defaults to the IP
    # instead of the original hostname. Servers that require hostname-based SNI
    # will reject the handshake. httpx supports overriding SNI via extensions.
    if validated.scheme == "https" and validated.pinned_ip != validated.hostname:
        extensions = kwargs.get("extensions", {})
        extensions["sni_hostname"] = validated.hostname.encode("ascii")
        kwargs["extensions"] = extensions

    return pinned_url, kwargs


class SSRFProtectedHttpx:
    """SSRF-protected wrapper for httpx module (synchronous).

    Validates all URLs and uses IP pinning to prevent DNS rebinding attacks.
    Explicitly disables follow_redirects to prevent redirect-based SSRF bypasses.
    """

    @classmethod
    def _prepare_request(cls, url: str, kwargs: dict) -> tuple[str, dict]:
        """Validate URL and prepare request with IP pinning."""
        # Force-disable redirects to prevent redirect-based SSRF bypass
        kwargs["follow_redirects"] = False
        try:
            return _prepare_pinned_request(url, kwargs)
        except SSRFError as e:
            raise ValueError(str(e))

    @classmethod
    def get(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.get(pinned_url, **kwargs)

    @classmethod
    def post(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.post(pinned_url, **kwargs)

    @classmethod
    def put(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.put(pinned_url, **kwargs)

    @classmethod
    def patch(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.patch(pinned_url, **kwargs)

    @classmethod
    def delete(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.delete(pinned_url, **kwargs)

    @classmethod
    def head(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.head(pinned_url, **kwargs)

    @classmethod
    def options(cls, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.options(pinned_url, **kwargs)

    @classmethod
    def request(cls, method, url, **kwargs):
        pinned_url, kwargs = cls._prepare_request(url, kwargs)
        return httpx.request(method, pinned_url, **kwargs)


class SSRFProtectedAsyncHttpClient:
    """Wrapper around httpx.AsyncClient that validates URLs before requests.

    Uses IP pinning to prevent DNS rebinding attacks.
    Uses __slots__ to prevent sandbox code from accessing the underlying
    client via attribute access (e.g., http._client).

    Optionally enforces a per-server network allowlist: if allowed_hosts is
    provided, only those hostnames can be contacted (in addition to the
    standard SSRF blocklist checks).
    """

    __slots__ = ("__wrapped_client", "__allowed_hosts")

    def __init__(
        self,
        client: httpx.AsyncClient,
        allowed_hosts: set[str] | None = None,
    ):
        # Use object.__setattr__ to bypass our __setattr__ guard
        object.__setattr__(
            self, "_SSRFProtectedAsyncHttpClient__wrapped_client", client
        )
        # None means no allowlist enforcement (server in "isolated" or no config).
        # Empty set means explicitly no hosts allowed.
        object.__setattr__(
            self, "_SSRFProtectedAsyncHttpClient__allowed_hosts", allowed_hosts
        )

    def __getattr__(self, name: str):
        raise AttributeError(
            f"Access to '{name}' is not allowed on the HTTP client. "
            f"Use http.get(), http.post(), etc."
        )

    def __setattr__(self, name: str, value):
        raise AttributeError("Cannot set attributes on the HTTP client")

    def _prepare_request(self, url: str, kwargs: dict) -> tuple[str, dict]:
        """Validate URL and prepare request with IP pinning.

        Also enforces the per-server network allowlist if configured.
        """
        # Force-disable redirects to prevent redirect-based SSRF bypass.
        # The underlying client may have been configured with follow_redirects=True;
        # per-request kwargs override the client-level setting in httpx.
        kwargs["follow_redirects"] = False

        # Enforce network allowlist before SSRF validation.
        # If allowed_hosts is set (even if empty), only those hosts are permitted.
        if self.__allowed_hosts is not None:
            parsed = urlparse(str(url))
            hostname = (parsed.hostname or "").lower()
            if hostname not in self.__allowed_hosts:
                raise SSRFError(
                    f"Network access to '{hostname}' is not approved for this server. "
                    f"Use mcpbox_request_network_access to request access."
                )

        return _prepare_pinned_request(url, kwargs)

    async def get(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.get(pinned_url, **kwargs)

    async def post(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.post(pinned_url, **kwargs)

    async def put(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.put(pinned_url, **kwargs)

    async def patch(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.patch(pinned_url, **kwargs)

    async def delete(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.delete(pinned_url, **kwargs)

    async def head(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.head(pinned_url, **kwargs)

    async def options(self, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.options(pinned_url, **kwargs)

    async def request(self, method, url, **kwargs):
        pinned_url, kwargs = self._prepare_request(url, kwargs)
        return await self.__wrapped_client.request(method, pinned_url, **kwargs)
