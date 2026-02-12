"""Rate limiting middleware for API protection."""

import asyncio
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.request_utils import _is_valid_ip

logger = logging.getLogger(__name__)

# Trusted proxy IPs that are allowed to set X-Forwarded-For
# Add your reverse proxy IPs here (e.g., Cloudflare IPs, nginx, etc.)
# If empty, X-Forwarded-For headers are trusted from any source (less secure)
TRUSTED_PROXY_IPS = {
    ip.strip() for ip in os.environ.get("TRUSTED_PROXY_IPS", "").split(",") if ip.strip()
}


@dataclass
class PathRateLimitConfig:
    """Configuration for rate limiting a specific path pattern."""

    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10


@dataclass
class RateLimitBucket:
    """Rate limit tracking for a single client+path combination."""

    tokens: float = 10.0
    last_update: float = field(default_factory=time.monotonic)
    minute_requests: list[float] = field(default_factory=list)
    hour_requests: list[float] = field(default_factory=list)


class RateLimiter:
    """In-memory rate limiter with per-path configuration.

    Designed for single-instance homelab deployments.
    """

    _instance: Optional["RateLimiter"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._buckets: dict[str, RateLimitBucket] = defaultdict(RateLimitBucket)
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()

        # Per-path rate limit configurations
        self._path_configs: dict[str, PathRateLimitConfig] = {
            # Health endpoints - reasonable limits for monitoring (allows checks every 2s)
            # Most monitoring systems check every 10-30 seconds
            "/health": PathRateLimitConfig(
                requests_per_minute=30,
                requests_per_hour=600,
                burst_size=10,
            ),
            "/mcp/health": PathRateLimitConfig(
                requests_per_minute=30,
                requests_per_hour=600,
                burst_size=10,
            ),
            # Tool execution - allow reasonable throughput
            "/api/tools/": PathRateLimitConfig(
                requests_per_minute=60,
                requests_per_hour=1000,
                burst_size=15,
            ),
            # MCP gateway - moderate limits to balance usability and DoS prevention
            # Management tools (mcpbox_*) also use this endpoint
            "/mcp": PathRateLimitConfig(
                requests_per_minute=60,
                requests_per_hour=1000,
                burst_size=15,
            ),
        }

        # Default config for unmatched paths
        self._default_config = PathRateLimitConfig(
            requests_per_minute=100,
            requests_per_hour=2000,
            burst_size=20,
        )

    @classmethod
    def get_instance(cls) -> "RateLimiter":
        """Get the singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_config_for_path(self, path: str) -> PathRateLimitConfig:
        """Get rate limit config for a given path."""
        for prefix, config in self._path_configs.items():
            if path.startswith(prefix):
                return config
        return self._default_config

    def _get_bucket_key(self, client_ip: str, path: str) -> str:
        """Get bucket key for client and path combination."""
        # Group by path prefix
        for prefix in self._path_configs.keys():
            if path.startswith(prefix):
                return f"{client_ip}:{prefix}"
        return f"{client_ip}:default"

    def _cleanup_old_requests(self, bucket: RateLimitBucket, now: float) -> None:
        """Remove old request timestamps from bucket."""
        minute_cutoff = now - 60
        hour_cutoff = now - 3600

        bucket.minute_requests = [ts for ts in bucket.minute_requests if ts > minute_cutoff]
        bucket.hour_requests = [ts for ts in bucket.hour_requests if ts > hour_cutoff]

    async def check_rate_limit(
        self,
        client_ip: str,
        path: str,
    ) -> tuple[bool, dict[str, str]]:
        """Check if request is allowed.

        Returns:
            Tuple of (is_allowed, headers_dict)
        """
        config = self.get_config_for_path(path)
        bucket_key = self._get_bucket_key(client_ip, path)

        async with self._lock:
            bucket = self._buckets[bucket_key]
            now = time.monotonic()

            # Clean up old requests
            self._cleanup_old_requests(bucket, now)

            # Calculate remaining requests
            minute_count = len(bucket.minute_requests)
            hour_count = len(bucket.hour_requests)

            minute_remaining = config.requests_per_minute - minute_count
            hour_remaining = config.requests_per_hour - hour_count

            # Build headers
            headers = {
                "X-RateLimit-Limit": str(config.requests_per_minute),
                "X-RateLimit-Remaining": str(max(0, minute_remaining - 1)),
                "X-RateLimit-Limit-Hour": str(config.requests_per_hour),
                "X-RateLimit-Remaining-Hour": str(max(0, hour_remaining - 1)),
            }

            # Check minute limit
            if minute_remaining <= 0:
                oldest = min(bucket.minute_requests) if bucket.minute_requests else now
                reset_seconds = max(1, int(60 - (now - oldest)))
                headers["Retry-After"] = str(reset_seconds)
                headers["X-RateLimit-Reset"] = str(reset_seconds)
                return False, headers

            # Check hour limit
            if hour_remaining <= 0:
                oldest = min(bucket.hour_requests) if bucket.hour_requests else now
                reset_seconds = max(1, int(3600 - (now - oldest)))
                headers["Retry-After"] = str(reset_seconds)
                headers["X-RateLimit-Reset"] = str(reset_seconds)
                return False, headers

            # Token bucket for burst control
            elapsed = now - bucket.last_update
            refill_rate = config.requests_per_minute / 60.0
            bucket.tokens = min(
                config.burst_size,
                bucket.tokens + elapsed * refill_rate,
            )
            bucket.last_update = now

            if bucket.tokens < 1.0:
                headers["Retry-After"] = "1"
                return False, headers

            # Allow request - consume token and record timestamp
            bucket.tokens -= 1.0
            bucket.minute_requests.append(now)
            bucket.hour_requests.append(now)

            return True, headers

    async def get_stats(self) -> dict[str, dict]:
        """Get current rate limit statistics."""
        async with self._lock:
            stats = {}
            for key, bucket in self._buckets.items():
                stats[key] = {
                    "minute_count": len(bucket.minute_requests),
                    "hour_count": len(bucket.hour_requests),
                    "tokens": round(bucket.tokens, 2),
                }
            return stats

    async def reset(self, client_ip: str | None = None) -> None:
        """Reset rate limit counters (thread-safe)."""
        async with self._lock:
            if client_ip:
                keys_to_remove = [k for k in self._buckets.keys() if k.startswith(f"{client_ip}:")]
                for key in keys_to_remove:
                    del self._buckets[key]
            else:
                self._buckets.clear()

    async def cleanup_inactive_buckets(self, inactive_seconds: int = 86400) -> int:
        """Remove buckets that have been inactive for the specified duration.

        This prevents unbounded memory growth from abandoned client IPs.

        Args:
            inactive_seconds: Duration of inactivity before bucket is removed (default: 24h)

        Returns:
            Number of buckets removed
        """
        async with self._lock:
            now = time.monotonic()
            cutoff = now - inactive_seconds
            keys_to_remove = []

            for key, bucket in self._buckets.items():
                # A bucket is inactive if its last update is older than cutoff
                # and it has no recent requests
                if bucket.last_update < cutoff:
                    # Also check that there are no requests in the current window
                    if not bucket.minute_requests and not bucket.hour_requests:
                        keys_to_remove.append(key)
                    elif bucket.minute_requests and max(bucket.minute_requests) < cutoff:
                        # All requests are older than cutoff
                        keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._buckets[key]

            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} inactive rate limit buckets")

            return len(keys_to_remove)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with per-endpoint configuration.

    Features:
    - Per-IP rate limiting
    - Different limits for different endpoint groups (LLM, import, etc.)
    - Token bucket algorithm for burst control
    - Sliding window for minute/hour limits
    - Rate limit headers on responses
    """

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 100,  # Default, overridden by path config
        exclude_paths: list[str] | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.default_rpm = requests_per_minute
        self.exclude_paths = exclude_paths or [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        self.enabled = enabled
        self.rate_limiter = RateLimiter.get_instance()

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request.

        Security: X-Forwarded-For headers can be spoofed by clients.
        When TRUSTED_PROXY_IPS is configured, only trust the header
        if the direct connection comes from a trusted proxy.
        """
        direct_ip = request.client.host if request.client else None

        # Check for forwarded headers (proxy scenarios)
        # SECURITY: Only trust X-Forwarded-For/X-Real-IP if TRUSTED_PROXY_IPS is configured
        # and the direct connection comes from a trusted proxy. Never trust these headers
        # from arbitrary sources as they can be spoofed to bypass rate limiting.
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Only trust X-Forwarded-For if trusted proxies are configured AND
            # the direct connection is from a trusted proxy
            if TRUSTED_PROXY_IPS and direct_ip and direct_ip in TRUSTED_PROXY_IPS:
                client_ip = forwarded.split(",")[0].strip()
                if _is_valid_ip(client_ip):
                    return client_ip
                else:
                    logger.warning(f"Invalid IP in X-Forwarded-For header: {client_ip}")
            elif not TRUSTED_PROXY_IPS:
                # No trusted proxies configured - ignore forwarded headers entirely
                logger.debug("X-Forwarded-For header ignored: TRUSTED_PROXY_IPS not configured")
            else:
                logger.debug(f"Ignoring X-Forwarded-For from untrusted source: {direct_ip}")

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            # Same security check for X-Real-IP
            if TRUSTED_PROXY_IPS and direct_ip and direct_ip in TRUSTED_PROXY_IPS:
                if _is_valid_ip(real_ip):
                    return real_ip
                else:
                    logger.warning(f"Invalid IP in X-Real-IP header: {real_ip}")

        if direct_ip:
            return direct_ip

        return "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request with rate limiting."""
        # Skip if disabled
        if not self.enabled:
            return await call_next(request)

        # Skip rate limiting for excluded paths
        path = request.url.path
        if any(path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        is_allowed, headers = await self.rate_limiter.check_rate_limit(client_ip, path)

        if not is_allowed:
            logger.warning(f"Rate limit exceeded for {client_ip} on {path}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Rate limit exceeded. Please try again later.",
                    "retry_after": int(headers.get("Retry-After", 60)),
                },
                headers=headers,
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers to response
        for key, value in headers.items():
            if not key.startswith("Retry"):
                response.headers[key] = str(value)

        return response


def get_rate_limiter() -> RateLimiter:
    """Get the rate limiter singleton for stats/management."""
    return RateLimiter.get_instance()
