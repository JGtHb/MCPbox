"""Unit tests for the tool registry."""

from app.registry import Tool


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_register_server_creates_server(
        self, tool_registry, sample_tool_def, sample_credentials
    ):
        """Registering a server adds it to the registry."""
        count = tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            credentials=sample_credentials,
        )

        assert count == 1
        assert "server-1" in tool_registry.servers
        assert tool_registry.servers["server-1"].server_name == "TestServer"

    def test_register_server_returns_tool_count(self, tool_registry, sample_tool_def):
        """register_server returns the number of tools registered."""
        tools = [sample_tool_def, {**sample_tool_def, "name": "tool2"}]

        count = tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=tools,
            credentials=[],
        )

        assert count == 2

    def test_register_server_replaces_existing(self, tool_registry, sample_tool_def):
        """Re-registering a server replaces the old one."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="OldServer",
            tools=[sample_tool_def],
            credentials=[],
        )

        tool_registry.register_server(
            server_id="server-1",
            server_name="NewServer",
            tools=[{**sample_tool_def, "name": "new_tool"}],
            credentials=[],
        )

        assert tool_registry.servers["server-1"].server_name == "NewServer"
        assert len(tool_registry.servers["server-1"].tools) == 1
        assert "new_tool" in tool_registry.servers["server-1"].tools

    def test_unregister_server_removes_server(self, tool_registry, sample_tool_def):
        """Unregistering removes the server."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            credentials=[],
        )

        result = tool_registry.unregister_server("server-1")

        assert result is True
        assert "server-1" not in tool_registry.servers

    def test_unregister_nonexistent_returns_false(self, tool_registry):
        """Unregistering non-existent server returns False."""
        result = tool_registry.unregister_server("nonexistent")
        assert result is False

    def test_get_tool_by_full_name(self, tool_registry, sample_tool_def):
        """Can get a tool by its full name."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            credentials=[],
        )

        tool = tool_registry.get_tool("TestServer__get_weather")

        assert tool is not None
        assert tool.name == "get_weather"
        assert tool.server_name == "TestServer"

    def test_get_tool_not_found_returns_none(self, tool_registry):
        """Getting non-existent tool returns None."""
        tool = tool_registry.get_tool("NonExistent__tool")
        assert tool is None

    def test_list_tools_returns_mcp_format(self, tool_registry, sample_tool_def):
        """list_tools returns tools in MCP format."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            credentials=[],
        )

        tools = tool_registry.list_tools()

        assert len(tools) == 1
        assert tools[0]["name"] == "TestServer__get_weather"
        assert "inputSchema" in tools[0]
        assert "description" in tools[0]

    def test_list_tools_for_server(self, tool_registry, sample_tool_def):
        """Can list tools for a specific server."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="Server1",
            tools=[sample_tool_def],
            credentials=[],
        )
        tool_registry.register_server(
            server_id="server-2",
            server_name="Server2",
            tools=[{**sample_tool_def, "name": "other_tool"}],
            credentials=[],
        )

        tools = tool_registry.list_tools_for_server("server-1")

        assert len(tools) == 1
        assert "Server1" in tools[0]["name"]

    def test_tool_count_property(self, tool_registry, sample_tool_def):
        """tool_count property returns total tools across all servers."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="Server1",
            tools=[sample_tool_def, {**sample_tool_def, "name": "tool2"}],
            credentials=[],
        )
        tool_registry.register_server(
            server_id="server-2",
            server_name="Server2",
            tools=[sample_tool_def],
            credentials=[],
        )

        assert tool_registry.tool_count == 3


class TestToolFullName:
    """Tests for Tool.full_name property."""

    def test_full_name_combines_server_and_tool(self):
        """Full name is server_name__tool_name."""
        tool = Tool(
            name="my_tool",
            description="Test",
            server_id="server-1",
            server_name="MyServer",
            parameters={},
            python_code="async def main(): return {}",
        )

        assert tool.full_name == "MyServer__my_tool"
