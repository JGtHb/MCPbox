"""Tests for MCP Management Tools service."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.mcp_management import (
    MCPManagementService,
    get_management_tools_list,
)


class TestManagementToolDefinitions:
    """Test the management tool definitions."""

    def test_tool_definitions_exist(self):
        """Test that management tools are defined."""
        tools = get_management_tools_list()
        assert len(tools) > 0
        assert len(tools) == 28  # 24 original + 4 external source tools

    def test_all_tools_have_required_fields(self):
        """Test that all tools have required MCP fields."""
        tools = get_management_tools_list()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["name"].startswith("mcpbox_")

    def test_input_schemas_are_valid(self):
        """Test that input schemas are valid JSON Schema format."""
        tools = get_management_tools_list()
        for tool in tools:
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_tool_names_unique(self):
        """Test that all tool names are unique."""
        tools = get_management_tools_list()
        names = [t["name"] for t in tools]
        assert len(names) == len(set(names))


@pytest.mark.asyncio
class TestMCPManagementService:
    """Test the MCPManagementService class."""

    async def test_get_tools(self, db_session):
        """Test getting tool definitions."""
        service = MCPManagementService(db_session)
        tools = service.get_tools()
        assert len(tools) == 28

    async def test_list_servers_empty(self, db_session):
        """Test listing servers when none exist."""
        service = MCPManagementService(db_session)
        result = await service.execute_tool("mcpbox_list_servers", {})

        assert "servers" in result
        assert result["servers"] == []
        assert result["total"] == 0

    async def test_create_server(self, db_session):
        """Test creating a server via management tool."""
        service = MCPManagementService(db_session)
        result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "test_server", "description": "A test server"},
        )

        assert result["success"] is True
        assert "id" in result
        assert result["name"] == "test_server"

    async def test_create_server_invalid_name(self, db_session):
        """Test creating a server with invalid name."""
        service = MCPManagementService(db_session)

        # Name with spaces
        result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "invalid name"},
        )
        assert "error" in result

        # Name starting with number
        result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "123server"},
        )
        assert "error" in result

    async def test_create_server_missing_name(self, db_session):
        """Test creating a server without name."""
        service = MCPManagementService(db_session)
        result = await service.execute_tool(
            "mcpbox_create_server",
            {"description": "No name provided"},
        )

        assert "error" in result
        assert "name is required" in result["error"]

    async def test_get_server(self, db_session):
        """Test getting a server by ID."""
        service = MCPManagementService(db_session)

        # Create a server first
        create_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "get_test"},
        )
        server_id = create_result["id"]

        # Get the server
        result = await service.execute_tool(
            "mcpbox_get_server",
            {"server_id": server_id},
        )

        assert result["id"] == server_id
        assert result["name"] == "get_test"

    async def test_get_server_not_found(self, db_session):
        """Test getting a non-existent server."""
        service = MCPManagementService(db_session)
        fake_id = str(uuid4())

        result = await service.execute_tool(
            "mcpbox_get_server",
            {"server_id": fake_id},
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_delete_server(self, db_session):
        """Test deleting a server."""
        service = MCPManagementService(db_session)

        # Create a server
        create_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "delete_test"},
        )
        server_id = create_result["id"]

        # Delete it
        result = await service.execute_tool(
            "mcpbox_delete_server",
            {"server_id": server_id},
        )

        assert result["success"] is True

        # Verify it's gone
        get_result = await service.execute_tool(
            "mcpbox_get_server",
            {"server_id": server_id},
        )
        assert "error" in get_result

    async def test_list_tools_empty(self, db_session):
        """Test listing tools for a server with no tools."""
        service = MCPManagementService(db_session)

        # Create a server
        create_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "empty_server"},
        )
        server_id = create_result["id"]

        # List tools
        result = await service.execute_tool(
            "mcpbox_list_tools",
            {"server_id": server_id},
        )

        assert result["tools"] == []
        assert result["total"] == 0

    async def test_create_tool_with_python_code(self, db_session):
        """Test creating a Python code tool."""
        service = MCPManagementService(db_session)

        # Create a server first
        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "python_tools"},
        )
        server_id = server_result["id"]

        # Create a Python code tool
        result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "get_weather",
                "description": "Get weather data",
                "python_code": '''async def main(city: str) -> dict:
    """Get weather for a city."""
    return {"city": city, "temp": 72}
''',
            },
        )

        assert result["success"] is True
        assert "id" in result
        assert result["name"] == "get_weather"

    async def test_create_tool_with_parameters(self, db_session):
        """Test creating a Python code tool with parameters."""
        service = MCPManagementService(db_session)

        # Create a server first
        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "math_tools"},
        )
        server_id = server_result["id"]

        # Create a Python code tool with typed parameters
        result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "calculate_sum",
                "description": "Calculate the sum of two numbers",
                "python_code": '''async def main(a: int, b: int) -> int:
    """Calculate sum of a and b."""
    return a + b
''',
            },
        )

        assert result["success"] is True
        assert "id" in result
        assert result["name"] == "calculate_sum"

    async def test_create_tool_invalid_python(self, db_session):
        """Test creating a tool with invalid Python code."""
        service = MCPManagementService(db_session)

        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "invalid_python"},
        )
        server_id = server_result["id"]

        # Invalid syntax
        result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "invalid_tool",
                "python_code": "def broken( pass",
            },
        )

        assert "error" in result

    async def test_create_tool_missing_main(self, db_session):
        """Test creating a tool without async main function."""
        service = MCPManagementService(db_session)

        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "no_main"},
        )
        server_id = server_result["id"]

        result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "no_main_tool",
                "python_code": """def helper():
    return 42
""",
            },
        )

        assert "error" in result
        assert "async def main()" in result["error"]

    async def test_get_tool(self, db_session):
        """Test getting a tool by ID."""
        service = MCPManagementService(db_session)

        # Setup
        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "get_tool_test"},
        )
        server_id = server_result["id"]

        tool_result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "my_tool",
                "python_code": 'async def main() -> str:\n    return "hello"',
            },
        )
        tool_id = tool_result["id"]

        # Get the tool
        result = await service.execute_tool(
            "mcpbox_get_tool",
            {"tool_id": tool_id},
        )

        assert result["id"] == tool_id
        assert result["name"] == "my_tool"
        assert "python_code" in result

    async def test_update_tool(self, db_session):
        """Test updating a tool."""
        service = MCPManagementService(db_session)

        # Setup
        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "update_tool_test"},
        )
        server_id = server_result["id"]

        tool_result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "original_tool",
                "description": "Original description",
                "python_code": 'async def main() -> str:\n    return "original"',
            },
        )
        tool_id = tool_result["id"]

        # Update the tool
        result = await service.execute_tool(
            "mcpbox_update_tool",
            {
                "tool_id": tool_id,
                "description": "Updated description",
            },
        )

        assert result["success"] is True

        # Verify the update
        get_result = await service.execute_tool(
            "mcpbox_get_tool",
            {"tool_id": tool_id},
        )
        assert get_result["description"] == "Updated description"

    async def test_delete_tool(self, db_session):
        """Test deleting a tool."""
        service = MCPManagementService(db_session)

        # Setup
        server_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "delete_tool_test"},
        )
        server_id = server_result["id"]

        tool_result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "deletable_tool",
                "python_code": 'async def main() -> str:\n    return "delete me"',
            },
        )
        tool_id = tool_result["id"]

        # Delete the tool
        result = await service.execute_tool(
            "mcpbox_delete_tool",
            {"tool_id": tool_id},
        )

        assert result["success"] is True

        # Verify it's gone
        get_result = await service.execute_tool(
            "mcpbox_get_tool",
            {"tool_id": tool_id},
        )
        assert "error" in get_result

    async def test_validate_code_valid(self, db_session):
        """Test validating valid Python code."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_validate_code",
            {
                "code": """
async def main(text: str) -> dict:
    \"\"\"Process text.\"\"\"
    return {"result": text.upper()}
"""
            },
        )

        assert result["valid"] is True
        assert result["has_main"] is True
        assert result["error"] is None
        assert "input_schema" in result

    async def test_validate_code_invalid(self, db_session):
        """Test validating invalid Python code."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_validate_code",
            {"code": "def broken( pass"},
        )

        assert result["valid"] is False

    async def test_start_stop_server(self, db_session, mock_sandbox_client):
        """Test starting and stopping a server."""
        from unittest.mock import AsyncMock

        service = MCPManagementService(db_session)

        # Create a server
        create_result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "startstop_test"},
        )
        server_id = create_result["id"]

        # Create a tool for this server (required before starting)
        tool_result = await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "test_tool",
                "description": "A test tool",
                "python_code": "async def main():\n    return 'test'",
            },
        )

        # Approve the tool — start_server only registers approved+enabled tools
        from sqlalchemy import select

        from app.models.tool import Tool

        tool_row = (
            await db_session.execute(select(Tool).where(Tool.id == tool_result["id"]))
        ).scalar_one()
        tool_row.approval_status = "approved"
        await db_session.flush()

        # Mock sandbox client for start/stop operations
        mock_sandbox_client.register_server = AsyncMock(
            return_value={
                "success": True,
                "tools_registered": 1,
            }
        )
        mock_sandbox_client.unregister_server = AsyncMock(
            return_value={
                "success": True,
            }
        )

        # Start the server (pass sandbox_client)
        start_result = await service.execute_tool(
            "mcpbox_start_server",
            {"server_id": server_id},
            sandbox_client=mock_sandbox_client,
        )

        assert start_result["success"] is True
        assert start_result["status"] == "running"

        # Stop the server
        stop_result = await service.execute_tool(
            "mcpbox_stop_server",
            {"server_id": server_id},
            sandbox_client=mock_sandbox_client,
        )

        assert stop_result["success"] is True
        assert stop_result["status"] == "stopped"

    async def test_unknown_tool(self, db_session):
        """Test calling an unknown tool."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_unknown_tool",
            {},
        )

        assert "error" in result
        assert "Unknown tool" in result["error"]

    async def test_invalid_server_id(self, db_session):
        """Test using invalid server_id format."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_get_server",
            {"server_id": "not-a-uuid"},
        )

        assert "error" in result
        assert "Invalid server_id" in result["error"]

    async def test_invalid_tool_id(self, db_session):
        """Test using invalid tool_id format."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_get_tool",
            {"tool_id": "not-a-uuid"},
        )

        assert "error" in result
        assert "Invalid tool_id" in result["error"]


@pytest.mark.asyncio
class TestExternalMCPSourceTools:
    """Test the 4 external MCP source management tools."""

    # =====================================================================
    # Helper to create a server via the service (reused across tests)
    # =====================================================================

    async def _create_server(self, service: MCPManagementService) -> str:
        result = await service.execute_tool(
            "mcpbox_create_server",
            {"name": "ext_test_server", "description": "Server for external source tests"},
        )
        assert result.get("success") is True
        return result["id"]

    # =====================================================================
    # mcpbox_add_external_source
    # =====================================================================

    async def test_add_external_source_success(self, db_session):
        """Test adding an external MCP source with default auth."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "GitHub MCP",
                "url": "https://mcp.github.com/sse",
            },
        )

        assert result["success"] is True
        assert "source_id" in result
        assert result["name"] == "GitHub MCP"
        assert result["url"] == "https://mcp.github.com/sse"
        assert result["auth_type"] == "none"
        assert result["transport_type"] == "streamable_http"

    async def test_add_external_source_with_bearer_auth(self, db_session):
        """Test adding an external source with bearer auth type."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Slack MCP",
                "url": "https://mcp.slack.com/mcp",
                "auth_type": "bearer",
                "auth_secret_name": "SLACK_TOKEN",
                "transport_type": "sse",
            },
        )

        assert result["success"] is True
        assert result["auth_type"] == "bearer"
        assert result["transport_type"] == "sse"

    async def test_add_external_source_with_header_auth(self, db_session):
        """Test adding an external source with custom header auth type."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Custom API",
                "url": "https://api.example.com/mcp",
                "auth_type": "header",
                "auth_secret_name": "API_KEY",
                "auth_header_name": "X-API-Key",
            },
        )

        assert result["success"] is True
        assert result["auth_type"] == "header"

    async def test_add_external_source_missing_name(self, db_session):
        """Test adding an external source without a name."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "url": "https://mcp.example.com/mcp",
            },
        )

        assert "error" in result
        assert "name is required" in result["error"]

    async def test_add_external_source_missing_url(self, db_session):
        """Test adding an external source without a URL."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "No URL Source",
            },
        )

        assert "error" in result
        assert "url is required" in result["error"]

    async def test_add_external_source_server_not_found(self, db_session):
        """Test adding an external source to a non-existent server."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": str(uuid4()),
                "name": "Orphan Source",
                "url": "https://mcp.example.com/mcp",
            },
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_add_external_source_invalid_server_id(self, db_session):
        """Test adding an external source with an invalid server_id."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": "not-a-uuid",
                "name": "Bad ID Source",
                "url": "https://mcp.example.com/mcp",
            },
        )

        assert "error" in result
        assert "Invalid server_id" in result["error"]

    # =====================================================================
    # mcpbox_list_external_sources
    # =====================================================================

    async def test_list_external_sources_empty(self, db_session):
        """Test listing sources when none exist."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        result = await service.execute_tool(
            "mcpbox_list_external_sources",
            {"server_id": server_id},
        )

        assert result["sources"] == []
        assert result["total"] == 0
        assert result["server_id"] == server_id

    async def test_list_external_sources_with_sources(self, db_session):
        """Test listing sources after adding some."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        # Add two sources
        await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Source A",
                "url": "https://a.example.com/mcp",
            },
        )
        await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Source B",
                "url": "https://b.example.com/mcp",
                "auth_type": "bearer",
                "auth_secret_name": "B_TOKEN",
            },
        )

        result = await service.execute_tool(
            "mcpbox_list_external_sources",
            {"server_id": server_id},
        )

        assert result["total"] == 2
        assert len(result["sources"]) == 2
        names = {s["name"] for s in result["sources"]}
        assert names == {"Source A", "Source B"}
        # Each source should have expected fields
        for source in result["sources"]:
            assert "id" in source
            assert "url" in source
            assert "auth_type" in source
            assert "status" in source

    async def test_list_external_sources_server_not_found(self, db_session):
        """Test listing sources for a non-existent server."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_list_external_sources",
            {"server_id": str(uuid4())},
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_list_external_sources_invalid_server_id(self, db_session):
        """Test listing sources with invalid server_id."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_list_external_sources",
            {"server_id": "not-a-uuid"},
        )

        assert "error" in result
        assert "Invalid server_id" in result["error"]

    # =====================================================================
    # mcpbox_discover_external_tools
    # =====================================================================

    async def test_discover_external_tools_success(self, db_session, mock_sandbox_client):
        """Test successful tool discovery from an external source."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        # Add a source
        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Discovery Test",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        # Mock sandbox discover_external_tools response
        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": True,
                "tools": [
                    {
                        "name": "get_repos",
                        "description": "List repositories",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"org": {"type": "string"}},
                        },
                    },
                    {
                        "name": "create_issue",
                        "description": "Create a GitHub issue",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "repo": {"type": "string"},
                                "title": {"type": "string"},
                            },
                        },
                    },
                ],
            }
        )

        result = await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )

        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["tools"]) == 2
        tool_names = {t["name"] for t in result["tools"]}
        assert tool_names == {"get_repos", "create_issue"}
        # Verify each tool has expected fields
        for tool in result["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    async def test_discover_external_tools_source_not_found(self, db_session, mock_sandbox_client):
        """Test discovery with a non-existent source ID."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": str(uuid4())},
            sandbox_client=mock_sandbox_client,
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_discover_external_tools_invalid_source_id(self, db_session, mock_sandbox_client):
        """Test discovery with an invalid source ID."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": "not-a-uuid"},
            sandbox_client=mock_sandbox_client,
        )

        assert "error" in result
        assert "Invalid source_id" in result["error"]

    async def test_discover_external_tools_sandbox_failure(self, db_session, mock_sandbox_client):
        """Test discovery when the sandbox returns a failure."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Failing Source",
                "url": "https://mcp.broken.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        # Mock sandbox failure
        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": False,
                "error": "Connection refused",
            }
        )

        result = await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )

        assert "error" in result
        assert "Discovery failed" in result["error"]

    async def test_discover_external_tools_requires_sandbox(self, db_session):
        """Test that discovery without sandbox_client returns an error."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "No Sandbox",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        # Call without sandbox_client
        result = await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
        )

        assert "error" in result
        assert "Sandbox client required" in result["error"]

    # =====================================================================
    # mcpbox_import_external_tools
    # =====================================================================

    async def test_import_external_tools_success(self, db_session, mock_sandbox_client):
        """Test importing tools from a discovered external source."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        # Add source and discover tools
        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Import Test",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": True,
                "tools": [
                    {
                        "name": "list_items",
                        "description": "List items",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "get_item",
                        "description": "Get single item",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                        },
                    },
                ],
            }
        )

        # Discover first
        await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )

        # Import one tool
        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": source_id,
                "tool_names": ["list_items"],
            },
        )

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["imported_tools"]) == 1
        imported = result["imported_tools"][0]
        assert "import_test_list_items" == imported["name"]
        assert imported["tool_type"] == "mcp_passthrough"
        assert imported["approval_status"] == "draft"

    async def test_import_external_tools_multiple(self, db_session, mock_sandbox_client):
        """Test importing multiple tools at once."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Multi Import",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": True,
                "tools": [
                    {"name": "tool_a", "description": "Tool A", "inputSchema": {}},
                    {"name": "tool_b", "description": "Tool B", "inputSchema": {}},
                    {"name": "tool_c", "description": "Tool C", "inputSchema": {}},
                ],
            }
        )

        await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )

        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": source_id,
                "tool_names": ["tool_a", "tool_b", "tool_c"],
            },
        )

        assert result["success"] is True
        assert result["count"] == 3
        imported_names = {t["name"] for t in result["imported_tools"]}
        assert imported_names == {
            "multi_import_tool_a",
            "multi_import_tool_b",
            "multi_import_tool_c",
        }

    async def test_import_external_tools_skip_not_found(self, db_session, mock_sandbox_client):
        """Test that importing a non-existent tool name is skipped."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Skip Test",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": True,
                "tools": [
                    {"name": "real_tool", "description": "Exists", "inputSchema": {}},
                ],
            }
        )

        await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )

        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": source_id,
                "tool_names": ["real_tool", "nonexistent_tool"],
            },
        )

        assert result["success"] is True
        assert result["count"] == 1
        assert result["skipped_count"] == 1
        assert result["skipped_tools"][0]["name"] == "nonexistent_tool"
        assert result["skipped_tools"][0]["status"] == "skipped_not_found"

    async def test_import_external_tools_skip_duplicate(self, db_session, mock_sandbox_client):
        """Test that importing a tool that already exists is skipped."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Dup Test",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": True,
                "tools": [
                    {"name": "my_tool", "description": "A tool", "inputSchema": {}},
                ],
            }
        )

        await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )

        # Import once
        first = await service.execute_tool(
            "mcpbox_import_external_tools",
            {"source_id": source_id, "tool_names": ["my_tool"]},
        )
        assert first["success"] is True
        assert first["count"] == 1

        # Import same tool again — should be skipped as conflict
        second = await service.execute_tool(
            "mcpbox_import_external_tools",
            {"source_id": source_id, "tool_names": ["my_tool"]},
        )
        assert second["success"] is True
        assert second["count"] == 0
        assert second["skipped_count"] == 1
        assert second["skipped_tools"][0]["status"] == "skipped_conflict"

    async def test_import_external_tools_no_cache(self, db_session):
        """Test importing tools when no discovery has been done (no cache)."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "No Cache",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        # Try to import without discovering first
        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": source_id,
                "tool_names": ["some_tool"],
            },
        )

        assert "error" in result
        assert "No cached tools" in result["error"]
        assert "mcpbox_discover_external_tools" in result["error"]

    async def test_import_external_tools_empty_tool_names(self, db_session):
        """Test importing with an empty tool_names list."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "Empty Import",
                "url": "https://mcp.example.com/mcp",
            },
        )
        source_id = add_result["source_id"]

        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": source_id,
                "tool_names": [],
            },
        )

        assert "error" in result
        assert "tool_names is required" in result["error"]

    async def test_import_external_tools_source_not_found(self, db_session):
        """Test importing from a non-existent source."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": str(uuid4()),
                "tool_names": ["some_tool"],
            },
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_import_external_tools_invalid_source_id(self, db_session):
        """Test importing with an invalid source_id."""
        service = MCPManagementService(db_session)

        result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": "not-a-uuid",
                "tool_names": ["some_tool"],
            },
        )

        assert "error" in result
        assert "Invalid source_id" in result["error"]

    async def test_discover_then_import_end_to_end(self, db_session, mock_sandbox_client):
        """End-to-end: add source, discover tools, import, verify in server tools."""
        service = MCPManagementService(db_session)
        server_id = await self._create_server(service)

        # Step 1: Add external source
        add_result = await service.execute_tool(
            "mcpbox_add_external_source",
            {
                "server_id": server_id,
                "name": "E2E Source",
                "url": "https://mcp.example.com/mcp",
                "auth_type": "bearer",
                "auth_secret_name": "MY_TOKEN",
            },
        )
        source_id = add_result["source_id"]

        # Step 2: Discover tools
        mock_sandbox_client.discover_external_tools = AsyncMock(
            return_value={
                "success": True,
                "tools": [
                    {
                        "name": "search",
                        "description": "Search items",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                    {
                        "name": "create",
                        "description": "Create an item",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                ],
            }
        )

        discover_result = await service.execute_tool(
            "mcpbox_discover_external_tools",
            {"source_id": source_id},
            sandbox_client=mock_sandbox_client,
        )
        assert discover_result["success"] is True
        assert discover_result["total"] == 2

        # Step 3: Import one tool
        import_result = await service.execute_tool(
            "mcpbox_import_external_tools",
            {
                "source_id": source_id,
                "tool_names": ["search"],
            },
        )
        assert import_result["success"] is True
        assert import_result["count"] == 1

        # Step 4: Verify imported tool appears in server's tool list
        tools_result = await service.execute_tool(
            "mcpbox_list_tools",
            {"server_id": server_id},
        )
        assert tools_result["total"] == 1
        assert tools_result["tools"][0]["name"] == "e2e_source_search"

        # Step 5: List sources should show updated tool count
        sources_result = await service.execute_tool(
            "mcpbox_list_external_sources",
            {"server_id": server_id},
        )
        assert sources_result["total"] == 1
        source = sources_result["sources"][0]
        assert source["tool_count"] == 2  # 2 discovered
        assert source["status"] == "active"
