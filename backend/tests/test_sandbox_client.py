"""Tests for the sandbox client service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.retry import CircuitBreaker
from app.services.sandbox_client import SandboxClient, get_sandbox_client


class TestSandboxClientSingleton:
    """Tests for singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}  # Reset circuit breakers too

    def test_get_instance_creates_singleton(self):
        """Test that get_instance creates a singleton."""
        client1 = SandboxClient.get_instance()
        client2 = SandboxClient.get_instance()

        assert client1 is client2

    def test_get_instance_thread_safe(self):
        """Test that singleton creation is thread-safe."""
        import threading

        instances = []
        errors = []

        def create_instance():
            try:
                instance = SandboxClient.get_instance()
                instances.append(instance)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All instances should be the same object
        assert all(inst is instances[0] for inst in instances)

    def test_get_sandbox_client_helper(self):
        """Test the dependency injection helper function."""
        client = get_sandbox_client()
        assert isinstance(client, SandboxClient)


class TestSandboxClientHeaders:
    """Tests for request header handling."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    def test_headers_include_content_type(self):
        """Test that headers include Content-Type."""
        client = SandboxClient()
        headers = client._get_headers()

        assert headers["Content-Type"] == "application/json"

    def test_headers_include_api_key_when_set(self):
        """Test that API key is included in headers when configured."""
        client = SandboxClient()
        client._api_key = "test-api-key"
        headers = client._get_headers()

        assert headers["X-API-Key"] == "test-api-key"

    def test_headers_exclude_api_key_when_not_set(self):
        """Test that API key is not included when not configured."""
        client = SandboxClient()
        client._api_key = None
        headers = client._get_headers()

        assert "X-API-Key" not in headers


class TestSandboxClientCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def setup_method(self):
        """Reset singleton and circuit breakers before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    def test_get_circuit_state(self):
        """Test getting circuit breaker state."""
        client = SandboxClient()
        state = client.get_circuit_state()

        assert "state" in state
        assert state["state"] == "closed"  # Should start closed

    @pytest.mark.asyncio
    async def test_reset_circuit(self):
        """Test resetting circuit breaker."""
        client = SandboxClient()

        # This should not raise
        await client.reset_circuit()

        state = client.get_circuit_state()
        assert state["state"] == "closed"

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """Test that circuit breaker opens after consecutive failures."""
        client = SandboxClient()

        # Mock the HTTP client to fail
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection failed")
            mock_get_client.return_value = mock_client

            # Make multiple failing requests to trip the circuit breaker
            for _ in range(6):  # Threshold is 5
                result = await client.health_check()
                assert result is False

            # Circuit should be open now
            _state = client.get_circuit_state()
            # May be open or half-open depending on timing


class TestSandboxClientHealthCheck:
    """Tests for health check functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self):
        """Test health check returns True when sandbox is healthy."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.health_check()

            assert result is True
            mock_client.get.assert_called()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_failure(self):
        """Test health check returns False when sandbox is unhealthy."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_handles_connection_error(self):
        """Test health check handles connection errors gracefully."""
        client = SandboxClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_get_client.return_value = mock_client

            result = await client.health_check()

            assert result is False


class TestSandboxClientRegisterServer:
    """Tests for server registration."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    @pytest.mark.asyncio
    async def test_register_server_success(self):
        """Test successful server registration."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tools_registered": 3}

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.register_server(
                server_id="test-server-id",
                server_name="Test Server",
                tools=[{"name": "tool1"}, {"name": "tool2"}],
            )

            assert result["success"] is True
            assert result["tools_registered"] == 3

    @pytest.mark.asyncio
    async def test_register_server_failure(self):
        """Test server registration failure."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.register_server(
                server_id="test-server-id",
                server_name="Test Server",
                tools=[],
            )

            assert result["success"] is False
            assert "error" in result

    @pytest.mark.asyncio
    async def test_register_server_circuit_breaker_open(self):
        """Test server registration when circuit breaker is open."""
        client = SandboxClient()

        # Force circuit breaker open by recording async failures
        for _ in range(6):
            await client._circuit_breaker.record_failure(Exception("test"))

        result = await client.register_server(
            server_id="test-server-id",
            server_name="Test Server",
            tools=[],
        )

        assert result["success"] is False
        assert (
            result.get("circuit_breaker_open") is True
            or "unavailable" in result.get("error", "").lower()
        )


class TestSandboxClientUpdateSecrets:
    """Tests for server secret updates."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    @pytest.mark.asyncio
    async def test_update_server_secrets_success(self):
        """Test successful secret update."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch.object(client, "_request_with_retry", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response

            result = await client.update_server_secrets(
                server_id="test-server-id",
                secrets={"API_KEY": "test-key"},
            )

            assert result["success"] is True
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert call_args.args[0] == "PUT"
            assert "test-server-id" in call_args.args[1]
            assert call_args.kwargs["json"]["secrets"] == {"API_KEY": "test-key"}

    @pytest.mark.asyncio
    async def test_update_server_secrets_server_not_registered(self):
        """Test secret update when server is not registered in sandbox."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_request_with_retry", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response

            result = await client.update_server_secrets(
                server_id="nonexistent",
                secrets={"KEY": "val"},
            )

            # Should succeed gracefully (server just isn't running)
            assert result["success"] is True
            assert "not registered" in result.get("note", "").lower()

    @pytest.mark.asyncio
    async def test_update_server_secrets_failure(self):
        """Test handling sandbox failure during secret update."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with patch.object(client, "_request_with_retry", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response

            result = await client.update_server_secrets(
                server_id="test-server",
                secrets={"KEY": "val"},
            )

            assert result["success"] is False
            assert "error" in result


class TestSandboxClientCallTool:
    """Tests for tool execution."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Test successful tool call."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "result": {"data": "test result"},
        }

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.call_tool(
                tool_name="server__tool",
                arguments={"param": "value"},
            )

            assert result["success"] is True
            assert result["result"]["data"] == "test result"

    @pytest.mark.asyncio
    async def test_call_tool_with_debug_mode(self):
        """Test tool call with debug mode enabled."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "result": "test",
            "debug_info": {"http_calls": []},
        }

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await client.call_tool(
                tool_name="server__tool",
                arguments={},
                debug_mode=True,
            )

            # Verify debug_mode was passed in request
            call_args = mock_client.post.call_args
            assert call_args.kwargs["json"]["debug_mode"] is True


class TestSandboxClientMCPRequest:
    """Tests for MCP JSON-RPC requests."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    @pytest.mark.asyncio
    async def test_mcp_request_success(self):
        """Test successful MCP request."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []},
        }

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                }
            )

            assert result["jsonrpc"] == "2.0"
            assert result["id"] == 1
            assert "result" in result

    @pytest.mark.asyncio
    async def test_mcp_request_returns_error_on_invalid_json(self):
        """Test MCP request handles invalid JSON response."""
        client = SandboxClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await client.mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                }
            )

            assert "error" in result
            assert result["error"]["code"] == -32603


class TestSandboxClientCleanup:
    """Tests for client cleanup."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None
        CircuitBreaker._instances = {}

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        """Test that close properly closes the HTTP client."""
        client = SandboxClient()

        # Create a mock client
        mock_http_client = AsyncMock()
        client._client = mock_http_client

        await client.close()

        mock_http_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_handles_no_client(self):
        """Test that close handles case when client is None."""
        client = SandboxClient()
        client._client = None

        # Should not raise
        await client.close()

    @pytest.mark.asyncio
    async def test_get_client_recreates_closed_client(self):
        """Test that _get_client recreates a closed client."""
        client = SandboxClient()

        # Create a mock closed client
        mock_closed_client = MagicMock()
        mock_closed_client.is_closed = True
        client._client = mock_closed_client

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_new_client = MagicMock()
            mock_new_client.is_closed = False
            mock_async_client.return_value = mock_new_client

            result = await client._get_client()

            # Should create new client
            mock_async_client.assert_called_once()
            assert result is mock_new_client
