"""Approval API endpoints for admin review of tools and requests.

Protected by admin API key authentication via AdminAuthMiddleware.
Admin identity is extracted from JWT token claims for audit trail integrity.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core import get_db
from app.models import Tool
from app.schemas.approval import (
    ApprovalDashboardStats,
    BulkActionResponse,
    BulkModuleRequestAction,
    BulkNetworkRequestAction,
    BulkToolAction,
    ModuleRequestAction,
    ModuleRequestQueueItem,
    ModuleRequestQueueResponse,
    ModuleRequestResponse,
    NetworkAccessRequestAction,
    NetworkAccessRequestQueueItem,
    NetworkAccessRequestQueueResponse,
    NetworkAccessRequestResponse,
    PyPIPackageInfo,
    ToolApprovalAction,
    ToolApprovalQueueItem,
    ToolApprovalQueueResponse,
    VulnerabilityInfo,
)
from app.services.approval import ApprovalService
from app.services.sandbox_client import SandboxClient, get_sandbox_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
)


def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    """Dependency to get approval service."""
    return ApprovalService(db)


async def _refresh_server_registration(tool: Any, db: AsyncSession) -> bool:
    """Re-register a server with sandbox after tool approval.

    This ensures newly approved tools are immediately available without
    requiring a server restart. Handles both python_code and mcp_passthrough tools.

    Returns True if successful, False if server not running or registration failed.
    """
    # Get server info
    server = tool.server
    if not server or server.status != "running":
        logger.debug(f"Server {server.id if server else 'unknown'} not running, skipping refresh")
        return False

    try:
        from app.api.sandbox import _build_external_source_configs, _build_tool_definitions
        from app.services.global_config import GlobalConfigService
        from app.services.server_secret import ServerSecretService
        from app.services.tool import ToolService

        # Get all tools for this server
        tool_service = ToolService(db)
        all_tools, _ = await tool_service.list_by_server(server.id)

        # Filter to approved + enabled only
        active_tools = [t for t in all_tools if t.enabled and t.approval_status == "approved"]

        # Build tool definitions (handles both python_code and mcp_passthrough)
        tool_defs = _build_tool_definitions(active_tools)

        # Get decrypted secrets for injection
        secret_service = ServerSecretService(db)
        secrets = await secret_service.get_decrypted_for_injection(server.id)

        # Get global allowed modules
        config_service = GlobalConfigService(db)
        allowed_modules = await config_service.get_allowed_modules()

        # Build external source configs for passthrough tools
        external_sources_data = await _build_external_source_configs(db, server.id, secrets)

        # Re-register with sandbox
        sandbox_client = SandboxClient.get_instance()
        reg_result = await sandbox_client.register_server(
            server_id=str(server.id),
            server_name=server.name,
            tools=tool_defs,
            allowed_modules=allowed_modules,
            secrets=secrets,
            external_sources=external_sources_data,
            allowed_hosts=server.allowed_hosts or [],
        )

        success = (
            bool(reg_result.get("success")) if isinstance(reg_result, dict) else bool(reg_result)
        )

        if success:
            logger.info(
                f"Server {server.name} re-registered with {len(tool_defs)} tools after approval"
            )
        else:
            logger.warning(f"Failed to re-register server {server.name} after approval")

        return bool(success)

    except Exception as e:
        logger.error(f"Error refreshing server registration: {e}")
        return False


def get_admin_identity(
    current_user: Any = Depends(get_current_user),
) -> str:
    """Extract admin identity from verified JWT token for audit trail.

    SECURITY: Identity is always derived from the cryptographically-verified
    JWT token, never from client-supplied headers. This prevents admin
    identity spoofing in approval audit logs.
    """
    return str(current_user.username)


# =============================================================================
# Dashboard
# =============================================================================


@router.get("/stats", response_model=ApprovalDashboardStats)
async def get_approval_stats(
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDashboardStats:
    """Get approval dashboard statistics.

    Returns counts of pending items and recent activity.
    """
    stats = await service.get_dashboard_stats()
    return ApprovalDashboardStats(**stats)


# =============================================================================
# Tool Approval Endpoints
# =============================================================================


@router.get("/tools", response_model=ToolApprovalQueueResponse)
async def get_pending_tools(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(
        None, description="Search by tool name, description, or server name"
    ),
    status: str | None = Query(
        None,
        description="Filter by status: pending_review, approved, rejected, or all",
    ),
    service: ApprovalService = Depends(get_approval_service),
) -> ToolApprovalQueueResponse:
    """Get tools by approval status.

    Returns tools filtered by approval status. Defaults to pending_review only.
    Pass status=all to include approved and rejected tools.
    """
    items, total = await service.get_pending_tools(
        page=page, page_size=page_size, search=search, status=status
    )
    pages = (total + page_size - 1) // page_size if total > 0 else 0

    return ToolApprovalQueueResponse(
        items=[ToolApprovalQueueItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/tools/{tool_id}/action")
async def take_tool_action(
    tool_id: UUID,
    action: ToolApprovalAction,
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> dict[str, Any]:
    """Approve, reject, or submit a tool for review.

    The admin must provide a reason for rejection.
    Admin identity is extracted from verified JWT token.

    When a tool is approved, the server is automatically re-registered with
    the sandbox to make the tool immediately available.
    """
    try:
        if action.action == "approve":
            tool = await service.approve_tool(
                tool_id=tool_id,
                approved_by=admin_identity,
            )

            # Auto-refresh server registration so tool is immediately available
            refreshed = await _refresh_server_registration(tool, db)

            # Notify MCP clients that tool list has changed
            from app.services.tool_change_notifier import fire_and_forget_notify

            fire_and_forget_notify()

            return {
                "success": True,
                "message": (
                    f"Tool '{tool.name}' has been approved and registered with the sandbox. "
                    "Users will need to restart or refresh their MCP client to see the new tool."
                ),
                "tool_id": str(tool.id),
                "status": tool.approval_status,
                "server_refreshed": refreshed,
            }
        elif action.action == "submit_for_review":
            tool = await service.request_publish(
                tool_id=tool_id,
                notes=action.reason,
                requested_by=admin_identity,
            )

            # If auto-approved, refresh server registration
            refreshed = False
            if tool.approval_status == "approved":
                refreshed = await _refresh_server_registration(tool, db)
                from app.services.tool_change_notifier import fire_and_forget_notify

                fire_and_forget_notify()

            return {
                "success": True,
                "message": (
                    f"Tool '{tool.name}' has been auto-approved"
                    if tool.approval_status == "approved"
                    else f"Tool '{tool.name}' has been submitted for review"
                ),
                "tool_id": str(tool.id),
                "status": tool.approval_status,
                "server_refreshed": refreshed,
            }
        else:
            if not action.reason:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reason is required for rejection",
                )
            tool = await service.reject_tool(
                tool_id=tool_id,
                rejected_by=admin_identity,
                reason=action.reason,
            )
            return {
                "success": True,
                "message": f"Tool '{tool.name}' has been rejected",
                "tool_id": str(tool.id),
                "status": tool.approval_status,
            }
    except ValueError as e:
        # Only expose safe error messages for known validation errors
        error_msg = str(e)
        if "not found" in error_msg.lower() or "status" in error_msg.lower():
            detail = error_msg
        else:
            detail = "Invalid tool approval request"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from e


@router.post("/tools/{tool_id}/revoke")
async def revoke_tool_approval(
    tool_id: UUID,
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> dict[str, Any]:
    """Revoke an approved tool back to pending_review status.

    The tool is immediately removed from the running server registration
    and placed back into the approval queue for re-review.
    Admin identity is extracted from verified JWT token.
    """
    try:
        tool = await service.revoke_tool_approval(
            tool_id=tool_id,
            revoked_by=admin_identity,
        )

        # Re-register server to remove the revoked tool from active sandbox
        refreshed = await _refresh_server_registration(tool, db)

        # Notify MCP clients that tool list has changed
        from app.services.tool_change_notifier import fire_and_forget_notify

        fire_and_forget_notify()

        return {
            "success": True,
            "message": f"Tool '{tool.name}' approval has been revoked",
            "tool_id": str(tool.id),
            "status": tool.approval_status,
            "server_refreshed": refreshed,
        }
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "status" in error_msg.lower():
            detail = error_msg
        else:
            detail = "Invalid tool revocation request"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from e


@router.post("/tools/bulk-action", response_model=BulkActionResponse)
async def bulk_tool_action(
    action: BulkToolAction,
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> BulkActionResponse:
    """Approve or reject multiple tools at once.

    The admin must provide a reason for bulk rejection.
    Admin identity is extracted from verified JWT token.

    When tools are approved, their servers are automatically re-registered with
    the sandbox to make the tools immediately available.
    """
    if action.action == "reject" and not action.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reason is required for rejection",
        )

    if action.action == "approve":
        result = await service.bulk_approve_tools(
            tool_ids=action.tool_ids,
            approved_by=admin_identity,
        )

        # Re-register servers for approved tools
        for tool_id in action.tool_ids:
            if not any(f["id"] == tool_id for f in result["failed"]):
                try:
                    stmt = select(Tool).where(Tool.id == tool_id)
                    tool_result = await db.execute(stmt)
                    tool = tool_result.scalar_one_or_none()
                    if tool:
                        await _refresh_server_registration(tool, db)
                except Exception as e:
                    logger.warning(f"Failed to refresh server for tool {tool_id}: {e}")

        # Notify MCP clients that tool list has changed
        from app.services.tool_change_notifier import fire_and_forget_notify

        fire_and_forget_notify()
    else:
        result = await service.bulk_reject_tools(
            tool_ids=action.tool_ids,
            rejected_by=admin_identity,
            reason=action.reason or "",
        )

    return BulkActionResponse(**result)


# =============================================================================
# Module Request Endpoints
# =============================================================================


@router.get("/modules", response_model=ModuleRequestQueueResponse)
async def get_pending_module_requests(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search by module name or justification"),
    status: str | None = Query(
        None, description="Filter by status: pending, approved, rejected, or all"
    ),
    service: ApprovalService = Depends(get_approval_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ModuleRequestQueueResponse:
    """Get module whitelist requests filtered by status.

    Returns module requests enriched with PyPI information.
    Defaults to pending only. Pass status=all to include all statuses.
    """
    items, total = await service.get_pending_module_requests(
        page=page, page_size=page_size, search=search, status=status
    )
    pages = (total + page_size - 1) // page_size if total > 0 else 0

    # Enrich with PyPI info for each module
    enriched_items = []
    for item in items:
        module_name = item["module_name"]

        # Get PyPI/stdlib info from sandbox
        pypi_result = await sandbox_client.get_pypi_info(module_name)
        package_status = await sandbox_client.get_package_status(module_name)

        pypi_info = PyPIPackageInfo(
            package_name=pypi_result.get("package_name", module_name),
            is_stdlib=pypi_result.get("is_stdlib", False),
            is_installed=package_status.get("is_installed", False),
            installed_version=package_status.get("installed_version"),
            latest_version=None,
            summary=None,
            author=None,
            license=None,
            home_page=None,
            # Safety data from sandbox (OSV.dev + deps.dev)
            vulnerabilities=[
                VulnerabilityInfo(**v) for v in pypi_result.get("vulnerabilities", [])
            ],
            vulnerability_count=pypi_result.get("vulnerability_count", 0),
            scorecard_score=pypi_result.get("scorecard_score"),
            scorecard_date=pypi_result.get("scorecard_date"),
            dependency_count=pypi_result.get("dependency_count"),
            source_repo=pypi_result.get("source_repo"),
            error=pypi_result.get("error") or package_status.get("error"),
        )

        # Extract PyPI metadata if available
        # Note: sandbox returns pypi_info directly with fields, not nested under "info"
        if pypi_result.get("pypi_info"):
            info = pypi_result["pypi_info"]
            pypi_info.latest_version = info.get("version")
            pypi_info.summary = info.get("summary")
            pypi_info.author = info.get("author")
            pypi_info.license = info.get("license")
            pypi_info.home_page = info.get("home_page") or info.get("package_url")

        queue_item = ModuleRequestQueueItem(**item, pypi_info=pypi_info)
        enriched_items.append(queue_item)

    return ModuleRequestQueueResponse(
        items=enriched_items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/modules/{request_id}/action", response_model=ModuleRequestResponse)
async def take_module_request_action(
    request_id: UUID,
    action: ModuleRequestAction,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> ModuleRequestResponse:
    """Approve or reject a module whitelist request.

    Approval will add the module to the server's allowed modules list.
    Rejection requires a reason.
    Admin identity is extracted from verified JWT token.
    """
    try:
        if action.action == "approve":
            request = await service.approve_module_request(
                request_id=request_id,
                approved_by=admin_identity,
            )
            return ModuleRequestResponse.model_validate(request)
        else:
            if not action.reason:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reason is required for rejection",
                )
            request = await service.reject_module_request(
                request_id=request_id,
                rejected_by=admin_identity,
                reason=action.reason,
            )
            return ModuleRequestResponse.model_validate(request)
    except ValueError as e:
        # Only expose safe error messages for known validation errors
        error_msg = str(e)
        if "not found" in error_msg.lower() or "status" in error_msg.lower():
            detail = error_msg
        else:
            detail = "Invalid module request"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from e


@router.post("/modules/{request_id}/revoke", response_model=ModuleRequestResponse)
async def revoke_module_request(
    request_id: UUID,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> ModuleRequestResponse:
    """Revoke an approved module whitelist request back to pending status.

    The module is removed from the global allowed modules list.
    Admin identity is extracted from verified JWT token.
    """
    try:
        request = await service.revoke_module_request(
            request_id=request_id,
            revoked_by=admin_identity,
        )
        return ModuleRequestResponse.model_validate(request)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "status" in error_msg.lower():
            detail = error_msg
        else:
            detail = "Invalid module revocation request"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from e


@router.post("/modules/bulk-action", response_model=BulkActionResponse)
async def bulk_module_request_action(
    action: BulkModuleRequestAction,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> BulkActionResponse:
    """Approve or reject multiple module requests at once.

    Approval will add the modules to the respective server's allowed modules list.
    Rejection requires a reason.
    Admin identity is extracted from verified JWT token.
    """
    if action.action == "reject" and not action.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reason is required for rejection",
        )

    if action.action == "approve":
        result = await service.bulk_approve_module_requests(
            request_ids=action.request_ids,
            approved_by=admin_identity,
        )
    else:
        result = await service.bulk_reject_module_requests(
            request_ids=action.request_ids,
            rejected_by=admin_identity,
            reason=action.reason or "",
        )

    return BulkActionResponse(**result)


# =============================================================================
# Network Access Request Endpoints
# =============================================================================


@router.get("/network", response_model=NetworkAccessRequestQueueResponse)
async def get_pending_network_requests(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(
        None, description="Search by host, justification, or server/tool name"
    ),
    status: str | None = Query(
        None, description="Filter by status: pending, approved, rejected, or all"
    ),
    service: ApprovalService = Depends(get_approval_service),
) -> NetworkAccessRequestQueueResponse:
    """Get network access requests filtered by status.

    Returns network access requests. Defaults to pending only.
    Pass status=all to include all statuses.
    """
    items, total = await service.get_pending_network_access_requests(
        page=page, page_size=page_size, search=search, status=status
    )
    pages = (total + page_size - 1) // page_size if total > 0 else 0

    return NetworkAccessRequestQueueResponse(
        items=[NetworkAccessRequestQueueItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/network/{request_id}/action", response_model=NetworkAccessRequestResponse)
async def take_network_request_action(
    request_id: UUID,
    action: NetworkAccessRequestAction,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> NetworkAccessRequestResponse:
    """Approve or reject a network access request.

    Approval will add the host to the server's allowed hosts list and
    switch the server to allowlist network mode if needed.
    Rejection requires a reason.
    Admin identity is extracted from verified JWT token.
    """
    try:
        if action.action == "approve":
            request = await service.approve_network_access_request(
                request_id=request_id,
                approved_by=admin_identity,
            )
            return NetworkAccessRequestResponse.model_validate(request)
        else:
            if not action.reason:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reason is required for rejection",
                )
            request = await service.reject_network_access_request(
                request_id=request_id,
                rejected_by=admin_identity,
                reason=action.reason,
            )
            return NetworkAccessRequestResponse.model_validate(request)
    except ValueError as e:
        # Only expose safe error messages for known validation errors
        error_msg = str(e)
        if "not found" in error_msg.lower() or "status" in error_msg.lower():
            detail = error_msg
        else:
            detail = "Invalid network access request"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from e


@router.post("/network/{request_id}/revoke", response_model=NetworkAccessRequestResponse)
async def revoke_network_access_request(
    request_id: UUID,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> NetworkAccessRequestResponse:
    """Revoke an approved network access request back to pending status.

    The host is removed from the server's allowed hosts list.
    Admin identity is extracted from verified JWT token.
    """
    try:
        request = await service.revoke_network_access_request(
            request_id=request_id,
            revoked_by=admin_identity,
        )
        return NetworkAccessRequestResponse.model_validate(request)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "status" in error_msg.lower():
            detail = error_msg
        else:
            detail = "Invalid network revocation request"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from e


@router.post("/network/bulk-action", response_model=BulkActionResponse)
async def bulk_network_request_action(
    action: BulkNetworkRequestAction,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> BulkActionResponse:
    """Approve or reject multiple network access requests at once.

    Approval will add the hosts to the respective server's allowed hosts list and
    switch servers to allowlist network mode if needed.
    Rejection requires a reason.
    Admin identity is extracted from verified JWT token.
    """
    if action.action == "reject" and not action.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reason is required for rejection",
        )

    if action.action == "approve":
        result = await service.bulk_approve_network_requests(
            request_ids=action.request_ids,
            approved_by=admin_identity,
        )
    else:
        result = await service.bulk_reject_network_requests(
            request_ids=action.request_ids,
            rejected_by=admin_identity,
            reason=action.reason or "",
        )

    return BulkActionResponse(**result)


# =============================================================================
# Server-scoped Approval History
# =============================================================================


@router.get("/server/{server_id}/modules")
async def get_server_module_requests(
    server_id: UUID,
    status: str | None = Query(
        "approved", description="Filter by status: pending, approved, rejected, or all"
    ),
    service: ApprovalService = Depends(get_approval_service),
) -> dict:
    """Get module requests for tools belonging to a specific server."""
    items, total = await service.get_module_requests_for_server(server_id=server_id, status=status)
    return {"items": items, "total": total}


@router.get("/server/{server_id}/network")
async def get_server_network_requests(
    server_id: UUID,
    status: str | None = Query(
        "approved", description="Filter by status: pending, approved, rejected, or all"
    ),
    service: ApprovalService = Depends(get_approval_service),
) -> dict:
    """Get network access requests for tools belonging to a specific server."""
    items, total = await service.get_network_requests_for_server(server_id=server_id, status=status)
    return {"items": items, "total": total}
