"""Request utility functions for handling common request operations."""

import ipaddress
import logging

from fastapi import Request

logger = logging.getLogger(__name__)


def _is_valid_ip(ip_str: str) -> bool:
    """Check if a string is a valid IP address."""
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def get_client_ip(request: Request) -> str | None:
    """Get the client IP address from a request.

    Security Priority Order:
    1. CF-Connecting-IP (Cloudflare - cryptographically guaranteed by tunnel)
    2. X-Real-IP (trusted proxy header)
    3. Direct client connection

    X-Forwarded-For is NOT trusted as it can be easily spoofed.
    Use CF-Connecting-IP from Cloudflare for MCP gateway requests.

    For local admin panel requests, direct client connection is used.

    Args:
        request: The FastAPI request object

    Returns:
        Client IP address or None if not available
    """
    # Priority 1: CF-Connecting-IP header (Cloudflare-specific, most secure)
    # This header is set by Cloudflare and cannot be spoofed by clients
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        ip = cf_ip.strip()
        if _is_valid_ip(ip):
            return ip
        else:
            logger.warning(f"Invalid CF-Connecting-IP: {cf_ip}")

    # Priority 2: X-Real-IP header - only trust when request comes from localhost
    # This prevents IP spoofing attacks from external clients
    # (Legitimate proxies like nginx running locally can set this header)
    if request.client and request.client.host in ("127.0.0.1", "::1", "localhost"):
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            ip = real_ip.strip()
            if _is_valid_ip(ip):
                return ip
            else:
                logger.warning(f"Invalid X-Real-IP: {real_ip}")

    # Priority 3: Fall back to direct client connection
    # This is used for local admin panel access
    if request.client:
        return request.client.host

    return None
