"""Pytest configuration and fixtures for backend tests.

PostgreSQL Handling:
- If testcontainers is installed and Docker is available, automatically spins up PostgreSQL
- Otherwise, uses TEST_DATABASE_URL environment variable
- Falls back to skipping DB-dependent tests if neither is available
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Set test environment variables before importing app modules
os.environ["MCPBOX_ENCRYPTION_KEY"] = "0" * 64  # Valid 32-byte key for tests
os.environ["SANDBOX_API_KEY"] = "0" * 32  # Valid sandbox API key for tests
# Set high rate limit for tests to prevent 429 errors
os.environ["RATE_LIMIT_REQUESTS_PER_MINUTE"] = "10000"

# Test admin credentials
TEST_ADMIN_USERNAME = "testadmin"
TEST_ADMIN_PASSWORD = "testpassword123"


# --- PostgreSQL Container Management ---

_container = None
_pg_available = None
_database_url = None


def _try_testcontainers() -> str | None:
    """Try to start PostgreSQL using testcontainers.

    Returns database URL if successful, None otherwise.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None

    try:
        global _container
        # Start PostgreSQL container with asyncpg-compatible settings
        _container = PostgresContainer(
            image="postgres:15-alpine",
            username="test",
            password="test",
            dbname="mcpbox_test",
        )
        _container.start()

        # Get connection URL and convert to asyncpg format
        url = _container.get_connection_url()
        # Convert postgresql:// or postgresql+psycopg2:// to postgresql+asyncpg://
        async_url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
        return async_url
    except Exception as e:
        # Docker not available or other error
        import warnings

        warnings.warn(f"Testcontainers not available: {e}", stacklevel=2)
        if _container:
            try:
                _container.stop()
            except Exception:
                pass
            _container = None
        return None


def _get_database_url() -> str:
    """Get database URL, preferring testcontainers if available."""
    global _database_url

    if _database_url is not None:
        return _database_url

    # First, check for explicit TEST_DATABASE_URL
    explicit_url = os.environ.get("TEST_DATABASE_URL")
    if explicit_url:
        _database_url = explicit_url
        return _database_url

    # Try testcontainers
    container_url = _try_testcontainers()
    if container_url:
        _database_url = container_url
        return _database_url

    # Fall back to default local PostgreSQL
    _database_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/mcpbox_test"
    return _database_url


# Set DATABASE_URL for app imports
os.environ["DATABASE_URL"] = _get_database_url()


def pytest_sessionfinish(session, exitstatus):
    """Clean up testcontainers when tests finish."""
    global _container
    if _container:
        try:
            _container.stop()
        except Exception:
            pass
        _container = None


# --- Async Event Loop ---


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# --- Circuit Breaker Reset Fixture ---


def _reset_circuit_breaker_state():
    """Reset all circuit breakers for tests.

    This ensures circuit breakers don't remain open between tests,
    which would cause cascading failures when sandbox calls fail.

    Uses direct state reset instead of async reset_all() since
    test fixtures are synchronous and don't need lock protection.
    """
    from app.core.retry import CircuitBreaker, CircuitBreakerState

    for cb in CircuitBreaker._instances.values():
        cb._state = CircuitBreakerState()


@pytest.fixture(autouse=True)
def reset_circuit_breakers(request):
    """Reset circuit breakers before each test.

    This is an autouse fixture that runs before every test to ensure
    clean circuit breaker state.

    Tests marked with pytest.mark.skip_circuit_breaker_reset will skip this.
    """
    if request.node.get_closest_marker("skip_circuit_breaker_reset"):
        yield
        return

    _reset_circuit_breaker_state()
    yield
    _reset_circuit_breaker_state()


# --- Rate Limiter Reset Fixture ---


def _reset_rate_limiter_state():
    """Reset rate limiter state for tests.

    IMPORTANT: The RateLimitMiddleware caches the RateLimiter instance at init time.
    We CANNOT replace the singleton - we must clear the buckets on the existing instance.
    Setting _instance = None would leave the middleware with a stale reference.

    We also must NOT reset the _lock since check_rate_limit uses it as an async context
    manager. The lock is fine to reuse - we just need to clear the rate limit data.

    For tests, we also increase the default path limits to avoid 429s during test runs.
    """
    from app.middleware.rate_limit import PathRateLimitConfig, RateLimiter

    # Get the singleton (creates one if needed)
    rate_limiter = RateLimiter.get_instance()

    # Clear the buckets - this is what the middleware references
    rate_limiter._buckets.clear()

    # Override path configs with very high limits for tests
    # This prevents 429 errors during test runs
    test_config = PathRateLimitConfig(
        requests_per_minute=10000,
        requests_per_hour=100000,
        burst_size=1000,
    )
    rate_limiter._path_configs = {
        "/health": test_config,
        "/mcp/health": test_config,
        "/api/tools/": test_config,
        "/mcp": test_config,
    }
    rate_limiter._default_config = test_config


def _reset_auth_rate_limiter_state():
    """Reset auth failure rate limiter state for tests.

    The auth_simple module tracks failed auth attempts per IP in a module-level dict.
    Without resetting this between tests, failures from earlier test modules accumulate
    and cause subsequent MCP gateway tests to get 429 errors.
    """
    from app.api.auth_simple import _failed_auth_attempts

    _failed_auth_attempts.clear()


def _reset_service_token_cache():
    """Reset ServiceTokenCache to local mode for tests.

    Ensures the singleton is in a clean "no token loaded" state (local mode),
    so MCP gateway tests that expect local mode aren't affected by CloudflareConfig
    rows created by other test modules (e.g., test_cloudflare.py).

    IMPORTANT: Set _last_loaded to current time so _refresh_if_stale() does NOT
    trigger a DB reload (which would find CloudflareConfig rows from other tests).
    """
    import time

    from app.services.service_token_cache import ServiceTokenCache

    cache = ServiceTokenCache.get_instance()
    cache._token = None
    cache._db_error = False
    cache._decryption_error = False
    cache._last_loaded = time.monotonic()  # Prevent stale refresh from re-loading


@pytest.fixture(autouse=True)
def reset_rate_limiter(request):
    """Reset rate limiter before each test to avoid 429 errors.

    This is an autouse fixture that runs before every test to ensure
    clean rate limiter state. Resets both:
    - Middleware rate limiter (requests per minute/hour)
    - Auth failure rate limiter (failed auth attempts per IP)
    - ServiceTokenCache (ensures local mode unless test explicitly mocks it)

    Tests marked with pytest.mark.skip_rate_limiter_reset will skip this
    fixture (useful for config tests that reload the config module).
    """
    # Skip for tests that reload config (they conflict with app module imports)
    if request.node.get_closest_marker("skip_rate_limiter_reset"):
        yield
        return

    _reset_rate_limiter_state()
    _reset_auth_rate_limiter_state()
    _reset_service_token_cache()
    yield
    _reset_rate_limiter_state()
    _reset_auth_rate_limiter_state()
    _reset_service_token_cache()


# --- Database Fixtures ---


def check_postgres_available() -> bool:
    """Check if PostgreSQL test database is available."""
    global _pg_available
    if _pg_available is not None:
        return _pg_available

    from sqlalchemy import text

    async def _check():
        try:
            engine = create_async_engine(_get_database_url(), poolclass=NullPool)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return True
        except Exception as e:
            import warnings

            warnings.warn(f"PostgreSQL not available: {e}", stacklevel=2)
            return False

    try:
        _pg_available = asyncio.get_event_loop().run_until_complete(_check())
    except RuntimeError:
        # No event loop available, create one
        _pg_available = asyncio.run(_check())

    return _pg_available


# Skip marker for tests requiring PostgreSQL
requires_postgres = pytest.mark.skipif(
    not check_postgres_available(), reason="PostgreSQL test database not available"
)


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a PostgreSQL database engine for testing.

    Requires PostgreSQL due to use of PostgreSQL-specific types (ARRAY, JSONB).
    """
    if not check_postgres_available():
        pytest.skip("PostgreSQL test database not available")

    from app.models.base import BaseModel

    engine = create_async_engine(
        _get_database_url(),
        poolclass=NullPool,
        echo=False,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

    yield engine

    # Drop all tables after test
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for testing."""
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with database override."""
    from app.core.database import get_db
    from app.main import app

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Reset rate limiter and auth state to ensure clean state for each test
    _reset_rate_limiter_state()
    _reset_auth_rate_limiter_state()
    _reset_service_token_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Clean up
    app.dependency_overrides.clear()
    # Reset rate limiter and auth state after test
    _reset_rate_limiter_state()
    _reset_auth_rate_limiter_state()
    _reset_service_token_cache()


@pytest.fixture(scope="module")
def sync_client() -> Generator[TestClient, None, None]:
    """Create a synchronous test client for simple tests.

    Note: This client won't have database override.
    Use for testing endpoints that don't require database.
    """
    if not check_postgres_available():
        pytest.skip("PostgreSQL test database not available")

    from app.main import app

    # Reset rate limiter and auth state before tests
    _reset_rate_limiter_state()
    _reset_auth_rate_limiter_state()
    _reset_service_token_cache()

    with TestClient(app) as client:
        yield client

    # Reset rate limiter and auth state after tests
    _reset_rate_limiter_state()
    _reset_auth_rate_limiter_state()
    _reset_service_token_cache()


# --- Test Factories ---


@pytest.fixture
def server_factory(db_session):
    """Factory for creating test Server objects."""
    from app.models.server import Server

    async def _create_server(
        name: str = "Test Server",
        description: str = "A test server",
        status: str = "imported",
        **kwargs,
    ) -> Server:
        server = Server(
            name=name,
            description=description,
            status=status,
            **kwargs,
        )
        db_session.add(server)
        await db_session.flush()
        await db_session.refresh(server)
        return server

    return _create_server


@pytest.fixture
def tool_factory(db_session, server_factory):
    """Factory for creating test Tool objects."""
    from app.models.tool import Tool
    from app.models.tool_version import ToolVersion

    async def _create_tool(
        server=None,
        name: str = "test_tool",
        description: str = "A test tool",
        input_schema: dict = None,
        enabled: bool = True,
        timeout_ms: int = None,
        python_code: str = None,
        approval_status: str = "approved",
        create_version: bool = True,
        **kwargs,
    ) -> Tool:
        if server is None:
            server = await server_factory()

        if input_schema is None:
            input_schema = {
                "type": "object",
                "properties": {},
            }

        if python_code is None:
            python_code = 'async def main() -> str:\n    return "test"'

        tool = Tool(
            server_id=server.id,
            name=name,
            description=description,
            input_schema=input_schema,
            enabled=enabled,
            timeout_ms=timeout_ms,
            python_code=python_code,
            approval_status=approval_status,
            current_version=1,
            **kwargs,
        )
        db_session.add(tool)
        await db_session.flush()
        await db_session.refresh(tool)

        # Create initial version entry (mirrors ToolService.create behavior)
        if create_version:
            version = ToolVersion(
                tool_id=tool.id,
                version_number=1,
                name=name,
                description=description,
                enabled=enabled,
                timeout_ms=timeout_ms,
                python_code=python_code,
                input_schema=input_schema,
                change_summary="Initial version",
                change_source="test",
            )
            db_session.add(version)
            await db_session.flush()

        return tool

    return _create_tool


# --- Sample Data Fixtures ---


@pytest.fixture
def sample_server_data() -> dict[str, Any]:
    """Sample server data for testing."""
    return {
        "name": "test_server",
        "description": "A test MCP server",
        "base_url": "https://api.example.com",
    }


@pytest.fixture
def sample_tool_data() -> dict[str, Any]:
    """Sample tool data for testing."""
    return {
        "name": "test_tool",
        "description": "A test tool",
        "python_code": 'async def main() -> str:\n    return "test"',
    }


# --- Mock Fixtures ---


@pytest.fixture
def mock_sandbox_client():
    """Mock sandbox client for testing without actual sandbox service.

    Patches SandboxClient in both its home module and in approvals.py
    (which imports the name directly), so that get_instance() returns
    the same mock regardless of call-site.
    """
    with (
        patch("app.services.sandbox_client.SandboxClient") as mock_orig,
        patch("app.api.approvals.SandboxClient") as mock_approvals,
    ):
        client_instance = MagicMock()
        client_instance.health_check.return_value = True
        client_instance.register_server = AsyncMock(
            return_value={"success": True, "tools_registered": 1}
        )
        client_instance.unregister_server.return_value = {"success": True}
        client_instance.list_tools.return_value = []
        client_instance.install_package = AsyncMock(
            return_value={"status": "installed", "package_name": "test", "version": "1.0"}
        )
        client_instance.sync_packages = AsyncMock(return_value={"synced": 0, "errors": []})
        mock_orig.get_instance.return_value = client_instance
        mock_approvals.get_instance.return_value = client_instance
        yield client_instance


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singleton caches between tests to prevent cross-test pollution.

    EmailPolicyCache and ServiceTokenCache are singletons that retain state
    across tests. When a test runs that initialises the singleton without
    a database (e.g. MCP gateway remote-mode tests), the singleton enters
    a "fail-closed" state and poisons all subsequent tests in the suite.
    """
    yield
    # Tear down: reset singletons after each test
    from app.services.email_policy_cache import EmailPolicyCache
    from app.services.service_token_cache import ServiceTokenCache

    EmailPolicyCache._instance = None
    ServiceTokenCache._instance = None


@pytest.fixture
def mock_tunnel_service():
    """Mock tunnel service for testing."""
    with patch("app.services.tunnel.TunnelService") as mock:
        service_instance = MagicMock()
        service_instance.status = "disconnected"
        mock.get_instance.return_value = service_instance
        yield service_instance


# --- Pytest Hooks for Auto-Marking ---


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests based on their fixtures and location.

    - Tests using db_session, db_engine, or async_client are marked as 'integration'
    - Tests in tests/unit/ are marked as 'unit'
    - Tests can override with explicit markers
    """
    integration_fixtures = {"db_session", "db_engine", "async_client", "sync_client"}

    for item in items:
        # Skip if already explicitly marked
        if any(mark.name in ("unit", "integration") for mark in item.iter_markers()):
            continue

        # Check fixture usage
        if hasattr(item, "fixturenames"):
            if integration_fixtures & set(item.fixturenames):
                item.add_marker(pytest.mark.integration)
                continue

        # Check path for unit tests
        if "/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        else:
            # Default: mark as unit if no DB fixtures used
            item.add_marker(pytest.mark.unit)


# --- Admin Auth Helpers ---


@pytest.fixture
def admin_user_factory(db_session):
    """Factory for creating test admin users."""
    from app.models.admin_user import AdminUser
    from app.services.auth import hash_password

    async def _create_admin_user(
        username: str = TEST_ADMIN_USERNAME,
        password: str = TEST_ADMIN_PASSWORD,
    ) -> AdminUser:
        user = AdminUser(
            username=username,
            password_hash=hash_password(password),
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        return user

    return _create_admin_user


@pytest_asyncio.fixture
async def admin_user(admin_user_factory):
    """Create a test admin user."""
    return await admin_user_factory()


@pytest_asyncio.fixture
async def auth_tokens(admin_user):
    """Get auth tokens for the test admin user."""
    from app.services.auth import create_access_token, create_refresh_token

    return {
        "access_token": create_access_token(admin_user.id, admin_user.password_version),
        "refresh_token": create_refresh_token(admin_user.id, admin_user.password_version),
    }


@pytest_asyncio.fixture
async def admin_headers(auth_tokens) -> dict[str, str]:
    """Headers with JWT token for authenticated requests."""
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}
