"""Tests for export/import API endpoints."""

import hashlib
import hmac
import json
import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _normalize_import_data(data: dict) -> dict:
    """Normalize import data to match what the API expects for signature verification.

    The API reconstructs the data structure for verification, so we need to ensure
    our test data matches that exact structure.
    """
    normalized = {
        "version": data.get("version", "1.0"),
        "servers": [],
    }

    for server in data.get("servers", []):
        normalized_server = {
            "name": server.get("name"),
            "description": server.get("description"),
            "tools": [],
        }

        for tool in server.get("tools", []):
            # Normalize tool structure to match ExportedTool model_dump()
            normalized_tool = {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "enabled": tool.get("enabled", True),
                "timeout_ms": tool.get("timeout_ms"),
                "python_code": tool.get("python_code"),
                "input_schema": tool.get("input_schema"),
            }
            normalized_server["tools"].append(normalized_tool)

        normalized["servers"].append(normalized_server)

    return normalized


def _compute_signature(data: dict) -> str:
    """Compute HMAC-SHA256 signature for test export data.

    Mirrors the signature computation in app.api.export_import._compute_export_signature
    """
    # Get the encryption key (set in conftest.py for tests)
    key = os.environ.get("MCPBOX_ENCRYPTION_KEY", "0" * 64)

    # Normalize the data to match the API's structure
    normalized_data = _normalize_import_data(data)

    # Create a stable JSON representation (sorted keys, no whitespace)
    canonical = json.dumps(normalized_data, sort_keys=True, separators=(",", ":"))

    # Use encryption key as HMAC key
    signature = hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return signature


def _sign_import_data(data: dict) -> dict:
    """Add a valid signature to import data for testing."""
    data["signature"] = _compute_signature(data)
    return data


class TestExportAllServers:
    """Tests for GET /api/export/servers endpoint."""

    async def test_export_empty(self, async_client: AsyncClient, admin_headers):
        """Test exporting when no servers exist."""
        response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.0"
        assert "exported_at" in data
        assert data["servers"] == []

    async def test_export_with_servers(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test exporting servers with tools."""
        server = await server_factory(name="Test Server", description="Test description")
        await tool_factory(
            server=server,
            name="test_tool",
            description="Test tool description",
            enabled=True,
            timeout_ms=5000,
            python_code='async def main() -> str:\n    return "test"',
        )

        response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert len(data["servers"]) == 1
        exported_server = data["servers"][0]
        assert exported_server["name"] == "Test Server"
        assert exported_server["description"] == "Test description"
        assert len(exported_server["tools"]) == 1

        exported_tool = exported_server["tools"][0]
        assert exported_tool["name"] == "test_tool"
        assert exported_tool["description"] == "Test tool description"
        assert exported_tool["enabled"] is True
        assert exported_tool["timeout_ms"] == 5000

    async def test_export_multiple_servers(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test exporting multiple servers."""
        server1 = await server_factory(name="Server 1")
        server2 = await server_factory(name="Server 2")
        await tool_factory(server=server1, name="tool_1")
        await tool_factory(server=server2, name="tool_2a")
        await tool_factory(server=server2, name="tool_2b")

        response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert len(data["servers"]) == 2
        # Find servers by name (order may vary)
        names = {s["name"]: s for s in data["servers"]}
        assert "Server 1" in names
        assert "Server 2" in names
        assert len(names["Server 1"]["tools"]) == 1
        assert len(names["Server 2"]["tools"]) == 2


class TestExportSingleServer:
    """Tests for GET /api/export/servers/{server_id} endpoint."""

    async def test_export_server_not_found(self, async_client: AsyncClient, admin_headers):
        """Test exporting a nonexistent server returns 404."""
        import uuid

        response = await async_client.get(
            f"/api/export/servers/{uuid.uuid4()}", headers=admin_headers
        )
        assert response.status_code == 404

    async def test_export_single_server(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test exporting a single server."""
        server = await server_factory(name="Single Server")
        await tool_factory(server=server, name="single_tool")

        response = await async_client.get(f"/api/export/servers/{server.id}", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Single Server"
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "single_tool"


class TestImportServers:
    """Tests for POST /api/export/import endpoint."""

    async def test_import_empty(self, async_client: AsyncClient, admin_headers):
        """Test importing with no servers."""
        import_data = _sign_import_data({"version": "1.0", "servers": []})
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["servers_created"] == 0
        assert data["tools_created"] == 0
        assert data["errors"] == []

    async def test_import_server_without_tools(self, async_client: AsyncClient, admin_headers):
        """Test importing a server without tools."""
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {
                        "name": "Imported Server",
                        "description": "An imported server",
                        "tools": [],
                    }
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["servers_created"] == 1
        assert data["tools_created"] == 0

        # Verify server was created
        list_response = await async_client.get("/api/servers", headers=admin_headers)
        servers = list_response.json()["items"]
        assert any(s["name"] == "Imported Server" for s in servers)

    async def test_import_server_with_tools(self, async_client: AsyncClient, admin_headers):
        """Test importing a server with tools."""
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {
                        "name": "Server With Tools",
                        "description": "Has tools",
                        "tools": [
                            {
                                "name": "tool_1",
                                "description": "First tool",
                                "enabled": True,
                                "timeout_ms": 10000,
                                "python_code": "async def main() -> dict:\n    return {'data': 'ok'}",
                                "input_schema": {"type": "object", "properties": {}},
                            },
                            {
                                "name": "tool_2",
                                "description": "Second tool",
                                "enabled": False,
                                "timeout_ms": 5000,
                                "python_code": "async def main() -> dict:\n    return {'result': 'ok'}",
                                "input_schema": None,
                            },
                        ],
                    }
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["servers_created"] == 1
        assert data["tools_created"] == 2

    async def test_imported_tools_are_pending_review(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test that imported tools are set to pending_review for admin approval."""
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {
                        "name": "Approval Test Server",
                        "description": "Tools should need approval",
                        "tools": [
                            {
                                "name": "needs_approval",
                                "description": "Should be pending_review",
                                "enabled": True,
                                "timeout_ms": 10000,
                                "python_code": "async def main() -> str:\n    return 'ok'",
                                "input_schema": None,
                            },
                        ],
                    }
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200

        # Verify the tool shows up in the approval queue
        approval_response = await async_client.get(
            "/api/approvals/tools?status=pending_review",
            headers=admin_headers,
        )
        assert approval_response.status_code == 200
        items = approval_response.json()["items"]
        tool_names = [item["name"] for item in items]
        assert "needs_approval" in tool_names

    async def test_import_duplicate_name_gets_suffix(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test importing a server with existing name gets (imported) suffix."""
        # Create an existing server
        await server_factory(name="Existing Server")

        # Import server with same name
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {
                        "name": "Existing Server",
                        "description": "Duplicate name",
                        "tools": [],
                    }
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["servers_created"] == 1

        # Verify both servers exist with different names
        list_response = await async_client.get("/api/servers", headers=admin_headers)
        servers = list_response.json()["items"]
        names = [s["name"] for s in servers]
        assert "Existing Server" in names
        assert "Existing Server (imported)" in names

    async def test_import_multiple_servers(self, async_client: AsyncClient, admin_headers):
        """Test importing multiple servers at once."""
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {"name": "Server A", "tools": []},
                    {"name": "Server B", "tools": []},
                    {"name": "Server C", "tools": []},
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["servers_created"] == 3

    async def test_roundtrip_export_import(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test that export -> import preserves data."""
        # Create a server with tools
        server = await server_factory(
            name="Roundtrip Server",
            description="Test roundtrip",
        )
        await tool_factory(
            server=server,
            name="roundtrip_tool",
            description="Tool for roundtrip",
            enabled=True,
            timeout_ms=15000,
            python_code='async def main() -> str:\n    return "roundtrip"',
        )

        # Export
        export_response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert export_response.status_code == 200
        export_data = export_response.json()

        # Delete the original server
        await async_client.delete(f"/api/servers/{server.id}", headers=admin_headers)

        # Import the exported data
        import_response = await async_client.post(
            "/api/export/import",
            json=export_data,
            headers=admin_headers,
        )
        assert import_response.status_code == 200
        import_result = import_response.json()
        assert import_result["success"] is True
        assert import_result["servers_created"] == 1
        assert import_result["tools_created"] == 1

        # Verify the imported server matches
        list_response = await async_client.get("/api/servers", headers=admin_headers)
        servers = list_response.json()["items"]
        imported_server = next(s for s in servers if s["name"] == "Roundtrip Server")

        detail_response = await async_client.get(
            f"/api/servers/{imported_server['id']}", headers=admin_headers
        )
        server_detail = detail_response.json()
        assert server_detail["description"] == "Test roundtrip"


class TestExportSignature:
    """Tests for export signature functionality."""

    async def test_export_includes_signature(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test that export includes a signature field."""
        await server_factory(name="Signature Test Server")

        response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert "signature" in data
        assert data["signature"] is not None
        assert len(data["signature"]) == 64  # SHA256 hex digest

    async def test_import_with_valid_signature(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test importing with a valid signature works."""
        # Create and export a server
        await server_factory(name="Valid Sig Server")

        export_response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert export_response.status_code == 200
        export_data = export_response.json()

        # Delete the server
        list_response = await async_client.get("/api/servers", headers=admin_headers)
        server = list_response.json()["items"][0]
        await async_client.delete(f"/api/servers/{server['id']}", headers=admin_headers)

        # Re-import with valid signature
        import_response = await async_client.post(
            "/api/export/import",
            json=export_data,
            headers=admin_headers,
        )
        assert import_response.status_code == 200
        result = import_response.json()
        assert result["success"] is True

    async def test_import_with_invalid_signature_warns(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test that import with tampered signature succeeds with warning."""
        response = await async_client.post(
            "/api/export/import",
            json={
                "version": "1.0",
                "servers": [
                    {
                        "name": "Tampered Server",
                        "description": "This was tampered",
                        "tools": [],
                    }
                ],
                "signature": "invalid_signature_that_does_not_match",
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert result["servers_created"] == 1
        assert any("signature" in w.lower() for w in result["warnings"])

    async def test_import_without_signature_warns(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test that import without signature succeeds with warning."""
        response = await async_client.post(
            "/api/export/import",
            json={
                "version": "1.0",
                "servers": [
                    {
                        "name": "Unsigned Server",
                        "description": "No signature provided",
                        "tools": [],
                    }
                ],
                # No signature field
            },
            headers=admin_headers,
        )
        # Should succeed with warning - unsigned imports allowed but flagged
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert result["servers_created"] == 1
        assert any("not signed" in w.lower() for w in result["warnings"])


class TestMCPPassthroughTools:
    """Tests for export/import behavior with mcp_passthrough tools."""

    async def test_export_excludes_mcp_passthrough_tools(
        self, async_client: AsyncClient, db_session, server_factory, tool_factory, admin_headers
    ):
        """Test that mcp_passthrough tools are excluded from export."""
        from app.models.tool import Tool

        server = await server_factory(name="Mixed Server")
        # Create a regular python_code tool via factory
        await tool_factory(
            server=server,
            name="python_tool",
            description="Regular tool",
            python_code='async def main() -> str:\n    return "ok"',
        )

        # Create an mcp_passthrough tool directly (factory defaults python_code)
        passthrough_tool = Tool(
            server_id=server.id,
            name="external_tool",
            description="Proxied from external MCP",
            tool_type="mcp_passthrough",
            python_code=None,
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            approval_status="approved",
            current_version=1,
        )
        db_session.add(passthrough_tool)
        await db_session.flush()

        response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert len(data["servers"]) == 1
        exported_tools = data["servers"][0]["tools"]
        assert len(exported_tools) == 1
        assert exported_tools[0]["name"] == "python_tool"

    async def test_export_single_server_excludes_mcp_passthrough(
        self, async_client: AsyncClient, db_session, server_factory, tool_factory, admin_headers
    ):
        """Test that single-server export also excludes mcp_passthrough tools."""
        from app.models.tool import Tool

        server = await server_factory(name="Single Mixed")
        await tool_factory(
            server=server,
            name="code_tool",
            python_code='async def main() -> str:\n    return "yes"',
        )
        passthrough = Tool(
            server_id=server.id,
            name="proxy_tool",
            description="External",
            tool_type="mcp_passthrough",
            python_code=None,
            input_schema=None,
            approval_status="approved",
            current_version=1,
        )
        db_session.add(passthrough)
        await db_session.flush()

        response = await async_client.get(f"/api/export/servers/{server.id}", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "code_tool"

    async def test_import_skips_tools_without_python_code(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test that importing tools without python_code skips them with a warning."""
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {
                        "name": "Server With Mixed Tools",
                        "description": "Has both types",
                        "tools": [
                            {
                                "name": "good_tool",
                                "description": "Has code",
                                "enabled": True,
                                "timeout_ms": 5000,
                                "python_code": 'async def main() -> str:\n    return "ok"',
                                "input_schema": None,
                            },
                            {
                                "name": "no_code_tool",
                                "description": "External tool without code",
                                "enabled": True,
                                "timeout_ms": None,
                                "python_code": None,
                                "input_schema": None,
                            },
                        ],
                    }
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()

        # Server should be created successfully with the valid tool
        assert data["success"] is True
        assert data["servers_created"] == 1
        assert data["tools_created"] == 1
        assert data["errors"] == []
        # The skipped tool should appear as a warning, not an error
        assert len(data["warnings"]) == 1
        assert "no_code_tool" in data["warnings"][0]

    async def test_import_server_with_only_passthrough_tools_still_created(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test that a server with only passthrough tools is still created (empty)."""
        import_data = _sign_import_data(
            {
                "version": "1.0",
                "servers": [
                    {
                        "name": "All External Server",
                        "description": "Only external tools",
                        "tools": [
                            {
                                "name": "ext_tool_1",
                                "description": "External",
                                "enabled": True,
                                "timeout_ms": None,
                                "python_code": None,
                                "input_schema": None,
                            },
                        ],
                    }
                ],
            }
        )
        response = await async_client.post(
            "/api/export/import",
            json=import_data,
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()

        # Server created, but no tools
        assert data["success"] is True
        assert data["servers_created"] == 1
        assert data["tools_created"] == 0
        assert len(data["warnings"]) == 1

    async def test_roundtrip_with_mixed_tools(
        self,
        async_client: AsyncClient,
        db_session,
        server_factory,
        tool_factory,
        admin_headers,
    ):
        """Test full roundtrip: export server with mixed tools, import preserves python_code tools."""
        from app.models.tool import Tool

        server = await server_factory(name="Roundtrip Mixed", description="Mixed tools")
        await tool_factory(
            server=server,
            name="native_tool",
            description="Native python tool",
            python_code='async def main() -> str:\n    return "native"',
        )
        passthrough = Tool(
            server_id=server.id,
            name="passthrough_tool",
            description="External proxy",
            tool_type="mcp_passthrough",
            python_code=None,
            input_schema=None,
            approval_status="approved",
            current_version=1,
        )
        db_session.add(passthrough)
        await db_session.flush()

        # Export
        export_response = await async_client.get("/api/export/servers", headers=admin_headers)
        assert export_response.status_code == 200
        export_data = export_response.json()

        # Verify passthrough was excluded from export
        assert len(export_data["servers"][0]["tools"]) == 1

        # Delete original server
        await async_client.delete(f"/api/servers/{server.id}", headers=admin_headers)

        # Import
        import_response = await async_client.post(
            "/api/export/import",
            json=export_data,
            headers=admin_headers,
        )
        assert import_response.status_code == 200
        result = import_response.json()
        assert result["success"] is True
        assert result["servers_created"] == 1
        assert result["tools_created"] == 1


class TestDownloadExport:
    """Tests for GET /api/export/download/servers endpoint."""

    async def test_download_returns_json_file(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test download endpoint returns JSON with attachment header."""
        await server_factory(name="Download Test")

        response = await async_client.get("/api/export/download/servers", headers=admin_headers)
        assert response.status_code == 200

        # Check content disposition header
        content_disposition = response.headers.get("content-disposition")
        assert content_disposition is not None
        assert "attachment" in content_disposition
        assert "mcpbox-export-" in content_disposition
        assert ".json" in content_disposition

        # Verify content is valid JSON
        data = response.json()
        assert "version" in data
        assert "servers" in data
        assert len(data["servers"]) == 1

    async def test_download_empty_export(self, async_client: AsyncClient, admin_headers):
        """Test downloading when no servers exist."""
        response = await async_client.get("/api/export/download/servers", headers=admin_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["servers"] == []
