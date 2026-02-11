"""Integration tests for tool API endpoints.

Note: Tools now use Python code only (no api_config mode).
All tools must have an async main() function.
"""

import pytest
from httpx import AsyncClient


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
async def test_create_tool_python_validation(
    async_client: AsyncClient, test_server, admin_headers
):
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
    response = await async_client.get(
        f"/api/tools/{tool_id}/versions", headers=admin_headers
    )
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
