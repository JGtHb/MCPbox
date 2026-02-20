"""Integration tests for tool API endpoints.

Note: Tools now use Python code only (no api_config mode).
All tools must have an async main() function.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.services.sandbox_client import get_sandbox_client
from app.services.setting import SettingService


@contextmanager
def override_sandbox_client(mock_client):
    """Context manager to override sandbox client dependency."""
    app.dependency_overrides[get_sandbox_client] = lambda: mock_client
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_sandbox_client, None)


@pytest.fixture
async def test_server(async_client: AsyncClient, admin_headers):
    """Create a test server for tool tests."""
    response = await async_client.post(
        "/api/servers",
        json={"name": "Tool Test Server"},
        headers=admin_headers,
    )
    return response.json()


@pytest.mark.asyncio
async def test_create_tool_python_code(async_client: AsyncClient, test_server, admin_headers):
    """Test creating a tool with Python code."""
    python_code = '''async def main(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"
'''
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "greet_user",
            "description": "Greet a user by name",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "greet_user"
    assert "async def main" in data["python_code"]
    assert "id" in data


@pytest.mark.asyncio
async def test_create_tool_validation_name(async_client: AsyncClient, test_server, admin_headers):
    """Test tool creation validation - invalid name."""
    python_code = 'async def main() -> str:\n    return "test"'

    # Invalid tool name (must be snake_case starting with letter)
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "Invalid-Name",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_tool_python_validation(async_client: AsyncClient, test_server, admin_headers):
    """Test Python code validation for tools."""
    # Missing async main function
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "no_main_tool",
            "python_code": "def not_main(): pass",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_tool_missing_code(async_client: AsyncClient, test_server, admin_headers):
    """Test tool creation requires python_code."""
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "missing_code_tool",
            "description": "A tool without code",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_tools(async_client: AsyncClient, test_server, admin_headers):
    """Test listing tools with pagination."""
    python_code = 'async def main() -> str:\n    return "test"'

    # Create multiple tools
    for i in range(3):
        await async_client.post(
            f"/api/servers/{test_server['id']}/tools",
            json={
                "name": f"tool_{i}",
                "python_code": python_code,
            },
            headers=admin_headers,
        )

    # List tools
    response = await async_client.get(
        f"/api/servers/{test_server['id']}/tools", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 3


@pytest.mark.asyncio
async def test_list_tools_pagination(async_client: AsyncClient, test_server, admin_headers):
    """Test tool listing pagination."""
    python_code = 'async def main() -> str:\n    return "test"'

    # Create tools
    for i in range(5):
        await async_client.post(
            f"/api/servers/{test_server['id']}/tools",
            json={
                "name": f"page_tool_{i}",
                "python_code": python_code,
            },
            headers=admin_headers,
        )

    # Get page 1
    response = await async_client.get(
        f"/api/servers/{test_server['id']}/tools?page=1&page_size=2", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_get_tool(async_client: AsyncClient, test_server, admin_headers):
    """Test getting a tool by ID."""
    python_code = 'async def main() -> str:\n    return "test"'

    # Create a tool
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "get_test_tool",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Get the tool
    response = await async_client.get(f"/api/tools/{tool_id}", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "get_test_tool"
    assert data["id"] == tool_id


@pytest.mark.asyncio
async def test_get_tool_not_found(async_client: AsyncClient, admin_headers):
    """Test getting a non-existent tool."""
    response = await async_client.get(
        "/api/tools/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_tool(async_client: AsyncClient, test_server, admin_headers):
    """Test updating a tool."""
    python_code = 'async def main() -> str:\n    return "test"'

    # Create a tool
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "update_tool",
            "description": "Original description",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Update the tool
    response = await async_client.patch(
        f"/api/tools/{tool_id}",
        json={"description": "Updated description"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "Updated description"
    assert data["current_version"] == 2  # Version should increment


@pytest.mark.asyncio
async def test_update_tool_python_code(async_client: AsyncClient, test_server, admin_headers):
    """Test updating tool Python code."""
    original_code = 'async def main() -> str:\n    return "original"'
    updated_code = 'async def main() -> str:\n    return "updated"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "update_code_tool",
            "python_code": original_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    response = await async_client.patch(
        f"/api/tools/{tool_id}",
        json={"python_code": updated_code},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "updated" in data["python_code"]


@pytest.mark.asyncio
async def test_toggle_tool_enabled(async_client: AsyncClient, test_server, admin_headers):
    """Test enabling/disabling a tool."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "toggle_tool",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Disable the tool
    response = await async_client.patch(
        f"/api/tools/{tool_id}",
        json={"enabled": False},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    # Re-enable the tool
    response = await async_client.patch(
        f"/api/tools/{tool_id}",
        json={"enabled": True},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True


@pytest.mark.asyncio
async def test_delete_tool(async_client: AsyncClient, test_server, admin_headers):
    """Test deleting a tool."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "delete_tool",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Delete the tool
    response = await async_client.delete(f"/api/tools/{tool_id}", headers=admin_headers)
    assert response.status_code == 204

    # Verify it's deleted
    get_response = await async_client.get(f"/api/tools/{tool_id}", headers=admin_headers)
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_tool_version_history(async_client: AsyncClient, test_server, admin_headers):
    """Test tool version history."""
    python_code = 'async def main() -> str:\n    return "test"'

    # Create a tool
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "version_tool",
            "description": "v1",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Update multiple times to create versions
    await async_client.patch(
        f"/api/tools/{tool_id}", json={"description": "v2"}, headers=admin_headers
    )
    await async_client.patch(
        f"/api/tools/{tool_id}", json={"description": "v3"}, headers=admin_headers
    )

    # Get version history
    response = await async_client.get(f"/api/tools/{tool_id}/versions", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 3  # At least 3 versions


@pytest.mark.asyncio
async def test_validate_code_endpoint(async_client: AsyncClient, admin_headers):
    """Test the code validation endpoint."""
    # Valid code
    response = await async_client.post(
        "/api/tools/validate-code",
        json={"code": "async def main(x: int) -> str:\n    return str(x)"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["has_main"] is True

    # Invalid code (syntax error)
    response = await async_client.post(
        "/api/tools/validate-code",
        json={"code": "def main(:\n    pass"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False

    # Valid syntax but no main function
    response = await async_client.post(
        "/api/tools/validate-code",
        json={"code": "def other_function(): pass"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["has_main"] is False


# =============================================================================
# Tool Version API Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_specific_version(async_client: AsyncClient, test_server, admin_headers):
    """Test getting a specific tool version."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "version_detail_tool",
            "description": "v1",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Get version 1
    response = await async_client.get(f"/api/tools/{tool_id}/versions/1", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["version_number"] == 1
    assert data["description"] == "v1"
    assert data["tool_id"] == tool_id


@pytest.mark.asyncio
async def test_get_nonexistent_version(async_client: AsyncClient, test_server, admin_headers):
    """Test getting a version that doesn't exist."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={"name": "version_404_tool", "python_code": python_code},
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    response = await async_client.get(f"/api/tools/{tool_id}/versions/999", headers=admin_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_compare_tool_versions(async_client: AsyncClient, test_server, admin_headers):
    """Test comparing two tool versions."""
    python_code_v1 = 'async def main() -> str:\n    return "v1"'
    python_code_v2 = 'async def main() -> str:\n    return "v2"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "compare_tool",
            "description": "Version 1",
            "python_code": python_code_v1,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Update to create version 2
    await async_client.patch(
        f"/api/tools/{tool_id}",
        json={"description": "Version 2", "python_code": python_code_v2},
        headers=admin_headers,
    )

    # Compare versions
    response = await async_client.get(
        f"/api/tools/{tool_id}/versions/compare",
        params={"from_version": 1, "to_version": 2},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["from_version"] == 1
    assert data["to_version"] == 2
    assert isinstance(data["differences"], list)
    assert len(data["differences"]) > 0  # Should have changes


@pytest.mark.asyncio
async def test_compare_versions_not_found(async_client: AsyncClient, test_server, admin_headers):
    """Test comparing versions where one doesn't exist."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={"name": "compare_404_tool", "python_code": python_code},
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    response = await async_client.get(
        f"/api/tools/{tool_id}/versions/compare",
        params={"from_version": 1, "to_version": 999},
        headers=admin_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rollback_tool(async_client: AsyncClient, test_server, admin_headers):
    """Test rolling back a tool to a previous version."""
    python_code_v1 = 'async def main() -> str:\n    return "v1"'
    python_code_v2 = 'async def main() -> str:\n    return "v2"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "rollback_tool",
            "description": "Version 1",
            "python_code": python_code_v1,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Update to v2
    await async_client.patch(
        f"/api/tools/{tool_id}",
        json={"python_code": python_code_v2},
        headers=admin_headers,
    )

    # Rollback to v1
    response = await async_client.post(
        f"/api/tools/{tool_id}/versions/1/rollback",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["current_version"] == 3  # Rollback creates a new version
    assert "v1" in data["python_code"]


@pytest.mark.asyncio
async def test_rollback_to_current_version_fails(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test that rolling back to current or future version fails."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={"name": "rollback_fail_tool", "python_code": python_code},
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Try to rollback to current version (1)
    response = await async_client.post(
        f"/api/tools/{tool_id}/versions/1/rollback",
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "cannot rollback" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_version_list_pagination(async_client: AsyncClient, test_server, admin_headers):
    """Test version list pagination."""
    python_code = 'async def main() -> str:\n    return "test"'

    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "page_version_tool",
            "description": "v1",
            "python_code": python_code,
        },
        headers=admin_headers,
    )
    tool_id = create_response.json()["id"]

    # Create several versions
    for i in range(2, 5):
        await async_client.patch(
            f"/api/tools/{tool_id}",
            json={"description": f"v{i}"},
            headers=admin_headers,
        )

    # Get paginated versions
    response = await async_client.get(
        f"/api/tools/{tool_id}/versions",
        params={"page": 1, "page_size": 2},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] >= 4
    assert data["pages"] >= 2


# =============================================================================
# Test Code Execution Tests
# =============================================================================


@pytest.mark.asyncio
async def test_test_code_tool_not_found(async_client: AsyncClient, admin_headers):
    """Test that testing a non-existent tool returns an error."""
    import uuid

    response = await async_client.post(
        "/api/tools/test-code",
        json={"tool_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "not found" in data["error"].lower()


@pytest.mark.asyncio
async def test_test_code_blocked_when_require_approval(
    async_client: AsyncClient,
    admin_headers,
    test_server,
    db_session: AsyncSession,
):
    """Test that testing is blocked for unapproved tools when require_approval mode is active."""
    # Create a tool (starts as pending_review by default)
    resp = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "blocked_test_tool",
            "description": "A tool to test the approval gate",
            "python_code": 'async def main() -> str:\n    return "hi"',
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    tool_id = resp.json()["id"]

    # Ensure require_approval mode is active (the default)
    setting_service = SettingService(db_session)
    await setting_service.set_value("tool_approval_mode", "require_approval")

    response = await async_client.post(
        "/api/tools/test-code",
        json={"tool_id": tool_id},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "cannot be tested" in data["error"]
    assert "approved" in data["error"]


@pytest.mark.asyncio
async def test_test_code_success(
    async_client: AsyncClient,
    admin_headers,
    test_server,
    db_session: AsyncSession,
):
    """Test successful code execution for an approved tool."""
    # Create and approve a tool
    resp = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "success_test_tool",
            "description": "A tool that runs successfully",
            "python_code": 'async def main() -> str:\n    return "Hello, world!"',
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    tool_id = resp.json()["id"]

    # Switch to auto_approve so we can test without admin approval flow
    setting_service = SettingService(db_session)
    await setting_service.set_value("tool_approval_mode", "auto_approve")

    mock_client = MagicMock()
    mock_client.execute_code = AsyncMock(
        return_value={
            "success": True,
            "result": "Hello, world!",
            "stdout": "",
            "duration_ms": 50,
        }
    )

    with override_sandbox_client(mock_client):
        response = await async_client.post(
            "/api/tools/test-code",
            json={"tool_id": tool_id, "arguments": {}},
            headers=admin_headers,
        )

    # Restore default approval mode
    await setting_service.set_value("tool_approval_mode", "require_approval")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["result"] == "Hello, world!"

    # Confirm execute_code was called (not the old register_server pattern)
    mock_client.execute_code.assert_called_once()


@pytest.mark.asyncio
async def test_test_code_logs_test_run(
    async_client: AsyncClient,
    admin_headers,
    test_server,
    db_session: AsyncSession,
):
    """Test that a test run is saved to execution history with is_test=True."""
    from sqlalchemy import select

    from app.models.tool_execution_log import ToolExecutionLog

    resp = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "logged_test_tool",
            "description": "A tool to verify test logging",
            "python_code": 'async def main() -> str:\n    return "logged"',
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    tool_id = resp.json()["id"]

    setting_service = SettingService(db_session)
    await setting_service.set_value("tool_approval_mode", "auto_approve")

    mock_client = MagicMock()
    mock_client.execute_code = AsyncMock(
        return_value={
            "success": True,
            "result": "logged",
            "stdout": "",
            "duration_ms": 10,
        }
    )

    with override_sandbox_client(mock_client):
        response = await async_client.post(
            "/api/tools/test-code",
            json={"tool_id": tool_id},
            headers=admin_headers,
        )

    await setting_service.set_value("tool_approval_mode", "require_approval")

    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify the execution log was written with is_test=True
    from uuid import UUID

    logs_result = await db_session.execute(
        select(ToolExecutionLog).where(ToolExecutionLog.tool_id == UUID(tool_id))
    )
    logs = logs_result.scalars().all()
    assert len(logs) == 1
    assert logs[0].is_test is True


@pytest.mark.asyncio
async def test_test_code_failure_returns_error(
    async_client: AsyncClient,
    admin_headers,
    test_server,
    db_session: AsyncSession,
):
    """Test that a failed execution returns error in the response."""
    resp = await async_client.post(
        f"/api/servers/{test_server['id']}/tools",
        json={
            "name": "error_test_tool",
            "description": "A tool that raises an error",
            "python_code": "async def main() -> str:\n    return undefined_var",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    tool_id = resp.json()["id"]

    setting_service = SettingService(db_session)
    await setting_service.set_value("tool_approval_mode", "auto_approve")

    mock_client = MagicMock()
    mock_client.execute_code = AsyncMock(
        return_value={
            "success": False,
            "error": "NameError: name 'undefined_var' is not defined",
            "duration_ms": 10,
        }
    )

    with override_sandbox_client(mock_client):
        response = await async_client.post(
            "/api/tools/test-code",
            json={"tool_id": tool_id},
            headers=admin_headers,
        )

    await setting_service.set_value("tool_approval_mode", "require_approval")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "NameError" in data["error"]
