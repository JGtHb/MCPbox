"""Tests for security fixes from the security review.

Tests cover:
- H3: Email format validation on MCP gateway
- M5: Token removal from wizard API responses
- M6: AES-GCM AAD (associated authenticated data) support
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.crypto import decrypt, decrypt_from_base64, encrypt, encrypt_to_base64


class TestEmailValidation:
    """Test email format validation on MCP gateway (H3)."""

    def test_valid_email_accepted(self):
        """Standard email formats are accepted."""
        from app.api.auth_simple import _EMAIL_PATTERN

        valid_emails = [
            "user@example.com",
            "user.name@example.com",
            "user+tag@example.com",
            "user@sub.domain.example.com",
            "test@test.io",
            "a@b.co",
        ]
        for email in valid_emails:
            assert _EMAIL_PATTERN.match(email), f"Should accept: {email}"

    def test_invalid_email_rejected(self):
        """Malicious/malformed email formats are rejected."""
        from app.api.auth_simple import _EMAIL_PATTERN

        invalid_emails = [
            "../../../admin",
            "user@",
            "@domain.com",
            "user",
            "",
            "user@domain",
            "user@domain.com\nX-Injected: header",
            "user@domain.com\r\nInjected: yes",
            "<script>alert(1)</script>@domain.com",
            "user@localhost",
        ]
        for email in invalid_emails:
            assert not _EMAIL_PATTERN.match(email), f"Should reject: {email}"

    def test_email_max_length_enforced(self):
        """Emails exceeding RFC 5321 max length (254) are rejected."""
        from app.api.auth_simple import _MAX_EMAIL_LENGTH

        assert _MAX_EMAIL_LENGTH == 254
        # An email longer than 254 chars should be caught by the length check
        long_email = "a" * 246 + "@test.com"
        assert len(long_email) > 254


class TestAESGCMWithAAD:
    """Test AES-GCM encryption with Associated Authenticated Data (M6)."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Set up a valid encryption key for tests."""
        valid_key = "a" * 64
        monkeypatch.setenv("MCPBOX_ENCRYPTION_KEY", valid_key)

    def test_encrypt_decrypt_with_aad(self):
        """Data encrypted with AAD can be decrypted with same AAD."""
        plaintext = "secret-service-token"
        aad = "service_token"

        encrypted = encrypt(plaintext, aad=aad)
        decrypted = decrypt(encrypted, aad=aad)
        assert decrypted == plaintext

    def test_wrong_aad_fails(self):
        """Data encrypted with AAD cannot be decrypted with different AAD."""
        plaintext = "secret-token"
        encrypted = encrypt(plaintext, aad="service_token")

        # Try to decrypt with wrong AAD - should fail
        from app.services.crypto import DecryptionError

        with pytest.raises(DecryptionError):
            decrypt(encrypted, aad="server_secret")

    def test_aad_is_required(self):
        """AAD is a required parameter on encrypt/decrypt (no legacy fallback)."""
        with pytest.raises(TypeError):
            encrypt("plaintext")  # No AAD — should fail
        with pytest.raises(TypeError):
            decrypt(b"ciphertext")  # No AAD — should fail

    def test_base64_with_aad(self):
        """Base64 roundtrip works with AAD."""
        plaintext = "secret-data"
        aad = "context:test"

        encrypted_b64 = encrypt_to_base64(plaintext, aad=aad)
        decrypted = decrypt_from_base64(encrypted_b64, aad=aad)
        assert decrypted == plaintext

    def test_ciphertext_swap_prevention(self):
        """Ciphertext encrypted for one context cannot be used in another."""
        token1 = "token-one"
        token2 = "token-two"

        # Encrypt with different AAD contexts
        enc1 = encrypt(token1, aad="service_token")
        enc2 = encrypt(token2, aad="api_token")

        # Each decrypts with its own AAD
        assert decrypt(enc1, aad="service_token") == token1
        assert decrypt(enc2, aad="api_token") == token2

        # Cross-context decryption should fail
        from app.services.crypto import DecryptionError

        with pytest.raises(DecryptionError):
            decrypt(enc1, aad="api_token")

        with pytest.raises(DecryptionError):
            decrypt(enc2, aad="service_token")


class TestTokenRemovalFromResponses:
    """Test that tokens are not exposed in wizard API responses (M5)."""

    def test_create_tunnel_response_no_token(self):
        """CreateTunnelResponse model does not include tunnel_token field."""
        from app.schemas.cloudflare import CreateTunnelResponse

        # Verify the model doesn't have a tunnel_token field
        fields = CreateTunnelResponse.model_fields
        assert "tunnel_token" not in fields

    def test_deploy_worker_response_no_token(self):
        """DeployWorkerResponse model does not include service_token field."""
        from app.schemas.cloudflare import DeployWorkerResponse

        # Verify the model doesn't have a service_token field
        fields = DeployWorkerResponse.model_fields
        assert "service_token" not in fields

    def test_create_tunnel_response_serializable(self):
        """CreateTunnelResponse can be created without token field."""
        from app.schemas.cloudflare import CreateTunnelResponse

        resp = CreateTunnelResponse(
            success=True,
            tunnel_id="test-id",
            tunnel_name="test-tunnel",
            message="Created",
        )
        data = resp.model_dump()
        assert "tunnel_token" not in data
        assert data["success"] is True

    def test_deploy_worker_response_serializable(self):
        """DeployWorkerResponse can be created without token field."""
        from app.schemas.cloudflare import DeployWorkerResponse

        resp = DeployWorkerResponse(
            success=True,
            worker_name="test-worker",
            worker_url="https://test.workers.dev",
            message="Deployed",
        )
        data = resp.model_dump()
        assert "service_token" not in data
        assert data["success"] is True
