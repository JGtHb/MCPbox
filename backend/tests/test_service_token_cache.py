"""Tests for ServiceTokenCache singleton."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from app.models.cloudflare_config import CloudflareConfig
from app.services.crypto import encrypt_to_base64
from app.services.service_token_cache import ServiceTokenCache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cloudflare_config_factory(db_session):
    """Factory for creating test CloudflareConfig objects."""

    async def _create_config(
        status: str = "active",
        service_token: str | None = "test-service-token-abc123def456",
        completed_step: int = 7,
    ) -> CloudflareConfig:
        config = CloudflareConfig(
            encrypted_api_token=encrypt_to_base64("fake-api-token", aad="cloudflare_api_token"),
            account_id="test-account-id",
            account_name="Test Account",
            status=status,
            encrypted_service_token=encrypt_to_base64(service_token, aad="service_token")
            if service_token
            else None,
            completed_step=completed_step,
        )
        db_session.add(config)
        await db_session.flush()
        await db_session.refresh(config)
        return config

    return _create_config


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the ServiceTokenCache singleton before each test."""
    cache = ServiceTokenCache.get_instance()
    cache.invalidate()
    yield
    cache.invalidate()


@pytest.fixture(autouse=True)
def patch_session_maker(db_session):
    """Patch async_session_maker in service_token_cache to use the test session.

    The app's global async_session_maker creates sessions on a different event loop
    than the test's event loop. This fixture ensures the cache uses the test session.
    """

    @asynccontextmanager
    async def mock_session_maker():
        yield db_session

    with patch("app.services.service_token_cache.async_session_maker", mock_session_maker):
        yield


class TestServiceTokenCache:
    """Tests for ServiceTokenCache."""

    async def test_load_with_active_config(self, cloudflare_config_factory):
        """Token is loaded from active CloudflareConfig."""
        await cloudflare_config_factory(service_token="my-secret-token")

        cache = ServiceTokenCache.get_instance()
        await cache.load()

        assert cache.token == "my-secret-token"
        assert cache.auth_enabled is True

    async def test_load_with_no_config(self):
        """No config → local-only mode."""
        cache = ServiceTokenCache.get_instance()
        await cache.load()

        assert cache.token is None
        assert cache.auth_enabled is False

    async def test_load_with_pending_config(self, cloudflare_config_factory):
        """Pending config is not picked up — only active."""
        await cloudflare_config_factory(status="pending", service_token="pending-token")

        cache = ServiceTokenCache.get_instance()
        await cache.load()

        assert cache.token is None
        assert cache.auth_enabled is False

    async def test_load_with_no_service_token(self, cloudflare_config_factory):
        """Active config without service token → local-only mode."""
        await cloudflare_config_factory(service_token=None)

        cache = ServiceTokenCache.get_instance()
        await cache.load()

        assert cache.token is None
        assert cache.auth_enabled is False

    async def test_invalidate_clears_token(self, cloudflare_config_factory):
        """invalidate() clears the cached token."""
        await cloudflare_config_factory(service_token="original-token")

        cache = ServiceTokenCache.get_instance()
        await cache.load()
        assert cache.token == "original-token"

        cache.invalidate()
        assert cache.token is None
        assert cache.auth_enabled is False

    async def test_reload_picks_up_new_token(self, db_session, cloudflare_config_factory):
        """invalidate() + load() picks up new token from DB."""
        config = await cloudflare_config_factory(service_token="old-token")

        cache = ServiceTokenCache.get_instance()
        await cache.load()
        assert cache.token == "old-token"

        # Simulate wizard generating a new token
        config.encrypted_service_token = encrypt_to_base64("new-token", aad="service_token")
        await db_session.flush()

        cache.invalidate()
        await cache.load()
        assert cache.token == "new-token"

    async def test_singleton_pattern(self):
        """get_instance() returns the same object."""
        a = ServiceTokenCache.get_instance()
        b = ServiceTokenCache.get_instance()
        assert a is b


class TestServiceTokenCacheFailClosed:
    """Tests for fail-closed behavior on database errors."""

    async def test_db_error_first_load_fails_closed(self):
        """DB error on first load → auth enabled, all denied."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def broken_session():
            raise ConnectionError("Database is down")
            yield  # pragma: no cover

        cache = ServiceTokenCache.get_instance()
        with patch("app.services.service_token_cache.async_session_maker", broken_session):
            await cache.load()

        # Fail-closed: auth is "enabled" but token is None → all requests denied
        assert cache.auth_enabled is True
        assert cache.token is None

    async def test_db_error_retains_previous_token(self, cloudflare_config_factory):
        """DB error after successful load → retains previous token."""
        from contextlib import asynccontextmanager

        await cloudflare_config_factory(service_token="valid-token")

        cache = ServiceTokenCache.get_instance()
        await cache.load()
        assert cache.token == "valid-token"

        @asynccontextmanager
        async def broken_session():
            raise ConnectionError("Database is down")
            yield  # pragma: no cover

        with patch("app.services.service_token_cache.async_session_maker", broken_session):
            await cache.load()

        # Should retain previous token
        assert cache.token == "valid-token"
        assert cache.auth_enabled is True

    async def test_db_recovery_clears_error(self):
        """DB recovery after error → clears error flag."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def broken_session():
            raise ConnectionError("Database is down")
            yield  # pragma: no cover

        cache = ServiceTokenCache.get_instance()
        with patch("app.services.service_token_cache.async_session_maker", broken_session):
            await cache.load()

        assert cache.auth_enabled is True  # fail-closed

        # Now DB recovers (no config → local mode)
        await cache.load()
        assert cache.auth_enabled is False  # back to normal
        assert cache.token is None
