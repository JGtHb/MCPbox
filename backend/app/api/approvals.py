"""Approval API endpoints for admin review of tools and requests.

Protected by admin API key authentication via AdminAuthMiddleware.
User identity is captured via X-Admin-Username header or client IP for audit trail.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _refresh_server_registration(tool, db: AsyncSession) -> bool:
    """Re-register a server with sandbox after tool approval.

    This ensures newly approved tools are immediately available without
    requiring a server restart.

    Returns True if successful, False if server not running or registration failed.
    """
    from app.services.credential import CredentialService

    # Get server info
    server = tool.server
    if not server or server.status != "running":
        logger.debug(f"Server {server.id if server else 'unknown'} not running, skipping refresh")
        return False

    try:
        # Get all approved, enabled tools for this server
        stmt = select(Tool).where(
            Tool.server_id == server.id,
            Tool.enabled.is_(True),
            Tool.approval_status == "approved",
        )
        result = await db.execute(stmt)
        tools = result.scalars().all()

        # Build tool definitions
        tool_defs = []
        for t in tools:
            tool_def = {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema or {},
                "python_code": t.python_code,
                "timeout_ms": t.timeout_ms or 30000,
            }
            tool_defs.append(tool_def)

        # Get credentials - build list with full metadata for sandbox
        credential_service = CredentialService(db)
        credentials = await credential_service.get_for_injection(server.id)
        creds_list = []
        for cred in credentials:
            cred_data = {
                "name": cred.name,
                "auth_type": cred.auth_type,
                "header_name": cred.header_name,
                "query_param_name": cred.query_param_name,
            }
            # Include values based on auth type
            if cred.auth_type in ("api_key_header", "api_key_query", "custom_header"):
                if cred.value:
                    cred_data["value"] = cred.value
            elif cred.auth_type == "bearer":
                if cred.access_token:
                    cred_data["value"] = cred.access_token
                elif cred.value:
                    cred_data["value"] = cred.value
            elif cred.auth_type == "basic":
                if cred.username:
                    cred_data["username"] = cred.username
                if cred.password:
                    cred_data["password"] = cred.password
            creds_list.append(cred_data)

        # Get global allowed modules
        from app.services.global_config import GlobalConfigService

        config_service = GlobalConfigService(db)
        allowed_modules = await config_service.get_allowed_modules()

        # Re-register with sandbox
        sandbox_client = SandboxClient.get_instance()
        success = await sandbox_client.register_server(
            server_id=str(server.id),
            server_name=server.name,
            tools=tool_defs,
            credentials=creds_list,
            allowed_modules=allowed_modules,
        )

        if success:
            logger.info(
                f"Server {server.name} re-registered with {len(tool_defs)} tools after approval"
            )
        else:
            logger.warning(f"Failed to re-register server {server.name} after approval")

        return success

    except Exception as e:
        logger.error(f"Error refreshing server registration: {e}")
        return False


def get_admin_identity(
    request: Request,
    x_admin_username: Annotated[str | None, Header()] = None,
) -> str:
    """Extract admin identity for audit trail.

    Uses X-Admin-Username header if provided, otherwise falls back to
    client IP address for audit trail purposes.
    """
    if x_admin_username:
        return x_admin_username

    # Get client IP, considering X-Forwarded-For for reverse proxy setups
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        client_ip = forwarded_for.split(",")[0].strip()
        # Validate we got a non-empty IP (handles malformed headers like ", , ,")
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"
    else:
        client_ip = request.client.host if request.client else "unknown"

    return f"admin@{client_ip}"


# =============================================================================
# Dashboard
# =============================================================================


@router.get("/stats", response_model=ApprovalDashboardStats)
async def get_approval_stats(
    service: ApprovalService = Depends(get_approval_service),
):
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
    service: ApprovalService = Depends(get_approval_service),
):
    """Get tools pending approval.

    Returns tools that have been submitted for review and need admin action.
    Supports filtering by search term across tool name, description, and server name.
    """
    items, total = await service.get_pending_tools(page=page, page_size=page_size, search=search)
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
):
    """Approve or reject a tool.

    The admin must provide a reason for rejection.
    Admin identity is captured via X-Admin-Username header or client IP.

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

            return {
                "success": True,
                "message": f"Tool '{tool.name}' has been approved",
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


@router.post("/tools/bulk-action", response_model=BulkActionResponse)
async def bulk_tool_action(
    action: BulkToolAction,
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
):
    """Approve or reject multiple tools at once.

    The admin must provide a reason for bulk rejection.
    Admin identity is captured via X-Admin-Username header or client IP.

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
    else:
        result = await service.bulk_reject_tools(
            tool_ids=action.tool_ids,
            rejected_by=admin_identity,
            reason=action.reason,
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
    service: ApprovalService = Depends(get_approval_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
):
    """Get pending module whitelist requests.

    Returns module requests that need admin review, enriched with PyPI information
    to help admins make informed decisions. Supports filtering by search term.
    """
    items, total = await service.get_pending_module_requests(
        page=page, page_size=page_size, search=search
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
):
    """Approve or reject a module whitelist request.

    Approval will add the module to the server's allowed modules list.
    Rejection requires a reason.
    Admin identity is captured via X-Admin-Username header or client IP.
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


@router.post("/modules/bulk-action", response_model=BulkActionResponse)
async def bulk_module_request_action(
    action: BulkModuleRequestAction,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
):
    """Approve or reject multiple module requests at once.

    Approval will add the modules to the respective server's allowed modules list.
    Rejection requires a reason.
    Admin identity is captured via X-Admin-Username header or client IP.
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
            reason=action.reason,
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
    service: ApprovalService = Depends(get_approval_service),
):
    """Get pending network access requests.

    Returns network access requests that need admin review.
    Supports filtering by search term.
    """
    items, total = await service.get_pending_network_access_requests(
        page=page, page_size=page_size, search=search
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
):
    """Approve or reject a network access request.

    Approval will add the host to the server's allowed hosts list and
    switch the server to allowlist network mode if needed.
    Rejection requires a reason.
    Admin identity is captured via X-Admin-Username header or client IP.
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


@router.post("/network/bulk-action", response_model=BulkActionResponse)
async def bulk_network_request_action(
    action: BulkNetworkRequestAction,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
):
    """Approve or reject multiple network access requests at once.

    Approval will add the hosts to the respective server's allowed hosts list and
    switch servers to allowlist network mode if needed.
    Rejection requires a reason.
    Admin identity is captured via X-Admin-Username header or client IP.
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
            reason=action.reason,
        )

    return BulkActionResponse(**result)
