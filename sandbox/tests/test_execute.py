"""Tests for the Python code execution endpoint.

Uses the shared authenticated_client fixture from conftest.py.
"""

import pytest


@pytest.fixture
def client(authenticated_client):
    """Alias for authenticated_client to avoid changing all test methods."""
    return authenticated_client


class TestExecuteEndpoint:
    """Tests for the /execute endpoint."""

    def test_execute_simple_code(self, client):
        """Test executing simple Python code."""
        response = client.post(
            "/execute",
            json={
                "code": "result = 1 + 1",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == 2

    def test_execute_with_arguments(self, client):
        """Test code execution with arguments."""
        response = client.post(
            "/execute",
            json={
                "code": "result = arguments['a'] + arguments['b']",
                "arguments": {"a": 10, "b": 20},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == 30

    def test_execute_with_print(self, client):
        """Test that print statements are captured."""
        response = client.post(
            "/execute",
            json={
                "code": "print('Hello, World!')\nresult = 'done'",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "done"
        assert "Hello, World!" in data["stdout"]

    def test_execute_with_json_module(self, client):
        """Test that json module is available."""
        response = client.post(
            "/execute",
            json={
                "code": "result = json.dumps({'key': 'value'})",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == '{"key": "value"}'

    def test_execute_error_handling(self, client):
        """Test that errors are caught and reported."""
        response = client.post(
            "/execute",
            json={
                "code": "result = 1 / 0",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "ZeroDivisionError" in data["error"]

    def test_execute_syntax_error(self, client):
        """Test that syntax errors are caught."""
        response = client.post(
            "/execute",
            json={
                "code": "result = if True",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "SyntaxError" in data["error"]

    def test_execute_code_too_long(self, client):
        """Test that overly long code is rejected."""
        long_code = "x = 1\n" * 50001  # Exceeds 50,000 char limit
        response = client.post(
            "/execute",
            json={
                "code": long_code,
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "too long" in data["error"].lower()

    def test_execute_safe_builtins_available(self, client):
        """Test that safe builtins are available."""
        response = client.post(
            "/execute",
            json={
                "code": """
numbers = [1, 2, 3, 4, 5]
result = {
    'len': len(numbers),
    'sum': sum(numbers),
    'max': max(numbers),
    'min': min(numbers),
    'sorted': sorted([3, 1, 2]),
    'list': list(range(3)),
}
""",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"]["len"] == 5
        assert data["result"]["sum"] == 15
        assert data["result"]["max"] == 5
        assert data["result"]["min"] == 1
        assert data["result"]["sorted"] == [1, 2, 3]
        assert data["result"]["list"] == [0, 1, 2]

    def test_execute_no_file_access(self, client):
        """Test that file access is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "result = open('/etc/passwd').read()",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        # open is not in safe builtins

    def test_execute_no_import_statement(self, client):
        """Test that arbitrary imports are blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "import subprocess\nresult = subprocess.run(['ls'])",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_blocked_import_hints_request_module(self, client):
        """Blocked imports include mcpbox_request_module hint so the LLM knows what to do."""
        response = client.post(
            "/execute",
            json={
                "code": "import asyncio\nresult = 'ok'",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "asyncio" in data["error"]
        assert "mcpbox_request_module" in data["error"]

    def test_execute_with_list_comprehension(self, client):
        """Test list comprehensions work."""
        response = client.post(
            "/execute",
            json={
                "code": "result = [x * 2 for x in range(5)]",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == [0, 2, 4, 6, 8]

    def test_execute_with_dict_operations(self, client):
        """Test dictionary operations work."""
        response = client.post(
            "/execute",
            json={
                "code": """
data = {'a': 1, 'b': 2}
data['c'] = 3
result = dict(sorted(data.items()))
""",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == {"a": 1, "b": 2, "c": 3}

    def test_execute_secrets_injected(self, client):
        """Test that secrets are available via the secrets dict."""
        response = client.post(
            "/execute",
            json={
                "code": "result = secrets.get('TEST_API_KEY')",
                "arguments": {},
                "secrets": {"TEST_API_KEY": "secret123"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "secret123"

    def test_execute_secrets_read_only(self, client):
        """Test that secrets dict is read-only."""
        response = client.post(
            "/execute",
            json={
                "code": "secrets['NEW_KEY'] = 'value'\nresult = True",
                "arguments": {},
                "secrets": {"API_KEY": "test"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert (
            "does not support item assignment" in data["error"]
            or "TypeError" in data["error"]
        )

    def test_execute_no_result_returns_none(self, client):
        """Test that if no result is set, None is returned."""
        response = client.post(
            "/execute",
            json={
                "code": "x = 1 + 1",  # No result variable set
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] is None

    def test_execute_print_inside_async_main(self, client):
        """Test that print() inside async def main() is captured in stdout.

        Regression test: redirect_stdout only covered Phase 1 (exec),
        so print() inside main() was lost. Fixed by overriding print()
        in the namespace builtins.
        """
        code = "async def main():\n    print('hello from main')\n    return 'done'\n"
        response = client.post(
            "/execute",
            json={"code": code, "arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "done"
        assert "hello from main" in data["stdout"]

    def test_execute_print_both_phases(self, client):
        """Test that print() is captured in both module-level and main()."""
        code = (
            "print('phase1')\nasync def main():\n    print('phase2')\n    return 'ok'\n"
        )
        response = client.post(
            "/execute",
            json={"code": code, "arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "phase1" in data["stdout"]
        assert "phase2" in data["stdout"]

    def test_execute_print_inside_sync_main(self, client):
        """Test that print() inside sync def main() is captured."""
        code = "def main():\n    print('sync hello')\n    return 'sync done'\n"
        response = client.post(
            "/execute",
            json={"code": code, "arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "sync done"
        assert "sync hello" in data["stdout"]

    def test_execute_result_size_limit(self, client, monkeypatch):
        """Test that oversized return values are truncated."""
        # Set a small limit for testing (10KB)
        monkeypatch.setattr("app.routes.MAX_RESULT_SIZE", 10 * 1024)
        code = (
            "async def main():\n"
            "    return 'x' * 50000\n"  # 50KB > 10KB limit
        )
        response = client.post(
            "/execute",
            json={"code": code, "arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Result should be truncated
        assert "RESULT TRUNCATED" in data["result"]
        assert len(data["result"]) < 50000

    def test_execute_result_under_limit_not_truncated(self, client):
        """Test that results under the size limit are returned in full."""
        code = "async def main():\n    return 'hello world'\n"
        response = client.post(
            "/execute",
            json={"code": code, "arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "hello world"
        assert "TRUNCATED" not in data["result"]


class TestSecretsSecurity:
    """Tests for secrets dict security in execute endpoint."""

    def test_secrets_dict_access(self, client):
        """Test that secrets can be accessed via dict-style access."""
        response = client.post(
            "/execute",
            json={
                "code": "result = secrets['API_KEY']",
                "arguments": {},
                "secrets": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "test-key"

    def test_secrets_get_method(self, client):
        """Test that secrets.get() works with default."""
        response = client.post(
            "/execute",
            json={
                "code": "result = secrets.get('API_KEY', 'default')",
                "arguments": {},
                "secrets": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "test-key"

    def test_secrets_get_missing_key_default(self, client):
        """Test that secrets.get() returns default for missing keys."""
        response = client.post(
            "/execute",
            json={
                "code": "result = secrets.get('NONEXISTENT', 'default_value')",
                "arguments": {},
                "secrets": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "default_value"

    def test_secrets_contains_check(self, client):
        """Test that 'in' operator works for secrets."""
        response = client.post(
            "/execute",
            json={
                "code": "result = 'API_KEY' in secrets",
                "arguments": {},
                "secrets": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] is True

    def test_secrets_read_only(self, client):
        """Test that secrets dict cannot be modified."""
        response = client.post(
            "/execute",
            json={
                "code": "secrets['NEW_KEY'] = 'hacked'\nresult = True",
                "arguments": {},
                "secrets": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_os_not_in_namespace(self, client):
        """Test that os module is not available in the namespace."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.path.exists('/etc/passwd')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestAllowedModulesNotOverridable:
    """Tests for SEC-015: allowed_modules on /execute is backend-controlled."""

    def test_backend_supplied_modules_are_used(self, client):
        """SEC-015: backend-supplied allowed_modules list is respected."""
        # The backend passes the admin-approved list; modules in it should work.
        response = client.post(
            "/execute",
            json={
                "code": "import math\nresult = math.pi",
                "arguments": {},
                "allowed_modules": ["math"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_module_not_in_backend_list_is_blocked(self, client):
        """SEC-015: modules absent from the backend-supplied list are blocked."""
        # Even if os is technically importable by the sandbox process,
        # it must not be available when the backend does not include it.
        response = client.post(
            "/execute",
            json={
                "code": "import os\nresult = os.getcwd()",
                "arguments": {},
                "allowed_modules": ["math"],  # os intentionally absent
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "os" in data["error"]

    def test_default_modules_used_when_not_supplied(self, client):
        """SEC-015: falls back to DEFAULT_ALLOWED_MODULES when not supplied."""
        # json is in DEFAULT_ALLOWED_MODULES, so it should work without a list.
        response = client.post(
            "/execute",
            json={
                "code": "import json\nresult = json.dumps({'ok': True})",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestErrorSanitization:
    """Tests that error responses don't leak internal details."""

    def test_known_exception_returns_details(self, client):
        """Test that safe exceptions (ValueError, etc.) include details."""
        response = client.post(
            "/execute",
            json={
                "code": "raise ValueError('bad input')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "ValueError" in data["error"]
        assert "bad input" in data["error"]

    def test_zero_division_returns_details(self, client):
        """Test that ZeroDivisionError includes details."""
        response = client.post(
            "/execute",
            json={
                "code": "result = 1 / 0",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "ZeroDivisionError" in data["error"]

    def test_unexpected_exception_returns_generic_message(self, client):
        """Test that unexpected exceptions return a generic error message."""
        response = client.post(
            "/execute",
            json={
                "code": "raise RuntimeError('internal db connection string: postgres://user:pass@host/db')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "internal error" in data["error"].lower()
        # Must NOT leak the connection string
        assert "postgres://" not in data["error"]
        assert "RuntimeError" not in data["error"]

    def test_network_block_returns_actionable_error(self, client):
        """Network blocks surface the hostname and mcpbox_request_network_access hint.

        When allowed_hosts is set (even to an empty list), any HTTP request to an
        unapproved host raises SSRFError.  The LLM must see the specific hostname
        and the hint to call mcpbox_request_network_access — not a generic
        'internal error' message — so it can request access without guessing.
        """
        code = """
async def main():
    response = await http.get("https://example.com")
    return response.status_code
"""
        response = client.post(
            "/execute",
            json={
                "code": code,
                "arguments": {},
                "allowed_hosts": [],  # Empty allowlist blocks all outbound requests
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Network access blocked" in data["error"]
        assert "example.com" in data["error"]
        assert "mcpbox_request_network_access" in data["error"]


class TestUpdateServerSecrets:
    """Tests for PUT /servers/{server_id}/secrets endpoint."""

    def test_update_secrets_on_registered_server(self, client):
        """Updating secrets on a registered server succeeds."""
        # First register a server
        client.post(
            "/servers/register",
            json={
                "server_id": "srv-1",
                "server_name": "TestServer",
                "tools": [
                    {
                        "name": "my_tool",
                        "description": "test",
                        "parameters": {},
                        "python_code": "async def main(): return secrets.get('API_KEY')",
                    }
                ],
                "secrets": {},
            },
        )

        # Update secrets
        response = client.put(
            "/servers/srv-1/secrets",
            json={"secrets": {"API_KEY": "new-key-value"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server_id"] == "srv-1"

    def test_update_secrets_not_found(self, client):
        """Updating secrets on a non-existent server returns 404."""
        response = client.put(
            "/servers/nonexistent/secrets",
            json={"secrets": {"KEY": "val"}},
        )

        assert response.status_code == 404

    def test_updated_secrets_available_to_tool(self, client):
        """After updating secrets, tool execution sees the new values."""
        # Register server with no secrets
        client.post(
            "/servers/register",
            json={
                "server_id": "srv-2",
                "server_name": "SecretServer",
                "tools": [
                    {
                        "name": "check_secret",
                        "description": "Returns secret value",
                        "parameters": {},
                        "python_code": "async def main(): return secrets.get('MY_SECRET', 'NOT_SET')",
                    }
                ],
                "secrets": {},
            },
        )

        # Tool should not have the secret yet
        response = client.post(
            "/tools/SecretServer__check_secret/call",
            json={"arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "NOT_SET"

        # Now update secrets
        client.put(
            "/servers/srv-2/secrets",
            json={"secrets": {"MY_SECRET": "secret-value-123"}},
        )

        # Tool should now see the secret (but it's redacted in output)
        response = client.post(
            "/tools/SecretServer__check_secret/call",
            json={"arguments": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Secret values are redacted in tool output to prevent accidental leakage.
        # The tool can read secrets internally, but returning them exposes them
        # in MCP responses and execution logs.
        assert data["result"] == "[REDACTED]"


class TestMCPEndpointErrorDetail:
    """Tests for error detail surfacing in the /mcp endpoint."""

    def test_mcp_tools_call_error_includes_detail(self, client):
        """When a tool fails, the MCP error response includes error_detail and stdout."""
        # Register a tool that prints then crashes
        reg_resp = client.post(
            "/servers/register",
            json={
                "server_id": "err-srv",
                "server_name": "ErrSrv",
                "tools": [
                    {
                        "name": "crash_tool",
                        "description": "Crashes on purpose",
                        "parameters": {},
                        "python_code": (
                            "async def main():\n"
                            "    print('debug output before crash')\n"
                            "    raise ValueError('something broke')\n"
                        ),
                    }
                ],
            },
        )
        assert reg_resp.json()["success"] is True

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "ErrSrv__crash_tool", "arguments": {}},
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Per MCP spec, tool execution errors use result with isError:true
        assert "result" in data
        assert "error" not in data  # NOT a JSON-RPC error
        assert data["result"]["isError"] is True

        error_text = data["result"]["content"][0]["text"]
        assert "ValueError" in error_text
        assert "something broke" in error_text
        assert "debug output before crash" in error_text
        assert "Error type: ValueError" in error_text

    def test_mcp_tools_call_success_has_isError_false(self, client):
        """Successful tool calls return isError: false."""
        client.post(
            "/servers/register",
            json={
                "server_id": "ok-srv",
                "server_name": "OkSrv",
                "tools": [
                    {
                        "name": "ok_tool",
                        "description": "Works fine",
                        "parameters": {},
                        "python_code": 'async def main():\n    return "all good"\n',
                    }
                ],
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "OkSrv__ok_tool", "arguments": {}},
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "result" in data
        assert "error" not in data
        assert data["result"]["isError"] is False
        assert data["result"]["content"][0]["text"] == "all good"


class TestHTTPErrorInfoExtraction:
    """Tests for structured HTTP error info in error_detail."""

    def test_extract_http_info_from_httpx_status_error(self):
        """HTTPStatusError should produce http_info with status_code, url, and body preview."""
        from app.executor import _extract_http_info

        import httpx

        request = httpx.Request("GET", "https://api.example.com/data")
        response = httpx.Response(
            403,
            text='{"error": "rate_limited"}',
            headers={"content-type": "application/json", "retry-after": "60"},
            request=request,
        )
        exc = httpx.HTTPStatusError("Client error", request=request, response=response)

        info = _extract_http_info(exc)
        assert info is not None
        assert info["status_code"] == 403
        assert info["url"] == "https://api.example.com/data"
        assert info["response_headers"]["content-type"] == "application/json"
        assert info["response_headers"]["retry-after"] == "60"
        assert "rate_limited" in info["body_preview"]

    def test_extract_http_info_connect_error(self):
        """ConnectError should produce http_info with error_type."""
        from app.executor import _extract_http_info

        import httpx

        exc = httpx.ConnectError("Connection refused")
        info = _extract_http_info(exc)
        assert info is not None
        assert info["error_type"] == "ConnectError"

    def test_extract_http_info_non_http_error(self):
        """Non-HTTP exceptions should return None."""
        from app.executor import _extract_http_info

        info = _extract_http_info(ValueError("not http"))
        assert info is None


class TestExecutionResultSerialization:
    """Tests for ExecutionResult.to_dict() handling edge cases."""

    def test_non_serializable_result_converted_to_string(self):
        """Non-JSON-serializable results should be converted to strings."""
        from app.executor import ExecutionResult

        class CustomObj:
            def __str__(self):
                return "custom_repr"

        result = ExecutionResult(success=True, result=CustomObj(), stdout="output")
        d = result.to_dict()
        assert d["success"] is True
        assert d["result"] == "custom_repr"

    def test_non_serializable_with_broken_str(self):
        """Objects that can't be stringified should get a fallback message."""
        from app.executor import ExecutionResult

        class BrokenObj:
            def __str__(self):
                raise RuntimeError("broken str")

        result = ExecutionResult(success=True, result=BrokenObj(), stdout="output")
        d = result.to_dict()
        assert d["success"] is True
        assert d["result"] == "<unserializable result>"

    def test_stdout_never_none(self):
        """stdout should always be a string, never None."""
        from app.executor import ExecutionResult

        result = ExecutionResult(success=True, result="ok", stdout="")
        d = result.to_dict()
        assert d["stdout"] == ""
        assert d["stdout"] is not None

    def test_error_fields_on_failure(self):
        """Failed execution should always have error populated."""
        from app.executor import ExecutionResult

        result = ExecutionResult(
            success=False, error="something failed", stdout="debug line"
        )
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "something failed"
        assert d["stdout"] == "debug line"


class TestMCPEndpointMetadata:
    """Tests for _meta.execution in MCP tools/call responses."""

    def test_mcp_success_includes_meta(self, client):
        """Successful MCP tool calls include _meta with execution metadata."""
        client.post(
            "/servers/register",
            json={
                "server_id": "meta-srv",
                "server_name": "MetaSrv",
                "tools": [
                    {
                        "name": "meta_tool",
                        "description": "Returns a value",
                        "parameters": {},
                        "python_code": (
                            "async def main():\n"
                            "    print('captured output')\n"
                            "    return 'hello'\n"
                        ),
                    }
                ],
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "MetaSrv__meta_tool", "arguments": {}},
            },
        )
        data = response.json()

        # Should have _meta with execution metadata
        assert "_meta" in data.get("result", {})
        meta = data["result"]["_meta"]
        assert "execution" in meta
        assert "stdout" in meta["execution"]
        assert "duration_ms" in meta["execution"]

    def test_mcp_failure_includes_meta(self, client):
        """Failed MCP tool calls include _meta with execution metadata."""
        client.post(
            "/servers/register",
            json={
                "server_id": "meta-fail-srv",
                "server_name": "MetaFailSrv",
                "tools": [
                    {
                        "name": "fail_tool",
                        "description": "Crashes",
                        "parameters": {},
                        "python_code": (
                            "async def main():\n"
                            "    print('debug before crash')\n"
                            "    raise ValueError('boom')\n"
                        ),
                    }
                ],
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "MetaFailSrv__fail_tool", "arguments": {}},
            },
        )
        data = response.json()

        # Should have _meta with execution metadata even on failure
        assert "_meta" in data.get("result", {})
        meta = data["result"]["_meta"]
        assert "execution" in meta
        assert "stdout" in meta["execution"]
        assert "duration_ms" in meta["execution"]
