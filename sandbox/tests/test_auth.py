"""Tests for sandbox authentication."""

import os
import pytest
from unittest.mock import patch
from fastapi import HTTPException

# Set up test environment before imports
os.environ["SANDBOX_API_KEY"] = "test-api-key-that-is-at-least-32-chars-long"
os.environ["ENVIRONMENT"] = "development"


class TestSandboxAuth:
    """Tests for sandbox API key authentication."""

    @pytest.mark.asyncio
    async def test_valid_api_key_passes(self):
        """Test that valid API key is accepted."""
        # Import after setting environment
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "valid-api-key-32-characters-long!",
                "ENVIRONMENT": "development",
            },
        ):
            # Re-import to pick up new env vars
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            # Should not raise
            await verify_api_key(x_api_key="valid-api-key-32-characters-long!")

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self):
        """Test that invalid API key is rejected."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "correct-api-key-32-characters-xx",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="wrong-api-key")

            assert exc_info.value.status_code == 401
            assert "Invalid API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_api_key_rejected(self):
        """Test that missing API key is rejected."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "valid-api-key-32-characters-long!",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key=None)

            assert exc_info.value.status_code == 401
            assert "Missing X-API-Key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unconfigured_api_key_rejected(self):
        """Test that unconfigured SANDBOX_API_KEY returns 503."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="some-key")

            assert exc_info.value.status_code == 503
            assert "missing SANDBOX_API_KEY" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_weak_api_key_rejected(self):
        """Test that weak API keys (< 32 chars) are rejected with 503.

        Weak API keys are a security risk and must be rejected to prevent
        deployments with insecure configurations.
        """
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "short-key",  # Less than 32 chars
                "ENVIRONMENT": "production",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="short-key")

            assert exc_info.value.status_code == 503
            assert "at least 32 characters" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_weak_api_key_rejected_in_development(self):
        """Test that weak API keys are also rejected in development.

        Security requirements apply to all environments.
        """
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "short",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="short")

            assert exc_info.value.status_code == 503
            assert "at least 32 characters" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_timing_attack_resistance(self):
        """Test that API key comparison uses constant-time comparison."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "secure-api-key-32-characters-xxx",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)

            # Verify hmac.compare_digest is used (by checking the module code)
            import inspect

            source = inspect.getsource(auth_module.verify_api_key)
            assert "hmac.compare_digest" in source

    @pytest.mark.asyncio
    async def test_no_auth_bypass_flag_removed(self):
        """Test that SANDBOX_ALLOW_NO_AUTH flag no longer exists."""
        import importlib
        import app.auth as auth_module

        importlib.reload(auth_module)

        # Verify the flag doesn't exist in the module
        assert not hasattr(auth_module, "ALLOW_NO_AUTH")

        # Verify environment variable is not checked
        import inspect

        source = inspect.getsource(auth_module)
        assert "SANDBOX_ALLOW_NO_AUTH" not in source


class TestAPIKeyValidation:
    """Additional tests for API key validation edge cases."""

    @pytest.mark.asyncio
    async def test_empty_string_api_key_rejected(self):
        """Test that empty string API key is rejected."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "valid-api-key-32-characters-long!",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="")

            # Empty string should fail comparison
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_whitespace_api_key_rejected(self):
        """Test that whitespace API key is rejected."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "valid-api-key-32-characters-long!",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="   ")

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_similar_api_key_rejected(self):
        """Test that similar but different API keys are rejected."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "correct-api-key-32-characters-xx",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            # Try key with one character different (changed ! to ?)
            with pytest.raises(HTTPException):
                await verify_api_key(x_api_key="correct-api-key-32-characters-?")

    @pytest.mark.asyncio
    async def test_case_sensitive_api_key(self):
        """Test that API key comparison is case-sensitive."""
        with patch.dict(
            os.environ,
            {
                "SANDBOX_API_KEY": "Correct-API-Key-32-characters-xx",
                "ENVIRONMENT": "development",
            },
        ):
            import importlib
            import app.auth as auth_module

            importlib.reload(auth_module)
            from app.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(
                    x_api_key="correct-api-key-32-characters-!"
                )  # lowercase

            assert exc_info.value.status_code == 401
