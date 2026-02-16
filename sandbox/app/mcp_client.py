"""MCP Client - connects to external MCP servers for tool discovery and proxying.

Implements the MCP Streamable HTTP client protocol using httpx.
No MCP SDK dependency - matches MCPbox's native protocol implementation pattern.
"""

import logging
import re
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# MCP protocol version we support as a client
MCP_PROTOCOL_VERSION = "2025-03-26"

# Fallback protocol versions if the server doesn't support our preferred version
MCP_FALLBACK_VERSIONS = ["2024-11-05"]

# Honest User-Agent identifying MCPbox as a server-to-server MCP client.
# We don't spoof browser UAs — if an external MCP server requires browser-level
# auth (Cloudflare JS challenge), the proper fix is the MCP OAuth 2.1 flow
# where the admin authenticates via a real browser popup.
DEFAULT_USER_AGENT = "MCPbox/1.0.0 (MCP Client; +https://github.com/JGtHb/MCPbox)"

# Patterns that indicate a Cloudflare bot-detection challenge page
_CF_CHALLENGE_PATTERNS = [
    re.compile(r"<title>\s*Just a moment\.{3}\s*</title>", re.IGNORECASE),
    re.compile(r"challenges\.cloudflare\.com", re.IGNORECASE),
    re.compile(r"cf-browser-verification", re.IGNORECASE),
    re.compile(r"cf_chl_opt", re.IGNORECASE),
]


class MCPClientError(Exception):
    """Error communicating with an external MCP server."""

    pass


class CloudflareChallengeError(MCPClientError):
    """Raised when the external server returns a Cloudflare bot-detection challenge.

    This means the target MCP server is behind Cloudflare with JavaScript
    challenge protection enabled, which automated HTTP clients cannot solve.
    """

    pass


def _is_cloudflare_challenge(response: httpx.Response) -> bool:
    """Detect whether a response is a Cloudflare JavaScript challenge page."""
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return False

    # Only check responses that look like error/challenge pages
    if response.status_code not in (403, 503):
        return False

    # Check for Cloudflare server header
    server = response.headers.get("server", "").lower()
    has_cf_header = "cloudflare" in server

    body = response.text[:4000]  # Only scan start of page
    has_cf_pattern = any(p.search(body) for p in _CF_CHALLENGE_PATTERNS)

    return has_cf_header or has_cf_pattern


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
            # SECURITY: Disable redirect following to prevent SSRF attacks.
            # An attacker-controlled MCP server could redirect to internal
            # services (e.g., cloud metadata at 169.254.169.254).
            follow_redirects=False,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
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
            if _is_cloudflare_challenge(response):
                raise CloudflareChallengeError(
                    f"HTTP {response.status_code}: The external MCP server is behind "
                    f"Cloudflare bot protection (JavaScript challenge). "
                    f"Automated clients cannot bypass this. "
                    f"Options: (1) use the OAuth auth type to authenticate via browser, "
                    f"(2) use an API key / Bearer token if the server provides one, "
                    f"(3) contact the MCP server operator to whitelist "
                    f"server-to-server traffic on their MCP endpoint."
                )
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
