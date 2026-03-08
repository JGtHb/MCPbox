"""Tool approval endpoints.

Handles tool publish/approve/reject/revoke and bulk actions.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.deps import calc_pages, get_approval_service
from app.api.sandbox import reregister_server
from app.core import get_db
from app.models import Tool
from app.schemas.approval import (
    BulkActionResponse,
    BulkToolAction,
    ToolApprovalAction,
    ToolApprovalQueueItem,
    ToolApprovalQueueResponse,
)
from app.services.approval import ApprovalService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["approvals"])


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
    pages = calc_pages(total, page_size)

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

    Admin identity is extracted from verified JWT token.
    Rejection reason is optional.

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
            refreshed = await reregister_server(tool.server_id, db)

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
                refreshed = await reregister_server(tool.server_id, db)
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
                    detail="A reason is required when rejecting",
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
        refreshed = await reregister_server(tool.server_id, db)

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

    Admin identity is extracted from verified JWT token.

    When tools are approved, their servers are automatically re-registered with
    the sandbox to make the tools immediately available.
    """
    if action.action == "approve":
        result = await service.bulk_approve_tools(
            tool_ids=action.tool_ids,
            approved_by=admin_identity,
        )

        # Re-register servers for approved tools
        refreshed_servers: set[str] = set()
        for tool_id in action.tool_ids:
            if not any(f["id"] == tool_id for f in result["failed"]):
                stmt = select(Tool.server_id).where(Tool.id == tool_id)
                row = await db.execute(stmt)
                sid = row.scalar_one_or_none()
                if sid and str(sid) not in refreshed_servers:
                    if await reregister_server(sid, db):
                        refreshed_servers.add(str(sid))

        # Notify MCP clients that tool list has changed
        from app.services.tool_change_notifier import fire_and_forget_notify

        fire_and_forget_notify()
    else:
        if not action.reason:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A reason is required when rejecting",
            )
        result = await service.bulk_reject_tools(
            tool_ids=action.tool_ids,
            rejected_by=admin_identity,
            reason=action.reason,
        )

    return BulkActionResponse(**result)
