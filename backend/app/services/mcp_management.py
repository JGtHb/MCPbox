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

from app.services.credential import CredentialService
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
        "description": "Create a new MCP tool in a server. Tools are created in 'draft' status and must be submitted for admin approval using mcpbox_request_publish before they become available. Write Python code with an async main() function.",
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
                    "description": "Enable or disable the tool (optional)",
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
        "description": "Test Python code execution without saving. Use the 'async def main()' format (same as mcpbox_create_tool) and pass arguments via the arguments parameter. Returns result, stdout, and any errors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code with 'async def main(param: str) -> type: return value' entry point",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments available in the 'arguments' dict variable (optional)",
                },
                "server_id": {
                    "type": "string",
                    "description": "UUID of the server to use for module whitelist (optional). If not specified, uses default modules.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "mcpbox_start_server",
        "description": "Start an MCP server, making its tools available.",
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
        "description": "Stop an MCP server, making its tools unavailable.",
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
]


class MCPManagementService:
    """Service for executing MCP management tools."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._server_service = ServerService(db)
        self._tool_service = ToolService(db)
        self._credential_service = CredentialService(db)

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
        }

        # Special handlers that need sandbox client
        sandbox_handlers = {
            "mcpbox_test_code": self._test_code,
            "mcpbox_start_server": self._start_server,
            "mcpbox_stop_server": self._stop_server,
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

        return {
            "id": str(server.id),
            "name": server.name,
            "description": server.description,
            "status": server.status,
            "network_mode": server.network_mode,
            "default_timeout_ms": server.default_timeout_ms,
            "helper_code": server.helper_code,
            "created_at": server.created_at.isoformat() if server.created_at else None,
            "updated_at": server.updated_at.isoformat() if server.updated_at else None,
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

        deleted = await self._tool_service.delete(tool_id)
        if not deleted:
            return {"error": f"Tool {tool_id} not found"}

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

        # Get tools for this server (only enabled ones)
        tools, _total = await self._tool_service.list_by_server(server_id)
        if not tools:
            return {"error": "Server has no tools defined. Add tools first."}

        # Build tool definitions for sandbox
        tool_defs = self._build_tool_definitions(tools)

        # Get credentials and build the credentials list
        credentials = await self._credential_service.get_for_injection(server_id)
        credentials_list = self._build_credentials_list(credentials)

        # Get global allowed modules
        from app.services.global_config import GlobalConfigService

        config_service = GlobalConfigService(self.db)
        allowed_modules = await config_service.get_allowed_modules()

        try:
            # Register with sandbox
            result = await sandbox_client.register_server(
                server_id=str(server_id),
                server_name=server.name,
                tools=tool_defs,
                credentials=credentials_list,
                helper_code=server.helper_code,
                allowed_modules=allowed_modules,
            )

            if not result.get("success"):
                logger.error(f"Failed to register server with sandbox: {result.get('error')}")
                return {"error": "Failed to register server with sandbox"}

            # Update server status
            await self._server_service.update_status(server_id, "running")
            await self.db.commit()

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
        """Test Python code execution.

        Code should use the async def main() format (same as mcpbox_create_tool):
           async def main(x: int) -> int:
               return x * 2
        """
        code = args.get("code")
        if not code:
            return {"error": "code is required"}

        arguments = args.get("arguments", {})

        # Detect async def main() pattern and wrap it to call main() with arguments
        # Arguments are passed via the sandbox's arguments injection mechanism (not string interpolation)
        if "async def main" in code:
            code = f"""{code}

import asyncio
result = asyncio.get_running_loop().run_until_complete(main(**arguments))
"""

        # Get global allowed modules
        from app.services.global_config import GlobalConfigService

        config_service = GlobalConfigService(self.db)
        allowed_modules = await config_service.get_allowed_modules()

        try:
            result = await sandbox_client.execute_code(
                code=code,
                arguments=arguments,
                timeout_seconds=30,
                allowed_modules=allowed_modules,
            )
            return result
        except httpx.TimeoutException:
            return {"error": "Code execution timed out"}
        except httpx.RequestError as e:
            return {"error": f"Sandbox communication failed: {e!s}"}
        except Exception as e:
            logger.exception(f"Test execution failed: {e}")
            return {"error": "Test execution failed due to an internal error"}

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
            return {
                "success": True,
                "tool_id": str(tool.id),
                "name": tool.name,
                "status": tool.approval_status,
                "message": f"Tool '{tool.name}' has been submitted for admin review. "
                "You will be notified when the admin approves or rejects it.",
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
    # Helper Methods for Server Registration
    # =========================================================================

    def _build_tool_definitions(self, tools: list) -> list[dict]:
        """Build tool definitions for sandbox registration."""
        tool_defs = []

        for tool in tools:
            # Only include enabled and approved tools
            if not tool.enabled:
                continue
            if tool.approval_status != "approved":
                continue

            tool_def = {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {},
                "timeout_ms": tool.timeout_ms or 30000,
                "python_code": tool.python_code,
            }

            tool_defs.append(tool_def)

        return tool_defs

    def _build_credentials_list(self, credentials: list) -> list[dict]:
        """Build credentials list for sandbox registration.

        Passes full credential metadata so sandbox can properly configure auth.
        Values are passed encrypted - sandbox will decrypt them.
        """
        result = []

        for cred in credentials:
            cred_data = {
                "name": cred.name,
                "auth_type": cred.auth_type,
                "header_name": cred.header_name,
                "query_param_name": cred.query_param_name,
            }

            # Include encrypted values based on auth type
            if cred.auth_type in ("api_key_header", "api_key_query", "custom_header"):
                if cred.value:
                    cred_data["value"] = cred.value  # Encrypted
            elif cred.auth_type == "bearer":
                if cred.access_token:
                    cred_data["value"] = cred.access_token  # Encrypted
                elif cred.value:
                    cred_data["value"] = cred.value  # Encrypted
            elif cred.auth_type == "basic":
                if cred.username:
                    cred_data["username"] = cred.username  # Encrypted
                if cred.password:
                    cred_data["password"] = cred.password  # Encrypted
            elif cred.auth_type == "oauth2":
                if cred.access_token:
                    cred_data["value"] = cred.access_token  # Encrypted

            result.append(cred_data)

        return result


def get_management_tools_list() -> list[dict]:
    """Get the list of management tools in MCP format."""
    return MCP_MANAGEMENT_TOOLS
