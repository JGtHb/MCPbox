"""MCP Client - connects to external MCP servers for tool discovery and proxying.

Implements the MCP Streamable HTTP client protocol using httpx.
No MCP SDK dependency - matches MCPbox's native protocol implementation pattern.
"""

import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# MCP protocol version we support as a client
MCP_PROTOCOL_VERSION = "2025-03-26"

# Fallback protocol versions if the server doesn't support our preferred version
MCP_FALLBACK_VERSIONS = ["2024-11-05"]


class MCPClientError(Exception):
    """Error communicating with an external MCP server."""

    pass


class MCPClient:
    """Client for communicating with external MCP servers.

    Supports Streamable HTTP transport (POST with JSON-RPC 2.0).
    Handles initialize handshake, tool discovery, and tool execution.
    """

    def __init__(
        self,
        url: str,
        auth_headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.auth_headers = auth_headers or {}
        self.timeout = timeout
        self._session_id: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MCPClient":
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            # Try to send session termination if we have a session
            if self._session_id:
                try:
                    await self._client.delete(
                        self.url,
                        headers=self._request_headers(),
                    )
                except Exception:
                    pass  # Best-effort cleanup
            await self._client.aclose()
            self._client = None

    def _request_headers(self) -> dict[str, str]:
        """Build headers for MCP requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.auth_headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request to the external MCP server.

        Handles both direct JSON responses and SSE streams.
        """
        if not self._client:
            raise MCPClientError("Client not initialized. Use async with.")

        try:
            response = await self._client.post(
                self.url,
                json=request,
                headers=self._request_headers(),
            )
        except httpx.ConnectError as e:
            raise MCPClientError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            raise MCPClientError(f"Request timed out: {e}") from e

        # Capture session ID from response headers
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if response.status_code >= 400:
            raise MCPClientError(f"HTTP {response.status_code}: {response.text[:500]}")

        content_type = response.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            # Parse SSE response - extract the first JSON-RPC result
            return self._parse_sse_response(response.text)
        else:
            # Direct JSON response
            try:
                return response.json()
            except ValueError as e:
                raise MCPClientError(f"Invalid JSON response: {e}") from e

    def _parse_sse_response(self, text: str) -> dict[str, Any]:
        """Parse a Server-Sent Events response to extract JSON-RPC result."""
        import json

        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data = line[6:]
                try:
                    parsed = json.loads(data)
                    # Return the first result message (not notifications)
                    if "result" in parsed or "error" in parsed:
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    continue

        raise MCPClientError("No JSON-RPC result found in SSE response")

    async def initialize(self) -> dict[str, Any]:
        """Perform MCP initialize handshake.

        Returns:
            Server capabilities from the initialize response.
        """
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "MCPbox",
                    "version": "1.0.0",
                },
            },
        }

        response = await self._send_request(request)

        if "error" in response:
            raise MCPClientError(
                f"Initialize failed: {response['error'].get('message', 'Unknown error')}"
            )

        result = response.get("result", {})

        # Send initialized notification (fire-and-forget)
        try:
            notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            if self._client:
                await self._client.post(
                    self.url,
                    json=notification,
                    headers=self._request_headers(),
                )
        except Exception:
            pass  # Notification is best-effort

        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """List tools available on the external MCP server.

        Returns:
            List of tool definitions with name, description, and inputSchema.
        """
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/list",
            "params": {},
        }

        response = await self._send_request(request)

        if "error" in response:
            raise MCPClientError(
                f"tools/list failed: {response['error'].get('message', 'Unknown error')}"
            )

        return response.get("result", {}).get("tools", [])

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool on the external MCP server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            Tool execution result in MCP format.
        """
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        response = await self._send_request(request)

        if "error" in response:
            return {
                "success": False,
                "error": response["error"].get("message", "Unknown error"),
            }

        result = response.get("result", {})
        # Extract text content from MCP response format
        content = result.get("content", [])
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return {
            "success": True,
            "result": "\n".join(text_parts) if text_parts else result,
            "is_error": result.get("isError", False),
        }


async def discover_tools(
    url: str,
    transport_type: str = "streamable_http",
    auth_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Discover tools from an external MCP server.

    Convenience function that handles the full initialize + tools/list flow.

    Returns:
        Dict with 'success', 'tools', and optional 'error'.
    """
    try:
        async with MCPClient(url, auth_headers=auth_headers) as client:
            await client.initialize()
            tools = await client.list_tools()
            return {
                "success": True,
                "tools": tools,
            }
    except MCPClientError as e:
        logger.error(f"MCP discovery failed for {url}: {e}")
        return {
            "success": False,
            "error": str(e),
            "tools": [],
        }
    except Exception as e:
        logger.exception(f"Unexpected error during MCP discovery for {url}: {e}")
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
            "tools": [],
        }


async def call_external_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    auth_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Call a tool on an external MCP server.

    Convenience function that handles initialize + tools/call.

    Returns:
        Execution result dict with 'success', 'result', and optional 'error'.
    """
    try:
        async with MCPClient(url, auth_headers=auth_headers) as client:
            await client.initialize()
            return await client.call_tool(tool_name, arguments)
    except MCPClientError as e:
        logger.error(f"External tool call failed ({tool_name}@{url}): {e}")
        return {
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        logger.exception(
            f"Unexpected error calling external tool {tool_name}@{url}: {e}"
        )
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
        }
