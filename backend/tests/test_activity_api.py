"""Tests for activity log API endpoints."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog


class TestActivityLogsList:
    """Tests for GET /api/activity/logs endpoint."""

    @pytest.mark.asyncio
    async def test_list_activity_logs_empty(self, async_client: AsyncClient, admin_headers):
        """Test listing activity logs when none exist."""
        response = await async_client.get("/api/activity/logs", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_activity_logs_with_data(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test listing activity logs with existing data."""
        # Create test logs
        log1 = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Test request 1",
        )
        log2 = ActivityLog(
            log_type="mcp_response",
            level="info",
            message="Test response 1",
        )
        db_session.add_all([log1, log2])
        await db_session.commit()

        response = await async_client.get("/api/activity/logs", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_activity_logs_filter_by_type(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test filtering logs by type."""
        log1 = ActivityLog(log_type="mcp_request", level="info", message="Request")
        log2 = ActivityLog(log_type="error", level="error", message="Error")
        db_session.add_all([log1, log2])
        await db_session.commit()

        response = await async_client.get(
            "/api/activity/logs?log_type=error", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["log_type"] == "error"

    @pytest.mark.asyncio
    async def test_list_activity_logs_filter_by_level(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test filtering logs by level."""
        log1 = ActivityLog(log_type="mcp_request", level="info", message="Info log")
        log2 = ActivityLog(log_type="mcp_request", level="error", message="Error log")
        db_session.add_all([log1, log2])
        await db_session.commit()

        response = await async_client.get("/api/activity/logs?level=error", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["level"] == "error"

    @pytest.mark.asyncio
    async def test_list_activity_logs_filter_by_server_id(
        self, async_client: AsyncClient, db_session: AsyncSession, server_factory, admin_headers
    ):
        """Test filtering logs by server ID."""
        server = await server_factory()
        log1 = ActivityLog(
            server_id=server.id,
            log_type="mcp_request",
            level="info",
            message="Server log",
        )
        log2 = ActivityLog(log_type="mcp_request", level="info", message="No server")
        db_session.add_all([log1, log2])
        await db_session.commit()

        response = await async_client.get(
            f"/api/activity/logs?server_id={server.id}", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["server_id"] == str(server.id)

    @pytest.mark.asyncio
    async def test_list_activity_logs_search(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test searching logs by message content."""
        log1 = ActivityLog(log_type="mcp_request", level="info", message="Hello world")
        log2 = ActivityLog(log_type="mcp_request", level="info", message="Goodbye world")
        db_session.add_all([log1, log2])
        await db_session.commit()

        response = await async_client.get("/api/activity/logs?search=Hello", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert "Hello" in data["items"][0]["message"]

    @pytest.mark.asyncio
    async def test_list_activity_logs_search_escapes_sql(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test that search properly escapes SQL LIKE patterns."""
        log1 = ActivityLog(log_type="mcp_request", level="info", message="100% complete")
        log2 = ActivityLog(log_type="mcp_request", level="info", message="50 percent")
        db_session.add_all([log1, log2])
        await db_session.commit()

        # Search for literal % character
        response = await async_client.get("/api/activity/logs?search=100%", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        # Should find only the log with "100%" not match all logs
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_activity_logs_pagination(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test pagination of logs."""
        # Create 15 logs
        for i in range(15):
            log = ActivityLog(log_type="mcp_request", level="info", message=f"Log {i}")
            db_session.add(log)
        await db_session.commit()

        # Get first page
        response = await async_client.get(
            "/api/activity/logs?page=1&page_size=10", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 15
        assert len(data["items"]) == 10
        assert data["pages"] == 2

        # Get second page
        response = await async_client.get(
            "/api/activity/logs?page=2&page_size=10", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5


class TestActivityLogGet:
    """Tests for GET /api/activity/logs/{log_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_activity_log(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test getting a single activity log."""
        log = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Test log",
            details={"key": "value"},
        )
        db_session.add(log)
        await db_session.commit()
        await db_session.refresh(log)

        response = await async_client.get(f"/api/activity/logs/{log.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Test log"
        assert data["details"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_activity_log_not_found(self, async_client: AsyncClient, admin_headers):
        """Test getting a non-existent log returns 404."""
        fake_id = uuid4()
        response = await async_client.get(f"/api/activity/logs/{fake_id}", headers=admin_headers)

        assert response.status_code == 404


class TestActivityStats:
    """Tests for GET /api/activity/stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_activity_stats_empty(self, async_client: AsyncClient, admin_headers):
        """Test getting stats when no logs exist."""
        response = await async_client.get("/api/activity/stats", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["errors"] == 0
        assert data["avg_duration_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_get_activity_stats_with_data(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test getting stats with existing logs."""
        log1 = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Request 1",
            duration_ms=100,
        )
        log2 = ActivityLog(
            log_type="mcp_response",
            level="info",
            message="Response 1",
            duration_ms=200,
        )
        log3 = ActivityLog(
            log_type="error",
            level="error",
            message="Error occurred",
        )
        db_session.add_all([log1, log2, log3])
        await db_session.commit()

        response = await async_client.get("/api/activity/stats", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["errors"] == 1
        assert data["avg_duration_ms"] == 150.0  # (100 + 200) / 2
        assert "mcp_request" in data["by_type"]
        assert "error" in data["by_level"]

    @pytest.mark.asyncio
    async def test_get_activity_stats_period_filter(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test stats with different time periods."""
        # Create a recent log
        recent_log = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Recent",
        )
        db_session.add(recent_log)
        await db_session.commit()

        # Test 1h period
        response = await async_client.get("/api/activity/stats?period=1h", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["total"] >= 1

        # Test 24h period
        response = await async_client.get("/api/activity/stats?period=24h", headers=admin_headers)
        assert response.status_code == 200


class TestActivityRecent:
    """Tests for GET /api/activity/recent endpoint."""

    @pytest.mark.asyncio
    async def test_get_recent_activity(self, async_client: AsyncClient, admin_headers):
        """Test getting recent activity from buffer."""
        response = await async_client.get("/api/activity/recent", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "count" in data
        assert isinstance(data["logs"], list)

    @pytest.mark.asyncio
    async def test_get_recent_activity_with_count(self, async_client: AsyncClient, admin_headers):
        """Test limiting recent activity count."""
        response = await async_client.get("/api/activity/recent?count=10", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["count"] <= 10


class TestActivityCleanup:
    """Tests for DELETE /api/activity/logs endpoint."""

    @pytest.mark.asyncio
    async def test_cleanup_old_logs(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test cleaning up old logs."""
        # Create an old log (manually set created_at)
        old_log = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Old log",
        )
        db_session.add(old_log)
        await db_session.commit()

        # Update the created_at to be old
        old_log.created_at = datetime.now(UTC) - timedelta(days=30)
        await db_session.commit()

        # Create a recent log
        recent_log = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Recent log",
        )
        db_session.add(recent_log)
        await db_session.commit()

        # Cleanup logs older than 7 days
        response = await async_client.delete(
            "/api/activity/logs?retention_days=7", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] >= 1
        assert data["retention_days"] == 7

    @pytest.mark.asyncio
    async def test_cleanup_validates_retention_days(self, async_client: AsyncClient, admin_headers):
        """Test that retention days are validated."""
        # Too low
        response = await async_client.delete(
            "/api/activity/logs?retention_days=0", headers=admin_headers
        )
        assert response.status_code == 422

        # Too high
        response = await async_client.delete(
            "/api/activity/logs?retention_days=100", headers=admin_headers
        )
        assert response.status_code == 422


class TestRequestChain:
    """Tests for GET /api/activity/request/{request_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_request_chain(
        self, async_client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """Test getting logs for a specific request ID."""
        request_id = "req-12345"
        log1 = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Request",
            request_id=request_id,
        )
        log2 = ActivityLog(
            log_type="mcp_response",
            level="info",
            message="Response",
            request_id=request_id,
        )
        log3 = ActivityLog(
            log_type="mcp_request",
            level="info",
            message="Other request",
            request_id="other-request",
        )
        db_session.add_all([log1, log2, log3])
        await db_session.commit()

        response = await async_client.get(
            f"/api/activity/request/{request_id}", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["request_id"] == request_id
        assert data["count"] == 2
        assert len(data["logs"]) == 2

    @pytest.mark.asyncio
    async def test_get_request_chain_empty(self, async_client: AsyncClient, admin_headers):
        """Test getting request chain for non-existent request ID."""
        response = await async_client.get(
            "/api/activity/request/nonexistent", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["logs"] == []
