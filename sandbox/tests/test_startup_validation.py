"""Tests for sandbox startup configuration validation.

Verifies that the sandbox fails fast on misconfiguration rather
than silently accepting requests that will fail at runtime.
"""

import os
from unittest.mock import patch

import pytest


class TestStartupValidation:
    """Test _check_security_configuration fails fast on bad config."""

    def test_missing_sandbox_api_key_aborts(self):
        """Sandbox must abort if SANDBOX_API_KEY is not set."""
        with patch.dict(
            os.environ, {"SANDBOX_API_KEY": "", "MCPBOX_ENCRYPTION_KEY": "a" * 64}
        ):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_short_sandbox_api_key_aborts(self):
        """Sandbox must abort if SANDBOX_API_KEY is too short."""
        with patch.dict(
            os.environ, {"SANDBOX_API_KEY": "short", "MCPBOX_ENCRYPTION_KEY": "a" * 64}
        ):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_missing_encryption_key_aborts(self):
        """Sandbox must abort if MCPBOX_ENCRYPTION_KEY is not set (without override)."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "a" * 32,
                "MCPBOX_ENCRYPTION_KEY": "",
                "SANDBOX_ALLOW_MISSING_ENCRYPTION": "",
            },
        ):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_missing_encryption_key_allowed_in_dev(self):
        """Sandbox should warn but not abort when SANDBOX_ALLOW_MISSING_ENCRYPTION=true."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "a" * 32,
                "MCPBOX_ENCRYPTION_KEY": "",
                "SANDBOX_ALLOW_MISSING_ENCRYPTION": "true",
            },
        ):
            from app.main import _check_security_configuration

            # Should not raise
            _check_security_configuration()

    def test_invalid_encryption_key_length_aborts(self):
        """Sandbox must abort if MCPBOX_ENCRYPTION_KEY has wrong length."""
        with patch.dict(
            os.environ,
            {"SANDBOX_API_KEY": "a" * 32, "MCPBOX_ENCRYPTION_KEY": "abcdef"},
        ):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_invalid_encryption_key_chars_aborts(self):
        """Sandbox must abort if MCPBOX_ENCRYPTION_KEY has non-hex chars."""
        with patch.dict(
            os.environ,
            {"SANDBOX_API_KEY": "a" * 32, "MCPBOX_ENCRYPTION_KEY": "g" * 64},
        ):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_valid_configuration_passes(self):
        """Sandbox should pass with valid configuration."""
        with patch.dict(
            os.environ,
            {"SANDBOX_API_KEY": "a" * 32, "MCPBOX_ENCRYPTION_KEY": "a" * 64},
        ):
            from app.main import _check_security_configuration

            # Should not raise
            _check_security_configuration()
