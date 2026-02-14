"""Pytest configuration and fixtures for sandbox tests."""

import asyncio
import os
from typing import Generator
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Generate a valid Fernet key for testing
# Fernet requires a 32-byte key encoded as URL-safe base64
TEST_FERNET_KEY = Fernet.generate_key().decode()

# The test API key - used for authenticating sandbox requests
TEST_API_KEY = "test-sandbox-api-key-for-testing-only"

# Set test environment variables BEFORE any app imports
# A test API key is required (sandbox enforces authentication)
os.environ["SANDBOX_API_KEY"] = TEST_API_KEY
os.environ["MCPBOX_ENCRYPTION_KEY"] = TEST_FERNET_KEY


# --- Authenticated Test Client ---


class AuthenticatedTestClient:
    """Test client wrapper that adds API key header to all requests.

    Use this for testing sandbox endpoints that require authentication.
    """

    def __init__(self, client: TestClient, api_key: str = TEST_API_KEY):
        self._client = client
        self._headers = {"X-API-Key": api_key}

    def post(self, url: str, **kwargs):
        """POST with authentication header."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers)
        return self._client.post(url, headers=headers, **kwargs)

    def get(self, url: str, **kwargs):
        """GET with authentication header."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers)
        return self._client.get(url, headers=headers, **kwargs)

    def put(self, url: str, **kwargs):
        """PUT with authentication header."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers)
        return self._client.put(url, headers=headers, **kwargs)

    def delete(self, url: str, **kwargs):
        """DELETE with authentication header."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers)
        return self._client.delete(url, headers=headers, **kwargs)

    @property
    def raw_client(self) -> TestClient:
        """Access the underlying TestClient for unauthenticated requests."""
        return self._client


@pytest.fixture
def authenticated_client():
    """Create an authenticated test client for sandbox endpoints.

    Patches the auth module's SANDBOX_API_KEY to ensure consistency
    between the client header and server-side validation.

    Usage:
        def test_something(authenticated_client):
            response = authenticated_client.post("/execute", json={...})
            assert response.status_code == 200
    """
    from app.main import app

    with patch("app.auth.SANDBOX_API_KEY", TEST_API_KEY):
        yield AuthenticatedTestClient(TestClient(app))


@pytest.fixture
def unauthenticated_client():
    """Create an unauthenticated test client for testing auth failures.

    Usage:
        def test_missing_auth(unauthenticated_client):
            response = unauthenticated_client.post("/execute", json={...})
            assert response.status_code == 401
    """
    from app.main import app

    with patch("app.auth.SANDBOX_API_KEY", TEST_API_KEY):
        yield TestClient(app)


# --- Event Loop ---


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# --- Registry Fixtures ---


@pytest.fixture
def tool_registry():
    """Fresh tool registry instance for each test."""
    from app.registry import ToolRegistry

    registry = ToolRegistry()
    registry.set_encryption_key(os.environ["MCPBOX_ENCRYPTION_KEY"])
    return registry


@pytest.fixture
def sample_tool_def():
    """Sample tool definition for testing."""
    return {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
        "python_code": 'async def main(city: str) -> dict:\n    response = await http.get(f"https://api.weather.com/v1/weather?q={city}")\n    return response.json()',
    }


@pytest.fixture
def sample_credentials():
    """Sample credentials for testing."""
    return [
        {
            "name": "API_KEY",
            "auth_type": "bearer",
            "value": "test-api-key-12345",
        }
    ]
