"""Tests for the MCP session pool - connection reuse, retry, and health checks."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.mcp_client import CloudflareChallengeError, MCPClientError
from app.mcp_session_pool import (
    MCPSessionPool,
    _is_transient_error,
    _pool_key,
)


class TestPoolKey:
    """Tests for pool key generation."""

    def test_same_url_same_headers_same_key(self):
        key1 = _pool_key("https://example.com/mcp", {"Authorization": "Bearer x"})
        key2 = _pool_key("https://example.com/mcp", {"Authorization": "Bearer x"})
        assert key1 == key2

    def test_different_url_different_key(self):
        key1 = _pool_key("https://a.com/mcp", {})
        key2 = _pool_key("https://b.com/mcp", {})
        assert key1 != key2

    def test_different_headers_different_key(self):
        key1 = _pool_key("https://example.com/mcp", {"Authorization": "Bearer x"})
        key2 = _pool_key("https://example.com/mcp", {"Authorization": "Bearer y"})
        assert key1 != key2

    def test_empty_headers(self):
        key = _pool_key("https://example.com/mcp", {})
        assert "example.com" in key


class TestTransientErrorClassification:
    """Tests for error classification."""

    def test_timeout_is_transient(self):
        assert _is_transient_error(MCPClientError("Request timed out")) is True

    def test_connection_refused_is_transient(self):
        assert _is_transient_error(MCPClientError("Connection refused")) is True

    def test_502_is_transient(self):
        assert _is_transient_error(MCPClientError("HTTP 502: Bad Gateway")) is True

    def test_503_is_transient(self):
        assert (
            _is_transient_error(MCPClientError("HTTP 503: Service Unavailable")) is True
        )

    def test_429_is_transient(self):
        assert (
            _is_transient_error(MCPClientError("HTTP 429: Too Many Requests")) is True
        )

    def test_401_is_not_transient(self):
        assert _is_transient_error(MCPClientError("HTTP 401: Unauthorized")) is False

    def test_404_is_not_transient(self):
        assert _is_transient_error(MCPClientError("HTTP 404: Not Found")) is False

    def test_cloudflare_is_not_transient(self):
        assert _is_transient_error(CloudflareChallengeError("CF challenge")) is False

    def test_generic_error_is_not_transient(self):
        assert _is_transient_error(MCPClientError("Something broke")) is False


class TestMCPSessionPool:
    """Tests for the MCPSessionPool class."""

    @pytest.mark.asyncio
    async def test_call_tool_creates_session_and_returns_result(self):
        """First call creates a session, initializes, and calls the tool."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "data"}
            )
            MockClient.return_value = mock_client

            result = await pool.call_tool(
                "https://example.com/mcp", "my_tool", {"arg": "val"}
            )

            assert result["success"] is True
            assert result["result"] == "data"
            mock_client.open.assert_called_once()
            mock_client.initialize.assert_called_once()
            mock_client.call_tool.assert_called_once_with("my_tool", {"arg": "val"})

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_session_reuse_skips_reinitialize(self):
        """Second call to same URL reuses the initialized session."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            # First call: creates session + initialize + call
            await pool.call_tool("https://example.com/mcp", "tool1", {})
            # Second call: reuses session, no reinitialize
            await pool.call_tool("https://example.com/mcp", "tool2", {})

            # MCPClient constructor called only once (session reused)
            assert MockClient.call_count == 1
            # initialize called only once
            assert mock_client.initialize.call_count == 1
            # call_tool called twice
            assert mock_client.call_tool.call_count == 2

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_different_urls_get_different_sessions(self):
        """Different URLs get independent pool entries."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool("https://a.com/mcp", "tool1", {})
            await pool.call_tool("https://b.com/mcp", "tool1", {})

            assert pool.size == 2
            # Two separate MCPClient instances created
            assert MockClient.call_count == 2

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        """Transient errors trigger retry with eventual success."""
        pool = MCPSessionPool()

        call_count = 0

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})

            async def call_tool_side_effect(name, args):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise MCPClientError("Request timed out")
                return {"success": True, "result": "ok"}

            mock_client.call_tool = AsyncMock(side_effect=call_tool_side_effect)
            MockClient.return_value = mock_client

            with patch("app.mcp_session_pool.asyncio.sleep", new_callable=AsyncMock):
                result = await pool.call_tool("https://example.com/mcp", "my_tool", {})

            assert result["success"] is True
            assert call_count == 2  # First attempt failed, second succeeded

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent_error(self):
        """Non-transient errors fail immediately without retry."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                side_effect=MCPClientError("HTTP 401: Unauthorized")
            )
            MockClient.return_value = mock_client

            result = await pool.call_tool("https://example.com/mcp", "my_tool", {})

            assert result["success"] is False
            assert "401" in result["error"]
            # Only called once — no retry for 401
            mock_client.call_tool.assert_called_once()

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_no_retry_on_cloudflare_challenge(self):
        """CloudflareChallengeError fails immediately."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                side_effect=CloudflareChallengeError("CF challenge")
            )
            MockClient.return_value = mock_client

            result = await pool.call_tool("https://example.com/mcp", "my_tool", {})

            assert result["success"] is False
            assert "CF challenge" in result["error"]
            mock_client.call_tool.assert_called_once()

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        """After max retries, returns the last error."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                side_effect=MCPClientError("Request timed out")
            )
            MockClient.return_value = mock_client

            with patch("app.mcp_session_pool.asyncio.sleep", new_callable=AsyncMock):
                result = await pool.call_tool("https://example.com/mcp", "my_tool", {})

            assert result["success"] is False
            assert "timed out" in result["error"]
            # 1 initial + 3 retries = 4 total attempts
            assert mock_client.call_tool.call_count == 4

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_discover_tools_with_retry(self):
        """discover_tools retries on transient errors."""
        pool = MCPSessionPool()
        call_count = 0

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})

            async def list_tools_side_effect():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise MCPClientError("HTTP 503: Service Unavailable")
                return [{"name": "tool1", "description": "A tool", "inputSchema": {}}]

            mock_client.list_tools = AsyncMock(side_effect=list_tools_side_effect)
            MockClient.return_value = mock_client

            with patch("app.mcp_session_pool.asyncio.sleep", new_callable=AsyncMock):
                result = await pool.discover_tools("https://example.com/mcp")

            assert result["success"] is True
            assert len(result["tools"]) == 1

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """health_check returns healthy with latency."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            MockClient.return_value = mock_client

            result = await pool.health_check("https://example.com/mcp")

            assert result["healthy"] is True
            assert "latency_ms" in result

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """health_check returns unhealthy with error on failure."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(
                side_effect=MCPClientError("Connection refused")
            )
            MockClient.return_value = mock_client

            result = await pool.health_check("https://down.example.com/mcp")

            assert result["healthy"] is False
            assert "Connection refused" in result["error"]

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_expired_session_evicted(self):
        """Expired sessions are evicted and recreated."""
        pool = MCPSessionPool(max_age=0.0)  # Expire immediately

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool("https://example.com/mcp", "tool1", {})
            await pool.call_tool("https://example.com/mcp", "tool2", {})

            # Two MCPClient instances created (first was expired)
            assert MockClient.call_count == 2
            # Two initialize calls (each new entry must initialize)
            assert mock_client.initialize.call_count == 2

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_pool_max_size_evicts_lru(self):
        """Pool evicts least recently used entry when at capacity."""
        pool = MCPSessionPool(max_size=2)

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool("https://a.com/mcp", "tool", {})
            await pool.call_tool("https://b.com/mcp", "tool", {})
            # This should evict https://a.com (LRU)
            await pool.call_tool("https://c.com/mcp", "tool", {})

            assert pool.size == 2

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_evict_by_source_url(self):
        """evict_by_source_url removes all entries for a URL."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool("https://a.com/mcp", "tool", {})
            await pool.call_tool("https://b.com/mcp", "tool", {})
            assert pool.size == 2

            await pool.evict_by_source_url("https://a.com/mcp")
            assert pool.size == 1

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_close_all(self):
        """close_all closes all sessions and empties the pool."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool("https://a.com/mcp", "tool", {})
            await pool.call_tool("https://b.com/mcp", "tool", {})
            assert pool.size == 2

            await pool.close_all()
            assert pool.size == 0

    @pytest.mark.asyncio
    async def test_stats(self):
        """stats returns pool information."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool("https://example.com/mcp", "tool", {})

            stats = pool.stats()
            assert stats["pool_size"] == 1
            assert len(stats["sessions"]) == 1
            assert stats["sessions"][0]["url"] == "https://example.com/mcp"
            assert stats["sessions"][0]["initialized"] is True

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_auth_headers_passed_to_client(self):
        """Auth headers are forwarded to MCPClient."""
        pool = MCPSessionPool()

        with patch("app.mcp_session_pool.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.open = AsyncMock(return_value=mock_client)
            mock_client.close = Mock()
            mock_client.initialize = AsyncMock(return_value={})
            mock_client.call_tool = AsyncMock(
                return_value={"success": True, "result": "ok"}
            )
            MockClient.return_value = mock_client

            await pool.call_tool(
                "https://example.com/mcp",
                "tool",
                {},
                auth_headers={"Authorization": "Bearer secret"},
            )

            # Verify MCPClient was created with auth headers
            MockClient.assert_called_once_with(
                "https://example.com/mcp",
                auth_headers={"Authorization": "Bearer secret"},
            )

        await pool.close_all()
