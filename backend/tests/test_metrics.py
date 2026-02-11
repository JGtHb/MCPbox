"""Tests for Prometheus metrics endpoint."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Get test client with fresh app instance."""
    from app.main import app

    return TestClient(app)


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    def test_metrics_endpoint_returns_prometheus_format(self, client):
        """Test that /metrics returns Prometheus text format."""
        response = client.get("/metrics")
        assert response.status_code == 200
        # Prometheus text format contains TYPE and HELP comments
        assert "http_request" in response.text or "HELP" in response.text

    def test_metrics_endpoint_no_auth_required(self, client):
        """Test that /metrics does not require admin auth."""
        response = client.get("/metrics")
        # Should not return 401
        assert response.status_code != 401
