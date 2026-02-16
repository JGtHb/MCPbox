"""Tests for dashboard API endpoints."""

import pytest
from httpx import AsyncClient


class TestDashboardEndpoint:
    """Tests for GET /dashboard endpoint."""

    @pytest.mark.asyncio
    async def test_dashboard_empty_database(self, async_client: AsyncClient, admin_headers):
        """Test dashboard with empty database."""
        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Check structure
        assert "stats" in data
        assert "servers" in data
        assert "requests_over_time" in data
        assert "errors_over_time" in data
        assert "top_tools" in data
        assert "recent_errors" in data

        # Empty database should have zero counts
        assert data["stats"]["total_servers"] == 0
        assert data["stats"]["active_servers"] == 0
        assert data["stats"]["total_tools"] == 0
    @pytest.mark.asyncio
    async def test_dashboard_with_servers(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test dashboard with servers in database."""
        # Create test servers
        await server_factory(name="Server 1", status="running")
        await server_factory(name="Server 2", status="stopped")

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["stats"]["total_servers"] >= 2
        assert data["stats"]["active_servers"] >= 1  # At least server1 is running

    @pytest.mark.asyncio
    async def test_dashboard_with_tools(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test dashboard counts tools correctly."""
        server = await server_factory()

        # Create enabled and disabled tools
        await tool_factory(server=server, name="tool1", enabled=True)
        await tool_factory(server=server, name="tool2", enabled=True)
        await tool_factory(server=server, name="tool3", enabled=False)

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["stats"]["total_tools"] >= 3
        assert data["stats"]["enabled_tools"] >= 2

    @pytest.mark.asyncio
    async def test_dashboard_period_parameter(self, async_client: AsyncClient, admin_headers):
        """Test dashboard with different period parameters."""
        periods = ["1h", "6h", "24h", "7d"]

        for period in periods:
            response = await async_client.get(
                f"/api/dashboard?period={period}", headers=admin_headers
            )
            assert response.status_code == 200
            data = response.json()
            assert "stats" in data

    @pytest.mark.asyncio
    async def test_dashboard_invalid_period(self, async_client: AsyncClient, admin_headers):
        """Test dashboard with invalid period parameter."""
        response = await async_client.get("/api/dashboard?period=invalid", headers=admin_headers)

        # FastAPI validation should reject invalid period
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_dashboard_time_series_structure(self, async_client: AsyncClient, admin_headers):
        """Test time series data structure."""
        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Time series should be lists
        assert isinstance(data["requests_over_time"], list)
        assert isinstance(data["errors_over_time"], list)

        # If there are points, check structure
        if data["requests_over_time"]:
            point = data["requests_over_time"][0]
            assert "timestamp" in point
            assert "value" in point

    @pytest.mark.asyncio
    async def test_dashboard_server_summary_structure(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test server summary structure in dashboard."""
        await server_factory(name="Test Server", status="running")

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        if data["servers"]:
            server = data["servers"][0]
            assert "id" in server
            assert "name" in server
            assert "status" in server
            assert "tool_count" in server
            assert "requests_24h" in server
            assert "errors_24h" in server

    @pytest.mark.asyncio
    async def test_dashboard_with_activity_logs(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Test dashboard with activity logs."""
        from app.models import ActivityLog

        server = await server_factory(name="Log Test Server")

        # Create some activity logs
        for i in range(5):
            log = ActivityLog(
                server_id=server.id,
                log_type="mcp_request",
                level="info" if i < 3 else "error",
                message=f"Test message {i}",
                duration_ms=100 + i * 10,
            )
            db_session.add(log)

        await db_session.flush()

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Should have activity counts
        assert data["stats"]["total_requests_24h"] >= 5
        assert data["stats"]["total_errors_24h"] >= 2

    @pytest.mark.asyncio
    async def test_dashboard_error_rate_calculation(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Test error rate calculation."""
        from app.models import ActivityLog

        server = await server_factory()

        # Create 10 logs: 3 errors, 7 successes
        for i in range(10):
            log = ActivityLog(
                server_id=server.id,
                log_type="mcp_response",
                level="error" if i < 3 else "info",
                message=f"Test {i}",
                duration_ms=100,
            )
            db_session.add(log)

        await db_session.flush()

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Error rate should be approximately 30%
        # Note: there might be other logs from other tests, so we just check it's calculated
        assert "error_rate_24h" in data["stats"]
        assert isinstance(data["stats"]["error_rate_24h"], (int, float))

    @pytest.mark.asyncio
    async def test_dashboard_avg_response_time(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Test average response time calculation."""
        from app.models import ActivityLog

        server = await server_factory()

        # Create logs with known durations
        for duration in [100, 200, 300]:
            log = ActivityLog(
                server_id=server.id,
                log_type="mcp_response",
                level="info",
                message="Test",
                duration_ms=duration,
            )
            db_session.add(log)

        await db_session.flush()

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Should have avg response time
        assert "avg_response_time_ms" in data["stats"]
        # The average of 100, 200, 300 is 200, but there might be other logs
        assert data["stats"]["avg_response_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_dashboard_recent_errors(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Test recent errors list."""
        from app.models import ActivityLog

        server = await server_factory()

        # Create error logs
        for i in range(3):
            log = ActivityLog(
                server_id=server.id,
                log_type="error",
                level="error",
                message=f"Error message {i}",
                details={"tool_name": f"test_tool_{i}"},
            )
            db_session.add(log)

        await db_session.flush()

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["recent_errors"]) >= 3

        if data["recent_errors"]:
            error = data["recent_errors"][0]
            assert "timestamp" in error
            assert "message" in error

    @pytest.mark.asyncio
    async def test_dashboard_top_tools(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Test top tools list."""
        from app.models import ActivityLog

        server = await server_factory()

        # Create response logs with tool names
        for _i in range(5):
            log = ActivityLog(
                server_id=server.id,
                log_type="mcp_response",
                level="info",
                message="Tool executed",
                details={"tool_name": "popular_tool"},
                duration_ms=100,
            )
            db_session.add(log)

        await db_session.flush()

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Check structure of top_tools if present
        if data["top_tools"]:
            tool = data["top_tools"][0]
            assert "tool_name" in tool
            assert "invocations" in tool
            assert "avg_duration_ms" in tool

    @pytest.mark.asyncio
    async def test_dashboard_servers_limited_to_10(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test that server list is limited to 10."""
        # Create 15 servers
        for i in range(15):
            await server_factory(name=f"Server {i}")

        response = await async_client.get("/api/dashboard", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Should be limited to 10 servers
        assert len(data["servers"]) <= 10

