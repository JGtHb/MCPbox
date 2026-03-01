"""Unit tests for the tool registry."""

import stat
from unittest.mock import patch

from app.registry import Tool


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_register_server_creates_server(self, tool_registry, sample_tool_def):
        """Registering a server adds it to the registry."""
        count = tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
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
        )

        assert count == 2

    def test_register_server_replaces_existing(self, tool_registry, sample_tool_def):
        """Re-registering a server replaces the old one."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="OldServer",
            tools=[sample_tool_def],
        )

        tool_registry.register_server(
            server_id="server-1",
            server_name="NewServer",
            tools=[{**sample_tool_def, "name": "new_tool"}],
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
        )
        tool_registry.register_server(
            server_id="server-2",
            server_name="Server2",
            tools=[{**sample_tool_def, "name": "other_tool"}],
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
        )
        tool_registry.register_server(
            server_id="server-2",
            server_name="Server2",
            tools=[sample_tool_def],
        )

        assert tool_registry.tool_count == 3


class TestPassthroughToolRegistration:
    """Tests for MCP passthrough tool registration and routing."""

    def test_register_passthrough_tool(self, tool_registry):
        """Can register a passthrough tool with external source."""
        passthrough_tool_def = {
            "name": "external_search",
            "description": "Search via external MCP",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            "tool_type": "mcp_passthrough",
            "external_source_id": "source-1",
            "external_tool_name": "search",
        }
        external_sources = [
            {
                "source_id": "source-1",
                "url": "https://external.example.com/mcp",
                "auth_headers": {"Authorization": "Bearer token"},
                "transport_type": "streamable_http",
            }
        ]

        count = tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[passthrough_tool_def],
            external_sources=external_sources,
        )

        assert count == 1
        tool = tool_registry.get_tool("TestServer__external_search")
        assert tool is not None
        assert tool.is_passthrough is True
        assert tool.external_source_id == "source-1"
        assert tool.external_tool_name == "search"

    def test_register_mixed_tools(self, tool_registry, sample_tool_def):
        """Can register both python_code and passthrough tools in one server."""
        passthrough_def = {
            "name": "ext_tool",
            "description": "External tool",
            "parameters": {},
            "tool_type": "mcp_passthrough",
            "external_source_id": "src-1",
            "external_tool_name": "original_tool",
        }
        external_sources = [
            {"source_id": "src-1", "url": "https://ext.example.com/mcp"},
        ]

        count = tool_registry.register_server(
            server_id="server-1",
            server_name="MixedServer",
            tools=[sample_tool_def, passthrough_def],
            external_sources=external_sources,
        )

        assert count == 2
        python_tool = tool_registry.get_tool("MixedServer__get_weather")
        assert python_tool is not None
        assert python_tool.is_passthrough is False

        ext_tool = tool_registry.get_tool("MixedServer__ext_tool")
        assert ext_tool is not None
        assert ext_tool.is_passthrough is True

    def test_external_sources_stored_on_server(self, tool_registry):
        """External source configs are stored on the registered server."""
        external_sources = [
            {
                "source_id": "src-1",
                "url": "https://a.example.com/mcp",
                "auth_headers": {"Authorization": "Bearer a"},
            },
            {
                "source_id": "src-2",
                "url": "https://b.example.com/mcp",
            },
        ]

        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[],
            external_sources=external_sources,
        )

        server = tool_registry.servers["server-1"]
        assert len(server.external_sources) == 2
        assert "src-1" in server.external_sources
        assert server.external_sources["src-1"].url == "https://a.example.com/mcp"
        assert server.external_sources["src-1"].auth_headers == {
            "Authorization": "Bearer a"
        }

    def test_python_tool_not_passthrough(self, sample_tool_def, tool_registry):
        """Regular python_code tools have is_passthrough=False."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
        )

        tool = tool_registry.get_tool("TestServer__get_weather")
        assert tool.is_passthrough is False
        assert tool.tool_type == "python_code"


class TestUpdateSecrets:
    """Tests for ToolRegistry.update_secrets method."""

    def test_update_secrets_on_running_server(self, tool_registry, sample_tool_def):
        """Updating secrets replaces the server's secrets dict."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            secrets={"OLD_KEY": "old_value"},
        )

        result = tool_registry.update_secrets(
            "server-1", {"NEW_KEY": "new_value", "ANOTHER": "val"}
        )

        assert result is True
        assert tool_registry.servers["server-1"].secrets == {
            "NEW_KEY": "new_value",
            "ANOTHER": "val",
        }

    def test_update_secrets_nonexistent_server(self, tool_registry):
        """Updating secrets for a non-existent server returns False."""
        result = tool_registry.update_secrets("nonexistent", {"KEY": "val"})
        assert result is False

    def test_update_secrets_clears_old_secrets(self, tool_registry, sample_tool_def):
        """Updating with an empty dict removes all secrets."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            secrets={"KEY": "value"},
        )

        result = tool_registry.update_secrets("server-1", {})

        assert result is True
        assert tool_registry.servers["server-1"].secrets == {}

    def test_update_secrets_does_not_affect_tools(self, tool_registry, sample_tool_def):
        """Updating secrets doesn't change registered tools."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            secrets={"KEY": "old"},
        )

        tool_registry.update_secrets("server-1", {"KEY": "new"})

        # Tools should still be intact
        assert len(tool_registry.servers["server-1"].tools) == 1
        assert "get_weather" in tool_registry.servers["server-1"].tools


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


class TestSquidACLFileUpdates:
    """Tests for _update_squid_approved_hosts writing the ACL file."""

    def test_writes_private_ips(self, tool_registry, sample_tool_def, tmp_path):
        """Private IPs from allowed_hosts are written to the ACL file."""
        acl_file = tmp_path / "approved-private.txt"
        with patch("app.registry._SQUID_ACL_PATH", acl_file):
            tool_registry.register_server(
                server_id="s1",
                server_name="S1",
                tools=[sample_tool_def],
                allowed_hosts=["192.168.1.2", "10.0.0.5", "api.example.com"],
            )

        content = acl_file.read_text()
        assert "192.168.1.2" in content
        assert "10.0.0.5" in content
        # Public hostnames must NOT appear (squid already allows them)
        assert "api.example.com" not in content

    def test_writes_lan_hostnames(self, tool_registry, sample_tool_def, tmp_path):
        """LAN hostname patterns (.local, .lan, single-label) are written."""
        acl_file = tmp_path / "approved-private.txt"
        with patch("app.registry._SQUID_ACL_PATH", acl_file):
            tool_registry.register_server(
                server_id="s1",
                server_name="S1",
                tools=[sample_tool_def],
                allowed_hosts=["mynas.local", "printer.lan", "homeserver"],
            )

        content = acl_file.read_text()
        assert "mynas.local" in content
        assert "printer.lan" in content
        assert "homeserver" in content

    def test_aggregates_across_servers(self, tool_registry, sample_tool_def, tmp_path):
        """Hosts from multiple servers are merged into one file."""
        acl_file = tmp_path / "approved-private.txt"
        with patch("app.registry._SQUID_ACL_PATH", acl_file):
            tool_registry.register_server(
                server_id="s1",
                server_name="S1",
                tools=[sample_tool_def],
                allowed_hosts=["192.168.1.1"],
            )
            tool_registry.register_server(
                server_id="s2",
                server_name="S2",
                tools=[{**sample_tool_def, "name": "tool2"}],
                allowed_hosts=["10.0.0.1"],
            )

        content = acl_file.read_text()
        assert "192.168.1.1" in content
        assert "10.0.0.1" in content

    def test_unregister_removes_hosts(self, tool_registry, sample_tool_def, tmp_path):
        """Unregistering a server removes its hosts from the ACL file."""
        acl_file = tmp_path / "approved-private.txt"
        with patch("app.registry._SQUID_ACL_PATH", acl_file):
            tool_registry.register_server(
                server_id="s1",
                server_name="S1",
                tools=[sample_tool_def],
                allowed_hosts=["192.168.1.1"],
            )
            tool_registry.register_server(
                server_id="s2",
                server_name="S2",
                tools=[{**sample_tool_def, "name": "t2"}],
                allowed_hosts=["10.0.0.1"],
            )

            tool_registry.unregister_server("s1")

        content = acl_file.read_text()
        assert "192.168.1.1" not in content
        assert "10.0.0.1" in content

    def test_empty_when_no_private_hosts(
        self, tool_registry, sample_tool_def, tmp_path
    ):
        """File is empty when only public hosts are approved."""
        acl_file = tmp_path / "approved-private.txt"
        with patch("app.registry._SQUID_ACL_PATH", acl_file):
            tool_registry.register_server(
                server_id="s1",
                server_name="S1",
                tools=[sample_tool_def],
                allowed_hosts=["api.github.com", "example.com"],
            )

        content = acl_file.read_text()
        assert content == ""

    def test_logs_warning_on_permission_error(
        self, tool_registry, sample_tool_def, tmp_path, caplog
    ):
        """Permission errors are logged (not silently swallowed)."""
        acl_dir = tmp_path / "squid-acl"
        acl_dir.mkdir()
        # Make directory read-only so writes fail
        acl_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        acl_file = acl_dir / "approved-private.txt"

        try:
            with patch("app.registry._SQUID_ACL_PATH", acl_file):
                import logging

                with caplog.at_level(logging.ERROR, logger="app.registry"):
                    tool_registry.register_server(
                        server_id="s1",
                        server_name="S1",
                        tools=[sample_tool_def],
                        allowed_hosts=["192.168.1.1"],
                    )

            assert "Failed to write squid ACL file" in caplog.text
        finally:
            # Restore permissions for cleanup
            acl_dir.chmod(stat.S_IRWXU)

    def test_skips_silently_when_volume_not_mounted(
        self, tool_registry, sample_tool_def, caplog
    ):
        """When the ACL volume doesn't exist, skip without error logs."""
        nonexistent = "/nonexistent/squid-acl/approved-private.txt"
        from pathlib import Path

        with patch("app.registry._SQUID_ACL_PATH", Path(nonexistent)):
            import logging

            with caplog.at_level(logging.ERROR, logger="app.registry"):
                tool_registry.register_server(
                    server_id="s1",
                    server_name="S1",
                    tools=[sample_tool_def],
                    allowed_hosts=["192.168.1.1"],
                )

        # Should NOT log an error (volume simply not mounted)
        assert "Failed to write squid ACL file" not in caplog.text
