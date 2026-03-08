"""Network access approval endpoints.

Handles network access request approve/reject/revoke/delete and bulk actions.
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
from app.models import NetworkAccessRequest as NetworkAccessRequestModel
from app.schemas.approval import (
    BulkActionResponse,
    BulkNetworkRequestAction,
    NetworkAccessRequestAction,
    NetworkAccessRequestQueueItem,
    NetworkAccessRequestQueueResponse,
    NetworkAccessRequestResponse,
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
    pages = calc_pages(total, page_size)

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
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> NetworkAccessRequestResponse:
    """Approve or reject a network access request.

    Approval will add the host to the server's allowed hosts list and
    re-register the server with the sandbox so the change takes effect
    immediately without requiring a restart.
    Rejection reason is optional.
    Admin identity is extracted from verified JWT token.
    """
    try:
        if action.action == "approve":
            request = await service.approve_network_access_request(
                request_id=request_id,
                approved_by=admin_identity,
            )

            # Re-register server so approved hosts take effect immediately
            if request.server_id:
                await reregister_server(request.server_id, db)

            resp: NetworkAccessRequestResponse = NetworkAccessRequestResponse.model_validate(
                request
            )
            return resp
        else:
            if not action.reason:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A reason is required when rejecting",
                )
            request = await service.reject_network_access_request(
                request_id=request_id,
                rejected_by=admin_identity,
                reason=action.reason,
            )
            rejected: NetworkAccessRequestResponse = NetworkAccessRequestResponse.model_validate(
                request
            )
            return rejected
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
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> NetworkAccessRequestResponse:
    """Revoke an approved network access request back to pending status.

    The host is removed from the server's allowed hosts list and the server
    is re-registered with the sandbox so the change takes effect immediately.
    Admin identity is extracted from verified JWT token.
    """
    try:
        request = await service.revoke_network_access_request(
            request_id=request_id,
            revoked_by=admin_identity,
        )

        # Re-register server so revoked hosts are removed immediately
        if request.server_id:
            await reregister_server(request.server_id, db)

        resp: NetworkAccessRequestResponse = NetworkAccessRequestResponse.model_validate(request)
        return resp
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


@router.delete("/network/{request_id}")
async def delete_network_access_request(
    request_id: UUID,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> dict[str, Any]:
    """Permanently delete a network access request.

    Only pending or rejected requests can be deleted. Approved requests
    must be revoked first before deletion.
    Admin identity is extracted from verified JWT token.
    """
    try:
        result = await service.delete_network_access_request(
            request_id=request_id,
            deleted_by=admin_identity,
        )
        port_str = f":{result['port']}" if result.get("port") else ""
        return {
            "success": True,
            "message": f"Network access request for '{result['host']}{port_str}' has been deleted",
            **result,
        }
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        ) from e


@router.post("/network/bulk-action", response_model=BulkActionResponse)
async def bulk_network_request_action(
    action: BulkNetworkRequestAction,
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> BulkActionResponse:
    """Approve or reject multiple network access requests at once.

    Approval will add the hosts to the respective server's allowed hosts list
    and re-register affected servers with the sandbox so changes take effect
    immediately.
    Admin identity is extracted from verified JWT token.
    """
    if action.action == "approve":
        result = await service.bulk_approve_network_requests(
            request_ids=action.request_ids,
            approved_by=admin_identity,
        )

        # Re-register affected servers so approved hosts take effect immediately
        refreshed_servers: set[str] = set()
        for req_id in action.request_ids:
            if not any(f["id"] == req_id for f in result["failed"]):
                stmt = select(NetworkAccessRequestModel.server_id).where(
                    NetworkAccessRequestModel.id == req_id
                )
                row = await db.execute(stmt)
                sid = row.scalar_one_or_none()
                if sid and str(sid) not in refreshed_servers:
                    if await reregister_server(sid, db):
                        refreshed_servers.add(str(sid))
    else:
        if not action.reason:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A reason is required when rejecting",
            )
        result = await service.bulk_reject_network_requests(
            request_ids=action.request_ids,
            rejected_by=admin_identity,
            reason=action.reason,
        )

    return BulkActionResponse(**result)


# =============================================================================
# Server-scoped Network History
# =============================================================================


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
