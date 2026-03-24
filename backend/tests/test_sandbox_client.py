"""Tests for the sandbox client service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.sandbox_client import (
    SandboxClient,
    _classify_sandbox_error,
    get_sandbox_client,
)


class TestSandboxClientSingleton:
    """Tests for singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None

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


class TestSandboxClientHealthCheck:
    """Tests for health check functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None

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


class TestSandboxClientUpdateSecrets:
    """Tests for server secret updates."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None

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


class TestSandboxClientMCPRequest:
    """Tests for MCP JSON-RPC requests."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None

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


class TestClassifySandboxError:
    """Tests for _classify_sandbox_error helper."""

    def test_read_timeout_produces_timeout_category(self):
        """ReadTimeout should produce a timeout category with non-empty message."""
        exc = httpx.ReadTimeout("read timed out")
        category, message = _classify_sandbox_error(exc)

        assert category == "timeout"
        assert "timed out" in message.lower()
        assert "ReadTimeout" in message

    def test_empty_read_timeout_still_produces_message(self):
        """ReadTimeout with empty str() must still produce a useful message.

        This is the exact bug from the report: str(httpx.ReadTimeout('')) == ''
        which led to 'Sandbox communication error: ' with no explanation.
        """
        exc = httpx.ReadTimeout("")
        category, message = _classify_sandbox_error(exc)

        assert category == "timeout"
        assert len(message) > 10  # Must be non-trivial
        assert message != "Sandbox communication error: "

    def test_connect_timeout(self):
        """ConnectTimeout is also a TimeoutException."""
        exc = httpx.ConnectTimeout("connect timed out")
        category, message = _classify_sandbox_error(exc)

        assert category == "timeout"
        assert "ConnectTimeout" in message

    def test_pool_timeout(self):
        """PoolTimeout is also a TimeoutException."""
        exc = httpx.PoolTimeout("pool exhausted")
        category, message = _classify_sandbox_error(exc)

        assert category == "timeout"
        assert "PoolTimeout" in message

    def test_connect_error(self):
        """ConnectError should produce a connection_error category."""
        exc = httpx.ConnectError("Connection refused")
        category, message = _classify_sandbox_error(exc)

        assert category == "connection_error"
        assert "connect" in message.lower()
        assert "Connection refused" in message

    def test_connect_error_empty_message(self):
        """ConnectError with empty message should still produce useful output."""
        exc = httpx.ConnectError("")
        category, message = _classify_sandbox_error(exc)

        assert category == "connection_error"
        assert len(message) > 10

    def test_network_error(self):
        """Generic NetworkError should produce network_error category."""
        exc = httpx.NetworkError("reset by peer")
        category, message = _classify_sandbox_error(exc)

        assert category == "network_error"
        assert "reset by peer" in message

    def test_os_error_errno_12_memory(self):
        """OSError with errno 12 is 'Cannot allocate memory'."""
        exc = OSError(12, "Cannot allocate memory")
        category, message = _classify_sandbox_error(exc)

        assert category == "resource_exhaustion"
        assert "memory" in message.lower()

    def test_os_error_other(self):
        """OSError with non-12 errno should be os_error."""
        exc = OSError(28, "No space left on device")
        category, message = _classify_sandbox_error(exc)

        assert category == "os_error"
        assert "No space left on device" in message

    def test_runtime_error_thread_exhaustion(self):
        """RuntimeError about threads should be resource_exhaustion."""
        exc = RuntimeError("can't start new thread")
        category, message = _classify_sandbox_error(exc)

        assert category == "resource_exhaustion"
        assert "thread" in message.lower()

    def test_runtime_error_other(self):
        """Other RuntimeError should be runtime_error."""
        exc = RuntimeError("something else broke")
        category, message = _classify_sandbox_error(exc)

        assert category == "runtime_error"
        assert "something else broke" in message

    def test_unknown_exception_includes_type(self):
        """Unknown exception types should include the type name."""
        exc = ValueError("bad value")
        category, message = _classify_sandbox_error(exc)

        assert category == "sandbox_error"
        assert "ValueError" in message
        assert "bad value" in message

    def test_unknown_exception_empty_str_uses_repr(self):
        """Unknown exception with empty str() should use repr() as fallback."""

        class WeirdError(Exception):
            def __str__(self):
                return ""

        exc = WeirdError()
        category, message = _classify_sandbox_error(exc)

        assert category == "sandbox_error"
        assert "WeirdError" in message
        assert len(message) > 10  # Not empty


class TestSandboxClientErrorClassification:
    """Tests that sandbox client methods use error classification."""

    def setup_method(self):
        """Reset singleton before each test."""
        SandboxClient._instance = None

    @pytest.mark.asyncio
    async def test_mcp_request_timeout_produces_classified_error(self):
        """MCP request timeout should produce classified error with category."""
        client = SandboxClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ReadTimeout("")
            mock_get_client.return_value = mock_client

            result = await client.mcp_request(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
            )

            assert "error" in result
            error = result["error"]
            assert error["code"] == -32603
            assert "timed out" in error["message"].lower()
            assert error["message"] != "Sandbox communication error: "
            assert error["data"]["error_category"] == "timeout"

    @pytest.mark.asyncio
    async def test_execute_code_timeout_produces_classified_error(self):
        """execute_code timeout should produce classified error with category."""
        client = SandboxClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ReadTimeout("")
            mock_get_client.return_value = mock_client

            result = await client.execute_code(code="async def main(): pass")

            assert result["success"] is False
            assert "timed out" in result["error"].lower()
            assert result["error"] != "Sandbox communication error: "
            assert result["error_category"] == "timeout"

    @pytest.mark.asyncio
    async def test_execute_code_connect_error_produces_classified_error(self):
        """execute_code connect error should produce connection_error category."""
        client = SandboxClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_get_client.return_value = mock_client

            result = await client.execute_code(code="async def main(): pass")

            assert result["success"] is False
            assert result["error_category"] == "connection_error"
            assert "connect" in result["error"].lower()
