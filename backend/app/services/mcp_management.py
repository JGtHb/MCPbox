"""MCP Management Tools - Expose MCPbox management as MCP tools.

These tools allow external LLMs (like Claude Code) to manage MCPbox
servers and tools programmatically.
"""

import logging
import re
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sandbox_client import SandboxClient
from app.services.server import ServerService
from app.services.tool import ToolService

logger = logging.getLogger(__name__)

# Pre-compiled name validation pattern (simple fixed pattern - no ReDoS risk)
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


# Tool definitions for MCP management
MCP_MANAGEMENT_TOOLS = [
    {
        "name": "mcpbox_list_servers",
        "description": "List all MCP servers in MCPbox. Returns server names, IDs, status, and tool counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (default: 1)",
                    "default": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page (default: 50, max: 100)",
                    "default": 50,
                },
            },
            "required": [],
        },
    },
    {
        "name": "mcpbox_get_server",
        "description": "Get details of a specific MCP server including its configuration and status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to retrieve",
                },
            },
            "required": ["server_id"],
        },
    },
    {
        "name": "mcpbox_create_server",
        "description": "Create a new MCP server. The server acts as a container for related tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Server name (e.g., 'weather_api', 'github_tools')",
                },
                "description": {
                    "type": "string",
                    "description": "Description of what this server does",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "mcpbox_delete_server",
        "description": "Delete an MCP server and all its tools. This action is irreversible.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to delete",
                },
            },
            "required": ["server_id"],
        },
    },
    {
        "name": "mcpbox_list_tools",
        "description": "List all tools in an MCP server.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server",
                },
            },
            "required": ["server_id"],
        },
    },
    {
        "name": "mcpbox_get_tool",
        "description": "Get details of a specific tool including its Python code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to retrieve",
                },
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "mcpbox_create_tool",
        "description": "Create a new MCP tool in a server. Tools are created in 'draft' status and must be submitted for admin approval using mcpbox_request_publish before they become available. Write Python code with an async main() function. Note: after approval, MCP clients do not automatically refresh their tool list — the user must restart or refresh their client to see new tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to add the tool to",
                },
                "name": {
                    "type": "string",
                    "description": "Tool name (lowercase with underscores, e.g., 'get_weather')",
                },
                "description": {
                    "type": "string",
                    "description": "Description of what the tool does (shown to LLMs)",
                },
                "python_code": {
                    "type": "string",
                    "description": "Python code with async def main() function. Use 'http' client for requests.",
                },
            },
            "required": ["server_id", "name", "python_code"],
        },
    },
    {
        "name": "mcpbox_update_tool",
        "description": "Update an existing tool's configuration or code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to update",
                },
                "name": {
                    "type": "string",
                    "description": "New tool name (optional)",
                },
                "description": {
                    "type": "string",
                    "description": "New description (optional)",
                },
                "python_code": {
                    "type": "string",
                    "description": "New Python code (optional)",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Enable or disable the tool (optional). Disabled tools are excluded when the server starts. Requires server restart to take effect.",
                },
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "mcpbox_delete_tool",
        "description": "Delete a tool from a server. This action is irreversible.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to delete",
                },
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "mcpbox_test_code",
        "description": "Test a saved tool by running its current code against the sandbox. Requires a tool_id — use mcpbox_create_tool or mcpbox_update_tool first, then test here. The test run is saved to the tool's execution history labelled as a test. Testing is blocked if the admin requires approval and the tool has not yet been approved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to test",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass to the tool's main() function (optional)",
                },
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "mcpbox_start_server",
        "description": "Start an MCP server, making its tools available. Only tools with approval_status='approved' and enabled=True are registered. Tools that are disabled or not yet approved are excluded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to start",
                },
            },
            "required": ["server_id"],
        },
    },
    {
        "name": "mcpbox_stop_server",
        "description": "Stop an MCP server, making its tools unavailable. All tools are unregistered from the sandbox. Individual tool states (enabled, approval_status) are preserved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to stop",
                },
            },
            "required": ["server_id"],
        },
    },
    {
        "name": "mcpbox_validate_code",
        "description": "Validate Python code syntax and check for required async main() function.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to validate",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "mcpbox_get_server_modules",
        "description": "Get the list of allowed Python modules. Use this to see what modules you can import in your tool code. Module configuration is global (applies to all servers).",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # Approval workflow tools
    {
        "name": "mcpbox_request_publish",
        "description": "Request admin approval to publish a draft or rejected tool. Tools must be approved before they become available for use.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to request publish for",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes for the admin reviewer explaining what this tool does and why it should be approved",
                },
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "mcpbox_request_module",
        "description": "Request a Python module to be whitelisted for use in your tool's code. Admin must approve before the module becomes available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool that needs this module",
                },
                "module_name": {
                    "type": "string",
                    "description": "Name of the Python module to whitelist (e.g., 'xml.etree.ElementTree', 'yaml')",
                },
                "justification": {
                    "type": "string",
                    "description": "Explanation of why this module is needed for your tool",
                },
            },
            "required": ["tool_id", "module_name", "justification"],
        },
    },
    {
        "name": "mcpbox_request_network_access",
        "description": "Request network access to an external host for your tool. Admin must approve before the tool can access the specified host.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool that needs network access",
                },
                "host": {
                    "type": "string",
                    "description": "Hostname or IP address to whitelist (e.g., 'api.github.com', 'example.com')",
                },
                "port": {
                    "type": "integer",
                    "description": "Optional port number. If not specified, any port is allowed.",
                },
                "justification": {
                    "type": "string",
                    "description": "Explanation of why your tool needs to access this host",
                },
            },
            "required": ["tool_id", "host", "justification"],
        },
    },
    {
        "name": "mcpbox_get_tool_status",
        "description": "Get the approval status of a tool, including any rejection reasons or pending requests.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to check status for",
                },
            },
            "required": ["tool_id"],
        },
    },
    # Versioning tools
    {
        "name": "mcpbox_list_tool_versions",
        "description": "List version history of a tool. Shows all previous versions with change summaries and timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to list versions for",
                },
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "mcpbox_rollback_tool",
        "description": "Rollback a tool to a previous version. Creates a new version with the old code (non-destructive). The tool's approval status is preserved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to rollback",
                },
                "version": {
                    "type": "integer",
                    "description": "Version number to rollback to",
                },
            },
            "required": ["tool_id", "version"],
        },
    },
    # Secrets management
    {
        "name": "mcpbox_create_server_secret",
        "description": 'Create an empty secret placeholder for a server. The secret value must be set by an admin in the MCPBox UI — secrets never pass through the LLM. Tool code accesses secrets via secrets["KEY_NAME"].',
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to add the secret to",
                },
                "key": {
                    "type": "string",
                    "description": "Secret key name (UPPER_SNAKE_CASE, e.g., 'THEIRSTACK_API_KEY')",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what this secret is for",
                },
            },
            "required": ["server_id", "key"],
        },
    },
    {
        "name": "mcpbox_list_server_secrets",
        "description": "List all secret key names configured for a server. Returns key names and whether each has a value set. Never returns actual secret values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to list secrets for",
                },
            },
            "required": ["server_id"],
        },
    },
    # Pending approvals overview
    {
        "name": "mcpbox_list_pending_requests",
        "description": "List all pending approval requests across the system. Returns pending tool publishes, module whitelist requests, and network access requests grouped by server.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # Execution logs
    {
        "name": "mcpbox_get_tool_logs",
        "description": "Get recent execution logs for a tool. Shows input arguments (secrets redacted), result, errors, stdout, duration, and success status for each invocation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {
                    "type": "string",
                    "description": "UUID of the tool to get logs for",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of logs to return (default: 10, max: 50)",
                    "default": 10,
                },
            },
            "required": ["tool_id"],
        },
    },
    # --- External MCP Sources ---
    {
        "name": "mcpbox_add_external_source",
        "description": "Add an external MCP server as a source for a MCPbox server. This allows importing tools from the external server. Auth credentials should be stored as server secrets first (use mcpbox_create_server_secret), then referenced by key name here.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the MCPbox server to add the source to",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name for this source (e.g., 'GitHub MCP', 'Slack MCP')",
                },
                "url": {
                    "type": "string",
                    "description": "URL of the external MCP server endpoint (e.g., 'https://mcp.example.com/mcp')",
                },
                "auth_type": {
                    "type": "string",
                    "enum": ["none", "bearer", "header"],
                    "description": "Authentication type: 'none', 'bearer' (Authorization: Bearer <secret>), or 'header' (custom header). Default: 'none'",
                    "default": "none",
                },
                "auth_secret_name": {
                    "type": "string",
                    "description": "Name of a server secret containing the auth credential (create it first with mcpbox_create_server_secret)",
                },
                "auth_header_name": {
                    "type": "string",
                    "description": "Custom header name when auth_type='header' (e.g., 'X-API-Key'). Default: 'Authorization'",
                },
                "transport_type": {
                    "type": "string",
                    "enum": ["streamable_http", "sse"],
                    "description": "MCP transport type. Default: 'streamable_http'",
                    "default": "streamable_http",
                },
            },
            "required": ["server_id", "name", "url"],
        },
    },
    {
        "name": "mcpbox_list_external_sources",
        "description": "List all external MCP sources configured for a server. Shows name, URL, auth type, status, and discovered tool count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to list sources for",
                },
            },
            "required": ["server_id"],
        },
    },
    {
        "name": "mcpbox_discover_external_tools",
        "description": "Connect to an external MCP server and discover its available tools. Returns tool names, descriptions, and input schemas. Does NOT import the tools - use mcpbox_import_external_tools after discovery.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "UUID of the external source to discover tools from",
                },
            },
            "required": ["source_id"],
        },
    },
    {
        "name": "mcpbox_import_external_tools",
        "description": "Import selected tools from an external MCP source into the MCPbox server. Imported tools are created in 'draft' status - use mcpbox_request_publish to submit them for admin approval. The admin must approve before the tools become available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "UUID of the external source to import from",
                },
                "tool_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tool names to import (as returned by mcpbox_discover_external_tools)",
                },
            },
            "required": ["source_id", "tool_names"],
        },
    },
]


class MCPManagementService:
    """Service for executing MCP management tools."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._server_service = ServerService(db)
        self._tool_service = ToolService(db)

    def get_tools(self) -> list[dict]:
        """Get all available management tools in MCP format."""
        return MCP_MANAGEMENT_TOOLS

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        sandbox_client: SandboxClient | None = None,
    ) -> dict[str, Any]:
        """Execute a management tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            sandbox_client: Optional sandbox client for test operations

        Returns:
            Tool execution result
        """
        # Dispatch to appropriate handler
        handlers = {
            "mcpbox_list_servers": self._list_servers,
            "mcpbox_get_server": self._get_server,
            "mcpbox_create_server": self._create_server,
            "mcpbox_delete_server": self._delete_server,
            "mcpbox_list_tools": self._list_tools,
            "mcpbox_get_tool": self._get_tool,
            "mcpbox_create_tool": self._create_tool,
            "mcpbox_update_tool": self._update_tool,
            "mcpbox_delete_tool": self._delete_tool,
            "mcpbox_validate_code": self._validate_code,
            "mcpbox_get_server_modules": self._get_server_modules,
            # Approval workflow handlers
            "mcpbox_request_publish": self._request_publish,
            "mcpbox_request_module": self._request_module,
            "mcpbox_request_network_access": self._request_network_access,
            "mcpbox_get_tool_status": self._get_tool_status,
            # Versioning handlers
            "mcpbox_list_tool_versions": self._list_tool_versions,
            "mcpbox_rollback_tool": self._rollback_tool,
            # Pending approvals overview
            "mcpbox_list_pending_requests": self._list_pending_requests,
            # Secrets management
            "mcpbox_create_server_secret": self._create_server_secret,
            "mcpbox_list_server_secrets": self._list_server_secrets,
            # Execution logs
            "mcpbox_get_tool_logs": self._get_tool_logs,
            # External MCP sources (no sandbox needed)
            "mcpbox_add_external_source": self._add_external_source,
            "mcpbox_list_external_sources": self._list_external_sources,
            # Import uses cached tools, no sandbox needed
            "mcpbox_import_external_tools": self._import_external_tools,
        }

        # Special handlers that need sandbox client
        sandbox_handlers = {
            "mcpbox_test_code": self._test_code,
            "mcpbox_start_server": self._start_server,
            "mcpbox_stop_server": self._stop_server,
            # Discovery needs sandbox for live MCP connection
            "mcpbox_discover_external_tools": self._discover_external_tools,
        }

        if tool_name in handlers:
            return await handlers[tool_name](arguments)
        elif tool_name in sandbox_handlers:
            if sandbox_client is None:
                return {"error": "Sandbox client required for this operation"}
            return await sandbox_handlers[tool_name](arguments, sandbox_client)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _list_servers(self, args: dict) -> dict:
        """List all servers."""
        page = args.get("page", 1)
        page_size = min(args.get("page_size", 50), 100)

        servers, total = await self._server_service.list(page=page, page_size=page_size)

        return {
            "servers": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "description": s.description,
                    "status": s.status,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in servers
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def _get_server(self, args: dict) -> dict:
        """Get server details."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        # Build tool list
        tools_list = []
        for tool in server.tools or []:
            tools_list.append(
                {
                    "id": str(tool.id),
                    "name": tool.name,
                    "description": tool.description,
                    "enabled": tool.enabled,
                    "approval_status": tool.approval_status,
                }
            )

        # Count pending requests across all tools in this server
        from sqlalchemy import func, select

        from app.models.module_request import ModuleRequest
        from app.models.network_access_request import NetworkAccessRequest

        tool_ids = [tool.id for tool in (server.tools or [])]
        pending_modules = 0
        pending_network = 0
        if tool_ids:
            mod_count = await self.db.execute(
                select(func.count(ModuleRequest.id)).where(
                    ModuleRequest.tool_id.in_(tool_ids),
                    ModuleRequest.status == "pending",
                )
            )
            pending_modules = mod_count.scalar() or 0

            net_count = await self.db.execute(
                select(func.count(NetworkAccessRequest.id)).where(
                    NetworkAccessRequest.tool_id.in_(tool_ids),
                    NetworkAccessRequest.status == "pending",
                )
            )
            pending_network = net_count.scalar() or 0

        return {
            "id": str(server.id),
            "name": server.name,
            "description": server.description,
            "status": server.status,
            "network_mode": server.network_mode,
            "default_timeout_ms": server.default_timeout_ms,
            "created_at": server.created_at.isoformat() if server.created_at else None,
            "updated_at": server.updated_at.isoformat() if server.updated_at else None,
            "tools": tools_list,
            "tool_count": len(tools_list),
            "pending_requests": {
                "modules": pending_modules,
                "network": pending_network,
            },
        }

    async def _create_server(self, args: dict) -> dict:
        """Create a new server."""
        from app.schemas.server import ServerCreate

        name = args.get("name")
        if not name:
            return {"error": "name is required"}

        # Check name format (simple fixed pattern - no ReDoS risk)
        if not _NAME_PATTERN.match(name):
            return {
                "error": "name must be lowercase alphanumeric with underscores, starting with a letter"
            }

        try:
            server_data = ServerCreate(
                name=name,
                description=args.get("description", ""),
            )
            server = await self._server_service.create(server_data)
            return {
                "success": True,
                "id": str(server.id),
                "name": server.name,
                "message": f"Server '{name}' created successfully",
            }
        except ValueError as e:
            return {"error": f"Invalid server data: {e!s}"}
        except Exception as e:
            logger.exception(f"Failed to create server '{name}': {e}")
            return {"error": "Failed to create server due to an internal error"}

    async def _delete_server(self, args: dict) -> dict:
        """Delete a server."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        deleted = await self._server_service.delete(server_id)
        if not deleted:
            return {"error": f"Server {server_id} not found"}

        return {
            "success": True,
            "message": f"Server {server_id} deleted successfully",
        }

    async def _list_tools(self, args: dict) -> dict:
        """List tools in a server."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        # Verify server exists
        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        tools, total = await self._tool_service.list_by_server(server_id)

        return {
            "server_id": str(server_id),
            "server_name": server.name,
            "tools": [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "description": t.description,
                    "enabled": t.enabled,
                }
                for t in tools
            ],
            "total": total,
        }

    async def _get_tool(self, args: dict) -> dict:
        """Get tool details."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        tool = await self._tool_service.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}

        return {
            "id": str(tool.id),
            "server_id": str(tool.server_id),
            "name": tool.name,
            "description": tool.description,
            "enabled": tool.enabled,
            "timeout_ms": tool.timeout_ms,
            "input_schema": tool.input_schema,
            "current_version": tool.current_version,
            "python_code": tool.python_code,
        }

    async def _create_tool(self, args: dict) -> dict:
        """Create a new tool."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        # Verify server exists
        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        name = args.get("name")
        if not name:
            return {"error": "name is required"}

        # Check name format (simple fixed pattern - no ReDoS risk)
        if not _NAME_PATTERN.match(name):
            return {
                "error": "name must be lowercase alphanumeric with underscores, starting with a letter"
            }

        python_code = args.get("python_code")
        if not python_code:
            return {"error": "python_code is required"}

        # Validate Python code
        from app.schemas.tool import validate_python_code

        validation = validate_python_code(python_code)
        if not validation["valid"]:
            return {"error": f"Invalid Python code: {validation['error']}"}
        if not validation["has_main"]:
            return {"error": "Python code must contain an async def main() function"}

        try:
            from app.schemas.tool import ToolCreate

            tool_data = ToolCreate(
                name=name,
                description=args.get("description"),
                python_code=python_code,
                code_dependencies=None,
                timeout_ms=None,
            )

            tool = await self._tool_service.create(server_id, tool_data)

            return {
                "success": True,
                "id": str(tool.id),
                "name": tool.name,
                "message": f"Tool '{name}' created successfully",
            }
        except ValueError as e:
            return {"error": f"Invalid tool data: {e!s}"}
        except Exception as e:
            logger.exception(f"Failed to create tool '{name}': {e}")
            return {"error": "Failed to create tool due to an internal error"}

    async def _update_tool(self, args: dict) -> dict:
        """Update a tool."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        # Check tool exists
        tool = await self._tool_service.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}

        # Build update data
        from app.schemas.tool import ToolUpdate

        update_fields = {}
        for field in ["name", "description", "enabled", "timeout_ms"]:
            if field in args and args[field] is not None:
                update_fields[field] = args[field]

        if "python_code" in args:
            # Validate Python code
            from app.schemas.tool import validate_python_code

            validation = validate_python_code(args["python_code"])
            if not validation["valid"]:
                return {"error": f"Invalid Python code: {validation['error']}"}
            if not validation["has_main"]:
                return {"error": "Python code must contain an async def main() function"}
            update_fields["python_code"] = args["python_code"]

        if not update_fields:
            return {"error": "No fields to update"}

        try:
            tool_update = ToolUpdate(**update_fields)
            updated_tool = await self._tool_service.update(tool_id, tool_update)

            if updated_tool is None:
                return {"error": f"Tool {tool_id} not found"}

            # If MCP-visible fields changed and server is running,
            # re-register with sandbox and notify MCP clients
            mcp_fields = {"name", "description", "enabled", "python_code"}
            if mcp_fields & update_fields.keys():
                try:
                    server = await self._server_service.get(updated_tool.server_id)
                    if server and server.status == "running":
                        # Re-register with sandbox so changes take effect
                        from app.api.sandbox import (
                            _build_external_source_configs,
                            _build_tool_definitions,
                        )
                        from app.services.global_config import GlobalConfigService
                        from app.services.server_secret import (
                            ServerSecretService,
                        )

                        all_tools, _ = await self._tool_service.list_by_server(server.id)
                        active_tools = [
                            t for t in all_tools if t.enabled and t.approval_status == "approved"
                        ]
                        tool_defs = _build_tool_definitions(active_tools)

                        secret_service = ServerSecretService(self.db)
                        secrets = await secret_service.get_decrypted_for_injection(server.id)
                        config_service = GlobalConfigService(self.db)
                        allowed_modules = await config_service.get_allowed_modules()
                        external_sources = await _build_external_source_configs(
                            self.db, server.id, secrets
                        )

                        sandbox_client = SandboxClient.get_instance()
                        await sandbox_client.register_server(
                            server_id=str(server.id),
                            server_name=server.name,
                            tools=tool_defs,
                            allowed_modules=allowed_modules,
                            secrets=secrets,
                            external_sources=external_sources,
                        )

                        # Notify MCP clients (same-process, gateway)
                        from app.services.tool_change_notifier import (
                            notify_tools_changed_local,
                        )

                        await notify_tools_changed_local()
                except Exception as e:
                    logger.warning(f"Failed to notify tool change: {e}")

            return {
                "success": True,
                "id": str(updated_tool.id),
                "name": updated_tool.name,
                "message": f"Tool '{updated_tool.name}' updated successfully",
            }
        except ValueError as e:
            return {"error": f"Invalid update data: {e!s}"}
        except Exception as e:
            logger.exception(f"Failed to update tool {tool_id}: {e}")
            return {"error": "Failed to update tool due to an internal error"}

    async def _delete_tool(self, args: dict) -> dict:
        """Delete a tool."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        # Fetch tool first to get server_id for notification
        tool = await self._tool_service.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}

        server_id = tool.server_id
        deleted = await self._tool_service.delete(tool_id)
        if not deleted:
            return {"error": f"Tool {tool_id} not found"}

        # Re-register with sandbox and notify MCP clients if server is running
        try:
            server = await self._server_service.get(server_id)
            if server and server.status == "running":
                from app.api.sandbox import (
                    _build_external_source_configs,
                    _build_tool_definitions,
                )
                from app.services.global_config import GlobalConfigService
                from app.services.server_secret import (
                    ServerSecretService,
                )

                all_tools, _ = await self._tool_service.list_by_server(server.id)
                active_tools = [
                    t for t in all_tools if t.enabled and t.approval_status == "approved"
                ]
                tool_defs = _build_tool_definitions(active_tools)

                secret_service = ServerSecretService(self.db)
                secrets = await secret_service.get_decrypted_for_injection(server.id)
                config_service = GlobalConfigService(self.db)
                allowed_modules = await config_service.get_allowed_modules()
                external_sources = await _build_external_source_configs(self.db, server.id, secrets)

                sandbox_client = SandboxClient.get_instance()
                await sandbox_client.register_server(
                    server_id=str(server.id),
                    server_name=server.name,
                    tools=tool_defs,
                    allowed_modules=allowed_modules,
                    secrets=secrets,
                    external_sources=external_sources,
                )

                from app.services.tool_change_notifier import (
                    notify_tools_changed_local,
                )

                await notify_tools_changed_local()
        except Exception as e:
            logger.warning(f"Failed to notify tool change after delete: {e}")

        return {
            "success": True,
            "message": f"Tool {tool_id} deleted successfully",
        }

    async def _start_server(self, args: dict, sandbox_client: SandboxClient) -> dict:
        """Start a server (register with sandbox)."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        if server.status == "running":
            return {"error": "Server is already running"}

        # Get tools for this server and filter to approved + enabled
        tools, _total = await self._tool_service.list_by_server(server_id)
        tool_defs = self._build_tool_definitions(tools)
        if not tool_defs:
            if not tools:
                return {"error": "Server has no tools defined. Add tools first."}
            return {
                "error": (
                    "Server has no approved and enabled tools. "
                    "Use mcpbox_request_publish to submit tools for approval, "
                    "then approve them in the admin UI."
                )
            }

        # Get secrets for injection
        from app.services.server_secret import ServerSecretService

        secret_service = ServerSecretService(self.db)
        secrets = await secret_service.get_decrypted_for_injection(server_id)

        # Get global allowed modules
        from app.services.global_config import GlobalConfigService

        config_service = GlobalConfigService(self.db)
        allowed_modules = await config_service.get_allowed_modules()

        # Build external source configs for passthrough tools
        from app.api.sandbox import _build_external_source_configs

        external_sources_data = await _build_external_source_configs(self.db, server_id, secrets)

        try:
            # Register with sandbox
            result = await sandbox_client.register_server(
                server_id=str(server_id),
                server_name=server.name,
                tools=tool_defs,
                allowed_modules=allowed_modules,
                secrets=secrets,
                external_sources=external_sources_data,
            )

            if not result.get("success"):
                logger.error(f"Failed to register server with sandbox: {result.get('error')}")
                return {"error": "Failed to register server with sandbox"}

            # Update server status
            await self._server_service.update_status(server_id, "running")
            await self.db.commit()

            # Notify MCP clients that tool list has changed
            from app.services.tool_change_notifier import notify_tools_changed_local

            await notify_tools_changed_local()

            return {
                "success": True,
                "message": f"Server '{server.name}' started",
                "status": "running",
                "registered_tools": result.get("tools_registered", len(tool_defs)),
            }
        except Exception as e:
            logger.exception(f"Failed to start server {server_id}: {e}")
            await self._server_service.update_status(server_id, "error")
            await self.db.commit()
            return {"error": "Failed to start server due to an internal error"}

    async def _stop_server(self, args: dict, sandbox_client: SandboxClient) -> dict:
        """Stop a server (unregister from sandbox)."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        if server.status != "running":
            return {"error": "Server is not running"}

        try:
            # Unregister from sandbox
            await sandbox_client.unregister_server(str(server_id))

            # Update server status
            await self._server_service.update_status(server_id, "stopped")
            await self.db.commit()

            # Notify MCP clients that tool list has changed
            from app.services.tool_change_notifier import notify_tools_changed_local

            await notify_tools_changed_local()

            return {
                "success": True,
                "message": f"Server '{server.name}' stopped",
                "status": "stopped",
            }
        except Exception as e:
            logger.exception(f"Failed to stop server {server_id}: {e}")
            return {"error": "Failed to stop server due to an internal error"}

    async def _validate_code(self, args: dict) -> dict:
        """Validate Python code."""
        code = args.get("code")
        if not code:
            return {"error": "code is required"}

        from app.schemas.tool import extract_input_schema_from_python, validate_python_code

        validation = validate_python_code(code)

        result = {
            "valid": validation["valid"],
            "has_main": validation["has_main"],
            "error": validation["error"],
            "parameters": validation["parameters"],
        }

        if validation["valid"] and validation["has_main"]:
            result["input_schema"] = extract_input_schema_from_python(code)

        return result

    async def _get_server_modules(self, args: dict) -> dict:
        """Get globally allowed Python modules."""
        from app.services.global_config import GlobalConfigService

        # Use global config service
        config_service = GlobalConfigService(self.db)
        allowed = await config_service.get_allowed_modules()
        is_custom = not await config_service.is_using_defaults()

        return {
            "is_custom_config": is_custom,
            "allowed_modules": sorted(allowed) if allowed else [],
            "default_modules": sorted(config_service.get_default_modules()),
            "total_allowed": len(allowed) if allowed else 0,
            "description": (
                "These are the Python modules you can import in your tool code. "
                "Module configuration is global and applies to all servers. "
                "Use mcpbox_request_module to request additional modules."
            ),
        }

    async def _test_code(self, args: dict, sandbox_client: SandboxClient) -> dict:
        """Test a saved tool by running its current code in the sandbox.

        Fetches the tool's code, secrets, and network config from the DB so the
        test environment is identical to production. Blocked if tool_approval_mode
        is 'require_approval' and the tool has not yet been approved, ensuring the
        admin retains control over what code runs even during development.

        Always logs the test run in the tool's execution history with is_test=True.
        """
        import time

        from sqlalchemy import select

        from app.models import Tool
        from app.services.execution_log import ExecutionLogService
        from app.services.global_config import GlobalConfigService
        from app.services.server_secret import ServerSecretService
        from app.services.setting import SettingService

        tool_id_str = args.get("tool_id")
        if not tool_id_str:
            return {"error": "tool_id is required"}

        try:
            tool_id = UUID(tool_id_str)
        except (ValueError, TypeError):
            return {"error": "Invalid tool_id"}

        # Fetch the tool — code, approval status, and server linkage
        tool_result = await self.db.execute(select(Tool).where(Tool.id == tool_id))
        tool = tool_result.scalar_one_or_none()
        if not tool:
            return {"error": f"Tool {tool_id_str} not found"}

        if not tool.python_code:
            return {"error": "Tool has no code to test"}

        # Enforce admin approval gate: if require_approval mode is active,
        # block testing of unapproved tools so the admin controls what runs.
        setting_service = SettingService(self.db)
        approval_mode = await setting_service.get_value(
            "tool_approval_mode", default="require_approval"
        )
        if approval_mode == "require_approval" and tool.approval_status != "approved":
            return {
                "error": (
                    f"Tool '{tool.name}' cannot be tested until it is approved "
                    f"(current status: {tool.approval_status}). "
                    "Use mcpbox_request_publish to submit it for admin review, "
                    "or ask the admin to set tool_approval_mode to 'auto_approve'."
                )
            }

        arguments = args.get("arguments", {})

        # Fetch global allowed modules (live admin-approved list)
        config_service = GlobalConfigService(self.db)
        allowed_modules = await config_service.get_allowed_modules()

        # Fetch server secrets and network allowlist — same as production execution
        server = await self._server_service.get(tool.server_id)
        secret_service = ServerSecretService(self.db)
        secrets = await secret_service.get_decrypted_for_injection(tool.server_id)
        allowed_hosts: list[str] | None = None
        if server and server.network_mode == "allowlist":
            allowed_hosts = server.allowed_hosts or []

        start_time = time.monotonic()
        try:
            result = await sandbox_client.execute_code(
                code=tool.python_code,
                arguments=arguments,
                timeout_seconds=30,
                secrets=secrets,
                allowed_hosts=allowed_hosts,
                allowed_modules=allowed_modules,
            )
        except httpx.TimeoutException:
            return {"error": "Code execution timed out"}
        except httpx.RequestError as e:
            return {"error": f"Sandbox communication failed: {e!s}"}
        except Exception as e:
            logger.exception(f"Test execution failed: {e}")
            return {"error": "Test execution failed due to an internal error"}

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Always log the test run — full visibility for admin and LLM alike
        try:
            log_service = ExecutionLogService(self.db)
            await log_service.create_log(
                tool_id=tool.id,
                server_id=tool.server_id,
                tool_name=tool.name,
                input_args={"arguments": arguments},
                result=result.get("result"),
                error=result.get("error"),
                stdout=result.get("stdout"),
                duration_ms=duration_ms,
                success=result.get("success", False),
                is_test=True,
            )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to save test execution log: {e}")
            # Never fail the test run itself due to logging errors

        return result

    # =========================================================================
    # Approval Workflow Handlers
    # =========================================================================

    async def _request_publish(self, args: dict) -> dict:
        """Request admin approval to publish a tool."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        notes = args.get("notes")

        from app.services.approval import ApprovalService

        approval_service = ApprovalService(self.db)

        try:
            tool = await approval_service.request_publish(
                tool_id=tool_id,
                notes=notes,
                requested_by=None,  # Will be set from JWT in gateway if available
            )

            if tool.approval_status == "approved":
                # Auto-approved: immediately re-register with sandbox so the tool
                # is live without requiring a manual server restart.
                from app.api.approvals import _refresh_server_registration
                from app.services.tool import ToolService as _ToolService

                tool_with_server = await _ToolService(self.db).get_with_server(tool_id)
                if tool_with_server:
                    await _refresh_server_registration(tool_with_server, self.db)
                    from app.services.tool_change_notifier import fire_and_forget_notify

                    fire_and_forget_notify()

                message = (
                    f"Tool '{tool.name}' has been auto-approved and registered with the sandbox. "
                    "Important: Most MCP clients do not currently "
                    "support automatic tool list refresh. The user will need to restart or refresh "
                    "their client to see the new tool."
                )
            else:
                message = (
                    f"Tool '{tool.name}' has been submitted for admin review. "
                    "Once approved, the user will need to restart or refresh their MCP client "
                    "to see the new tool, as clients do not currently support automatic tool "
                    "list refresh."
                )

            return {
                "success": True,
                "tool_id": str(tool.id),
                "name": tool.name,
                "status": tool.approval_status,
                "message": message,
            }
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception(f"Failed to request publish for tool {tool_id}: {e}")
            return {"error": "Failed to request publish due to an internal error"}

    async def _request_module(self, args: dict) -> dict:
        """Request a Python module to be whitelisted."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        module_name = args.get("module_name")
        justification = args.get("justification")

        if not module_name:
            return {"error": "module_name is required"}
        if not justification:
            return {"error": "justification is required"}

        from app.services.approval import ApprovalService

        approval_service = ApprovalService(self.db)

        try:
            request = await approval_service.create_module_request(
                tool_id=tool_id,
                module_name=module_name,
                justification=justification,
                requested_by=None,  # Will be set from JWT in gateway if available
            )
            return {
                "success": True,
                "request_id": str(request.id),
                "module_name": request.module_name,
                "status": request.status,
                "message": f"Request to whitelist module '{module_name}' has been submitted. "
                "An admin will review and approve or reject it.",
            }
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception(f"Failed to create module request: {e}")
            return {"error": "Failed to create module request due to an internal error"}

    async def _request_network_access(self, args: dict) -> dict:
        """Request network access to a host."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        host = args.get("host")
        port = args.get("port")
        justification = args.get("justification")

        if not host:
            return {"error": "host is required"}
        if not justification:
            return {"error": "justification is required"}

        from app.services.approval import ApprovalService

        approval_service = ApprovalService(self.db)

        try:
            request = await approval_service.create_network_access_request(
                tool_id=tool_id,
                host=host,
                port=port,
                justification=justification,
                requested_by=None,  # Will be set from JWT in gateway if available
            )
            port_str = f":{port}" if port else ""
            return {
                "success": True,
                "request_id": str(request.id),
                "host": request.host,
                "port": request.port,
                "status": request.status,
                "message": f"Request to access '{host}{port_str}' has been submitted. "
                "An admin will review and approve or reject it.",
            }
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception(f"Failed to create network access request: {e}")
            return {"error": "Failed to create network access request due to an internal error"}

    async def _get_tool_status(self, args: dict) -> dict:
        """Get detailed status of a tool including approval status and pending requests."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        tool = await self._tool_service.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}

        from app.services.approval import ApprovalService

        approval_service = ApprovalService(self.db)

        # Get pending requests for this tool
        module_requests = await approval_service.get_module_requests_for_tool(tool_id)
        network_requests = await approval_service.get_network_access_requests_for_tool(tool_id)

        return {
            "tool_id": str(tool.id),
            "name": tool.name,
            "approval_status": tool.approval_status,
            "created_by": tool.created_by,
            "approval_requested_at": tool.approval_requested_at.isoformat()
            if tool.approval_requested_at
            else None,
            "approved_at": tool.approved_at.isoformat() if tool.approved_at else None,
            "approved_by": tool.approved_by,
            "rejection_reason": tool.rejection_reason,
            "publish_notes": tool.publish_notes,
            "module_requests": [
                {
                    "id": str(req.id),
                    "module_name": req.module_name,
                    "status": req.status,
                    "rejection_reason": req.rejection_reason,
                    "created_at": req.created_at.isoformat() if req.created_at else None,
                }
                for req in module_requests
            ],
            "network_access_requests": [
                {
                    "id": str(req.id),
                    "host": req.host,
                    "port": req.port,
                    "status": req.status,
                    "rejection_reason": req.rejection_reason,
                    "created_at": req.created_at.isoformat() if req.created_at else None,
                }
                for req in network_requests
            ],
        }

    # =========================================================================
    # Secrets Management Handlers
    # =========================================================================

    async def _create_server_secret(self, args: dict) -> dict:
        """Create an empty secret placeholder for a server."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        key = args.get("key")
        if not key:
            return {"error": "key is required"}

        description = args.get("description")

        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        from app.services.server_secret import ServerSecretService

        secret_service = ServerSecretService(self.db)

        try:
            secret = await secret_service.create(
                server_id=server_id,
                key_name=key,
                description=description,
            )
            return {
                "success": True,
                "server_id": str(server_id),
                "key": secret.key_name,
                "description": secret.description,
                "has_value": False,
                "message": f"Secret placeholder '{key}' created. "
                "An admin must set the value in the MCPBox UI before it can be used.",
            }
        except Exception as e:
            if "uq_server_secrets_server_key" in str(e):
                return {"error": f"Secret '{key}' already exists for this server"}
            logger.exception(f"Failed to create secret: {e}")
            return {"error": "Failed to create secret due to an internal error"}

    async def _list_server_secrets(self, args: dict) -> dict:
        """List secret key names for a server (never returns values)."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        from app.services.server_secret import ServerSecretService

        secret_service = ServerSecretService(self.db)
        secrets = await secret_service.list_by_server(server_id)

        return {
            "server_id": str(server_id),
            "server_name": server.name,
            "secrets": [
                {
                    "key": s.key_name,
                    "description": s.description,
                    "has_value": s.has_value,
                }
                for s in secrets
            ],
            "total": len(secrets),
        }

    # =========================================================================
    # Version Management Handlers
    # =========================================================================

    async def _list_tool_versions(self, args: dict) -> dict:
        """List version history for a tool."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        tool = await self._tool_service.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}

        versions, total = await self._tool_service.list_versions(tool_id)

        return {
            "tool_id": str(tool.id),
            "tool_name": tool.name,
            "current_version": tool.current_version,
            "total_versions": total,
            "versions": [
                {
                    "version": v.version_number,
                    "change_summary": v.change_summary,
                    "change_source": v.change_source,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ],
        }

    async def _rollback_tool(self, args: dict) -> dict:
        """Rollback a tool to a previous version."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        version = args.get("version")
        if version is None:
            return {"error": "version is required"}

        try:
            version = int(version)
        except (ValueError, TypeError):
            return {"error": "version must be an integer"}

        tool = await self._tool_service.rollback(tool_id, version)
        if not tool:
            return {"error": f"Tool {tool_id} not found or version {version} does not exist"}

        return {
            "success": True,
            "tool_id": str(tool.id),
            "name": tool.name,
            "current_version": tool.current_version,
            "message": f"Tool '{tool.name}' rolled back to version {version}. "
            f"Current version is now {tool.current_version}.",
        }

    # =========================================================================
    # Pending Approvals Overview Handler
    # =========================================================================

    async def _list_pending_requests(self, args: dict) -> dict:
        """List all pending approval requests across the system."""
        from app.services.approval import ApprovalService

        approval_service = ApprovalService(self.db)

        try:
            # Get pending tools
            pending_tools_raw, tools_total = await approval_service.get_pending_tools(
                page=1, page_size=50
            )
            pending_tools = [
                {
                    "id": str(t["id"]) if isinstance(t, dict) else str(t.id),
                    "name": t["name"] if isinstance(t, dict) else t.name,
                    "server_name": t.get("server_name", "") if isinstance(t, dict) else "",
                    "requested_at": (
                        t["approval_requested_at"].isoformat()
                        if isinstance(t, dict) and t.get("approval_requested_at")
                        else (
                            t.approval_requested_at.isoformat()
                            if hasattr(t, "approval_requested_at") and t.approval_requested_at
                            else None
                        )
                    ),
                }
                for t in pending_tools_raw
            ]

            # Get pending module requests
            pending_modules_raw, modules_total = await approval_service.get_pending_module_requests(
                page=1, page_size=50
            )
            pending_modules = [
                {
                    "id": str(m["id"]) if isinstance(m, dict) else str(m.id),
                    "module_name": m["module_name"] if isinstance(m, dict) else m.module_name,
                    "tool_name": m.get("tool_name", "") if isinstance(m, dict) else "",
                    "server_name": m.get("server_name", "") if isinstance(m, dict) else "",
                }
                for m in pending_modules_raw
            ]

            # Get pending network access requests
            (
                pending_network_raw,
                network_total,
            ) = await approval_service.get_pending_network_access_requests(page=1, page_size=50)
            pending_network = [
                {
                    "id": str(n["id"]) if isinstance(n, dict) else str(n.id),
                    "host": n["host"] if isinstance(n, dict) else n.host,
                    "port": n.get("port") if isinstance(n, dict) else n.port,
                    "tool_name": n.get("tool_name", "") if isinstance(n, dict) else "",
                    "server_name": n.get("server_name", "") if isinstance(n, dict) else "",
                }
                for n in pending_network_raw
            ]

            total = tools_total + modules_total + network_total

            return {
                "pending_tools": pending_tools,
                "pending_module_requests": pending_modules,
                "pending_network_requests": pending_network,
                "summary": {
                    "tools": tools_total,
                    "modules": modules_total,
                    "network": network_total,
                    "total": total,
                },
            }
        except Exception as e:
            logger.exception(f"Failed to list pending requests: {e}")
            return {"error": "Failed to list pending requests due to an internal error"}

    # =========================================================================
    # Execution Log Handlers
    # =========================================================================

    async def _get_tool_logs(self, args: dict) -> dict:
        """Get recent execution logs for a tool."""
        try:
            tool_id = UUID(args["tool_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid tool_id"}

        tool = await self._tool_service.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}

        limit = min(args.get("limit", 10), 50)

        from app.services.execution_log import ExecutionLogService

        log_service = ExecutionLogService(self.db)
        logs, total = await log_service.list_by_tool(tool_id, page=1, page_size=limit)

        return {
            "tool_id": str(tool.id),
            "tool_name": tool.name,
            "logs": [
                {
                    "id": str(log.id),
                    "success": log.success,
                    "duration_ms": log.duration_ms,
                    "error": log.error,
                    "input_args": log.input_args,
                    "result": log.result,
                    "stdout": log.stdout,
                    "executed_by": log.executed_by,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ],
            "total": total,
        }

    # =========================================================================
    # External MCP Source Handlers
    # =========================================================================

    async def _add_external_source(self, args: dict) -> dict:
        """Add an external MCP source to a server."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        name = args.get("name")
        url = args.get("url")
        if not name:
            return {"error": "name is required"}
        if not url:
            return {"error": "url is required"}

        # Validate server exists
        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        from app.schemas.external_mcp_source import ExternalMCPSourceCreate
        from app.services.external_mcp_source import ExternalMCPSourceService

        source_service = ExternalMCPSourceService(self.db)

        try:
            data = ExternalMCPSourceCreate(
                name=name,
                url=url,
                auth_type=args.get("auth_type", "none"),
                auth_secret_name=args.get("auth_secret_name"),
                auth_header_name=args.get("auth_header_name"),
                transport_type=args.get("transport_type", "streamable_http"),
            )
            source = await source_service.create(server_id, data)

            return {
                "success": True,
                "source_id": str(source.id),
                "name": source.name,
                "url": source.url,
                "auth_type": source.auth_type,
                "transport_type": source.transport_type,
                "message": f"External source '{name}' added to server '{server.name}'. "
                "Use mcpbox_discover_external_tools to see available tools, "
                "then mcpbox_import_external_tools to import them.",
            }
        except Exception as e:
            logger.exception(f"Failed to add external source: {e}")
            return {"error": f"Failed to add external source: {e}"}

    async def _list_external_sources(self, args: dict) -> dict:
        """List external MCP sources for a server."""
        try:
            server_id = UUID(args["server_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid server_id"}

        server = await self._server_service.get(server_id)
        if not server:
            return {"error": f"Server {server_id} not found"}

        from app.services.external_mcp_source import ExternalMCPSourceService

        source_service = ExternalMCPSourceService(self.db)
        sources = await source_service.list_by_server(server_id)

        return {
            "server_id": str(server_id),
            "server_name": server.name,
            "sources": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "url": s.url,
                    "auth_type": s.auth_type,
                    "transport_type": s.transport_type,
                    "status": s.status,
                    "tool_count": s.tool_count,
                    "last_discovered_at": (
                        s.last_discovered_at.isoformat() if s.last_discovered_at else None
                    ),
                }
                for s in sources
            ],
            "total": len(sources),
        }

    async def _discover_external_tools(self, args: dict, sandbox_client: SandboxClient) -> dict:
        """Discover tools from an external MCP source."""
        try:
            source_id = UUID(args["source_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid source_id"}

        from app.services.external_mcp_source import ExternalMCPSourceService
        from app.services.server_secret import ServerSecretService

        source_service = ExternalMCPSourceService(self.db)
        source = await source_service.get(source_id)
        if not source:
            return {"error": f"External source {source_id} not found"}

        # Get decrypted secrets for auth
        secret_service = ServerSecretService(self.db)
        secrets = await secret_service.get_decrypted_for_injection(source.server_id)

        try:
            discovered = await source_service.discover_tools(
                source_id=source_id,
                sandbox_client=sandbox_client,
                secrets=secrets,
            )

            return {
                "success": True,
                "source_id": str(source.id),
                "source_name": source.name,
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                    }
                    for t in discovered
                ],
                "total": len(discovered),
                "message": f"Found {len(discovered)} tools on '{source.name}'. "
                "Use mcpbox_import_external_tools with the tool names you want to import.",
            }
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception(f"Failed to discover external tools: {e}")
            return {"error": f"Discovery failed: {e}"}

    async def _import_external_tools(self, args: dict) -> dict:
        """Import selected tools from an external MCP source."""
        try:
            source_id = UUID(args["source_id"])
        except (ValueError, KeyError):
            return {"error": "Invalid source_id"}

        tool_names = args.get("tool_names", [])
        if not tool_names:
            return {"error": "tool_names is required (list of tool names to import)"}

        from app.services.external_mcp_source import ExternalMCPSourceService

        source_service = ExternalMCPSourceService(self.db)
        source = await source_service.get(source_id)
        if not source:
            return {"error": f"External source {source_id} not found"}

        # Use cached tools instead of re-discovering
        cached = await source_service.get_cached_tools(source_id)
        if cached is None:
            return {
                "error": "No cached tools available. "
                "Use mcpbox_discover_external_tools first to discover tools."
            }

        # Import selected tools from cache
        try:
            result = await source_service.import_tools(
                source_id=source_id,
                tool_names=tool_names,
                discovered_tools=cached,
            )

            response = {
                "success": True,
                "imported_tools": [
                    {
                        "id": str(t.id),
                        "name": t.name,
                        "description": t.description,
                        "tool_type": t.tool_type,
                        "approval_status": t.approval_status,
                    }
                    for t in result.created
                ],
                "count": len(result.created),
                "message": f"Imported {len(result.created)} tool(s) as drafts. "
                "Use mcpbox_request_publish for each tool to submit for admin approval.",
            }
            if result.skipped:
                response["skipped_tools"] = result.skipped
                response["skipped_count"] = len(result.skipped)
                response["message"] = (
                    f"Imported {len(result.created)} tool(s) as drafts, "
                    f"skipped {len(result.skipped)}. "
                    "Use mcpbox_request_publish for each tool to submit for admin approval."
                )
            return response
        except Exception as e:
            logger.exception(f"Failed to import external tools: {e}")
            return {"error": f"Import failed: {e}"}

    # =========================================================================
    # Helper Methods for Server Registration
    # =========================================================================

    def _build_tool_definitions(self, tools: list) -> list[dict]:
        """Build tool definitions for sandbox registration (enabled + approved only)."""
        from app.services.tool_utils import build_tool_definitions

        return build_tool_definitions(tools, filter_enabled_approved=True)


def get_management_tools_list() -> list[dict]:
    """Get the list of management tools in MCP format."""
    return MCP_MANAGEMENT_TOOLS
