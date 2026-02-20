"""Tests for the MCP client used for external server discovery and proxying."""

import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.mcp_client import (
    MCPClient,
    MCPClientError,
    CloudflareChallengeError,
    USER_AGENT,
    _is_cloudflare_challenge,
    discover_tools,
    call_external_tool,
)


def _mock_response(status_code=200, json_data=None, text=None, headers=None):
    """Create a mock httpx.Response."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = httpx.Headers(headers or {})
    if json_data is not None:
        response.json.return_value = json_data
        response.text = json.dumps(json_data)
    elif text is not None:
        response.text = text
        response.json.side_effect = ValueError("No JSON")
    else:
        response.text = ""
        response.json.return_value = {}
    return response


class TestMCPClient:
    """Tests for MCPClient class."""

    @pytest.mark.asyncio
    async def test_initialize_sends_correct_request(self):
        """Initialize sends proper MCP handshake."""
        mock_response = _mock_response(
            200,
            json_data={
                "jsonrpc": "2.0",
                "id": "test",
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "TestServer", "version": "1.0"},
                },
            },
            headers={"mcp-session-id": "session-123"},
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                result = await client.initialize()

            assert result["protocolVersion"] == "2025-03-26"
            assert client._session_id == "session-123"

            # Verify the initialize request was sent correctly
            call_args = mock_client.post.call_args_list[0]
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["method"] == "initialize"
            assert body["params"]["clientInfo"]["name"] == "MCPbox"

    @pytest.mark.asyncio
    async def test_list_tools_returns_tools(self):
        """list_tools returns tool definitions from external server."""
        tools_data = [
            {
                "name": "search",
                "description": "Search the web",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ]

        init_response = _mock_response(
            200,
            json_data={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {"protocolVersion": "2025-03-26"},
            },
            headers={"mcp-session-id": "session-1"},
        )
        tools_response = _mock_response(
            200,
            json_data={"jsonrpc": "2.0", "id": "2", "result": {"tools": tools_data}},
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [init_response, AsyncMock(), tools_response]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=_mock_response(200))
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()
                tools = await client.list_tools()

            assert len(tools) == 1
            assert tools[0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_call_tool_returns_result(self):
        """call_tool proxies the call and returns the result."""
        call_response = _mock_response(
            200,
            json_data={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {
                    "content": [{"type": "text", "text": "sunny, 72F"}],
                },
            },
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                _mock_response(
                    200,
                    json_data={
                        "jsonrpc": "2.0",
                        "id": "1",
                        "result": {"protocolVersion": "2025-03-26"},
                    },
                    headers={"mcp-session-id": "s1"},
                ),
                AsyncMock(),  # initialized notification
                call_response,
            ]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=_mock_response(200))
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()
                result = await client.call_tool("get_weather", {"city": "SF"})

            assert result["success"] is True
            assert "sunny" in result["result"]

    @pytest.mark.asyncio
    async def test_call_tool_handles_error(self):
        """call_tool returns error when tool execution fails."""
        error_response = _mock_response(
            200,
            json_data={
                "jsonrpc": "2.0",
                "id": "1",
                "error": {"code": -32000, "message": "Tool execution failed"},
            },
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                _mock_response(
                    200,
                    json_data={
                        "jsonrpc": "2.0",
                        "id": "1",
                        "result": {"protocolVersion": "2025-03-26"},
                    },
                    headers={"mcp-session-id": "s1"},
                ),
                AsyncMock(),
                error_response,
            ]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=_mock_response(200))
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()
                result = await client.call_tool("failing_tool", {})

            assert result["success"] is False
            assert "failed" in result["error"]

    @pytest.mark.asyncio
    async def test_connection_error_raises(self):
        """Connection failure raises MCPClientError."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://unreachable.example.com/mcp") as client:
                with pytest.raises(MCPClientError, match="Connection failed"):
                    await client.initialize()

    @pytest.mark.asyncio
    async def test_timeout_error_raises(self):
        """Timeout raises MCPClientError with timeout message."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("Operation timed out")
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://slow.example.com/mcp") as client:
                with pytest.raises(MCPClientError, match="timed out"):
                    await client.initialize()

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """HTTP error responses raise MCPClientError."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response(401, text="Unauthorized")
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                with pytest.raises(MCPClientError, match="HTTP 401"):
                    await client.initialize()

    @pytest.mark.asyncio
    async def test_sse_response_parsing(self):
        """SSE response format is correctly parsed."""
        sse_body = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":"1","result":{"tools":[{"name":"test","description":"Test tool","inputSchema":{}}]}}\n\n'
        )
        sse_response = _mock_response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                _mock_response(
                    200,
                    json_data={
                        "jsonrpc": "2.0",
                        "id": "1",
                        "result": {"protocolVersion": "2025-03-26"},
                    },
                    headers={"mcp-session-id": "s1"},
                ),
                AsyncMock(),
                sse_response,
            ]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=_mock_response(200))
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()
                tools = await client.list_tools()

            assert len(tools) == 1
            assert tools[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_auth_headers_sent(self):
        """Auth headers are included in requests."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response(
                200,
                json_data={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {"protocolVersion": "2025-03-26"},
                },
                headers={"mcp-session-id": "s1"},
            )
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient(
                "https://example.com/mcp",
                auth_headers={"Authorization": "Bearer test-token"},
            ) as client:
                await client.initialize()

            # Check headers include auth
            call_args = mock_client.post.call_args_list[0]
            headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
            assert headers["Authorization"] == "Bearer test-token"


class TestDiscoverToolsHelper:
    """Tests for the discover_tools convenience function."""

    @pytest.mark.asyncio
    async def test_discover_tools_success(self):
        """discover_tools returns tools on success."""
        with patch("app.mcp_client.MCPClient") as MockMCPClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.initialize = AsyncMock(return_value={})
            mock_instance.list_tools = AsyncMock(
                return_value=[
                    {"name": "tool1", "description": "A tool", "inputSchema": {}}
                ]
            )
            MockMCPClient.return_value = mock_instance

            result = await discover_tools("https://example.com/mcp")

            assert result["success"] is True
            assert len(result["tools"]) == 1

    @pytest.mark.asyncio
    async def test_discover_tools_connection_failure(self):
        """discover_tools returns error on connection failure."""
        with patch("app.mcp_client.MCPClient") as MockMCPClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.initialize = AsyncMock(
                side_effect=MCPClientError("Connection refused")
            )
            MockMCPClient.return_value = mock_instance

            result = await discover_tools("https://unreachable.com/mcp")

            assert result["success"] is False
            assert "Connection refused" in result["error"]


class TestCallExternalToolHelper:
    """Tests for the call_external_tool convenience function."""

    @pytest.mark.asyncio
    async def test_call_external_tool_success(self):
        """call_external_tool returns result on success."""
        with patch("app.mcp_client.MCPClient") as MockMCPClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.initialize = AsyncMock(return_value={})
            mock_instance.call_tool = AsyncMock(
                return_value={"success": True, "result": "tool output"}
            )
            MockMCPClient.return_value = mock_instance

            result = await call_external_tool(
                "https://example.com/mcp", "my_tool", {"arg": "value"}
            )

            assert result["success"] is True
            assert result["result"] == "tool output"


class TestCloudflareDetection:
    """Tests for Cloudflare challenge page detection."""

    def test_detects_cf_challenge_with_title(self):
        """Detects CF challenge by 'Just a moment...' title."""
        body = "<html><head><title>Just a moment...</title></head><body></body></html>"
        response = _mock_response(
            403,
            text=body,
            headers={"content-type": "text/html", "server": "cloudflare"},
        )
        assert _is_cloudflare_challenge(response) is True

    def test_detects_cf_challenge_by_server_header(self):
        """Detects CF challenge by cloudflare server header alone."""
        body = (
            "<html><head><title>Access denied</title></head><body>blocked</body></html>"
        )
        response = _mock_response(
            403,
            text=body,
            headers={"content-type": "text/html", "server": "cloudflare"},
        )
        assert _is_cloudflare_challenge(response) is True

    def test_detects_cf_challenge_by_script_pattern(self):
        """Detects CF challenge by challenges.cloudflare.com script reference."""
        body = (
            "<html><head><title>Verify</title></head>"
            '<body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></body></html>'
        )
        response = _mock_response(
            403,
            text=body,
            headers={"content-type": "text/html"},
        )
        assert _is_cloudflare_challenge(response) is True

    def test_does_not_flag_normal_403(self):
        """Normal 403 JSON responses are not flagged as CF challenges."""
        response = _mock_response(
            403,
            text='{"error": "Forbidden"}',
            headers={"content-type": "application/json"},
        )
        assert _is_cloudflare_challenge(response) is False

    def test_does_not_flag_200_html(self):
        """A 200 HTML page is not flagged even with cloudflare server header."""
        body = "<html><body>Welcome</body></html>"
        response = _mock_response(
            200,
            text=body,
            headers={"content-type": "text/html", "server": "cloudflare"},
        )
        assert _is_cloudflare_challenge(response) is False

    def test_detects_503_challenge(self):
        """CF challenges can also come as 503 status codes."""
        body = "<html><head><title>Just a moment...</title></head></html>"
        response = _mock_response(
            503,
            text=body,
            headers={"content-type": "text/html", "server": "cloudflare"},
        )
        assert _is_cloudflare_challenge(response) is True

    @pytest.mark.asyncio
    async def test_send_request_raises_cloudflare_error(self):
        """_send_request raises CloudflareChallengeError for CF challenge pages."""
        cf_body = (
            "<html><head><title>Just a moment...</title></head><body></body></html>"
        )
        cf_response = _mock_response(
            403,
            text=cf_body,
            headers={"content-type": "text/html", "server": "cloudflare"},
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = cf_response
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                with pytest.raises(CloudflareChallengeError, match="bot protection"):
                    await client.initialize()


class TestRedirectPrevention:
    """Tests for SSRF redirect prevention (SEC-007)."""

    @pytest.mark.asyncio
    async def test_client_created_with_follow_redirects_false(self):
        """httpx.AsyncClient is created with follow_redirects=False."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response(
                200,
                json_data={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {"protocolVersion": "2025-03-26"},
                },
                headers={"mcp-session-id": "s1"},
            )
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()

            # Verify AsyncClient was created with follow_redirects=False
            init_kwargs = MockClient.call_args.kwargs
            assert init_kwargs["follow_redirects"] is False


class TestUserAgent:
    """Tests for User-Agent configuration."""

    @pytest.mark.asyncio
    async def test_client_uses_custom_user_agent(self):
        """httpx.AsyncClient is created with MCPbox User-Agent."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response(
                200,
                json_data={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {"protocolVersion": "2025-03-26"},
                },
                headers={"mcp-session-id": "s1"},
            )
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()

            # Verify User-Agent is set in client headers
            init_kwargs = MockClient.call_args.kwargs
            assert init_kwargs["headers"]["User-Agent"] == USER_AGENT

    def test_user_agent_does_not_contain_library_name(self):
        """User-Agent must not match Cloudflare's known bot library patterns."""
        blocked_patterns = [
            "python-httpx",
            "python-requests",
            "Go-http-client",
            "node-fetch",
        ]
        ua_lower = USER_AGENT.lower()
        for pattern in blocked_patterns:
            assert pattern.lower() not in ua_lower, (
                f"USER_AGENT '{USER_AGENT}' contains blocked pattern '{pattern}'"
            )

    @pytest.mark.asyncio
    async def test_mcp_headers_sent_per_request(self):
        """MCP-specific headers (Content-Type, Accept) are sent per-request."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response(
                200,
                json_data={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {"protocolVersion": "2025-03-26"},
                },
                headers={"mcp-session-id": "s1"},
            )
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()

            # Check request-level headers contain MCP headers
            call_args = mock_client.post.call_args_list[0]
            headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
            assert headers["Content-Type"] == "application/json"
            assert "application/json" in headers["Accept"]
            assert "text/event-stream" in headers["Accept"]

    @pytest.mark.asyncio
    async def test_auth_headers_merge_with_mcp_headers(self):
        """Auth headers merge with MCP headers per-request."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response(
                200,
                json_data={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {"protocolVersion": "2025-03-26"},
                },
                headers={"mcp-session-id": "s1"},
            )
            mock_client.aclose = AsyncMock()
            MockClient.return_value = mock_client

            async with MCPClient(
                "https://example.com/mcp",
                auth_headers={"Authorization": "Bearer token123"},
            ) as client:
                await client.initialize()

            call_args = mock_client.post.call_args_list[0]
            headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
            assert headers["Authorization"] == "Bearer token123"
            assert headers["Content-Type"] == "application/json"
