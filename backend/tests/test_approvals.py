"""Integration tests for approval API endpoints.

Tests the tool approval workflow, module requests, and network access requests.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module_request import ModuleRequest
from app.models.network_access_request import NetworkAccessRequest
from app.models.server import Server
from app.models.tool import Tool
from app.services.global_config import GlobalConfigService


@pytest.fixture
async def test_server(db_session: AsyncSession) -> Server:
    """Create a test server for approval tests."""
    server = Server(
        name="Approval Test Server",
        description="Server for testing approvals",
        status="imported",
    )
    db_session.add(server)
    await db_session.flush()
    await db_session.refresh(server)
    return server


@pytest.fixture
async def draft_tool(db_session: AsyncSession, test_server: Server) -> Tool:
    """Create a draft tool for approval testing."""
    tool = Tool(
        server_id=test_server.id,
        name="draft_tool",
        description="A tool in draft status",
        python_code='async def main() -> str:\n    return "test"',
        input_schema={"type": "object", "properties": {}},
        approval_status="draft",
    )
    db_session.add(tool)
    await db_session.flush()
    await db_session.refresh(tool)
    return tool


@pytest.fixture
async def pending_tool(db_session: AsyncSession, test_server: Server) -> Tool:
    """Create a tool pending approval."""
    tool = Tool(
        server_id=test_server.id,
        name="pending_tool",
        description="A tool pending review",
        python_code='async def main() -> str:\n    return "test"',
        input_schema={"type": "object", "properties": {}},
        approval_status="pending_review",
    )
    db_session.add(tool)
    await db_session.flush()
    await db_session.refresh(tool)
    return tool


@pytest.fixture
async def pending_module_request(db_session: AsyncSession, draft_tool: Tool) -> ModuleRequest:
    """Create a pending module request."""
    request = ModuleRequest(
        tool_id=draft_tool.id,
        module_name="pandas",
        justification="Need pandas for data processing",
        requested_by="test@example.com",
        status="pending",
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


@pytest.fixture
async def pending_network_request(
    db_session: AsyncSession, draft_tool: Tool
) -> NetworkAccessRequest:
    """Create a pending network access request."""
    request = NetworkAccessRequest(
        tool_id=draft_tool.id,
        host="api.example.com",
        port=443,
        justification="Need to call external API",
        requested_by="test@example.com",
        status="pending",
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


# =============================================================================
# Dashboard Stats Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_approval_stats(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
    pending_module_request: ModuleRequest,
    pending_network_request: NetworkAccessRequest,
):
    """Test getting approval dashboard statistics."""
    response = await async_client.get(
        "/api/approvals/stats",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert "pending_tools" in data
    assert "pending_module_requests" in data
    assert "pending_network_requests" in data
    assert "recently_approved" in data
    assert "recently_rejected" in data

    # Should have at least the pending items we created
    assert data["pending_tools"] >= 1
    assert data["pending_module_requests"] >= 1
    assert data["pending_network_requests"] >= 1


@pytest.mark.asyncio
async def test_get_approval_stats_empty(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test getting stats with no pending items."""
    response = await async_client.get(
        "/api/approvals/stats",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    # All counts should be valid integers (0 or more)
    assert isinstance(data["pending_tools"], int)
    assert isinstance(data["pending_module_requests"], int)
    assert isinstance(data["pending_network_requests"], int)


# =============================================================================
# Tool Approval Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_pending_tools(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
):
    """Test listing tools pending approval."""
    response = await async_client.get(
        "/api/approvals/tools",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "pages" in data

    # Should find our pending tool
    assert data["total"] >= 1
    tool_ids = [item["id"] for item in data["items"]]
    assert str(pending_tool.id) in tool_ids


@pytest.mark.asyncio
async def test_get_pending_tools_pagination(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test pagination on pending tools list."""
    response = await async_client.get(
        "/api/approvals/tools",
        params={"page": 1, "page_size": 5},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["page"] == 1
    assert data["page_size"] == 5


@pytest.mark.asyncio
async def test_approve_tool(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
    db_session: AsyncSession,
):
    """Test approving a tool."""
    response = await async_client.post(
        f"/api/approvals/tools/{pending_tool.id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["status"] == "approved"
    assert "approved" in data["message"].lower()

    # Verify in database
    await db_session.refresh(pending_tool)
    assert pending_tool.approval_status == "approved"
    # approved_by includes IP address when X-Admin-Username header is present
    assert pending_tool.approved_by is not None
    assert "admin" in pending_tool.approved_by


@pytest.mark.asyncio
async def test_reject_tool(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
    db_session: AsyncSession,
):
    """Test rejecting a tool with reason."""
    response = await async_client.post(
        f"/api/approvals/tools/{pending_tool.id}/action",
        json={"action": "reject", "reason": "Security concerns with the code"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["status"] == "rejected"

    # Verify in database
    await db_session.refresh(pending_tool)
    assert pending_tool.approval_status == "rejected"
    assert pending_tool.rejection_reason == "Security concerns with the code"


@pytest.mark.asyncio
async def test_reject_tool_requires_reason(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
):
    """Test that rejecting without reason fails."""
    response = await async_client.post(
        f"/api/approvals/tools/{pending_tool.id}/action",
        json={"action": "reject"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_non_pending_tool_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    draft_tool: Tool,
):
    """Test that approving a non-pending tool fails."""
    response = await async_client.post(
        f"/api/approvals/tools/{draft_tool.id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "status" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_nonexistent_tool(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test approving a tool that doesn't exist."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await async_client.post(
        f"/api/approvals/tools/{fake_id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


# =============================================================================
# Module Request Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_pending_module_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
):
    """Test listing pending module requests."""
    response = await async_client.get(
        "/api/approvals/modules",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1

    # Should find our pending request
    request_ids = [item["id"] for item in data["items"]]
    assert str(pending_module_request.id) in request_ids


@pytest.mark.asyncio
async def test_approve_module_request(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
    test_server: Server,
    db_session: AsyncSession,
):
    """Test approving a module request."""
    response = await async_client.post(
        f"/api/approvals/modules/{pending_module_request.id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "approved"
    assert data["module_name"] == "pandas"

    # Verify module was added to global allowed modules
    config_service = GlobalConfigService(db_session)
    allowed_modules = await config_service.get_allowed_modules()
    assert "pandas" in allowed_modules


@pytest.mark.asyncio
async def test_reject_module_request(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
    db_session: AsyncSession,
):
    """Test rejecting a module request."""
    response = await async_client.post(
        f"/api/approvals/modules/{pending_module_request.id}/action",
        json={"action": "reject", "reason": "Module not allowed for security reasons"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "rejected"
    assert data["rejection_reason"] == "Module not allowed for security reasons"


@pytest.mark.asyncio
async def test_reject_module_request_requires_reason(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
):
    """Test that rejecting module request without reason fails."""
    response = await async_client.post(
        f"/api/approvals/modules/{pending_module_request.id}/action",
        json={"action": "reject"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


# =============================================================================
# Network Access Request Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_pending_network_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
):
    """Test listing pending network access requests."""
    response = await async_client.get(
        "/api/approvals/network",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1

    # Should find our pending request
    request_ids = [item["id"] for item in data["items"]]
    assert str(pending_network_request.id) in request_ids


@pytest.mark.asyncio
async def test_approve_network_request(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
    test_server: Server,
    db_session: AsyncSession,
):
    """Test approving a network access request."""
    response = await async_client.post(
        f"/api/approvals/network/{pending_network_request.id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "approved"
    assert data["host"] == "api.example.com"

    # Verify host was added to server's allowed list
    await db_session.refresh(test_server)
    assert "api.example.com" in test_server.allowed_hosts
    # Server should be switched to allowlist mode
    assert test_server.network_mode == "allowlist"


@pytest.mark.asyncio
async def test_reject_network_request(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
    db_session: AsyncSession,
):
    """Test rejecting a network access request."""
    response = await async_client.post(
        f"/api/approvals/network/{pending_network_request.id}/action",
        json={"action": "reject", "reason": "External API not authorized"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "rejected"
    assert data["rejection_reason"] == "External API not authorized"


@pytest.mark.asyncio
async def test_reject_network_request_requires_reason(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
):
    """Test that rejecting network request without reason fails."""
    response = await async_client.post(
        f"/api/approvals/network/{pending_network_request.id}/action",
        json={"action": "reject"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


# =============================================================================
# Bulk Action Tests
# =============================================================================


@pytest.fixture
async def multiple_pending_tools(db_session: AsyncSession, test_server: Server) -> list[Tool]:
    """Create multiple tools pending approval."""
    tools = []
    for i in range(3):
        tool = Tool(
            server_id=test_server.id,
            name=f"bulk_tool_{i}",
            description=f"Bulk test tool {i}",
            python_code='async def main() -> str:\n    return "test"',
            input_schema={"type": "object", "properties": {}},
            approval_status="pending_review",
        )
        db_session.add(tool)
        tools.append(tool)
    await db_session.flush()
    for tool in tools:
        await db_session.refresh(tool)
    return tools


@pytest.fixture
async def multiple_pending_module_requests(
    db_session: AsyncSession, draft_tool: Tool
) -> list[ModuleRequest]:
    """Create multiple pending module requests."""
    requests = []
    for module_name in ["numpy", "scipy", "matplotlib"]:
        req = ModuleRequest(
            tool_id=draft_tool.id,
            module_name=module_name,
            justification=f"Need {module_name} for data processing",
            requested_by="test@example.com",
            status="pending",
        )
        db_session.add(req)
        requests.append(req)
    await db_session.flush()
    for req in requests:
        await db_session.refresh(req)
    return requests


@pytest.fixture
async def multiple_pending_network_requests(
    db_session: AsyncSession, draft_tool: Tool
) -> list[NetworkAccessRequest]:
    """Create multiple pending network requests."""
    requests = []
    for host in ["api.github.com", "api.stripe.com", "api.openai.com"]:
        req = NetworkAccessRequest(
            tool_id=draft_tool.id,
            host=host,
            port=443,
            justification=f"Need access to {host}",
            requested_by="test@example.com",
            status="pending",
        )
        db_session.add(req)
        requests.append(req)
    await db_session.flush()
    for req in requests:
        await db_session.refresh(req)
    return requests


@pytest.mark.asyncio
async def test_bulk_approve_tools(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_tools: list[Tool],
    db_session: AsyncSession,
):
    """Test bulk approving multiple tools."""
    tool_ids = [str(t.id) for t in multiple_pending_tools]
    response = await async_client.post(
        "/api/approvals/tools/bulk-action",
        json={"tool_ids": tool_ids, "action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3
    assert data["failed"] == []

    for tool in multiple_pending_tools:
        await db_session.refresh(tool)
        assert tool.approval_status == "approved"


@pytest.mark.asyncio
async def test_bulk_reject_tools(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_tools: list[Tool],
    db_session: AsyncSession,
):
    """Test bulk rejecting multiple tools."""
    tool_ids = [str(t.id) for t in multiple_pending_tools]
    response = await async_client.post(
        "/api/approvals/tools/bulk-action",
        json={
            "tool_ids": tool_ids,
            "action": "reject",
            "reason": "Bulk rejection: security review pending",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3

    for tool in multiple_pending_tools:
        await db_session.refresh(tool)
        assert tool.approval_status == "rejected"
        assert tool.rejection_reason == "Bulk rejection: security review pending"


@pytest.mark.asyncio
async def test_bulk_reject_tools_requires_reason(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_tools: list[Tool],
):
    """Test that bulk rejection requires a reason."""
    tool_ids = [str(t.id) for t in multiple_pending_tools]
    response = await async_client.post(
        "/api/approvals/tools/bulk-action",
        json={"tool_ids": tool_ids, "action": "reject"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bulk_approve_tools_partial_failure(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_tools: list[Tool],
):
    """Test bulk approval with a mix of valid and invalid tool IDs."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    tool_ids = [str(multiple_pending_tools[0].id), fake_id]
    response = await async_client.post(
        "/api/approvals/tools/bulk-action",
        json={"tool_ids": tool_ids, "action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["processed_count"] == 1
    assert len(data["failed"]) == 1


@pytest.mark.asyncio
async def test_bulk_approve_module_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_module_requests: list[ModuleRequest],
    db_session: AsyncSession,
):
    """Test bulk approving multiple module requests."""
    request_ids = [str(r.id) for r in multiple_pending_module_requests]
    response = await async_client.post(
        "/api/approvals/modules/bulk-action",
        json={"request_ids": request_ids, "action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3

    config_service = GlobalConfigService(db_session)
    allowed_modules = await config_service.get_allowed_modules()
    for req in multiple_pending_module_requests:
        assert req.module_name in allowed_modules


@pytest.mark.asyncio
async def test_bulk_reject_module_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_module_requests: list[ModuleRequest],
):
    """Test bulk rejecting multiple module requests."""
    request_ids = [str(r.id) for r in multiple_pending_module_requests]
    response = await async_client.post(
        "/api/approvals/modules/bulk-action",
        json={
            "request_ids": request_ids,
            "action": "reject",
            "reason": "Bulk rejection: not approved",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3


@pytest.mark.asyncio
async def test_bulk_reject_module_requests_requires_reason(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_module_requests: list[ModuleRequest],
):
    """Test that bulk module rejection requires a reason."""
    request_ids = [str(r.id) for r in multiple_pending_module_requests]
    response = await async_client.post(
        "/api/approvals/modules/bulk-action",
        json={"request_ids": request_ids, "action": "reject"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bulk_approve_network_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_network_requests: list[NetworkAccessRequest],
    test_server: Server,
    db_session: AsyncSession,
):
    """Test bulk approving multiple network access requests."""
    request_ids = [str(r.id) for r in multiple_pending_network_requests]
    response = await async_client.post(
        "/api/approvals/network/bulk-action",
        json={"request_ids": request_ids, "action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3

    await db_session.refresh(test_server)
    for req in multiple_pending_network_requests:
        assert req.host in test_server.allowed_hosts


@pytest.mark.asyncio
async def test_bulk_reject_network_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_network_requests: list[NetworkAccessRequest],
):
    """Test bulk rejecting multiple network access requests."""
    request_ids = [str(r.id) for r in multiple_pending_network_requests]
    response = await async_client.post(
        "/api/approvals/network/bulk-action",
        json={
            "request_ids": request_ids,
            "action": "reject",
            "reason": "Network access not authorized",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3


@pytest.mark.asyncio
async def test_bulk_reject_network_requests_requires_reason(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_pending_network_requests: list[NetworkAccessRequest],
):
    """Test that bulk network rejection requires a reason."""
    request_ids = [str(r.id) for r in multiple_pending_network_requests]
    response = await async_client.post(
        "/api/approvals/network/bulk-action",
        json={"request_ids": request_ids, "action": "reject"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


# =============================================================================
# Search / Filtering Tests
# =============================================================================


@pytest.mark.asyncio
async def test_search_pending_tools(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
):
    """Test searching pending tools by name."""
    response = await async_client.get(
        "/api/approvals/tools",
        params={"search": "pending"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


# =============================================================================
# Auth Tests
# =============================================================================


@pytest.mark.asyncio
async def test_approval_endpoints_require_auth(
    async_client: AsyncClient,
):
    """Test that approval endpoints require admin authentication."""
    # No auth header
    endpoints = [
        ("GET", "/api/approvals/stats"),
        ("GET", "/api/approvals/tools"),
        ("GET", "/api/approvals/modules"),
        ("GET", "/api/approvals/network"),
    ]

    for method, path in endpoints:
        if method == "GET":
            response = await async_client.get(path)
        assert response.status_code == 401, f"Expected 401 for {method} {path}"
