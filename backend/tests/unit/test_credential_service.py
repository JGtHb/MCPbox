"""Unit tests for CredentialService business logic."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.schemas.credential import CredentialCreate, CredentialUpdate
from app.services.credential import CredentialEncryptionError, CredentialService

pytestmark = pytest.mark.asyncio


class TestCredentialServiceCreate:
    """Tests for CredentialService.create()."""

    async def test_create_api_key_header_credential(self, db_session, server_factory):
        """Create an api_key_header credential with encrypted value."""
        server = await server_factory()
        service = CredentialService(db_session)

        data = CredentialCreate(
            name="API_KEY",
            description="Test API key",
            auth_type="api_key_header",
            header_name="X-API-Key",
            value="secret-api-key-12345",
        )

        credential = await service.create(server.id, data)

        assert credential.name == "API_KEY"
        assert credential.description == "Test API key"
        assert credential.auth_type == "api_key_header"
        assert credential.header_name == "X-API-Key"
        assert credential.encrypted_value is not None
        # Value should be encrypted (not plaintext)
        assert credential.encrypted_value != b"secret-api-key-12345"

    async def test_create_api_key_query_credential(self, db_session, server_factory):
        """Create an api_key_query credential."""
        server = await server_factory()
        service = CredentialService(db_session)

        data = CredentialCreate(
            name="TOKEN",
            auth_type="api_key_query",
            query_param_name="api_token",
            value="query-token-value",
        )

        credential = await service.create(server.id, data)

        assert credential.auth_type == "api_key_query"
        assert credential.query_param_name == "api_token"

    async def test_create_basic_auth_credential(self, db_session, server_factory):
        """Create a basic auth credential with username and password."""
        server = await server_factory()
        service = CredentialService(db_session)

        data = CredentialCreate(
            name="BASIC_AUTH",
            auth_type="basic",
            username="admin",
            password="secret123",
        )

        credential = await service.create(server.id, data)

        assert credential.auth_type == "basic"
        assert credential.encrypted_username is not None
        assert credential.encrypted_password is not None

    async def test_create_oauth2_credential(self, db_session, server_factory):
        """Create an OAuth2 credential."""
        server = await server_factory()
        service = CredentialService(db_session)

        data = CredentialCreate(
            name="GITHUB_OAUTH",
            auth_type="oauth2",
            oauth_client_id="client-id-123",
            oauth_client_secret="client-secret-456",
            oauth_token_url="https://github.com/login/oauth/access_token",
            oauth_authorization_url="https://github.com/login/oauth/authorize",
            oauth_scopes=["read:user", "repo"],
            oauth_grant_type="authorization_code",
        )

        credential = await service.create(server.id, data)

        assert credential.auth_type == "oauth2"
        assert credential.oauth_client_id == "client-id-123"
        assert credential.oauth_client_secret is not None  # Encrypted
        assert credential.oauth_scopes == ["read:user", "repo"]
        assert credential.oauth_grant_type == "authorization_code"

    async def test_create_credential_with_tokens(self, db_session, server_factory):
        """Create a credential with pre-existing access/refresh tokens."""
        server = await server_factory()
        service = CredentialService(db_session)

        data = CredentialCreate(
            name="BEARER",
            auth_type="bearer",
            value="existing-bearer-token",
        )

        credential = await service.create(server.id, data)

        assert credential.auth_type == "bearer"
        assert credential.encrypted_value is not None

    async def test_create_credential_encryption_failure(self, db_session, server_factory):
        """Create raises CredentialEncryptionError on encryption failure."""
        server = await server_factory()
        service = CredentialService(db_session)

        data = CredentialCreate(
            name="BROKEN",
            auth_type="api_key_header",
            header_name="X-Key",
            value="test-value",
        )

        with patch("app.services.credential.encrypt", side_effect=Exception("Encryption failed")):
            with pytest.raises(CredentialEncryptionError) as exc_info:
                await service.create(server.id, data)

            assert "Failed to encrypt credential" in str(exc_info.value)


class TestCredentialServiceGet:
    """Tests for CredentialService.get()."""

    async def test_get_existing_credential(self, db_session, credential_factory):
        """Get an existing credential by ID."""
        credential = await credential_factory(name="TEST_KEY")
        service = CredentialService(db_session)

        result = await service.get(credential.id)

        assert result is not None
        assert result.id == credential.id
        assert result.name == "TEST_KEY"

    async def test_get_nonexistent_credential(self, db_session):
        """Get non-existent credential returns None."""
        service = CredentialService(db_session)

        result = await service.get(uuid4())

        assert result is None


class TestCredentialServiceListByServer:
    """Tests for CredentialService.list_by_server()."""

    async def test_list_credentials_for_server(
        self, db_session, server_factory, credential_factory
    ):
        """List credentials belonging to a specific server."""
        server1 = await server_factory(name="Server 1")
        server2 = await server_factory(name="Server 2")

        await credential_factory(server=server1, name="KEY1")
        await credential_factory(server=server1, name="KEY2")
        await credential_factory(server=server2, name="KEY3")

        service = CredentialService(db_session)
        credentials, total = await service.list_by_server(server1.id)

        assert total == 2
        assert len(credentials) == 2
        assert all(c.server_id == server1.id for c in credentials)

    async def test_list_credentials_pagination(
        self, db_session, server_factory, credential_factory
    ):
        """List credentials respects pagination parameters."""
        server = await server_factory()
        for i in range(10):
            await credential_factory(server=server, name=f"KEY_{i}")

        service = CredentialService(db_session)

        # First page
        credentials, total = await service.list_by_server(server.id, page=1, page_size=3)
        assert total == 10
        assert len(credentials) == 3

        # Second page
        credentials2, _ = await service.list_by_server(server.id, page=2, page_size=3)
        assert len(credentials2) == 3
        # Should be different credentials
        assert credentials[0].id != credentials2[0].id

    async def test_list_credentials_empty_server(self, db_session, server_factory):
        """List credentials for server with no credentials."""
        server = await server_factory()
        service = CredentialService(db_session)

        credentials, total = await service.list_by_server(server.id)

        assert total == 0
        assert credentials == []


class TestCredentialServiceUpdate:
    """Tests for CredentialService.update()."""

    async def test_update_credential_name(self, db_session, credential_factory):
        """Update credential name."""
        credential = await credential_factory(name="OLD_NAME", description="Old desc")
        service = CredentialService(db_session)

        updated = await service.update(
            credential.id,
            CredentialUpdate(name="NEW_NAME"),
        )

        assert updated.name == "NEW_NAME"
        assert updated.description == "Old desc"  # Unchanged

    async def test_update_credential_description(self, db_session, credential_factory):
        """Update credential description."""
        credential = await credential_factory(description="Old description")
        service = CredentialService(db_session)

        updated = await service.update(
            credential.id,
            CredentialUpdate(description="New description"),
        )

        assert updated.description == "New description"

    async def test_update_encrypted_fields(self, db_session, credential_factory):
        """Update encrypted fields re-encrypts values."""
        credential = await credential_factory()
        old_value = credential.encrypted_value
        service = CredentialService(db_session)

        updated = await service.update(
            credential.id,
            CredentialUpdate(value="new-secret-value"),
        )

        assert updated.encrypted_value is not None
        assert updated.encrypted_value != old_value

    async def test_update_nonexistent_credential(self, db_session):
        """Update non-existent credential returns None."""
        service = CredentialService(db_session)

        result = await service.update(
            uuid4(),
            CredentialUpdate(name="test"),
        )

        assert result is None

    async def test_update_credential_encryption_failure(self, db_session, credential_factory):
        """Update raises CredentialEncryptionError on encryption failure."""
        credential = await credential_factory()
        service = CredentialService(db_session)

        with patch("app.services.credential.encrypt", side_effect=Exception("Encryption failed")):
            with pytest.raises(CredentialEncryptionError) as exc_info:
                await service.update(
                    credential.id,
                    CredentialUpdate(value="new-value"),
                )

            assert "Failed to encrypt credential update" in str(exc_info.value)


class TestCredentialServiceDelete:
    """Tests for CredentialService.delete()."""

    async def test_delete_existing_credential(self, db_session, credential_factory):
        """Delete an existing credential."""
        credential = await credential_factory()
        credential_id = credential.id
        service = CredentialService(db_session)

        result = await service.delete(credential_id)

        assert result is True
        assert await service.get(credential_id) is None

    async def test_delete_nonexistent_credential(self, db_session):
        """Delete non-existent credential returns False."""
        service = CredentialService(db_session)

        result = await service.delete(uuid4())

        assert result is False


class TestCredentialServiceForInjection:
    """Tests for CredentialService.get_for_injection()."""

    async def test_get_for_injection_decrypts_values(self, db_session, server_factory):
        """Get for injection returns decrypted credential values."""
        server = await server_factory()
        service = CredentialService(db_session)

        # Create credential with encrypted value
        data = CredentialCreate(
            name="API_KEY",
            auth_type="api_key_header",
            header_name="X-API-Key",
            value="secret-value-123",
        )
        await service.create(server.id, data)

        # Get for injection
        injections = await service.get_for_injection(server.id)

        assert len(injections) == 1
        assert injections[0].name == "API_KEY"
        assert injections[0].value == "secret-value-123"  # Decrypted

    async def test_get_for_injection_multiple_credentials(self, db_session, server_factory):
        """Get for injection returns all server credentials."""
        server = await server_factory()
        service = CredentialService(db_session)

        await service.create(
            server.id,
            CredentialCreate(
                name="KEY1", auth_type="api_key_header", header_name="X-Key1", value="val1"
            ),
        )
        await service.create(
            server.id,
            CredentialCreate(
                name="BASIC",
                auth_type="basic",
                username="user",
                password="pass",
            ),
        )

        injections = await service.get_for_injection(server.id)

        assert len(injections) == 2
        names = {i.name for i in injections}
        assert names == {"KEY1", "BASIC"}

    async def test_get_for_injection_decryption_failure_returns_none(
        self, db_session, credential_factory
    ):
        """Decryption failure for one credential returns None for that value."""
        credential = await credential_factory(name="BAD_KEY")
        server_id = credential.server_id
        service = CredentialService(db_session)

        with patch("app.services.credential.decrypt", side_effect=Exception("Decryption failed")):
            injections = await service.get_for_injection(server_id)

            assert len(injections) == 1
            assert injections[0].value is None  # Failed to decrypt


class TestDecryptIfPresent:
    """Tests for CredentialService._decrypt_if_present()."""

    async def test_decrypt_if_present_with_value(self, db_session):
        """Decrypt present encrypted value."""
        service = CredentialService(db_session)

        # Need to encrypt something first
        from app.services.crypto import encrypt

        encrypted = encrypt("test-value")
        result = service._decrypt_if_present(encrypted)

        assert result == "test-value"

    async def test_decrypt_if_present_none(self, db_session):
        """Decrypt None returns None."""
        service = CredentialService(db_session)

        result = service._decrypt_if_present(None)

        assert result is None

    async def test_decrypt_if_present_failure(self, db_session):
        """Decrypt failure returns None (logs warning)."""
        service = CredentialService(db_session)

        with patch("app.services.credential.decrypt", side_effect=Exception("Bad key")):
            result = service._decrypt_if_present(b"invalid-data")

            assert result is None
