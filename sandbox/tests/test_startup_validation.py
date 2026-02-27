"""Tests for sandbox startup configuration validation.

Verifies that the sandbox fails fast on misconfiguration rather
than silently accepting requests that will fail at runtime.

Note: Encryption key validation was removed when the sandbox switched
from Fernet-based credential encryption to backend-decrypted secrets
passed via API. Only SANDBOX_API_KEY validation remains.
"""

import os
from unittest.mock import patch

import pytest


class TestStartupValidation:
    """Test _check_security_configuration fails fast on bad config."""

    def test_missing_sandbox_api_key_aborts(self):
        """Sandbox must abort if SANDBOX_API_KEY is not set."""
        with patch.dict(os.environ, {"SANDBOX_API_KEY": ""}):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_short_sandbox_api_key_aborts(self):
        """Sandbox must abort if SANDBOX_API_KEY is too short."""
        with patch.dict(os.environ, {"SANDBOX_API_KEY": "short"}):
            from app.main import _check_security_configuration

            with pytest.raises(SystemExit, match="configuration errors"):
                _check_security_configuration()

    def test_valid_configuration_passes(self):
        """Sandbox should pass with valid configuration."""
        with patch.dict(
            os.environ,
            {"SANDBOX_API_KEY": "a" * 32},
        ):
            from app.main import _check_security_configuration

            # Should not raise
            _check_security_configuration()
