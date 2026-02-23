"""Integration tests for approval API endpoints.

Tests the tool approval workflow, module requests, and network access requests.
"""

from unittest.mock import AsyncMock

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
async def test_approve_draft_tool_directly(
    async_client: AsyncClient,
    admin_headers: dict,
    draft_tool: Tool,
    db_session: AsyncSession,
):
    """Test that admin can approve a draft tool directly (skip pending_review)."""
    response = await async_client.post(
        f"/api/approvals/tools/{draft_tool.id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "approved"

    await db_session.refresh(draft_tool)
    assert draft_tool.approval_status == "approved"


@pytest.mark.asyncio
async def test_approve_already_approved_tool_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_tool: Tool,
):
    """Test that approving an already-approved tool fails."""
    response = await async_client.post(
        f"/api/approvals/tools/{approved_tool.id}/action",
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


# =============================================================================
# request_publish (MCP tool) Tests
# =============================================================================


@pytest.mark.asyncio
async def test_request_publish_moves_draft_to_pending(
    async_client: AsyncClient,
    admin_headers: dict,
    draft_tool: Tool,
    db_session: AsyncSession,
):
    """Test that mcpbox_request_publish moves a draft tool to pending_review."""
    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    tool = await service.request_publish(
        tool_id=draft_tool.id,
        notes="Ready for review",
        requested_by="dev@example.com",
    )

    assert tool.approval_status == "pending_review"
    assert tool.publish_notes == "Ready for review"
    assert tool.approval_requested_at is not None


@pytest.mark.asyncio
async def test_request_publish_already_pending_raises(
    db_session: AsyncSession,
    pending_tool: Tool,
):
    """Test that request_publish on a pending tool raises ValueError."""
    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    with pytest.raises(ValueError, match="draft.*rejected"):
        await service.request_publish(tool_id=pending_tool.id)


@pytest.mark.asyncio
async def test_request_publish_nonexistent_tool_raises(
    db_session: AsyncSession,
):
    """Test that request_publish on missing tool raises ValueError."""
    import uuid

    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.request_publish(tool_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_request_publish_auto_approve_mode(
    db_session: AsyncSession,
    draft_tool: Tool,
):
    """Test that request_publish auto-approves when mode is auto_approve."""
    from app.services.approval import ApprovalService
    from app.services.setting import SettingService

    # Set auto_approve mode
    setting_service = SettingService(db_session)
    await setting_service.set_value("tool_approval_mode", "auto_approve")

    service = ApprovalService(db_session)
    tool = await service.request_publish(tool_id=draft_tool.id)

    assert tool.approval_status == "approved"
    assert tool.approved_by == "auto_approve"

    # Clean up
    await setting_service.set_value("tool_approval_mode", "require_approval")


# =============================================================================
# Revocation Tests
# =============================================================================


@pytest.fixture
async def approved_tool(db_session: AsyncSession, test_server: Server) -> Tool:
    """Create a tool that is already approved."""
    from datetime import UTC, datetime

    tool = Tool(
        server_id=test_server.id,
        name="approved_tool",
        description="An already-approved tool",
        python_code='async def main() -> str:\n    return "test"',
        input_schema={"type": "object", "properties": {}},
        approval_status="approved",
        approved_by="admin@example.com",
        approved_at=datetime.now(UTC),
    )
    db_session.add(tool)
    await db_session.flush()
    await db_session.refresh(tool)
    return tool


@pytest.fixture
async def approved_module_request(db_session: AsyncSession, draft_tool: Tool) -> ModuleRequest:
    """Create an already-approved module request."""
    from datetime import UTC, datetime

    request = ModuleRequest(
        tool_id=draft_tool.id,
        module_name="requests",
        justification="Need requests for HTTP calls",
        requested_by="dev@example.com",
        status="approved",
        reviewed_by="admin@example.com",
        reviewed_at=datetime.now(UTC),
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


@pytest.fixture
async def approved_network_request(
    db_session: AsyncSession, draft_tool: Tool
) -> NetworkAccessRequest:
    """Create an already-approved network access request."""
    from datetime import UTC, datetime

    request = NetworkAccessRequest(
        tool_id=draft_tool.id,
        host="api.approved.com",
        port=443,
        justification="Need access",
        requested_by="dev@example.com",
        status="approved",
        reviewed_by="admin@example.com",
        reviewed_at=datetime.now(UTC),
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


@pytest.mark.asyncio
async def test_revoke_tool_approval(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_tool: Tool,
    db_session: AsyncSession,
):
    """Test revoking an approved tool back to pending_review."""
    response = await async_client.post(
        f"/api/approvals/tools/{approved_tool.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "pending_review"

    await db_session.refresh(approved_tool)
    assert approved_tool.approval_status == "pending_review"
    assert approved_tool.approved_by is None


@pytest.mark.asyncio
async def test_revoke_non_approved_tool_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
):
    """Test that revoking a non-approved tool returns 400."""
    response = await async_client.post(
        f"/api/approvals/tools/{pending_tool.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "status" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_revoke_module_request(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_module_request: ModuleRequest,
    db_session: AsyncSession,
):
    """Test revoking an approved module request back to pending."""
    response = await async_client.post(
        f"/api/approvals/modules/{approved_module_request.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"

    await db_session.refresh(approved_module_request)
    assert approved_module_request.status == "pending"


@pytest.mark.asyncio
async def test_revoke_non_approved_module_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
):
    """Test that revoking a non-approved module request returns 400."""
    response = await async_client.post(
        f"/api/approvals/modules/{pending_module_request.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_revoke_network_request(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_network_request: NetworkAccessRequest,
    db_session: AsyncSession,
):
    """Test revoking an approved network access request back to pending."""
    response = await async_client.post(
        f"/api/approvals/network/{approved_network_request.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"

    await db_session.refresh(approved_network_request)
    assert approved_network_request.status == "pending"


@pytest.mark.asyncio
async def test_revoke_non_approved_network_request_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
):
    """Test that revoking a non-approved network request returns 400."""
    response = await async_client.post(
        f"/api/approvals/network/{pending_network_request.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 400


# =============================================================================
# create_module_request / create_network_access_request Tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_module_request(
    db_session: AsyncSession,
    draft_tool: Tool,
):
    """Test creating a module request via service."""
    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    request = await service.create_module_request(
        tool_id=draft_tool.id,
        module_name="pandas",
        justification="Need for data analysis",
        requested_by="dev@example.com",
    )

    assert request.module_name == "pandas"
    assert request.status == "pending"
    assert request.tool_id == draft_tool.id


@pytest.mark.asyncio
async def test_create_module_request_nonexistent_tool_raises(
    db_session: AsyncSession,
):
    """Test that creating a module request for missing tool raises ValueError."""
    import uuid

    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.create_module_request(
            tool_id=uuid.uuid4(),
            module_name="pandas",
            justification="Need it",
        )


@pytest.mark.asyncio
async def test_create_network_access_request(
    db_session: AsyncSession,
    draft_tool: Tool,
):
    """Test creating a network access request via service."""
    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    request = await service.create_network_access_request(
        tool_id=draft_tool.id,
        host="api.openai.com",
        port=443,
        justification="Need OpenAI access",
        requested_by="dev@example.com",
    )

    assert request.host == "api.openai.com"
    assert request.port == 443
    assert request.status == "pending"


@pytest.mark.asyncio
async def test_create_network_access_request_nonexistent_tool_raises(
    db_session: AsyncSession,
):
    """Test that creating a network request for missing tool raises ValueError."""
    import uuid

    from app.services.approval import ApprovalService

    service = ApprovalService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.create_network_access_request(
            tool_id=uuid.uuid4(),
            host="api.example.com",
            port=None,
            justification="Need it",
        )


# =============================================================================
# Status filtering Tests (status=all, status=approved, search)
# =============================================================================


@pytest.mark.asyncio
async def test_get_tools_with_status_all(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
    approved_tool: Tool,
):
    """Test listing tools with status=all returns all statuses."""
    response = await async_client.get(
        "/api/approvals/tools",
        params={"status": "all"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2
    statuses = {item["approval_status"] for item in data["items"]}
    assert "pending_review" in statuses
    assert "approved" in statuses


@pytest.mark.asyncio
async def test_get_tools_with_status_approved(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_tool: Tool,
    pending_tool: Tool,
):
    """Test listing tools with status=approved returns only approved."""
    response = await async_client.get(
        "/api/approvals/tools",
        params={"status": "approved"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    for item in data["items"]:
        assert item["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_get_modules_with_status_all(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
    approved_module_request: ModuleRequest,
):
    """Test listing module requests with status=all."""
    response = await async_client.get(
        "/api/approvals/modules",
        params={"status": "all"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_get_network_requests_with_status_all(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
    approved_network_request: NetworkAccessRequest,
):
    """Test listing network requests with status=all."""
    response = await async_client.get(
        "/api/approvals/network",
        params={"status": "all"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_search_module_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_module_request: ModuleRequest,
):
    """Test searching module requests by module name."""
    response = await async_client.get(
        "/api/approvals/modules",
        params={"search": "pandas"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(item["module_name"] == "pandas" for item in data["items"])


@pytest.mark.asyncio
async def test_search_network_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_network_request: NetworkAccessRequest,
):
    """Test searching network requests by host."""
    response = await async_client.get(
        "/api/approvals/network",
        params={"search": "api.example.com"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


# =============================================================================
# Server-scoped History Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_server_module_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_module_request: ModuleRequest,
    test_server: Server,
):
    """Test getting module requests scoped to a specific server."""
    response = await async_client.get(
        f"/api/approvals/server/{test_server.id}/modules",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_server_module_requests_status_all(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_module_request: ModuleRequest,
    pending_module_request: ModuleRequest,
    test_server: Server,
):
    """Test getting all module requests for a server with status=all."""
    response = await async_client.get(
        f"/api/approvals/server/{test_server.id}/modules",
        params={"status": "all"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_get_server_network_requests(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_network_request: NetworkAccessRequest,
    test_server: Server,
):
    """Test getting network requests scoped to a specific server."""
    response = await async_client.get(
        f"/api/approvals/server/{test_server.id}/network",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_server_network_requests_status_all(
    async_client: AsyncClient,
    admin_headers: dict,
    approved_network_request: NetworkAccessRequest,
    pending_network_request: NetworkAccessRequest,
    test_server: Server,
):
    """Test getting all network requests for a server with status=all."""
    response = await async_client.get(
        f"/api/approvals/server/{test_server.id}/network",
        params={"status": "all"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2


# =============================================================================
# Reject-nonexistent Tests (error path coverage)
# =============================================================================


@pytest.mark.asyncio
async def test_reject_nonexistent_tool(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test rejecting a tool that doesn't exist returns 400."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    response = await async_client.post(
        f"/api/approvals/tools/{fake_id}/action",
        json={"action": "reject", "reason": "Bad code"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reject_nonexistent_module_request(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test rejecting a module request that doesn't exist returns 400."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    response = await async_client.post(
        f"/api/approvals/modules/{fake_id}/action",
        json={"action": "reject", "reason": "Not allowed"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_nonexistent_module_request(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test approving a module request that doesn't exist returns 400."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    response = await async_client.post(
        f"/api/approvals/modules/{fake_id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reject_nonexistent_network_request(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test rejecting a network request that doesn't exist returns 400."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    response = await async_client.post(
        f"/api/approvals/network/{fake_id}/action",
        json={"action": "reject", "reason": "Not allowed"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_nonexistent_network_request(
    async_client: AsyncClient,
    admin_headers: dict,
):
    """Test approving a network request that doesn't exist returns 400."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    response = await async_client.post(
        f"/api/approvals/network/{fake_id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 400


# =============================================================================
# Admin State Transition Tests (submit_for_review via action endpoint)
# =============================================================================


@pytest.fixture
async def rejected_tool(db_session: AsyncSession, test_server: Server) -> Tool:
    """Create a tool in rejected status."""
    tool = Tool(
        server_id=test_server.id,
        name="rejected_tool",
        description="A tool that was rejected",
        python_code='async def main() -> str:\n    return "test"',
        input_schema={"type": "object", "properties": {}},
        approval_status="rejected",
        rejection_reason="Security concerns",
    )
    db_session.add(tool)
    await db_session.flush()
    await db_session.refresh(tool)
    return tool


@pytest.mark.asyncio
async def test_submit_draft_tool_for_review(
    async_client: AsyncClient,
    admin_headers: dict,
    draft_tool: Tool,
    db_session: AsyncSession,
):
    """Test that admin can submit a draft tool for review via action endpoint."""
    response = await async_client.post(
        f"/api/approvals/tools/{draft_tool.id}/action",
        json={"action": "submit_for_review"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "pending_review"
    assert "submitted" in data["message"].lower() or "review" in data["message"].lower()

    # Verify in database
    await db_session.refresh(draft_tool)
    assert draft_tool.approval_status == "pending_review"
    assert draft_tool.approval_requested_at is not None


@pytest.mark.asyncio
async def test_submit_rejected_tool_for_review(
    async_client: AsyncClient,
    admin_headers: dict,
    rejected_tool: Tool,
    db_session: AsyncSession,
):
    """Test that admin can re-submit a rejected tool for review."""
    response = await async_client.post(
        f"/api/approvals/tools/{rejected_tool.id}/action",
        json={"action": "submit_for_review"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "pending_review"

    await db_session.refresh(rejected_tool)
    assert rejected_tool.approval_status == "pending_review"


@pytest.mark.asyncio
async def test_submit_already_pending_tool_fails(
    async_client: AsyncClient,
    admin_headers: dict,
    pending_tool: Tool,
):
    """Test that submitting an already pending tool for review fails."""
    response = await async_client.post(
        f"/api/approvals/tools/{pending_tool.id}/action",
        json={"action": "submit_for_review"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    # request_publish raises ValueError for non-draft/non-rejected tools
    assert (
        "draft" in response.json()["detail"].lower()
        or "rejected" in response.json()["detail"].lower()
    )


@pytest.mark.asyncio
async def test_get_all_tools_includes_drafts(
    async_client: AsyncClient,
    admin_headers: dict,
    draft_tool: Tool,
    pending_tool: Tool,
):
    """Test that status=all filter includes draft tools."""
    response = await async_client.get(
        "/api/approvals/tools",
        params={"status": "all"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()

    tool_ids = [item["id"] for item in data["items"]]
    # Both draft and pending_review tools should appear
    assert str(draft_tool.id) in tool_ids
    assert str(pending_tool.id) in tool_ids

    # Verify we actually see draft status
    statuses = {item["approval_status"] for item in data["items"]}
    assert "draft" in statuses


# =============================================================================
# Network Access Approval → Sandbox Re-registration Tests
# =============================================================================
# Regression tests for: approving/revoking network access should immediately
# re-register the server with the sandbox so changes take effect without restart.


@pytest.fixture
async def running_server(db_session: AsyncSession) -> Server:
    """Create a test server in 'running' status for re-registration tests."""
    server = Server(
        name="Running Test Server",
        description="Server in running state",
        status="running",
    )
    db_session.add(server)
    await db_session.flush()
    await db_session.refresh(server)
    return server


@pytest.fixture
async def running_server_tool(db_session: AsyncSession, running_server: Server) -> Tool:
    """Create an approved tool on a running server."""
    tool = Tool(
        server_id=running_server.id,
        name="network_tool",
        description="A tool needing network access",
        python_code='async def main() -> str:\n    return "test"',
        input_schema={"type": "object", "properties": {}},
        approval_status="approved",
    )
    db_session.add(tool)
    await db_session.flush()
    await db_session.refresh(tool)
    return tool


@pytest.fixture
async def running_server_pending_network_request(
    db_session: AsyncSession, running_server_tool: Tool
) -> NetworkAccessRequest:
    """Create a pending network access request on a running server."""
    request = NetworkAccessRequest(
        tool_id=running_server_tool.id,
        host="api.newhost.com",
        port=443,
        justification="Need access to new API",
        requested_by="test@example.com",
        status="pending",
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


@pytest.fixture
async def running_server_approved_network_request(
    db_session: AsyncSession, running_server_tool: Tool, running_server: Server
) -> NetworkAccessRequest:
    """Create an approved network access request on a running server."""
    from datetime import UTC, datetime

    # Add host to server's allowed_hosts so revocation has something to remove
    running_server.allowed_hosts = ["api.revokable.com"]
    await db_session.flush()

    request = NetworkAccessRequest(
        tool_id=running_server_tool.id,
        host="api.revokable.com",
        port=443,
        justification="Previously approved access",
        requested_by="dev@example.com",
        status="approved",
        reviewed_by="admin@example.com",
        reviewed_at=datetime.now(UTC),
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


@pytest.mark.asyncio
async def test_approve_network_request_triggers_server_reregistration(
    async_client: AsyncClient,
    admin_headers: dict,
    running_server_pending_network_request: NetworkAccessRequest,
    running_server: Server,
    db_session: AsyncSession,
    mock_sandbox_client,
):
    """Approving a network request re-registers the server with sandbox.

    Regression test: previously, approving network access only updated the DB
    but did not push the new allowed_hosts to the running sandbox, requiring
    a manual server restart for the change to take effect.
    """
    mock_sandbox_client.register_server = AsyncMock(
        return_value={"success": True, "tools_registered": 1}
    )

    response = await async_client.post(
        f"/api/approvals/network/{running_server_pending_network_request.id}/action",
        json={"action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    # Verify the server was re-registered with the sandbox
    mock_sandbox_client.register_server.assert_called_once()
    call_kwargs = mock_sandbox_client.register_server.call_args
    # allowed_hosts should include the newly approved host
    passed_hosts = call_kwargs.kwargs.get(
        "allowed_hosts", call_kwargs.args[6] if len(call_kwargs.args) > 6 else []
    )
    assert "api.newhost.com" in passed_hosts


@pytest.mark.asyncio
async def test_revoke_network_request_triggers_server_reregistration(
    async_client: AsyncClient,
    admin_headers: dict,
    running_server_approved_network_request: NetworkAccessRequest,
    running_server: Server,
    db_session: AsyncSession,
    mock_sandbox_client,
):
    """Revoking a network request re-registers the server with sandbox.

    Regression test: ensures that revoking network access pushes the updated
    (reduced) allowed_hosts to the sandbox immediately.
    """
    mock_sandbox_client.register_server = AsyncMock(
        return_value={"success": True, "tools_registered": 1}
    )

    response = await async_client.post(
        f"/api/approvals/network/{running_server_approved_network_request.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"

    # Verify the server was re-registered with the sandbox
    mock_sandbox_client.register_server.assert_called_once()
    call_kwargs = mock_sandbox_client.register_server.call_args
    # allowed_hosts should NOT include the revoked host
    passed_hosts = call_kwargs.kwargs.get(
        "allowed_hosts", call_kwargs.args[6] if len(call_kwargs.args) > 6 else []
    )
    assert "api.revokable.com" not in passed_hosts


@pytest.fixture
async def multiple_running_server_pending_network_requests(
    db_session: AsyncSession, running_server_tool: Tool
) -> list[NetworkAccessRequest]:
    """Create multiple pending network requests on a running server."""
    requests = []
    for host in ["api.bulk1.com", "api.bulk2.com", "api.bulk3.com"]:
        req = NetworkAccessRequest(
            tool_id=running_server_tool.id,
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
async def test_bulk_approve_network_requests_triggers_server_reregistration(
    async_client: AsyncClient,
    admin_headers: dict,
    multiple_running_server_pending_network_requests: list[NetworkAccessRequest],
    running_server: Server,
    db_session: AsyncSession,
    mock_sandbox_client,
):
    """Bulk approving network requests re-registers affected servers.

    Regression test: ensures bulk network approval pushes the updated
    allowed_hosts to the sandbox without requiring a server restart.
    """
    mock_sandbox_client.register_server = AsyncMock(
        return_value={"success": True, "tools_registered": 1}
    )

    request_ids = [str(r.id) for r in multiple_running_server_pending_network_requests]
    response = await async_client.post(
        "/api/approvals/network/bulk-action",
        json={"request_ids": request_ids, "action": "approve"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["processed_count"] == 3

    # Server should be re-registered (at least once, deduplicated per server)
    assert mock_sandbox_client.register_server.call_count >= 1
    call_kwargs = mock_sandbox_client.register_server.call_args
    passed_hosts = call_kwargs.kwargs.get(
        "allowed_hosts", call_kwargs.args[6] if len(call_kwargs.args) > 6 else []
    )
    for host in ["api.bulk1.com", "api.bulk2.com", "api.bulk3.com"]:
        assert host in passed_hosts
