"""Tests for the Python code execution endpoint.

Uses the shared authenticated_client fixture from conftest.py.

All test code uses ``async def main()`` because PythonExecutor.execute()
requires it.  The /execute endpoint delegates to the same executor as
/tools/{name}/call, ensuring test and production behavior are identical.
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
                "code": "async def main():\n    return 1 + 1\n",
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
                "code": "async def main(a, b):\n    return a + b\n",
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
                "code": "async def main():\n    print('Hello, World!')\n    return 'done'\n",
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
                "code": "async def main():\n    return json.dumps({'key': 'value'})\n",
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
                "code": "async def main():\n    return 1 / 0\n",
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
                "code": "async def main():\n    return if True\n",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "yntax" in data["error"]  # "Syntax error" or "SyntaxError"

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
                "code": (
                    "async def main():\n"
                    "    numbers = [1, 2, 3, 4, 5]\n"
                    "    return {\n"
                    "        'len': len(numbers),\n"
                    "        'sum': sum(numbers),\n"
                    "        'max': max(numbers),\n"
                    "        'min': min(numbers),\n"
                    "        'sorted': sorted([3, 1, 2]),\n"
                    "        'list': list(range(3)),\n"
                    "    }\n"
                ),
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
                "code": "async def main():\n    return open('/etc/passwd').read()\n",
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
                "code": "import subprocess\nasync def main():\n    return subprocess.run(['ls'])\n",
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
                "code": "import asyncio\nasync def main():\n    return 'ok'\n",
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
                "code": "async def main():\n    return [x * 2 for x in range(5)]\n",
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
                "code": (
                    "async def main():\n"
                    "    data = {'a': 1, 'b': 2}\n"
                    "    data['c'] = 3\n"
                    "    return dict(sorted(data.items()))\n"
                ),
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
                "code": "async def main():\n    return secrets.get('TEST_API_KEY')\n",
                "arguments": {},
                "secrets": {"TEST_API_KEY": "secret123"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Secret values are redacted in output by the executor
        assert data["result"] == "[REDACTED]"

    def test_execute_secrets_read_only(self, client):
        """Test that secrets dict is read-only."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    secrets['NEW_KEY'] = 'value'\n    return True\n",
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

    def test_execute_no_main_returns_error(self, client):
        """Test that code without main() returns a clear error."""
        response = client.post(
            "/execute",
            json={
                "code": "x = 1 + 1",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "main" in data["error"].lower()

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

    def test_execute_result_size_limit(self, client, monkeypatch):
        """Test that oversized return values are truncated.

        The executor enforces MAX_OUTPUT_SIZE on results via to_dict().
        """
        monkeypatch.setattr("app.executor.MAX_OUTPUT_SIZE", 10 * 1024)
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
                "code": "async def main():\n    return secrets['API_KEY']\n",
                "arguments": {},
                "secrets": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Secret values are redacted by the executor
        assert data["result"] == "[REDACTED]"

    def test_secrets_get_method(self, client):
        """Test that secrets.get() works with default."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    return secrets.get('API_KEY', 'default')\n",
                "arguments": {},
                "secrets": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Secret values are redacted by the executor
        assert data["result"] == "[REDACTED]"

    def test_secrets_get_missing_key_default(self, client):
        """Test that secrets.get() returns default for missing keys."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    return secrets.get('NONEXISTENT', 'default_value')\n",
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
                "code": "async def main():\n    return 'API_KEY' in secrets\n",
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
                "code": "async def main():\n    secrets['NEW_KEY'] = 'hacked'\n    return True\n",
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
                "code": "async def main():\n    return os.path.exists('/etc/passwd')\n",
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
                "code": "import math\nasync def main():\n    return math.pi\n",
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
                "code": "import os\nasync def main():\n    return os.getcwd()\n",
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
                "code": "import json\nasync def main():\n    return json.dumps({'ok': True})\n",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestSocketModuleImport:
    """Tests for socket module import via SafeSocket."""

    def test_socket_blocked_when_not_in_allowed_modules(self, client):
        """socket import fails when not in allowed_modules list."""
        response = client.post(
            "/execute",
            json={
                "code": "import socket\nasync def main():\n    return 'imported'\n",
                "arguments": {},
                "allowed_modules": ["json"],  # socket intentionally absent
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "socket" in data["error"]

    def test_socket_returns_module_when_approved(self, client):
        """socket import returns socket module (with PatchedSocket) when in allowed_modules."""
        response = client.post(
            "/execute",
            json={
                "code": (
                    "import socket\n"
                    "async def main():\n"
                    "    return {\n"
                    "        'af_inet': socket.AF_INET,\n"
                    "        'sock_stream': socket.SOCK_STREAM,\n"
                    "        'has_socket_class': callable(socket.socket),\n"
                    "    }\n"
                ),
                "arguments": {},
                "allowed_modules": ["socket"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        result = data["result"]
        assert result["af_inet"] == 2  # AF_INET value
        assert result["sock_stream"] == 1  # SOCK_STREAM value
        assert result["has_socket_class"] is True

    def test_socket_create_connection_requires_proxy(self, client):
        """socket.create_connection fails without proxy (expected in tests)."""
        response = client.post(
            "/execute",
            json={
                "code": (
                    "import socket\n"
                    "async def main():\n"
                    "    try:\n"
                    "        sock = socket.create_connection(('example.com', 80), timeout=0.1)\n"
                    "        return 'connected'\n"
                    "    except (ConnectionError, OSError) as e:\n"
                    "        return str(e)\n"
                ),
                "arguments": {},
                "allowed_modules": ["socket"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should fail because no SOCKS5 proxy in test env
        assert "proxy" in data["result"].lower() or "connect" in data["result"].lower()

    def test_socket_blocked_by_default(self, client):
        """socket is NOT in DEFAULT_ALLOWED_MODULES."""
        response = client.post(
            "/execute",
            json={
                "code": "import socket\nasync def main():\n    return 'imported'\n",
                "arguments": {},
                # No allowed_modules → uses DEFAULT_ALLOWED_MODULES
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestErrorSanitization:
    """Tests that error responses surface useful info for debugging."""

    def test_known_exception_returns_details(self, client):
        """Test that safe exceptions (ValueError, etc.) include details."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    raise ValueError('bad input')\n",
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
                "code": "async def main():\n    return 1 / 0\n",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "ZeroDivisionError" in data["error"]

    def test_runtime_error_returns_details(self, client):
        """Test that RuntimeError includes error type and message."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    raise RuntimeError('something broke')\n",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "RuntimeError" in data["error"]

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
        assert "example.com" in data["error"]
        assert "mcpbox_request_network_access" in data["error"]


class TestErrorCategory:
    """Tests for error_category field in responses."""

    def test_successful_execution_has_no_error_category(self, client):
        """Successful execution has null error_category."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    return 42\n",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["error_category"] is None

    def test_code_error_category(self, client):
        """Code errors get 'code_error' category."""
        response = client.post(
            "/execute",
            json={
                "code": "async def main():\n    raise RuntimeError('test')\n",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error_category"] == "code_error"

    def test_validation_error_category(self, client):
        """Code safety validation failures get 'validation_error' category."""
        response = client.post(
            "/execute",
            json={
                "code": "x = 1\n" * 50001,  # too long
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error_category"] == "validation_error"


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

        # Call tool — should see NOT_SET
        response = client.post(
            "/tools/SecretServer__check_secret/call",
            json={"arguments": {}},
        )
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "NOT_SET"

        # Update secrets
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

        # Error text should contain the exception details
        text = data["result"]["content"][0]["text"]
        assert "ValueError" in text
        assert "something broke" in text

        # Structured error_detail should be present (nested under execution key)
        meta = data["result"].get("_meta", {})
        execution = meta.get("execution", meta)  # may be nested or flat
        assert "error_detail" in execution
        detail = execution["error_detail"]
        assert detail["error_type"] == "ValueError"
        assert "something broke" in detail["message"]

        # Stdout from the execution
        assert "debug output before crash" in execution.get("stdout", "")

    def test_mcp_tools_call_success_no_error_detail(self, client):
        """Successful tool calls don't include error_detail."""
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

        request = httpx.Request("POST", "https://unreachable.example.com/api")
        exc = httpx.ConnectError("Connection refused", request=request)

        info = _extract_http_info(exc)
        assert info is not None
        assert info["error_type"] == "ConnectError"
        assert "Connection refused" in info["detail"]

    def test_extract_http_info_non_httpx_returns_none(self):
        """Non-httpx exceptions should return None."""
        from app.executor import _extract_http_info

        info = _extract_http_info(ValueError("not http"))
        assert info is None
