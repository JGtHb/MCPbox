"""Tests for sandbox startup configuration validation.

Verifies that the sandbox fails fast on misconfiguration rather
than silently accepting requests that will fail at runtime.

Note: Encryption key validation was removed when the sandbox switched
from Fernet-based credential encryption to backend-decrypted secrets
passed via API. Only SANDBOX_API_KEY validation remains.
"""

import logging
import os
import stat
from pathlib import Path
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


class TestSquidACLVolumeCheck:
    """Test _check_squid_acl_volume detects permission issues at startup."""

    def test_writable_volume_logs_info(self, tmp_path, caplog):
        """Writable volume logs success at INFO level."""
        acl_file = tmp_path / "approved-private.txt"
        with patch("app.registry._SQUID_ACL_PATH", acl_file):
            from app.main import _check_squid_acl_volume

            with caplog.at_level(logging.INFO, logger="app.main"):
                _check_squid_acl_volume()

        assert "is writable" in caplog.text

    def test_readonly_volume_logs_error(self, tmp_path, caplog):
        """Read-only volume logs actionable error."""
        acl_dir = tmp_path / "squid-acl"
        acl_dir.mkdir()
        acl_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        acl_file = acl_dir / "approved-private.txt"

        try:
            with patch("app.registry._SQUID_ACL_PATH", acl_file):
                from app.main import _check_squid_acl_volume

                with caplog.at_level(logging.ERROR, logger="app.main"):
                    _check_squid_acl_volume()

            assert "NOT writable" in caplog.text
            assert "docker compose down" in caplog.text
        finally:
            acl_dir.chmod(stat.S_IRWXU)

    def test_missing_volume_skips_silently(self, caplog):
        """Missing volume (dev/test) is silently skipped."""
        nonexistent = Path("/nonexistent/squid-acl/approved-private.txt")
        with patch("app.registry._SQUID_ACL_PATH", nonexistent):
            from app.main import _check_squid_acl_volume

            with caplog.at_level(logging.ERROR, logger="app.main"):
                _check_squid_acl_volume()

        assert "NOT writable" not in caplog.text
