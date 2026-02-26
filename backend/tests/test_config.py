"""Tests for configuration validation.

Tests the Settings validation to ensure invalid configurations
are rejected at startup.

Note: These tests use pytest.mark.skip_rate_limiter_reset to skip the
autouse reset_rate_limiter fixture, which would otherwise import app modules
that conflict with config module reloading.
"""

import os
from unittest.mock import patch

import pytest

# Mark all tests in this module to skip rate limiter reset
pytestmark = pytest.mark.skip_rate_limiter_reset


class TestEncryptionKeyValidation:
    """Tests for encryption key validation."""

    def test_valid_encryption_key_accepted(self):
        """Test that a valid 64-character hex key is accepted."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "0" * 32,
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            reload(config_module)
            assert config_module.settings.mcpbox_encryption_key == "0" * 64

    def test_short_encryption_key_rejected(self):
        """Test that a short encryption key is rejected."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 32,  # Too short
                "SANDBOX_API_KEY": "0" * 32,
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            with pytest.raises(Exception) as exc_info:
                reload(config_module)

            assert "64" in str(exc_info.value)


class TestSandboxApiKeyValidation:
    """Tests for sandbox API key validation."""

    def test_valid_sandbox_api_key_accepted(self):
        """Test that a valid sandbox API key is accepted."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "a" * 32,
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            reload(config_module)
            assert config_module.settings.sandbox_api_key == "a" * 32

    def test_short_sandbox_api_key_rejected(self):
        """Test that a short sandbox API key is rejected."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "short",
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            with pytest.raises(Exception) as exc_info:
                reload(config_module)

            assert "32 characters" in str(exc_info.value)


class TestSecretUniquenessValidation:
    """Tests for secret uniqueness validation."""

    def test_duplicate_secrets_warning(self):
        """Test that duplicate secrets generate warnings."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "duplicate_secret_12345678901234567890",
                "JWT_SECRET_KEY": "duplicate_secret_12345678901234567890",  # Same as SANDBOX_API_KEY
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            reload(config_module)
            warnings = config_module.settings.check_security_configuration()
            # Should have a warning about duplicate secrets
            assert any("same value" in w for w in warnings)

    def test_unique_secrets_no_warning(self):
        """Test that unique secrets don't generate warnings about duplicates."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "a" * 32,
                "JWT_SECRET_KEY": "c" * 32,
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            reload(config_module)
            warnings = config_module.settings.check_security_configuration()
            # Should not have any warning about duplicate secrets
            assert not any("same value" in w for w in warnings)


class TestAllZerosKeyWarning:
    """Tests for all-zeros encryption key warning."""

    def test_all_zeros_key_warns_outside_ci(self):
        """Test that all-zeros encryption key triggers a warning outside CI."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "a" * 32,
            },
            clear=False,
        ):
            # Remove CI env var if present
            env = os.environ.copy()
            env.pop("CI", None)
            with patch.dict(os.environ, env, clear=True):
                from importlib import reload

                import app.core.config as config_module

                reload(config_module)
                warnings = config_module.settings.check_security_configuration()
                assert any("all zeros" in w for w in warnings)

    def test_all_zeros_key_no_warning_in_ci(self):
        """Test that all-zeros encryption key is accepted in CI."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "0" * 64,
                "SANDBOX_API_KEY": "a" * 32,
                "CI": "true",
            },
            clear=False,
        ):
            from importlib import reload

            import app.core.config as config_module

            reload(config_module)
            warnings = config_module.settings.check_security_configuration()
            assert not any("all zeros" in w for w in warnings)

    def test_real_key_no_zeros_warning(self):
        """Test that a real encryption key doesn't trigger all-zeros warning."""
        with patch.dict(
            os.environ,
            {
                "MCPBOX_ENCRYPTION_KEY": "a1b2c3d4e5f6" + "0" * 52,
                "SANDBOX_API_KEY": "a" * 32,
            },
            clear=False,
        ):
            env = os.environ.copy()
            env.pop("CI", None)
            with patch.dict(os.environ, env, clear=True):
                from importlib import reload

                import app.core.config as config_module

                reload(config_module)
                warnings = config_module.settings.check_security_configuration()
                assert not any("all zeros" in w for w in warnings)


class TestLogRetentionSetting:
    """Tests for log_retention_days as a database-only setting.

    log_retention_days is managed via the admin panel (/api/settings/security-policy)
    and loaded from the database at startup. It is no longer an environment variable.
    See test_settings_api.py for the full API-level tests.
    """

    pass
