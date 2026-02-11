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

    def test_execute_credentials_injected(self, client):
        """Test that credentials are available as environment variables."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.getenv('TEST_API_KEY')",
                "arguments": {},
                "credentials": {"TEST_API_KEY": "secret123"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "secret123"

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


class TestIsolatedOsSecurity:
    """Tests for IsolatedOs wrapper security."""

    def test_os_environ_access(self, client):
        """Test that os.environ can be accessed for credentials."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.environ.get('API_KEY')",
                "arguments": {},
                "credentials": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "test-key"

    def test_os_environ_dict_access(self, client):
        """Test that os.environ supports dict-like access."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.environ['API_KEY']",
                "arguments": {},
                "credentials": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "test-key"

    def test_os_environ_contains_check(self, client):
        """Test that 'in' operator works for os.environ."""
        response = client.post(
            "/execute",
            json={
                "code": "result = 'API_KEY' in os.environ",
                "arguments": {},
                "credentials": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] is True

    def test_os_getenv_function(self, client):
        """Test that os.getenv() function works."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.getenv('API_KEY', 'default')",
                "arguments": {},
                "credentials": {"API_KEY": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "test-key"

    def test_os_getenv_with_default(self, client):
        """Test that os.getenv() returns default for missing keys."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.getenv('NONEXISTENT', 'default_value')",
                "arguments": {},
                "credentials": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "default_value"

    def test_os_path_blocked(self, client):
        """Test that os.path is not accessible."""
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
        assert "not available" in data["error"] or "AttributeError" in data["error"]

    def test_os_system_blocked(self, client):
        """Test that os.system is not accessible."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.system('ls')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not available" in data["error"] or "AttributeError" in data["error"]

    def test_os_getcwd_blocked(self, client):
        """Test that os.getcwd is not accessible."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.getcwd()",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not available" in data["error"] or "AttributeError" in data["error"]

    def test_os_listdir_blocked(self, client):
        """Test that os.listdir is not accessible."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.listdir('/')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not available" in data["error"] or "AttributeError" in data["error"]

    def test_os_environ_isolated_from_real_env(self, client):
        """Test that os.environ doesn't expose real environment variables."""
        response = client.post(
            "/execute",
            json={
                "code": "result = os.environ.get('PATH')",
                "arguments": {},
                "credentials": {},  # No PATH credential provided
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # PATH should not be accessible as it's not in the credentials
        assert data["result"] is None

    def test_os_setattr_blocked(self, client):
        """Test that setting attributes on os is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "os.custom_attr = 'value'\nresult = os.custom_attr",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Cannot set" in data["error"] or "AttributeError" in data["error"]
