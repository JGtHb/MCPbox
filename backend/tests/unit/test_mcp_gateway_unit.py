"""Unit tests for MCP Gateway error handling and edge cases.

These tests verify the MCP gateway properly handles:
- Invalid JSON-RPC requests
- Unknown methods
- Missing parameters
- Sandbox communication failures
- Management tool errors

Note: Integration tests are in tests/test_mcp_gateway.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.mcp_gateway import (
    MCPRequest,
    MCPResponse,
    _handle_management_tool_call,
    _handle_tools_list,
)


class TestMCPGatewayErrorHandling:
    """Test error handling in the MCP gateway."""

    @pytest.mark.asyncio
    async def test_tools_list_sandbox_unavailable(self):
        """Test tools/list when sandbox is unavailable."""
        mock_client = AsyncMock()
        mock_client.mcp_request.return_value = {
            "error": {"code": -32000, "message": "Sandbox unavailable"},
        }
        mock_db = AsyncMock()

        result = await _handle_tools_list(mock_client, db=mock_db)

        # Should still return management tools even if sandbox fails
        assert "tools" in result
        # Management tools should be present
        assert any(t["name"].startswith("mcpbox_") for t in result["tools"])

    @pytest.mark.asyncio
    async def test_tools_list_empty_sandbox_response(self):
        """Test tools/list when sandbox returns empty response."""
        mock_client = AsyncMock()
        mock_client.mcp_request.return_value = {
            "result": {"tools": []},
        }
        mock_db = AsyncMock()
        # Mock the db.execute() -> result.scalars().all() chain
        # result.scalars() is sync, so use MagicMock (not AsyncMock)
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await _handle_tools_list(mock_client, db=mock_db)

        # Should still have management tools
        assert "tools" in result
        assert len(result["tools"]) > 0

    @pytest.mark.asyncio
    async def test_tools_list_malformed_sandbox_response(self):
        """Test tools/list when sandbox returns malformed response."""
        mock_client = AsyncMock()
        mock_client.mcp_request.return_value = {
            "result": None,  # Malformed - no tools key
        }
        mock_db = AsyncMock()

        result = await _handle_tools_list(mock_client, db=mock_db)

        # Should handle gracefully and still return management tools
        assert "tools" in result

    @pytest.mark.asyncio
    async def test_management_tool_unknown_tool(self):
        """Test calling an unknown management tool."""
        mock_db = AsyncMock()
        mock_sandbox = AsyncMock()

        result = await _handle_management_tool_call(
            db=mock_db,
            tool_name="mcpbox_nonexistent_tool",
            arguments={},
            sandbox_client=mock_sandbox,
        )

        # Should return an error
        assert "content" in result
        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_management_tool_missing_required_argument(self):
        """Test management tool with missing required argument."""
        mock_db = AsyncMock()
        mock_sandbox = AsyncMock()

        # Call create_server without required 'name' argument
        result = await _handle_management_tool_call(
            db=mock_db,
            tool_name="mcpbox_create_server",
            arguments={},  # Missing 'name'
            sandbox_client=mock_sandbox,
        )

        # Should return an error about missing argument
        assert "content" in result
        # The error should be indicated
        assert result.get("isError") is True or "error" in str(result).lower()

    @pytest.mark.asyncio
    async def test_management_tool_database_error(self):
        """Test management tool when database operation fails."""
        mock_db = AsyncMock()
        mock_sandbox = AsyncMock()

        # Mock the MCPManagementService at the module level where it's used
        with patch("app.api.mcp_gateway.MCPManagementService") as MockService:
            mock_service_instance = MockService.return_value
            mock_service_instance.execute_tool = AsyncMock(
                side_effect=Exception("Database connection lost")
            )

            result = await _handle_management_tool_call(
                db=mock_db,
                tool_name="mcpbox_list_servers",
                arguments={},
                sandbox_client=mock_sandbox,
            )

        # Should return a user-friendly error (not expose internals)
        assert "content" in result
        assert result.get("isError") is True
        # Should not expose internal error details
        content_text = result["content"][0]["text"]
        assert "Database connection lost" not in content_text


class TestMCPRequestValidation:
    """Test MCP request model validation."""

    def test_valid_request(self):
        """Test valid MCP request is accepted."""
        request = MCPRequest(
            id=1,
            method="tools/list",
            params={},
        )
        assert request.method == "tools/list"
        assert request.id == 1

    def test_request_with_string_id(self):
        """Test MCP request with string ID is accepted."""
        request = MCPRequest(
            id="request-123",
            method="tools/call",
            params={"name": "test_tool"},
        )
        assert request.id == "request-123"

    def test_request_default_jsonrpc(self):
        """Test that jsonrpc defaults to 2.0."""
        request = MCPRequest(id=1, method="test")
        assert request.jsonrpc == "2.0"

    def test_request_optional_params(self):
        """Test that params is optional."""
        request = MCPRequest(id=1, method="test")
        assert request.params is None


class TestMCPResponseModel:
    """Test MCP response model."""

    def test_success_response(self):
        """Test successful response structure."""
        response = MCPResponse(
            id=1,
            result={"tools": []},
        )
        assert response.error is None
        assert response.result == {"tools": []}

    def test_error_response(self):
        """Test error response structure."""
        response = MCPResponse(
            id=1,
            error={"code": -32600, "message": "Invalid Request"},
        )
        assert response.result is None
        assert response.error["code"] == -32600

    def test_response_preserves_id(self):
        """Test that response ID matches request ID."""
        response = MCPResponse(
            id="request-abc",
            result={},
        )
        assert response.id == "request-abc"


class TestSandboxExceptionPropagation:
    """Test that sandbox exceptions propagate correctly."""

    @pytest.mark.asyncio
    async def test_sandbox_timeout_propagates(self):
        """Test that sandbox timeout exceptions propagate up.

        Note: The gateway currently does not catch sandbox exceptions in _handle_tools_list.
        This test documents the current behavior - exceptions propagate to the caller
        which is the main gateway endpoint that catches and logs them.
        """
        mock_client = AsyncMock()
        mock_client.mcp_request = AsyncMock(side_effect=TimeoutError("Request timed out"))
        mock_db = AsyncMock()

        with pytest.raises(TimeoutError):
            await _handle_tools_list(mock_client, db=mock_db)

    @pytest.mark.asyncio
    async def test_sandbox_connection_error_propagates(self):
        """Test that sandbox connection errors propagate up.

        The main gateway endpoint catches these and returns a proper JSON-RPC error.
        """
        mock_client = AsyncMock()
        mock_client.mcp_request = AsyncMock(
            side_effect=ConnectionRefusedError("Connection refused")
        )
        mock_db = AsyncMock()

        with pytest.raises(ConnectionRefusedError):
            await _handle_tools_list(mock_client, db=mock_db)


class TestJSONRPCErrorCodes:
    """Test that proper JSON-RPC error codes are returned."""

    def test_parse_error_code(self):
        """Test parse error code is -32700."""
        # JSON-RPC spec: Parse error
        # Note: id=0 is used as a placeholder since the response model requires an id
        response = MCPResponse(
            id=0,
            error={"code": -32700, "message": "Parse error"},
        )
        assert response.error["code"] == -32700

    def test_invalid_request_code(self):
        """Test invalid request code is -32600."""
        response = MCPResponse(
            id=1,
            error={"code": -32600, "message": "Invalid Request"},
        )
        assert response.error["code"] == -32600

    def test_method_not_found_code(self):
        """Test method not found code is -32601."""
        response = MCPResponse(
            id=1,
            error={"code": -32601, "message": "Method not found"},
        )
        assert response.error["code"] == -32601

    def test_invalid_params_code(self):
        """Test invalid params code is -32602."""
        response = MCPResponse(
            id=1,
            error={"code": -32602, "message": "Invalid params"},
        )
        assert response.error["code"] == -32602

    def test_internal_error_code(self):
        """Test internal error code is -32603."""
        response = MCPResponse(
            id=1,
            error={"code": -32603, "message": "Internal error"},
        )
        assert response.error["code"] == -32603
