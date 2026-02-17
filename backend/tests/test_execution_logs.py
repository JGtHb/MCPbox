"""Integration tests for execution logs API endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_execution_log import ToolExecutionLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def execution_log(db_session: AsyncSession, tool_factory):
    """Create a single execution log entry with its associated tool."""
    tool = await tool_factory()
    log = ToolExecutionLog(
        tool_id=tool.id,
        server_id=tool.server_id,
        tool_name=tool.name,
        input_args={"query": "test"},
        result={"output": "test result"},
        success=True,
        duration_ms=100,
    )
    db_session.add(log)
    await db_session.commit()
    await db_session.refresh(log)
    return log, tool


async def test_list_tool_logs(
    async_client: AsyncClient,
    admin_headers: dict,
    db_session: AsyncSession,
    tool_factory,
):
    """Test listing execution logs for a specific tool returns paginated results."""
    tool = await tool_factory()

    # Insert three log entries for this tool
    for i in range(3):
        log = ToolExecutionLog(
            tool_id=tool.id,
            server_id=tool.server_id,
            tool_name=tool.name,
            input_args={"index": i},
            result={"value": f"result_{i}"},
            success=True,
            duration_ms=100 + i,
        )
        db_session.add(log)
    await db_session.commit()

    response = await async_client.get(
        f"/api/tools/{tool.id}/logs",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 3
    assert len(data["items"]) == 3
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["pages"] == 1

    # Each item should have expected fields
    item = data["items"][0]
    assert "id" in item
    assert item["tool_id"] == str(tool.id)
    assert item["server_id"] == str(tool.server_id)
    assert item["tool_name"] == tool.name
    assert item["success"] is True
    assert "created_at" in item


async def test_list_tool_logs_pagination(
    async_client: AsyncClient,
    admin_headers: dict,
    db_session: AsyncSession,
    tool_factory,
):
    """Test pagination parameters for tool execution logs."""
    tool = await tool_factory()

    # Insert 5 log entries
    for i in range(5):
        log = ToolExecutionLog(
            tool_id=tool.id,
            server_id=tool.server_id,
            tool_name=tool.name,
            input_args={"index": i},
            result={"value": f"result_{i}"},
            success=True,
            duration_ms=50 * (i + 1),
        )
        db_session.add(log)
    await db_session.commit()

    # Request page 1 with page_size=2
    response = await async_client.get(
        f"/api/tools/{tool.id}/logs?page=1&page_size=2",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["pages"] == 3  # ceil(5/2) = 3

    # Request page 2
    response = await async_client.get(
        f"/api/tools/{tool.id}/logs?page=2&page_size=2",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 2

    # Request page 3 (last page, only 1 item)
    response = await async_client.get(
        f"/api/tools/{tool.id}/logs?page=3&page_size=2",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 5
    assert len(data["items"]) == 1
    assert data["page"] == 3


async def test_list_server_logs(
    async_client: AsyncClient,
    admin_headers: dict,
    db_session: AsyncSession,
    server_factory,
    tool_factory,
):
    """Test listing execution logs for a server returns logs from all its tools."""
    server = await server_factory(name="Log Test Server")

    tool_a = await tool_factory(server=server, name="tool_a")
    tool_b = await tool_factory(server=server, name="tool_b")

    # Insert logs for both tools
    for tool in [tool_a, tool_b]:
        log = ToolExecutionLog(
            tool_id=tool.id,
            server_id=server.id,
            tool_name=tool.name,
            input_args={"q": "hello"},
            result={"r": "world"},
            success=True,
            duration_ms=42,
        )
        db_session.add(log)
    await db_session.commit()

    response = await async_client.get(
        f"/api/servers/{server.id}/execution-logs",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["pages"] == 1

    # All returned logs should belong to the server
    tool_names = {item["tool_name"] for item in data["items"]}
    assert tool_names == {"tool_a", "tool_b"}
    for item in data["items"]:
        assert item["server_id"] == str(server.id)


async def test_get_single_log(
    async_client: AsyncClient,
    admin_headers: dict,
    execution_log,
):
    """Test retrieving a single execution log by ID."""
    log, tool = execution_log

    response = await async_client.get(
        f"/api/logs/{log.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == str(log.id)
    assert data["tool_id"] == str(tool.id)
    assert data["server_id"] == str(tool.server_id)
    assert data["tool_name"] == tool.name
    assert data["input_args"] == {"query": "test"}
    assert data["result"] == {"output": "test result"}
    assert data["success"] is True
    assert data["duration_ms"] == 100
    assert "created_at" in data


async def test_get_nonexistent_log(
    async_client: AsyncClient,
    admin_headers: dict,
    admin_user,
):
    """Test that requesting a non-existent log returns 404."""
    fake_id = uuid4()

    response = await async_client.get(
        f"/api/logs/{fake_id}",
        headers=admin_headers,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
