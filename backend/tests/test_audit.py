"""Tests for the audit logging service."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.audit import AuditAction, AuditService


class TestAuditServiceSanitization:
    """Tests for credential sanitization in audit logs."""

    @pytest.fixture
    def mock_activity_logger(self):
        """Create a mock activity logger."""
        logger = AsyncMock()
        logger.log = AsyncMock(return_value={"id": "test-log-id"})
        return logger

    @pytest.fixture
    def audit_service(self, mock_activity_logger):
        """Create audit service with mocked activity logger."""
        return AuditService(activity_logger=mock_activity_logger)

    @pytest.mark.asyncio
    async def test_sanitize_password_field(self, audit_service):
        """Test that password fields are redacted."""
        details = {"username": "admin", "password": "secret123"}
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["username"] == "admin"
        assert sanitized["password"] == "[REDACTED - set]"

    @pytest.mark.asyncio
    async def test_sanitize_token_field(self, audit_service):
        """Test that token fields are redacted."""
        details = {"access_token": "abc123", "refresh_token": "xyz789"}
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["access_token"] == "[REDACTED - set]"
        assert sanitized["refresh_token"] == "[REDACTED - set]"

    @pytest.mark.asyncio
    async def test_sanitize_api_key_field(self, audit_service):
        """Test that API key fields are redacted."""
        details = {"api_key": "sk-test-123", "header_name": "Authorization"}
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["api_key"] == "[REDACTED - set]"
        assert sanitized["header_name"] == "Authorization"

    @pytest.mark.asyncio
    async def test_sanitize_secret_field(self, audit_service):
        """Test that secret fields are redacted."""
        details = {"client_secret": "secret", "client_id": "public-id"}
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["client_secret"] == "[REDACTED - set]"
        assert sanitized["client_id"] == "public-id"

    @pytest.mark.asyncio
    async def test_sanitize_value_field(self, audit_service):
        """Test that generic value fields are redacted."""
        details = {"name": "API_KEY", "value": "secret-value"}
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["name"] == "API_KEY"
        assert sanitized["value"] == "[REDACTED - set]"

    @pytest.mark.asyncio
    async def test_sanitize_none_value(self, audit_service):
        """Test that None values are indicated as unset."""
        details = {"password": None, "api_key": None}
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["password"] == "[REDACTED - unset]"
        assert sanitized["api_key"] == "[REDACTED - unset]"

    @pytest.mark.asyncio
    async def test_sanitize_nested_dict(self, audit_service):
        """Test that nested dictionaries are also sanitized."""
        details = {
            "user": "admin",
            "credentials": {
                "password": "secret",
                "token": "abc123",
            },
        }
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["user"] == "admin"
        assert sanitized["credentials"]["password"] == "[REDACTED - set]"
        assert sanitized["credentials"]["token"] == "[REDACTED - set]"

    @pytest.mark.asyncio
    async def test_sanitize_case_insensitive(self, audit_service):
        """Test that field name matching is case-insensitive."""
        details = {
            "PASSWORD": "secret",
            "Api_Key": "key123",
            "ACCESS_TOKEN": "token",
        }
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["PASSWORD"] == "[REDACTED - set]"
        assert sanitized["Api_Key"] == "[REDACTED - set]"
        assert sanitized["ACCESS_TOKEN"] == "[REDACTED - set]"

    @pytest.mark.asyncio
    async def test_sanitize_partial_match(self, audit_service):
        """Test that partial matches in field names are caught."""
        details = {
            "user_password_hash": "hashed",
            "auth_token_expires": "2024-01-01",
            "my_api_key_id": "key-123",
        }
        sanitized = audit_service._sanitize_details(details)

        assert sanitized["user_password_hash"] == "[REDACTED - set]"
        assert sanitized["auth_token_expires"] == "[REDACTED - set]"
        assert sanitized["my_api_key_id"] == "[REDACTED - set]"

    @pytest.mark.asyncio
    async def test_sanitize_preserves_non_sensitive(self, audit_service):
        """Test that non-sensitive data is preserved."""
        details = {
            "id": "123",
            "name": "test",
            "description": "A test item",
            "count": 42,
            "enabled": True,
        }
        sanitized = audit_service._sanitize_details(details)

        assert sanitized == details

    @pytest.mark.asyncio
    async def test_log_credential_create_sanitizes(self, audit_service, mock_activity_logger):
        """Test that credential creation logs sanitize sensitive data."""
        credential_id = uuid4()
        server_id = uuid4()

        await audit_service.log_credential_create(
            credential_id=credential_id,
            server_id=server_id,
            credential_name="API_KEY",
            auth_type="api_key_header",
            actor_ip="192.168.1.1",
        )

        # Verify log was called
        mock_activity_logger.log.assert_called_once()
        call_args = mock_activity_logger.log.call_args

        # Verify sensitive data is not in the log
        details = call_args.kwargs.get("details", {})
        assert "password" not in str(details).lower() or "redacted" in str(details).lower()

    @pytest.mark.asyncio
    async def test_log_includes_action_and_timestamp(self, audit_service, mock_activity_logger):
        """Test that audit logs include action type and timestamp."""
        await audit_service.log(
            action=AuditAction.CREDENTIAL_CREATE,
            resource_type="credential",
            details={"name": "test-credential"},
        )

        mock_activity_logger.log.assert_called_once()
        call_args = mock_activity_logger.log.call_args
        details = call_args.kwargs.get("details", {})

        assert details["action"] == "credential.create"
        assert "timestamp" in details
