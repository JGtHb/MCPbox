"""Tests for health check endpoints."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import check_postgres_available

# Skip health tests if PostgreSQL is not available since the app requires DB
pytestmark = pytest.mark.skipif(
    not check_postgres_available(), reason="PostgreSQL test database not available"
)


class TestHealthEndpoints:
    """Test suite for health check functionality."""

    def test_health_check_returns_status(self, sync_client: TestClient):
        """Test that health endpoint returns a response."""
        response = sync_client.get("/health")

        # Should return 200 or 503 depending on DB
        assert response.status_code in (200, 503)

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "database" in data

    def test_health_detail_returns_extended_info(self, sync_client: TestClient):
        """Test that health detail endpoint returns extended health info."""
        response = sync_client.get("/health/detail")

        # Should return 200 or 503 depending on DB
        assert response.status_code in (200, 503)

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "database" in data
        assert "sandbox" in data

    def test_health_response_schema(self, sync_client: TestClient):
        """Test that health response matches expected schema."""
        response = sync_client.get("/health")
        data = response.json()

        # Validate status field values
        assert data["status"] in ("healthy", "unhealthy")
        assert data["database"] in ("connected", "disconnected")

        # Version should be a string
        assert isinstance(data["version"], str)
