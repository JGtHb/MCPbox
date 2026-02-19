"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient

from tests.conftest import check_postgres_available

# Skip health tests if PostgreSQL is not available since the app requires DB
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not check_postgres_available(), reason="PostgreSQL test database not available"
    ),
]


class TestHealthEndpoints:
    """Test suite for health check functionality."""

    async def test_health_check_returns_status(self, async_client: AsyncClient):
        """Test that health endpoint returns a response."""
        response = await async_client.get("/health")

        # Should return 200 or 503 depending on DB
        assert response.status_code in (200, 503)

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "database" in data

    async def test_health_detail_returns_extended_info(self, async_client: AsyncClient):
        """Test that health detail endpoint returns extended health info."""
        response = await async_client.get("/health/detail")

        # Should return 200 or 503 depending on DB
        assert response.status_code in (200, 503)

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "database" in data
        assert "sandbox" in data

    async def test_health_response_schema(self, async_client: AsyncClient):
        """Test that health response matches expected schema."""
        response = await async_client.get("/health")
        data = response.json()

        # Validate status field values
        assert data["status"] in ("healthy", "unhealthy")
        assert data["database"] in ("connected", "disconnected")

        # Version should be a string
        assert isinstance(data["version"], str)
