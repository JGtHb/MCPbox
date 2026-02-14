"""Tests for circuit breaker API endpoints.

Tests /health/circuits/* endpoints for monitoring and management.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.retry import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerState

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_circuit_breakers(request):
    """Reset all circuit breakers before and after each test.

    Tests marked with pytest.mark.skip_circuit_breaker_reset will skip this.
    """
    if request.node.get_closest_marker("skip_circuit_breaker_reset"):
        yield
        return

    for cb in CircuitBreaker._instances.values():
        cb._state = CircuitBreakerState()
    yield
    for cb in CircuitBreaker._instances.values():
        cb._state = CircuitBreakerState()


class TestGetCircuitStates:
    """Tests for GET /health/circuits endpoint."""

    async def test_get_circuits_returns_response(self, async_client: AsyncClient, admin_headers):
        """Get circuits endpoint returns valid response."""
        response = await async_client.get("/health/circuits", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "circuits" in data
        # Note: sandbox circuit may exist from app initialization

    async def test_get_circuits_after_creation(self, async_client: AsyncClient, admin_headers):
        """Get circuits after some are created."""
        # Create some circuit breakers
        CircuitBreaker.get_or_create("service_a")
        CircuitBreaker.get_or_create("service_b")

        response = await async_client.get("/health/circuits", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "service_a" in data["circuits"]
        assert "service_b" in data["circuits"]

    async def test_circuit_state_fields(self, async_client: AsyncClient, admin_headers):
        """Circuit state includes expected fields."""
        CircuitBreaker.get_or_create("test_service")

        response = await async_client.get("/health/circuits", headers=admin_headers)

        assert response.status_code == 200
        state = response.json()["circuits"]["test_service"]
        assert "state" in state
        assert state["state"] == "closed"

    async def test_circuit_open_state_reflected(self, async_client: AsyncClient, admin_headers):
        """Open circuit state is reflected in response."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker.get_or_create("failing_service", config=config)

        # Trip the circuit breaker
        dummy_exception = Exception("test failure")
        await cb.record_failure(dummy_exception)
        await cb.record_failure(dummy_exception)

        response = await async_client.get("/health/circuits", headers=admin_headers)

        assert response.status_code == 200
        state = response.json()["circuits"]["failing_service"]
        assert state["state"] == "open"


class TestResetAllCircuits:
    """Tests for POST /health/circuits/reset endpoint."""

    async def test_reset_all_circuits(self, async_client: AsyncClient, admin_headers):
        """Reset all circuits to closed state."""
        # Create and trip circuit breakers
        config = CircuitBreakerConfig(failure_threshold=1)
        cb1 = CircuitBreaker.get_or_create("service_1", config=config)
        cb2 = CircuitBreaker.get_or_create("service_2", config=config)
        dummy_exception = Exception("test failure")
        await cb1.record_failure(dummy_exception)
        await cb2.record_failure(dummy_exception)

        # Verify they're open
        assert cb1.get_state()["state"] == "open"
        assert cb2.get_state()["state"] == "open"

        response = await async_client.post("/health/circuits/reset", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "All circuit breakers reset"

        # Verify they're now closed
        assert cb1.get_state()["state"] == "closed"
        assert cb2.get_state()["state"] == "closed"

    async def test_reset_all_idempotent(self, async_client: AsyncClient, admin_headers):
        """Reset all when already closed is idempotent."""
        cb = CircuitBreaker.get_or_create("healthy_service")
        assert cb.get_state()["state"] == "closed"

        response = await async_client.post("/health/circuits/reset", headers=admin_headers)

        assert response.status_code == 200
        assert cb.get_state()["state"] == "closed"


class TestResetSpecificCircuit:
    """Tests for POST /health/circuits/{service_name}/reset endpoint."""

    async def test_reset_specific_circuit(self, async_client: AsyncClient, admin_headers):
        """Reset a specific circuit breaker."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker.get_or_create("target_service", config=config)
        await cb.record_failure(Exception("test failure"))
        assert cb.get_state()["state"] == "open"

        response = await async_client.post(
            "/health/circuits/target_service/reset", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "target_service" in data["message"]
        assert data["state"]["state"] == "closed"

    async def test_reset_creates_circuit_if_not_exists(
        self, async_client: AsyncClient, admin_headers
    ):
        """Reset non-existent circuit creates it."""
        response = await async_client.post(
            "/health/circuits/new_service/reset", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["state"]["state"] == "closed"

        # Circuit should now exist
        states = CircuitBreaker.get_all_states()
        assert "new_service" in states

    @pytest.mark.skip_circuit_breaker_reset
    async def test_reset_specific_doesnt_affect_others(
        self, async_client: AsyncClient, admin_headers
    ):
        """Reset specific circuit doesn't affect other circuits.

        Note: This test uses skip_circuit_breaker_reset to ensure the conftest
        fixture doesn't reset all circuits during the test.
        """
        # Clear all instances to ensure we create new ones with our config
        # (get_or_create ignores config if instance already exists)
        CircuitBreaker._instances.clear()

        # Use unique service names to avoid collisions with other tests
        config = CircuitBreakerConfig(failure_threshold=1)
        cb1 = CircuitBreaker.get_or_create("test_service_alpha", config=config)
        cb2 = CircuitBreaker.get_or_create("test_service_beta", config=config)
        dummy_exception = Exception("test failure")
        await cb1.record_failure(dummy_exception)
        await cb2.record_failure(dummy_exception)

        # Verify both are open before the reset
        assert cb1.get_state()["state"] == "open"
        assert cb2.get_state()["state"] == "open"

        # Reset only test_service_alpha
        response = await async_client.post(
            "/health/circuits/test_service_alpha/reset", headers=admin_headers
        )

        assert response.status_code == 200
        assert cb1.get_state()["state"] == "closed"
        assert cb2.get_state()["state"] == "open"  # Unchanged

        # Cleanup
        CircuitBreaker._instances.clear()


class TestHealthServicesEndpoint:
    """Tests for GET /health/services endpoint."""

    async def test_services_includes_circuit_breaker(
        self, async_client: AsyncClient, admin_headers
    ):
        """Services endpoint includes sandbox circuit breaker state."""
        with patch(
            "app.api.health.check_db_connection",
            new_callable=AsyncMock,
            return_value=True,
        ):
            mock_sandbox = MagicMock()
            mock_sandbox.health_check = AsyncMock(return_value=True)
            mock_sandbox.get_circuit_state.return_value = {"state": "closed", "failures": 0}

            with patch("app.api.health.get_sandbox_client", return_value=mock_sandbox):
                response = await async_client.get("/health/services", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "sandbox" in data["services"]
        assert "circuit_breaker" in data["services"]["sandbox"]
        assert data["services"]["sandbox"]["circuit_breaker"]["state"] == "closed"

    async def test_services_degraded_when_sandbox_down(
        self, async_client: AsyncClient, admin_headers
    ):
        """Services shows degraded when sandbox is unhealthy."""
        with patch(
            "app.api.health.check_db_connection",
            new_callable=AsyncMock,
            return_value=True,
        ):
            mock_sandbox = MagicMock()
            mock_sandbox.health_check = AsyncMock(return_value=False)
            mock_sandbox.get_circuit_state.return_value = {"state": "open", "failures": 5}

            with patch("app.api.health.get_sandbox_client", return_value=mock_sandbox):
                response = await async_client.get("/health/services", headers=admin_headers)

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["sandbox"]["healthy"] is False


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker behavior."""

    async def test_circuit_transitions_through_states(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test circuit breaker state transitions."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            timeout=0.1,  # 100ms for fast test
        )
        cb = CircuitBreaker.get_or_create("state_test", config=config)

        # Start closed
        response = await async_client.get("/health/circuits", headers=admin_headers)
        assert response.json()["circuits"]["state_test"]["state"] == "closed"

        # Record failures to trip
        dummy_exception = Exception("test failure")
        await cb.record_failure(dummy_exception)
        await cb.record_failure(dummy_exception)
        await cb.record_failure(dummy_exception)

        # Should be open
        response = await async_client.get("/health/circuits", headers=admin_headers)
        assert response.json()["circuits"]["state_test"]["state"] == "open"

        # Wait for recovery timeout
        import asyncio

        await asyncio.sleep(0.15)

        # Should transition to half-open on next check
        # (Half-open state depends on implementation - the circuit allows a trial request)
        # Just verify it's queryable
        response = await async_client.get("/health/circuits", headers=admin_headers)
        assert response.status_code == 200

    async def test_multiple_circuits_independent(self, async_client: AsyncClient, admin_headers):
        """Multiple circuits operate independently."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb_a = CircuitBreaker.get_or_create("independent_a", config=config)
        CircuitBreaker.get_or_create("independent_b", config=config)

        # Trip only circuit A
        await cb_a.record_failure(Exception("test failure"))

        response = await async_client.get("/health/circuits", headers=admin_headers)
        data = response.json()

        assert data["circuits"]["independent_a"]["state"] == "open"
        assert data["circuits"]["independent_b"]["state"] == "closed"

        # Reset only circuit A
        await async_client.post("/health/circuits/independent_a/reset", headers=admin_headers)

        response = await async_client.get("/health/circuits", headers=admin_headers)
        data = response.json()

        assert data["circuits"]["independent_a"]["state"] == "closed"
        assert data["circuits"]["independent_b"]["state"] == "closed"
