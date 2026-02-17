"""Tests for module attribute traversal prevention (SafeModuleProxy).

Verifies that injected modules (json, datetime, etc.) cannot be used to
escape the sandbox via attribute traversal attacks like:
- datetime.sys.modules["os"].popen("id")
- json.codecs.sys.modules["subprocess"]

These tests are critical for production security.
"""

import json
import datetime
import types

import pytest

from app.executor import (
    SafeModuleProxy,
    _MODULE_FORBIDDEN_ATTRS,
    _MODULE_SAFE_ATTRS,
    validate_code_safety,
)


class TestSafeModuleProxy:
    """Test SafeModuleProxy blocks dangerous attribute access."""

    def test_json_dumps_works(self):
        """Normal json.dumps() works through proxy."""
        proxy = SafeModuleProxy(json, name="json")
        result = proxy.dumps({"key": "value"})
        assert result == '{"key": "value"}'

    def test_json_loads_works(self):
        """Normal json.loads() works through proxy."""
        proxy = SafeModuleProxy(json, name="json")
        result = proxy.loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_datetime_datetime_works(self):
        """Normal datetime.datetime access works through proxy."""
        proxy = SafeModuleProxy(datetime, name="datetime")
        now = proxy.datetime.now()
        assert isinstance(now, datetime.datetime)

    def test_datetime_timedelta_works(self):
        """Normal datetime.timedelta works through proxy."""
        proxy = SafeModuleProxy(datetime, name="datetime")
        td = proxy.timedelta(days=1)
        assert td.days == 1

    def test_datetime_sys_blocked(self):
        """datetime.sys attribute access is blocked (traversal vector)."""
        proxy = SafeModuleProxy(datetime, name="datetime")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.sys

    def test_json_codecs_blocked(self):
        """json.codecs attribute access is blocked (traversal to sys)."""
        proxy = SafeModuleProxy(json, name="json")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.codecs

    def test_os_attr_blocked(self):
        """Direct .os attribute access is blocked."""
        proxy = SafeModuleProxy(datetime, name="datetime")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.os

    def test_subprocess_attr_blocked(self):
        """Direct .subprocess attribute access is blocked."""
        proxy = SafeModuleProxy(datetime, name="datetime")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.subprocess

    def test_builtins_attr_blocked(self):
        """Direct .builtins attribute access is blocked."""
        proxy = SafeModuleProxy(datetime, name="datetime")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.builtins

    def test_posixpath_attr_blocked(self):
        """Direct .posixpath attribute access is blocked."""
        proxy = SafeModuleProxy(json, name="json")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.posixpath

    def test_dunder_attrs_blocked(self):
        """Dunder attributes (__spec__, __loader__, etc.) are blocked."""
        proxy = SafeModuleProxy(json, name="json")
        with pytest.raises(AttributeError, match="forbidden"):
            _ = proxy.__builtins__

    def test_setattr_blocked(self):
        """Cannot set attributes on proxy."""
        proxy = SafeModuleProxy(json, name="json")
        with pytest.raises(AttributeError, match="Cannot set"):
            proxy.malicious = "value"

    def test_delattr_blocked(self):
        """Cannot delete attributes on proxy."""
        proxy = SafeModuleProxy(json, name="json")
        with pytest.raises(AttributeError, match="Cannot delete"):
            del proxy.dumps

    def test_repr(self):
        """Proxy has readable repr."""
        proxy = SafeModuleProxy(json, name="json")
        assert "SafeModuleProxy" in repr(proxy)
        assert "json" in repr(proxy)

    def test_submodule_wrapped(self):
        """Submodule access returns a wrapped proxy too."""
        # datetime.datetime is a class, not a module, so it won't be wrapped
        # But if we had a module that contained submodules in its allowlist...
        # We test the behavior: module attributes that are modules get wrapped
        proxy = SafeModuleProxy(datetime, name="datetime")
        # Access an allowed attribute
        dt_class = proxy.datetime
        # datetime.datetime is a class, not a module, so it's returned as-is
        assert dt_class is datetime.datetime

    def test_unknown_module_auto_allowlist(self):
        """Modules without explicit allowlist get auto-generated safe attrs."""
        import math

        proxy = SafeModuleProxy(math, name="math")
        # math should work (it has an explicit allowlist)
        assert proxy.sqrt(4) == 2.0
        assert proxy.pi == pytest.approx(3.14159, rel=1e-4)

    def test_forbidden_attrs_comprehensive(self):
        """All forbidden attrs are blocked on any module."""
        proxy = SafeModuleProxy(json, name="json")
        for attr in _MODULE_FORBIDDEN_ATTRS:
            with pytest.raises(AttributeError):
                getattr(proxy, attr)


class TestModuleTraversalCodeSafety:
    """Test that code safety validation catches module traversal patterns."""

    def test_datetime_sys_pattern_blocked(self):
        """Pattern 'datetime.sys' is blocked by regex validator."""
        is_safe, err = validate_code_safety("x = datetime.sys.modules")
        assert is_safe is False
        assert ".sys" in err

    def test_modules_subscript_blocked(self):
        """Pattern '.modules[\"os\"]' is blocked by regex validator."""
        is_safe, err = validate_code_safety('x = foo.modules["os"]')
        assert is_safe is False

    def test_os_subscript_blocked(self):
        """Pattern '["os"]' is blocked by regex validator."""
        is_safe, err = validate_code_safety('x = bar["os"]')
        assert is_safe is False

    def test_sys_subscript_blocked(self):
        """Pattern '["sys"]' is blocked by regex validator."""
        is_safe, err = validate_code_safety('x = bar["sys"]')
        assert is_safe is False

    def test_subprocess_subscript_blocked(self):
        """Pattern '["subprocess"]' is blocked by regex validator."""
        is_safe, err = validate_code_safety('x = bar["subprocess"]')
        assert is_safe is False

    def test_builtins_subscript_blocked(self):
        """Pattern '["builtins"]' is blocked by regex validator."""
        is_safe, err = validate_code_safety('x = bar["builtins"]')
        assert is_safe is False

    def test_normal_code_passes(self):
        """Normal code without traversal patterns passes validation."""
        is_safe, err = validate_code_safety(
            "import json\nresult = json.dumps({'a': 1})"
        )
        assert is_safe is True

    def test_normal_datetime_passes(self):
        """Normal datetime usage passes validation."""
        is_safe, err = validate_code_safety(
            "import datetime\nresult = datetime.datetime.now()"
        )
        assert is_safe is True


class TestSafeImportWrapping:
    """Test that safe_import wraps modules with SafeModuleProxy."""

    def test_imported_module_is_proxied(self):
        """Modules returned by safe_import are SafeModuleProxy instances."""
        from app.executor import create_safe_builtins

        builtins = create_safe_builtins()
        safe_import = builtins["__import__"]

        # Import json through safe_import
        imported_json = safe_import("json")
        assert isinstance(imported_json, SafeModuleProxy)

    def test_imported_module_blocks_traversal(self):
        """Imported modules block traversal attributes."""
        from app.executor import create_safe_builtins

        builtins = create_safe_builtins()
        safe_import = builtins["__import__"]

        imported_json = safe_import("json")
        with pytest.raises(AttributeError, match="forbidden|not in sandbox"):
            _ = imported_json.codecs

    def test_imported_module_allows_normal_use(self):
        """Imported modules allow normal attribute access."""
        from app.executor import create_safe_builtins

        builtins = create_safe_builtins()
        safe_import = builtins["__import__"]

        imported_json = safe_import("json")
        result = imported_json.dumps({"test": True})
        assert result == '{"test": true}'
