"""Tests for MCP Management Tools service."""

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
        assert len(tools) == 18  # 18 management tools (test_endpoint removed for security)

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
        assert len(tools) == 19

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
                "python_code": '''def helper():
    return 42
''',
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
        await service.execute_tool(
            "mcpbox_create_tool",
            {
                "server_id": server_id,
                "name": "test_tool",
                "description": "A test tool",
                "python_code": "async def main():\n    return 'test'",
            },
        )

        # Mock sandbox client for start/stop operations
        mock_sandbox_client.register_server = AsyncMock(return_value={
            "success": True,
            "tools_registered": 1,
        })
        mock_sandbox_client.unregister_server = AsyncMock(return_value={
            "success": True,
        })

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
