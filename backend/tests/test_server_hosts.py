"""Integration tests for server allowed-hosts management endpoints.

Tests the manual host whitelisting feature (POST/DELETE /api/servers/{id}/allowed-hosts).
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.network_access_request import NetworkAccessRequest
from app.models.server import Server


@pytest.fixture
async def host_server(db_session: AsyncSession) -> Server:
    """Create a test server for host management tests."""
    server = Server(
        name="Host Test Server",
        description="Server for testing host management",
        status="imported",
    )
    db_session.add(server)
    await db_session.flush()
    await db_session.refresh(server)
    return server


@pytest.fixture
async def server_with_hosts(db_session: AsyncSession) -> Server:
    """Create a test server with allowed hosts backed by admin NAR records.

    Creates both the Server with allowed_hosts cache and the corresponding
    NetworkAccessRequest records (single source of truth).
    """
    now = datetime.now(UTC)
    server = Server(
        name="Server With Hosts",
        description="Server with existing hosts",
        status="imported",
        allowed_hosts=["api.github.com", "api.stripe.com"],
    )
    db_session.add(server)
    await db_session.flush()

    # Create admin-originated NAR records (single source of truth)
    for host in ["api.github.com", "api.stripe.com"]:
        nar = NetworkAccessRequest(
            server_id=server.id,
            tool_id=None,
            host=host,
            port=None,
            justification="Manually added by admin",
            requested_by="admin",
            status="approved",
            reviewed_at=now,
            reviewed_by="admin",
        )
        db_session.add(nar)

    await db_session.flush()
    await db_session.refresh(server)
    return server


# =============================================================================
# Add Allowed Host Tests
# =============================================================================


@pytest.mark.asyncio
async def test_add_allowed_host(
    async_client: AsyncClient,
    admin_headers: dict,
    host_server: Server,
    db_session: AsyncSession,
):
    """Test adding a host to a server's allowlist."""
    response = await async_client.post(
        f"/api/servers/{host_server.id}/allowed-hosts",
        json={"host": "api.github.com"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["server_id"] == str(host_server.id)
    assert "api.github.com" in data["allowed_hosts"]

    # Verify in database
    await db_session.refresh(host_server)
    assert "api.github.com" in host_server.allowed_hosts


@pytest.mark.asyncio
async def test_add_host_idempotent(
    async_client: AsyncClient,
    admin_headers: dict,
    server_with_hosts: Server,
):
    """Test that adding an existing host is a no-op (no duplicates)."""
    response = await async_client.post(
        f"/api/servers/{server_with_hosts.id}/allowed-hosts",
        json={"host": "api.github.com"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    # Should not duplicate
    assert data["allowed_hosts"].count("api.github.com") == 1


@pytest.mark.asyncio
async def test_add_host_normalizes_case(
    async_client: AsyncClient,
    admin_headers: dict,
    host_server: Server,
):
    """Test that host names are normalized to lowercase."""
    response = await async_client.post(
        f"/api/servers/{host_server.id}/allowed-hosts",
        json={"host": "API.GitHub.COM"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "api.github.com" in data["allowed_hosts"]


@pytest.mark.asyncio
async def test_add_host_to_nonexistent_server(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test that adding a host to a nonexistent server returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await async_client.post(
        f"/api/servers/{fake_id}/allowed-hosts",
        json={"host": "example.com"},
        headers=admin_headers,
    )
    assert response.status_code == 404


# =============================================================================
# Remove Allowed Host Tests
# =============================================================================


@pytest.mark.asyncio
async def test_remove_allowed_host(
    async_client: AsyncClient,
    admin_headers: dict,
    server_with_hosts: Server,
    db_session: AsyncSession,
):
    """Test removing a host from a server's allowlist."""
    response = await async_client.delete(
        f"/api/servers/{server_with_hosts.id}/allowed-hosts",
        params={"host": "api.github.com"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert "api.github.com" not in data["allowed_hosts"]
    assert "api.stripe.com" in data["allowed_hosts"]

    await db_session.refresh(server_with_hosts)
    assert "api.github.com" not in server_with_hosts.allowed_hosts


@pytest.mark.asyncio
async def test_remove_last_host_results_in_empty_list(
    async_client: AsyncClient,
    admin_headers: dict,
    db_session: AsyncSession,
):
    """Test that removing the last host results in an empty allowlist."""
    now = datetime.now(UTC)
    # Create a server with a single host (backed by admin NAR record)
    server = Server(
        name="Single Host Server",
        description="Server with one host",
        status="imported",
        allowed_hosts=["only-host.example.com"],
    )
    db_session.add(server)
    await db_session.flush()

    nar = NetworkAccessRequest(
        server_id=server.id,
        tool_id=None,
        host="only-host.example.com",
        port=None,
        justification="Manually added by admin",
        requested_by="admin",
        status="approved",
        reviewed_at=now,
        reviewed_by="admin",
    )
    db_session.add(nar)
    await db_session.flush()
    await db_session.refresh(server)

    response = await async_client.delete(
        f"/api/servers/{server.id}/allowed-hosts",
        params={"host": "only-host.example.com"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["allowed_hosts"] == []

    await db_session.refresh(server)
    assert server.allowed_hosts == []


@pytest.mark.asyncio
async def test_remove_nonexistent_host_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    server_with_hosts: Server,
):
    """Test that removing a host not in the allowlist returns 400."""
    response = await async_client.delete(
        f"/api/servers/{server_with_hosts.id}/allowed-hosts",
        params={"host": "not-in-list.example.com"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "not in the allowlist" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_remove_host_from_nonexistent_server(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test that removing a host from a nonexistent server returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await async_client.delete(
        f"/api/servers/{fake_id}/allowed-hosts",
        params={"host": "example.com"},
        headers=admin_headers,
    )
    assert response.status_code == 404
