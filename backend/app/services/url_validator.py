"""URL validation utilities for SSRF prevention.

Implements IP pinning to prevent DNS rebinding attacks:
- DNS is resolved once during validation
- The resolved IP is returned and must be used for the actual request
- This prevents attackers from using DNS that changes between validation and request
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


class SSRFError(Exception):
    """Raised when a URL is blocked for SSRF prevention.

    This includes private IPs, loopback addresses, cloud metadata endpoints,
    and any URL that resolves to a blocked IP range.
    """


@dataclass
class ValidatedURL:
    """Result of URL validation with IP pinning.

    Attributes:
        original_url: The original URL as provided
        pinned_ip: The resolved IP address to connect to
        hostname: The original hostname (for Host header)
        port: The port to connect to
        scheme: http or https
        path: The path portion of the URL
    """

    original_url: str
    pinned_ip: str
    hostname: str
    port: int
    scheme: str
    path: str

    def get_pinned_url(self) -> str:
        """Get URL with IP instead of hostname for direct connection."""
        # For IPv6, wrap in brackets
        if ":" in self.pinned_ip:
            host = f"[{self.pinned_ip}]"
        else:
            host = self.pinned_ip

        # Include port if non-standard
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


# Private/internal IP ranges that should be blocked
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("::/128"),  # IPv6 unspecified
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("ff00::/8"),  # IPv6 multicast
]

# Blocked hostnames - comprehensive list for SSRF prevention
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


def is_private_ip(ip_str: str) -> bool:
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
                        if isinstance(network, ipaddress.IPv4Network) and ipv4 in network:
                            return True
                except ValueError:
                    pass

        # Standard check against all blocked ranges
        for network in BLOCKED_IP_RANGES:
            if ip in network:
                return True
        return False
    except ValueError:
        # Invalid IP address
        return False


def validate_url_with_pinning(url: str) -> ValidatedURL:
    """Validate a URL and return pinned IP to prevent DNS rebinding.

    This function resolves DNS once and returns the IP address that MUST be used
    for the actual HTTP request. This prevents DNS rebinding attacks where an
    attacker's DNS returns a safe IP during validation but a private IP during
    the actual request.

    Args:
        url: The URL to validate

    Returns:
        ValidatedURL with pinned IP address

    Raises:
        SSRFError: If the URL targets internal/private resources
    """
    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFError(f"Invalid URL format: {e}") from e

    # Check scheme
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"URL scheme must be http or https, got: {parsed.scheme}")

    # Check for empty host
    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL must have a hostname")

    # Check against blocked hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise SSRFError(f"Access to '{hostname}' is not allowed")

    # Determine port
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    # Resolve hostname and check IP - this is the pinned IP we'll use
    pinned_ip: str | None = None
    try:
        # Get all IP addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _, _, _, sockaddr in addr_info:
            ip_str = str(sockaddr[0])
            if is_private_ip(ip_str):
                raise SSRFError(
                    f"URL resolves to private IP address ({ip_str}). "
                    "Access to internal resources is not allowed."
                )
            # Use the first valid IP as our pinned address
            if pinned_ip is None:
                pinned_ip = ip_str
    except socket.gaierror:
        # DNS resolution failed - block the request to prevent bypass attacks
        raise SSRFError(
            f"DNS resolution failed for '{hostname}'. Cannot verify the URL is safe to access."
        ) from None

    if pinned_ip is None:
        raise SSRFError(f"No valid IP addresses found for '{hostname}'")

    return ValidatedURL(
        original_url=url,
        pinned_ip=pinned_ip,
        hostname=hostname,
        port=port,
        scheme=parsed.scheme,
        path=parsed.path or "/",
    )
