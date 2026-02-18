"""Tests for the rate limiting middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.rate_limit import (
    PathRateLimitConfig,
    RateLimiter,
    RateLimitMiddleware,
    _is_valid_ip,
)


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    @pytest.fixture
    def rate_limiter(self):
        """Create a fresh rate limiter instance."""
        # Reset singleton for testing
        RateLimiter._instance = None
        return RateLimiter()

    @pytest.mark.asyncio
    async def test_allows_first_request(self, rate_limiter):
        """Test that the first request is always allowed."""
        allowed, headers = await rate_limiter.check_rate_limit("192.168.1.1", "/api/test")

        assert allowed is True
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers

    @pytest.mark.asyncio
    async def test_rate_limit_headers(self, rate_limiter):
        """Test that rate limit headers are returned."""
        _, headers = await rate_limiter.check_rate_limit("192.168.1.1", "/api/test")

        assert headers["X-RateLimit-Limit"] == "100"  # Default limit
        assert int(headers["X-RateLimit-Remaining"]) >= 0

    @pytest.mark.asyncio
    async def test_per_path_config_mcp(self, rate_limiter):
        """Test that /mcp path has specific rate limits."""
        config = rate_limiter.get_config_for_path("/mcp")

        assert config.requests_per_minute == 300
        assert config.requests_per_hour == 5000

    @pytest.mark.asyncio
    async def test_default_config_for_unknown_path(self, rate_limiter):
        """Test that unknown paths use default config."""
        config = rate_limiter.get_config_for_path("/api/unknown")

        assert config.requests_per_minute == 100
        assert config.requests_per_hour == 2000

    @pytest.mark.asyncio
    async def test_separate_buckets_per_ip(self, rate_limiter):
        """Test that different IPs have separate rate limit buckets."""
        # Make request from first IP
        allowed1, _ = await rate_limiter.check_rate_limit("192.168.1.1", "/api/test")
        # Make request from second IP
        allowed2, _ = await rate_limiter.check_rate_limit("192.168.1.2", "/api/test")

        assert allowed1 is True
        assert allowed2 is True

        # Both should have their own remaining counts
        stats = await rate_limiter.get_stats()
        assert "192.168.1.1:default" in stats
        assert "192.168.1.2:default" in stats

    @pytest.mark.asyncio
    async def test_burst_limiting(self, rate_limiter):
        """Test that burst limits are enforced."""
        # Make many rapid requests
        client_ip = "192.168.1.100"
        results = []

        for _ in range(30):  # Exceed burst size
            allowed, _ = await rate_limiter.check_rate_limit(client_ip, "/api/test")
            results.append(allowed)

        # Some should be rejected due to burst limiting
        assert False in results

    @pytest.mark.asyncio
    async def test_minute_limit_enforced(self, rate_limiter):
        """Test that minute-based rate limits are enforced."""
        # Create a path with very low limit for testing
        rate_limiter._path_configs["/test/limited"] = PathRateLimitConfig(
            requests_per_minute=5,
            requests_per_hour=100,
            burst_size=10,
        )

        client_ip = "192.168.1.200"
        allowed_count = 0

        for _ in range(10):
            allowed, headers = await rate_limiter.check_rate_limit(client_ip, "/test/limited")
            if allowed:
                allowed_count += 1
            else:
                assert "Retry-After" in headers
                break

        # Should allow up to the minute limit
        assert allowed_count <= 5

    @pytest.mark.asyncio
    async def test_update_mcp_config(self, rate_limiter):
        """Test that update_mcp_config changes the /mcp path limits."""
        rate_limiter.update_mcp_config(500)

        config = rate_limiter.get_config_for_path("/mcp")
        assert config.requests_per_minute == 500
        assert config.requests_per_hour == 500 * 17
        assert config.burst_size == 50  # 500 // 10

    @pytest.mark.asyncio
    async def test_update_mcp_config_minimum_burst(self, rate_limiter):
        """Test that burst size has a minimum of 5."""
        rate_limiter.update_mcp_config(10)

        config = rate_limiter.get_config_for_path("/mcp")
        assert config.requests_per_minute == 10
        assert config.burst_size == 5  # max(5, 10 // 10) = max(5, 1) = 5

    @pytest.mark.asyncio
    async def test_reset_clears_buckets(self, rate_limiter):
        """Test that reset clears rate limit buckets."""
        client_ip = "192.168.1.50"

        # Make some requests
        await rate_limiter.check_rate_limit(client_ip, "/api/test")
        await rate_limiter.check_rate_limit(client_ip, "/api/test")

        stats_before = await rate_limiter.get_stats()
        assert len(stats_before) > 0

        # Reset
        await rate_limiter.reset()

        stats_after = await rate_limiter.get_stats()
        assert len(stats_after) == 0

    @pytest.mark.asyncio
    async def test_reset_specific_ip(self, rate_limiter):
        """Test that reset can clear a specific IP's buckets."""
        # Make requests from two IPs
        await rate_limiter.check_rate_limit("192.168.1.10", "/api/test")
        await rate_limiter.check_rate_limit("192.168.1.20", "/api/test")

        # Reset only one IP
        await rate_limiter.reset("192.168.1.10")

        stats = await rate_limiter.get_stats()
        assert "192.168.1.10:default" not in stats
        assert "192.168.1.20:default" in stats


class TestIPValidation:
    """Tests for IP address validation."""

    def test_valid_ipv4(self):
        """Test valid IPv4 addresses."""
        assert _is_valid_ip("192.168.1.1") is True
        assert _is_valid_ip("10.0.0.1") is True
        assert _is_valid_ip("8.8.8.8") is True

    def test_valid_ipv6(self):
        """Test valid IPv6 addresses."""
        assert _is_valid_ip("::1") is True
        assert _is_valid_ip("2001:db8::1") is True

    def test_invalid_ip(self):
        """Test invalid IP addresses."""
        assert _is_valid_ip("not-an-ip") is False
        assert _is_valid_ip("256.256.256.256") is False
        assert _is_valid_ip("") is False


class TestRateLimitMiddleware:
    """Tests for the rate limit middleware."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        RateLimiter._instance = None  # Reset singleton
        app = AsyncMock()
        return RateLimitMiddleware(app, enabled=True)

    @pytest.mark.asyncio
    async def test_excludes_health_endpoint(self, middleware):
        """Test that health endpoints are excluded from rate limiting."""
        request = MagicMock()
        request.url.path = "/health"
        request.client.host = "192.168.1.1"

        call_next = AsyncMock()
        response = MagicMock()
        call_next.return_value = response

        await middleware.dispatch(request, call_next)

        # Health endpoint should pass through
        call_next.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_excludes_docs_endpoint(self, middleware):
        """Test that docs endpoints are excluded from rate limiting."""
        request = MagicMock()
        request.url.path = "/docs"
        request.client.host = "192.168.1.1"

        call_next = AsyncMock()
        response = MagicMock()
        call_next.return_value = response

        await middleware.dispatch(request, call_next)

        call_next.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_disabled_middleware_passes_through(self):
        """Test that disabled middleware passes all requests."""
        RateLimiter._instance = None
        app = AsyncMock()
        middleware = RateLimitMiddleware(app, enabled=False)

        request = MagicMock()
        request.url.path = "/api/test"
        request.client.host = "192.168.1.1"

        call_next = AsyncMock()
        response = MagicMock()
        call_next.return_value = response

        await middleware.dispatch(request, call_next)

        call_next.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_adds_rate_limit_headers_to_response(self, middleware):
        """Test that rate limit headers are added to responses."""
        request = MagicMock()
        request.url.path = "/api/test"
        request.client.host = "192.168.1.1"
        request.headers = {}

        call_next = AsyncMock()
        response = MagicMock()
        response.headers = {}
        call_next.return_value = response

        await middleware.dispatch(request, call_next)

        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers

    @pytest.mark.asyncio
    async def test_returns_429_when_rate_limited(self, middleware):
        """Test that 429 is returned when rate limit is exceeded."""
        # Configure very low limit for testing
        middleware.rate_limiter._path_configs["/test/limited"] = PathRateLimitConfig(
            requests_per_minute=1,
            requests_per_hour=100,
            burst_size=1,
        )

        request = MagicMock()
        request.url.path = "/test/limited"
        request.client.host = "192.168.1.1"
        request.headers = {}

        call_next = AsyncMock()
        response = MagicMock()
        response.headers = {}
        call_next.return_value = response

        # First request should pass
        await middleware.dispatch(request, call_next)

        # Second request should be rate limited
        result2 = await middleware.dispatch(request, call_next)

        # Check if it's a 429 response
        assert result2.status_code == 429


class TestXForwardedForHandling:
    """Tests for X-Forwarded-For header handling."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        RateLimiter._instance = None
        app = AsyncMock()
        return RateLimitMiddleware(app, enabled=True)

    def test_uses_direct_ip_when_no_proxy_configured(self, middleware):
        """Test that direct IP is used when no trusted proxies are configured."""
        request = MagicMock()
        request.client.host = "192.168.1.1"
        request.headers = {"X-Forwarded-For": "10.0.0.1"}

        # With no TRUSTED_PROXY_IPS configured, X-Forwarded-For should be ignored
        with patch("app.middleware.rate_limit.TRUSTED_PROXY_IPS", set()):
            ip = middleware._get_client_ip(request)

        assert ip == "192.168.1.1"

    def test_uses_forwarded_ip_when_trusted_proxy(self, middleware):
        """Test that forwarded IP is used when request comes from trusted proxy."""
        request = MagicMock()
        request.client.host = "10.0.0.100"  # Trusted proxy IP
        request.headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.100"}

        with patch("app.middleware.rate_limit.TRUSTED_PROXY_IPS", {"10.0.0.100"}):
            ip = middleware._get_client_ip(request)

        assert ip == "192.168.1.1"

    def test_ignores_forwarded_from_untrusted_source(self, middleware):
        """Test that forwarded IP is ignored from untrusted sources."""
        request = MagicMock()
        request.client.host = "192.168.1.100"  # Not a trusted proxy
        request.headers = {"X-Forwarded-For": "10.0.0.1"}

        with patch("app.middleware.rate_limit.TRUSTED_PROXY_IPS", {"10.0.0.200"}):
            ip = middleware._get_client_ip(request)

        assert ip == "192.168.1.100"

    def test_returns_unknown_when_no_client(self, middleware):
        """Test that 'unknown' is returned when client info is missing."""
        request = MagicMock()
        request.client = None
        request.headers = {}

        ip = middleware._get_client_ip(request)

        assert ip == "unknown"
