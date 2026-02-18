"""Tests for global execution logs API endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.tool_execution_log import ToolExecutionLog


@pytest.fixture
async def execution_logs(db_session, server_factory, tool_factory):
    """Create sample execution logs for testing."""
    server = await server_factory(name="Test Server")
    tool1 = await tool_factory(server=server, name="fetch_data")
    tool2 = await tool_factory(server=server, name="send_email")

    logs = []
    # 3 successful fetch_data calls
    for i in range(3):
        log = ToolExecutionLog(
            tool_id=tool1.id,
            server_id=server.id,
            tool_name="fetch_data",
            input_args={"url": f"https://example.com/{i}"},
            result={"status": "ok"},
            duration_ms=100 + i * 50,
            success=True,
            executed_by="user@test.com",
        )
        db_session.add(log)
        logs.append(log)

    # 2 failed send_email calls
    for i in range(2):
        log = ToolExecutionLog(
            tool_id=tool2.id,
            server_id=server.id,
            tool_name="send_email",
            input_args={"to": "test@example.com"},
            error="SMTP connection failed",
            duration_ms=5000 + i * 1000,
            success=False,
            executed_by="admin@test.com",
        )
        db_session.add(log)
        logs.append(log)

    await db_session.flush()
    return logs, server, tool1, tool2


class TestListAllLogs:
    """Tests for GET /api/execution-logs."""

    @pytest.mark.asyncio
    async def test_list_all_empty(self, async_client: AsyncClient, admin_headers):
        """Test listing logs when none exist."""
        response = await async_client.get("/api/execution-logs", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["pages"] == 1

    @pytest.mark.asyncio
    async def test_list_all_returns_logs(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test listing all logs returns paginated results."""
        response = await async_client.get("/api/execution-logs", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    @pytest.mark.asyncio
    async def test_filter_by_tool_name(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test filtering by tool name."""
        response = await async_client.get(
            "/api/execution-logs?tool_name=fetch", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        for item in data["items"]:
            assert "fetch" in item["tool_name"]

    @pytest.mark.asyncio
    async def test_filter_by_success(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test filtering by success status."""
        response = await async_client.get(
            "/api/execution-logs?success=false", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["success"] is False

    @pytest.mark.asyncio
    async def test_pagination(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test pagination works correctly."""
        response = await async_client.get(
            "/api/execution-logs?page=1&page_size=2", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["pages"] == 3

    @pytest.mark.asyncio
    async def test_response_structure(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test that response items have the expected structure."""
        response = await async_client.get("/api/execution-logs", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        item = data["items"][0]
        assert "id" in item
        assert "tool_id" in item
        assert "server_id" in item
        assert "tool_name" in item
        assert "success" in item
        assert "duration_ms" in item
        assert "executed_by" in item
        assert "created_at" in item


class TestExecutionStats:
    """Tests for GET /api/execution-logs/stats."""

    @pytest.mark.asyncio
    async def test_stats_empty(self, async_client: AsyncClient, admin_headers):
        """Test stats when no logs exist."""
        response = await async_client.get(
            "/api/execution-logs/stats", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_executions"] == 0
        assert data["successful"] == 0
        assert data["failed"] == 0
        assert data["avg_duration_ms"] is None
        assert data["period_hours"] == 24
        assert data["unique_tools"] == 0
        assert data["unique_users"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_data(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test stats return correct aggregate values."""
        response = await async_client.get(
            "/api/execution-logs/stats", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_executions"] == 5
        assert data["successful"] == 3
        assert data["failed"] == 2
        assert data["avg_duration_ms"] is not None
        assert data["period_executions"] == 5  # All created within last 24h
        assert data["unique_tools"] == 2  # fetch_data + send_email
        assert data["unique_users"] == 2  # user@test.com + admin@test.com

    @pytest.mark.asyncio
    async def test_stats_custom_period(
        self, async_client: AsyncClient, admin_headers, execution_logs
    ):
        """Test stats with custom period parameter."""
        response = await async_client.get(
            "/api/execution-logs/stats?period_hours=1", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["period_hours"] == 1

    @pytest.mark.asyncio
    async def test_stats_response_structure(
        self, async_client: AsyncClient, admin_headers
    ):
        """Test that stats response has all expected fields."""
        response = await async_client.get(
            "/api/execution-logs/stats", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        expected_fields = [
            "total_executions",
            "successful",
            "failed",
            "avg_duration_ms",
            "period_executions",
            "period_hours",
            "unique_tools",
            "unique_users",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
