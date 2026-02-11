"""Unit tests for validate_code_safety function.

Tests the code safety validator directly without going through the HTTP API.
This covers the regex-based pattern detection that prevents sandbox escapes.
"""

import pytest

from app.executor import validate_code_safety


class TestValidateCodeSafety:
    """Test the validate_code_safety function directly."""

    def test_safe_code_passes(self):
        """Normal code passes validation."""
        is_safe, error = validate_code_safety("result = 1 + 1")
        assert is_safe is True
        assert error is None

    def test_safe_code_with_loops(self):
        """Code with loops and comprehensions passes."""
        code = """
numbers = [1, 2, 3]
result = [x * 2 for x in numbers]
for n in numbers:
    print(n)
"""
        is_safe, error = validate_code_safety(code)
        assert is_safe is True
        assert error is None

    def test_class_access_fails(self):
        """__class__ access is detected."""
        is_safe, error = validate_code_safety("x = [].__class__")
        assert is_safe is False
        assert "__class__" in error

    def test_bases_access_fails(self):
        """__bases__ access is detected."""
        is_safe, error = validate_code_safety("x = str.__bases__")
        assert is_safe is False
        assert "__bases__" in error

    def test_mro_access_fails(self):
        """__mro__ access is detected."""
        is_safe, error = validate_code_safety("x = int.__mro__")
        assert is_safe is False
        assert "__mro__" in error

    def test_subclasses_access_fails(self):
        """__subclasses__ access is detected."""
        is_safe, error = validate_code_safety("x = object.__subclasses__()")
        assert is_safe is False
        assert "__subclasses__" in error

    def test_globals_access_fails(self):
        """__globals__ access is detected."""
        is_safe, error = validate_code_safety("x = f.__globals__")
        assert is_safe is False
        assert "__globals__" in error

    def test_code_access_fails(self):
        """__code__ access is detected."""
        is_safe, error = validate_code_safety("x = f.__code__")
        assert is_safe is False
        assert "__code__" in error

    def test_builtins_dunder_attr_access_fails(self):
        """.__builtins__ attribute access is detected."""
        is_safe, error = validate_code_safety("x = f.__builtins__")
        assert is_safe is False
        assert "__builtins__" in error

    def test_import_dunder_attr_access_fails(self):
        """.__import__ attribute access is detected."""
        is_safe, error = validate_code_safety("x = module.__import__")
        assert is_safe is False
        assert "__import__" in error

    def test_standalone_builtins_not_pattern_matched(self):
        """Standalone __builtins__ is not caught by pattern (handled by runtime)."""
        # The regex patterns require a dot prefix (e.g., .__builtins__)
        # Standalone __builtins__ is handled by the safe builtins namespace
        is_safe, _error = validate_code_safety("x = __builtins__")
        # This passes pattern validation but fails at runtime
        assert is_safe is True

    def test_standalone_import_not_pattern_matched(self):
        """Standalone __import__ is not caught by pattern (handled by safe import)."""
        # __import__('os') without a dot prefix passes pattern validation
        # but fails at runtime because __import__ is replaced with safe_import
        is_safe, _error = validate_code_safety("x = __import__('os')")
        assert is_safe is True

    def test_loader_access_fails(self):
        """__loader__ access is detected."""
        is_safe, error = validate_code_safety("x = json.__loader__")
        assert is_safe is False
        assert "__loader__" in error

    def test_spec_access_fails(self):
        """__spec__ access is detected."""
        is_safe, error = validate_code_safety("x = json.__spec__")
        assert is_safe is False
        assert "__spec__" in error

    def test_vars_call_fails(self):
        """vars() call is detected."""
        is_safe, error = validate_code_safety("x = vars()")
        assert is_safe is False
        assert "vars" in error

    def test_dir_call_fails(self):
        """dir() call is detected."""
        is_safe, error = validate_code_safety("x = dir([])")
        assert is_safe is False
        assert "dir" in error

    def test_getattr_with_dunder_string_fails(self):
        """getattr with dunder string argument is detected."""
        is_safe, error = validate_code_safety("getattr(x, '__class__')")
        assert is_safe is False

    def test_full_escape_chain_fails(self):
        """Full escape chain is detected at the first pattern."""
        code = "().__class__.__bases__[0].__subclasses__()"
        is_safe, error = validate_code_safety(code)
        assert is_safe is False
        assert "Security violation" in error

    def test_custom_source_name_in_error(self):
        """Source name appears in error message."""
        is_safe, error = validate_code_safety("x.__class__", source_name="my_tool")
        assert is_safe is False
        assert "my_tool" in error

    def test_multiline_code_scanned(self):
        """Forbidden patterns detected even in multiline code."""
        code = """
x = 1
y = 2
z = x.__class__
result = z
"""
        is_safe, error = validate_code_safety(code)
        assert is_safe is False
        assert "__class__" in error
