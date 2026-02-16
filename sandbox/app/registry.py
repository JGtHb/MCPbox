"""Tool Registry - manages tool definitions and execution."""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.executor import python_executor

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """A registered tool using Python code execution."""

    name: str
    description: str
    server_id: str
    server_name: str
    parameters: dict[str, Any]
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
    secrets: dict[str, str] = field(default_factory=dict)  # Decrypted key-value secrets


class ToolRegistry:
    """Registry for managing MCP tools.

    Handles:
    - Tool registration/unregistration
    - Tool execution via Python code
    """

    def __init__(self):
        self.servers: dict[str, RegisteredServer] = {}

    @property
    def tool_count(self) -> int:
        """Total number of registered tools."""
        return sum(len(s.tools) for s in self.servers.values())

    def register_server(
        self,
        server_id: str,
        server_name: str,
        tools: list[dict[str, Any]],
        credentials: list[dict[str, Any]] | None = None,
        helper_code: Optional[str] = None,
        allowed_modules: Optional[list[str]] = None,
        secrets: dict[str, str] | None = None,
    ) -> int:
        """Register a server with its tools.

        Args:
            server_id: Unique server identifier
            server_name: Human-readable server name
            tools: List of tool definitions
            credentials: Deprecated, ignored. Kept for API compatibility.
            helper_code: Optional shared Python code for all tools
            allowed_modules: Custom list of allowed Python modules (None = defaults)
            secrets: Dict of secret key→value pairs for injection into tool namespace

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
            secrets=secrets or {},
        )

        for tool_def in tools:
            tool = Tool(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                server_id=server_id,
                server_name=server_name,
                parameters=tool_def.get("parameters", {}),
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

        # Get the server for helper code, allowed modules, and secrets
        server = self.get_server_for_tool(tool.full_name)
        helper_code = server.helper_code if server else None
        allowed_modules = (
            set(server.allowed_modules) if server and server.allowed_modules else None
        )
        secrets = server.secrets if server else {}

        # Build HTTP client (unauthenticated — tools use secrets for auth)
        http_client = httpx.AsyncClient(
            timeout=tool.timeout_ms / 1000,
            follow_redirects=False,
        )

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
                secrets=secrets,
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
