"""Tests for sandbox escape prevention.

Verifies that common Python sandbox escape techniques are blocked by
the code safety validator and restricted builtins.

These tests are critical for production security - they ensure that
user-submitted tool code cannot break out of the sandbox to access
the host system.
"""

import pytest


@pytest.fixture
def client(authenticated_client):
    """Alias for authenticated_client."""
    return authenticated_client


class TestDunderAttributeBlocking:
    """Test that dunder attribute access patterns are blocked.

    These are the most common Python sandbox escape vectors:
    - __class__.__mro__ to reach object
    - __subclasses__() to find dangerous classes
    - __globals__ to access module namespaces
    """

    def test_class_access_blocked(self, client):
        """__class__ access is blocked (leads to __mro__ and __bases__)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = [].__class__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]
        assert "__class__" in data["error"]

    def test_mro_access_blocked(self, client):
        """__mro__ access is blocked (Method Resolution Order)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = [].__class__.__mro__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_bases_access_blocked(self, client):
        """__bases__ access is blocked (parent class access)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = ''.__class__.__bases__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_subclasses_access_blocked(self, client):
        """__subclasses__() access is blocked (exposes dangerous classes)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = ().__class__.__bases__[0].__subclasses__()",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_globals_access_blocked(self, client):
        """__globals__ access is blocked (namespace access)."""
        response = client.post(
            "/execute",
            json={
                "code": "def f(): pass\nresult = f.__globals__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_code_access_blocked(self, client):
        """__code__ access is blocked (code object manipulation)."""
        response = client.post(
            "/execute",
            json={
                "code": "def f(): pass\nresult = f.__code__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_builtins_dunder_access_blocked(self, client):
        """Accessing .__builtins__ on an object is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "def f(): pass\nresult = f.__builtins__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_import_dunder_via_safe_import(self, client):
        """__import__('os') is blocked by the safe import function."""
        response = client.post(
            "/execute",
            json={
                "code": "result = __import__('os')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not allowed" in data["error"] or "ImportError" in data["error"]

    def test_loader_access_blocked(self, client):
        """__loader__ access is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "import json\nresult = json.__loader__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_spec_access_blocked(self, client):
        """__spec__ access is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "import json\nresult = json.__spec__",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]


class TestEscapeViaBuiltins:
    """Test that dangerous builtins are removed."""

    def test_type_not_available(self, client):
        """type() is removed (can access __bases__.__subclasses__)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = type(42)",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_getattr_not_available(self, client):
        """getattr() is removed (can access dunder attrs via string)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = getattr([], '__len__')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_setattr_not_available(self, client):
        """setattr() is removed."""
        response = client.post(
            "/execute",
            json={
                "code": "x = []\nsetattr(x, 'test', True)\nresult = True",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_eval_not_available(self, client):
        """eval() is not in safe builtins."""
        response = client.post(
            "/execute",
            json={
                "code": "result = eval('1 + 1')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_exec_not_available(self, client):
        """exec() is not in safe builtins."""
        response = client.post(
            "/execute",
            json={
                "code": "exec('result = 42')\nresult = result",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_compile_not_available(self, client):
        """compile() is not in safe builtins."""
        response = client.post(
            "/execute",
            json={
                "code": "c = compile('result = 1', '<string>', 'exec')\nresult = c",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_open_not_available(self, client):
        """open() is not in safe builtins."""
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


class TestEscapeViaDiscovery:
    """Test that attribute discovery functions are blocked."""

    def test_vars_blocked(self, client):
        """vars() is blocked (exposes __dict__)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = vars()",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]

    def test_dir_blocked(self, client):
        """dir() is blocked (discovers attributes)."""
        response = client.post(
            "/execute",
            json={
                "code": "result = dir([])",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Security violation" in data["error"]


class TestImportRestrictions:
    """Test that import whitelist is enforced."""

    def test_os_import_blocked(self, client):
        """os module import is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "import os\nresult = os.listdir('/')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "ImportError" in data["error"] or "not allowed" in data["error"]

    def test_subprocess_import_blocked(self, client):
        """subprocess module import is blocked."""
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

    def test_sys_import_blocked(self, client):
        """sys module import is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "import sys\nresult = sys.modules",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_importlib_blocked(self, client):
        """importlib module import is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "import importlib\nresult = importlib.import_module('os')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_allowed_module_json_works(self, client):
        """json module (whitelisted) can be imported."""
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
        assert data["result"] == '{"ok": true}'

    def test_allowed_module_math_works(self, client):
        """math module (whitelisted) can be imported."""
        response = client.post(
            "/execute",
            json={
                "code": "import math\nresult = math.sqrt(16)",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == 4.0

    def test_allowed_module_datetime_works(self, client):
        """datetime module (whitelisted) can be imported."""
        response = client.post(
            "/execute",
            json={
                "code": "import datetime\nresult = str(datetime.date(2024, 1, 1))",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["result"] == "2024-01-01"


class TestGetattStringEscape:
    """Test that getattr-via-string patterns are blocked."""

    def test_getattr_dunder_string_blocked(self, client):
        """getattr with dunder string argument is blocked."""
        response = client.post(
            "/execute",
            json={
                "code": 'result = getattr([], "__class__")',
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_getattr_double_quoted_blocked(self, client):
        """getattr with double-quoted dunder is also blocked."""
        response = client.post(
            "/execute",
            json={
                "code": "result = getattr([], '__class__')",
                "arguments": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
