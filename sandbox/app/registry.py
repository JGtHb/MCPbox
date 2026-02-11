"""Tool Registry - manages tool definitions and execution."""

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from cryptography.fernet import Fernet

from app.executor import python_executor

logger = logging.getLogger(__name__)


@dataclass
class Credential:
    """Credential with auth type metadata."""

    name: str
    auth_type: str
    header_name: Optional[str] = None
    query_param_name: Optional[str] = None
    value: Optional[str] = None  # Encrypted
    username: Optional[str] = None  # Encrypted (for basic auth)
    password: Optional[str] = None  # Encrypted (for basic auth)


@dataclass
class Tool:
    """A registered tool using Python code execution."""

    name: str
    description: str
    server_id: str
    server_name: str
    parameters: dict[str, Any]
    credentials: list[Credential] = field(default_factory=list)
    python_code: Optional[str] = None
    timeout_ms: int = 30000

    @property
    def full_name(self) -> str:
        """Full tool name with server prefix."""
        return f"{self.server_name}__{self.name}"


@dataclass
class RegisteredServer:
    """A registered server with its tools."""

    server_id: str
    server_name: str
    helper_code: Optional[str] = None
    allowed_modules: Optional[list[str]] = None  # Custom modules or None for defaults
    tools: dict[str, Tool] = field(default_factory=dict)


class ToolRegistry:
    """Registry for managing MCP tools.

    Handles:
    - Tool registration/unregistration
    - Credential decryption
    - Tool execution via Python code
    """

    def __init__(self):
        self.servers: dict[str, RegisteredServer] = {}
        self._encryption_key: Optional[bytes] = None

    def set_encryption_key(self, key: str):
        """Set the encryption key for credential decryption."""
        self._encryption_key = key.encode() if isinstance(key, str) else key

    @property
    def tool_count(self) -> int:
        """Total number of registered tools."""
        return sum(len(s.tools) for s in self.servers.values())

    def _build_authenticated_client(
        self, credentials: list[Credential], timeout_ms: int = 30000
    ) -> httpx.AsyncClient:
        """Build an httpx client with authentication from credentials.

        Decrypts credentials and sets up appropriate auth based on auth_type.
        """
        headers = {}
        auth = None

        for cred in credentials:
            if cred.auth_type == "none":
                continue

            elif cred.auth_type == "bearer":
                # Bearer token authentication
                if cred.value:
                    decrypted = self._decrypt_credential(cred.value)
                    headers["Authorization"] = f"Bearer {decrypted}"

            elif cred.auth_type == "api_key_header":
                # API key in custom header
                if cred.value:
                    decrypted = self._decrypt_credential(cred.value)
                    header_name = cred.header_name or "X-API-Key"
                    headers[header_name] = decrypted

            elif cred.auth_type == "api_key_query":
                # API key in query param - this is handled at request time
                # For now, we'll store it in headers and extract it later
                # Or we can inject it differently
                pass

            elif cred.auth_type == "basic":
                # Basic auth (username:password)
                if cred.username and cred.password:
                    username = self._decrypt_credential(cred.username)
                    password = self._decrypt_credential(cred.password)
                    credentials_str = f"{username}:{password}"
                    encoded = base64.b64encode(credentials_str.encode()).decode()
                    headers["Authorization"] = f"Basic {encoded}"

            elif cred.auth_type == "oauth2":
                # OAuth2 - use access token as bearer
                if cred.value:
                    decrypted = self._decrypt_credential(cred.value)
                    headers["Authorization"] = f"Bearer {decrypted}"

            elif cred.auth_type == "custom_header":
                # Custom header with custom value
                if cred.value and cred.header_name:
                    decrypted = self._decrypt_credential(cred.value)
                    headers[cred.header_name] = decrypted

        # Limit max response size to 10MB to prevent memory exhaustion
        max_response_size = 10 * 1024 * 1024  # 10MB

        async def check_response_size(response: httpx.Response) -> None:
            """Event hook to check Content-Length before reading response."""
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_response_size:
                raise httpx.HTTPStatusError(
                    f"Response too large: {content_length} bytes exceeds {max_response_size} byte limit",
                    request=response.request,
                    response=response,
                )

        return httpx.AsyncClient(
            headers=headers,
            auth=auth,
            timeout=timeout_ms / 1000,
            follow_redirects=False,
            event_hooks={"response": [check_response_size]},
        )

    def register_server(
        self,
        server_id: str,
        server_name: str,
        tools: list[dict[str, Any]],
        credentials: list[dict[str, Any]],
        helper_code: Optional[str] = None,
        allowed_modules: Optional[list[str]] = None,
    ) -> int:
        """Register a server with its tools.

        Args:
            server_id: Unique server identifier
            server_name: Human-readable server name
            tools: List of tool definitions
            credentials: List of credential dicts with auth_type metadata
            helper_code: Optional shared Python code for all tools
            allowed_modules: Custom list of allowed Python modules (None = defaults)

        Returns:
            The number of tools registered.
        """
        if server_id in self.servers:
            # Unregister existing first
            self.unregister_server(server_id)

        server = RegisteredServer(
            server_id=server_id,
            server_name=server_name,
            helper_code=helper_code,
            allowed_modules=allowed_modules,
        )

        # Convert credential dicts to Credential objects
        cred_objects = [
            Credential(
                name=c.get("name", ""),
                auth_type=c.get("auth_type", "none"),
                header_name=c.get("header_name"),
                query_param_name=c.get("query_param_name"),
                value=c.get("value"),
                username=c.get("username"),
                password=c.get("password"),
            )
            for c in credentials
        ]

        for tool_def in tools:
            tool = Tool(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                server_id=server_id,
                server_name=server_name,
                parameters=tool_def.get("parameters", {}),
                credentials=cred_objects,
                python_code=tool_def.get("python_code"),
                timeout_ms=tool_def.get("timeout_ms", 30000),
            )
            server.tools[tool.name] = tool

        self.servers[server_id] = server
        logger.info(
            f"Registered server {server_name} ({server_id}) with {len(server.tools)} tools"
        )
        return len(server.tools)

    def unregister_server(self, server_id: str) -> bool:
        """Unregister a server and all its tools."""
        if server_id in self.servers:
            server = self.servers.pop(server_id)
            logger.info(f"Unregistered server {server.server_name} ({server_id})")
            return True
        return False

    def get_tool(self, full_name: str) -> Optional[Tool]:
        """Get a tool by its full name (servername__toolname)."""
        for server in self.servers.values():
            for tool in server.tools.values():
                if tool.full_name == full_name:
                    return tool
        return None

    def get_server_for_tool(self, full_name: str) -> Optional[RegisteredServer]:
        """Get the server that owns a tool."""
        for server in self.servers.values():
            for tool in server.tools.values():
                if tool.full_name == full_name:
                    return server
        return None

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools in MCP format."""
        tools = []
        for server in self.servers.values():
            for tool in server.tools.values():
                tools.append(
                    {
                        "name": tool.full_name,
                        "description": tool.description,
                        "inputSchema": tool.parameters,
                    }
                )
        return tools

    def list_tools_for_server(self, server_id: str) -> list[dict[str, Any]]:
        """List tools for a specific server."""
        server = self.servers.get(server_id)
        if not server:
            return []

        return [
            {
                "name": tool.full_name,
                "description": tool.description,
                "inputSchema": tool.parameters,
            }
            for tool in server.tools.values()
        ]

    def _decrypt_credential(self, encrypted_value: str) -> str:
        """Decrypt an encrypted credential value.

        Raises:
            ValueError: If decryption fails or key is missing.
        """
        if not self._encryption_key:
            raise ValueError(
                "Encryption key not configured - cannot decrypt credentials"
            )

        try:
            fernet = Fernet(self._encryption_key)
            decrypted = fernet.decrypt(encrypted_value.encode())
            return decrypted.decode()
        except Exception as e:
            # Never return encrypted value on failure - raise error instead
            logger.error(f"Failed to decrypt credential: {e}")
            raise ValueError(f"Credential decryption failed: {e}")

    async def execute_tool(
        self,
        full_name: str,
        arguments: dict[str, Any],
        debug_mode: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool with the given arguments."""
        tool = self.get_tool(full_name)
        if not tool:
            return {
                "error": f"Tool not found: {full_name}",
                "success": False,
            }

        return await self._execute_python_tool(tool, arguments, debug_mode)

    async def _execute_python_tool(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        debug_mode: bool = False,
    ) -> dict[str, Any]:
        """Execute a python_code mode tool."""
        if not tool.python_code:
            return {
                "success": False,
                "error": "Tool has no Python code defined",
            }

        # Get the server for helper code and allowed modules
        server = self.get_server_for_tool(tool.full_name)
        helper_code = server.helper_code if server else None
        allowed_modules = (
            set(server.allowed_modules) if server and server.allowed_modules else None
        )

        # Build authenticated HTTP client
        try:
            http_client = self._build_authenticated_client(
                tool.credentials,
                tool.timeout_ms,
            )
        except ValueError as e:
            # Credential decryption failed
            logger.error(
                f"Failed to build authenticated client for {tool.full_name}: {e}"
            )
            return {
                "success": False,
                "error": f"Credential error: {e}",
            }

        try:
            # Execute the Python code
            result = await python_executor.execute(
                python_code=tool.python_code,
                arguments=arguments,
                http_client=http_client,
                helper_code=helper_code,
                timeout=tool.timeout_ms / 1000,
                debug_mode=debug_mode,
                allowed_modules=allowed_modules,
            )

            return result.to_dict()

        finally:
            # Always close the per-request client
            await http_client.aclose()

    async def clear_all(self):
        """Clear all registrations."""
        self.servers.clear()


# Global registry instance
tool_registry = ToolRegistry()
