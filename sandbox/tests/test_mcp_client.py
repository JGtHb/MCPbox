"""Tests for the MCP client used for external server discovery and proxying."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.mcp_client import MCPClient, MCPClientError, discover_tools, call_external_tool


class TestMCPClient:
    """Tests for MCPClient class."""

    @pytest.mark.asyncio
    async def test_initialize_sends_correct_request(self):
        """Initialize sends proper MCP handshake."""
        mock_response = httpx.Response(
            200,
            json={
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
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            }
        ]

        init_response = httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-03-26"}},
            headers={"mcp-session-id": "session-1"},
        )
        tools_response = httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "2", "result": {"tools": tools_data}},
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [init_response, AsyncMock(), tools_response]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=httpx.Response(200))
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()
                tools = await client.list_tools()

            assert len(tools) == 1
            assert tools[0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_call_tool_returns_result(self):
        """call_tool proxies the call and returns the result."""
        call_response = httpx.Response(
            200,
            json={
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
                httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-03-26"}}, headers={"mcp-session-id": "s1"}),
                AsyncMock(),  # initialized notification
                call_response,
            ]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=httpx.Response(200))
            MockClient.return_value = mock_client

            async with MCPClient("https://example.com/mcp") as client:
                await client.initialize()
                result = await client.call_tool("get_weather", {"city": "SF"})

            assert result["success"] is True
            assert "sunny" in result["result"]

    @pytest.mark.asyncio
    async def test_call_tool_handles_error(self):
        """call_tool returns error when tool execution fails."""
        error_response = httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "error": {"code": -32000, "message": "Tool execution failed"},
            },
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-03-26"}}, headers={"mcp-session-id": "s1"}),
                AsyncMock(),
                error_response,
            ]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=httpx.Response(200))
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
    async def test_http_error_raises(self):
        """HTTP error responses raise MCPClientError."""
        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = httpx.Response(401, text="Unauthorized")
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
        sse_response = httpx.Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-03-26"}}, headers={"mcp-session-id": "s1"}),
                AsyncMock(),
                sse_response,
            ]
            mock_client.aclose = AsyncMock()
            mock_client.delete = AsyncMock(return_value=httpx.Response(200))
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
            mock_client.post.return_value = httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-03-26"}},
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
                return_value=[{"name": "tool1", "description": "A tool", "inputSchema": {}}]
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
