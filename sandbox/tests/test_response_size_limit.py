"""Tests for response size limiting, tools/list error handling, and MemoryError recovery."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ssrf import (
    MAX_RESPONSE_SIZE,
    ResponseTooLargeError,
    SSRFProtectedAsyncHttpClient,
)


# =============================================================================
# Response Size Limiting Tests (Layer 1)
# =============================================================================


class TestResponseSizeLimit:
    """Tests for SSRFProtectedAsyncHttpClient response size enforcement."""

    def _make_client(self, max_response_size=None):
        """Create an SSRFProtectedAsyncHttpClient with a mock underlying client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        kwargs = {"proxy_mode": True}  # Skip DNS resolution in tests
        if max_response_size is not None:
            kwargs["max_response_size"] = max_response_size
        return SSRFProtectedAsyncHttpClient(mock_client, **kwargs), mock_client

    def _mock_stream_response(self, mock_client, body: bytes, headers=None):
        """Set up the mock client to return a streaming response."""
        mock_response = AsyncMock()
        mock_response.headers = httpx.Headers(headers or {})

        # Make aiter_bytes yield chunks
        async def aiter_bytes(chunk_size=65536):
            for i in range(0, len(body), chunk_size):
                yield body[i : i + chunk_size]

        mock_response.aiter_bytes = aiter_bytes
        mock_response.aclose = AsyncMock()

        # Mock build_request + send
        mock_request = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send = AsyncMock(return_value=mock_response)
        return mock_response

    @pytest.mark.asyncio
    async def test_normal_response_passes_through(self):
        """Responses under the limit are returned normally."""
        client, mock = self._make_client(max_response_size=1024)
        body = b'{"result": "ok"}'
        self._mock_stream_response(mock, body, {"content-length": str(len(body))})

        resp = await client.get("https://api.example.com/data")

        assert resp._content == body

    @pytest.mark.asyncio
    async def test_content_length_header_over_limit_raises(self):
        """Raises ResponseTooLargeError when Content-Length exceeds limit."""
        client, mock = self._make_client(max_response_size=1024)
        # Body doesn't matter — Content-Length check happens first
        self._mock_stream_response(mock, b"x" * 100, {"content-length": "999999"})

        with pytest.raises(
            ResponseTooLargeError, match="server reported 999,999 bytes"
        ):
            await client.get("https://api.example.com/huge")

    @pytest.mark.asyncio
    async def test_streaming_body_over_limit_raises(self):
        """Raises ResponseTooLargeError when body exceeds limit during streaming."""
        client, mock = self._make_client(max_response_size=1024)
        # No Content-Length header — must detect via streaming
        body = b"x" * 2048
        self._mock_stream_response(mock, body)

        with pytest.raises(ResponseTooLargeError, match="exceeded.*1,024 byte limit"):
            await client.get("https://api.example.com/chunked")

    @pytest.mark.asyncio
    async def test_exact_limit_passes(self):
        """Response exactly at the limit passes through."""
        client, mock = self._make_client(max_response_size=1024)
        body = b"x" * 1024
        self._mock_stream_response(mock, body, {"content-length": "1024"})

        resp = await client.get("https://api.example.com/data")

        assert len(resp._content) == 1024

    @pytest.mark.asyncio
    async def test_post_method_enforces_limit(self):
        """POST requests also enforce the size limit."""
        client, mock = self._make_client(max_response_size=1024)
        self._mock_stream_response(mock, b"x" * 100, {"content-length": "999999"})

        with pytest.raises(ResponseTooLargeError):
            await client.post("https://api.example.com/data", json={"q": "test"})

    @pytest.mark.asyncio
    async def test_head_and_options_skip_size_limit(self):
        """HEAD and OPTIONS don't go through size limiting (no body expected)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        client = SSRFProtectedAsyncHttpClient(mock_client, proxy_mode=True)

        mock_response = MagicMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.options = AsyncMock(return_value=mock_response)

        # These should NOT raise even with no streaming setup
        await client.head("https://api.example.com/data")
        await client.options("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_default_limit_is_10mb(self):
        """Default MAX_RESPONSE_SIZE is 10MB."""
        assert MAX_RESPONSE_SIZE == 10 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_malformed_content_length_falls_through(self):
        """Malformed Content-Length header doesn't crash — falls through to streaming."""
        client, mock = self._make_client(max_response_size=1024)
        body = b"small"
        self._mock_stream_response(mock, body, {"content-length": "not-a-number"})

        resp = await client.get("https://api.example.com/data")

        assert resp._content == body

    @pytest.mark.asyncio
    async def test_stream_closed_on_size_error(self):
        """Response stream is closed when size limit is exceeded."""
        client, mock = self._make_client(max_response_size=1024)
        mock_resp = self._mock_stream_response(
            mock, b"x" * 100, {"content-length": "999999"}
        )

        with pytest.raises(ResponseTooLargeError):
            await client.get("https://api.example.com/huge")

        mock_resp.aclose.assert_called()


# =============================================================================
# tools/list Error Handling Tests (Layer 2)
# =============================================================================


class TestToolsListErrorHandling:
    """Tests for tools/list endpoint error handling."""

    @pytest.fixture
    def client(self, authenticated_client):
        return authenticated_client

    def test_tools_list_returns_error_on_registry_failure(self, client):
        """tools/list returns JSON-RPC error instead of 500 when registry fails."""
        with patch("app.routes.tool_registry") as mock_registry:
            mock_registry.list_tools.side_effect = RuntimeError("registry corrupted")

            response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32603
        assert "RuntimeError" in data["error"]["message"]
        assert "registry corrupted" in data["error"]["message"]

    def test_tools_list_returns_error_on_memory_error(self, client):
        """tools/list returns JSON-RPC error on MemoryError (not HTTP 500)."""
        with patch("app.routes.tool_registry") as mock_registry:
            mock_registry.list_tools.side_effect = MemoryError()

            response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32603
        assert "MemoryError" in data["error"]["message"]

    def test_tools_list_success_unchanged(self, client):
        """Normal tools/list still works correctly."""
        # Register a tool
        client.post(
            "/servers/register",
            json={
                "server_id": "test-srv",
                "server_name": "TestSrv",
                "tools": [
                    {
                        "name": "my_tool",
                        "description": "A test tool",
                        "parameters": {},
                        "python_code": 'async def main():\n    return "ok"\n',
                    }
                ],
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "error" not in data
        tools = data["result"]["tools"]
        assert any(t["name"] == "TestSrv__my_tool" for t in tools)


# =============================================================================
# gc.collect() After MemoryError Tests (Layer 3)
# =============================================================================


class TestMemoryErrorRecovery:
    """Tests for gc.collect() being called after MemoryError in executor."""

    @pytest.mark.asyncio
    async def test_gc_collect_called_after_memory_error(self):
        """gc.collect() is called when execution raises MemoryError."""
        import os

        from app.executor import PythonExecutor

        executor = PythonExecutor()
        # Use a code that will succeed in compilation but we'll mock the
        # async execution to raise MemoryError
        code = 'async def main():\n    return "ok"\n'

        with patch("app.executor.gc.collect") as mock_gc:
            with patch.dict(os.environ, {"REQUIRE_RESOURCE_LIMITS": "false"}):
                # Patch asyncio.wait_for to raise MemoryError, simulating
                # an OOM during tool execution
                with patch(
                    "app.executor.asyncio.wait_for",
                    side_effect=MemoryError("out of memory"),
                ):
                    result = await executor.execute(
                        python_code=code,
                        arguments={},
                        http_client=AsyncMock(),
                    )

        assert result.success is False
        assert "MemoryError" in result.error
        mock_gc.assert_called_once()

    @pytest.mark.asyncio
    async def test_gc_not_called_for_other_errors(self):
        """gc.collect() is NOT called for non-MemoryError exceptions."""
        import os

        from app.executor import PythonExecutor

        executor = PythonExecutor()
        code = "async def main():\n    raise ValueError('bad input')\n"

        with patch("app.executor.gc.collect") as mock_gc:
            with patch.dict(os.environ, {"REQUIRE_RESOURCE_LIMITS": "false"}):
                result = await executor.execute(
                    python_code=code,
                    arguments={},
                    http_client=AsyncMock(),
                )

        assert result.success is False
        assert "ValueError" in result.error
        mock_gc.assert_not_called()
