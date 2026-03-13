"""Module whitelist approval endpoints.

Handles module request approve/reject/revoke/delete and bulk actions.
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
from app.models import ModuleRequest as ModuleRequestModel
from app.schemas.approval import (
    BulkActionResponse,
    BulkModuleRequestAction,
    ModuleRequestAction,
    ModuleRequestQueueItem,
    ModuleRequestQueueResponse,
    ModuleRequestResponse,
    PyPIPackageInfo,
    VulnerabilityInfo,
)
from app.services.approval import ApprovalService
from app.services.sandbox_client import SandboxClient, get_sandbox_client

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
    pages = calc_pages(total, page_size)

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
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ModuleRequestResponse:
    """Approve or reject a module whitelist request.

    Approval will add the module to the global allowed modules list,
    install the package in the sandbox, and re-register the server so
    the change takes effect immediately without requiring a restart.
    Rejection reason is optional.
    Admin identity is extracted from verified JWT token.
    """
    try:
        if action.action == "approve":
            request = await service.approve_module_request(
                request_id=request_id,
                approved_by=admin_identity,
            )

            # Install the package in the sandbox so it's available for import
            install_result = await sandbox_client.install_package(request.module_name)
            if install_result.get("status") == "failed":
                logger.warning(
                    "Package installation failed for %s: %s",
                    request.module_name,
                    install_result.get("error_message"),
                )

            # Re-register server so the updated module list takes effect immediately
            if request.server_id:
                await reregister_server(request.server_id, db)

            resp: ModuleRequestResponse = ModuleRequestResponse.model_validate(request)
            return resp
        else:
            request = await service.reject_module_request(
                request_id=request_id,
                rejected_by=admin_identity,
                reason=action.reason,
            )
            rejected: ModuleRequestResponse = ModuleRequestResponse.model_validate(request)
            return rejected
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
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> ModuleRequestResponse:
    """Revoke an approved module whitelist request back to pending status.

    The module is removed from the global allowed modules list and the server
    is re-registered with the sandbox so the change takes effect immediately.
    Admin identity is extracted from verified JWT token.
    """
    try:
        request = await service.revoke_module_request(
            request_id=request_id,
            revoked_by=admin_identity,
        )

        # Re-register server so the revoked module is removed immediately
        if request.server_id:
            await reregister_server(request.server_id, db)

        resp: ModuleRequestResponse = ModuleRequestResponse.model_validate(request)
        return resp
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


@router.delete("/modules/{request_id}")
async def delete_module_request(
    request_id: UUID,
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
) -> dict[str, Any]:
    """Permanently delete a module request.

    Only pending or rejected requests can be deleted. Approved requests
    must be revoked first before deletion.
    Admin identity is extracted from verified JWT token.
    """
    try:
        result = await service.delete_module_request(
            request_id=request_id,
            deleted_by=admin_identity,
        )
        return {
            "success": True,
            "message": f"Module request for '{result['module_name']}' has been deleted",
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


@router.post("/modules/bulk-action", response_model=BulkActionResponse)
async def bulk_module_request_action(
    action: BulkModuleRequestAction,
    db: AsyncSession = Depends(get_db),
    service: ApprovalService = Depends(get_approval_service),
    admin_identity: str = Depends(get_admin_identity),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> BulkActionResponse:
    """Approve or reject multiple module requests at once.

    Approval will add the modules to the global allowed modules list,
    install the packages in the sandbox, and re-register affected servers
    so changes take effect immediately.
    Admin identity is extracted from verified JWT token.
    """
    if action.action == "approve":
        result = await service.bulk_approve_module_requests(
            request_ids=action.request_ids,
            approved_by=admin_identity,
        )

        # Install packages and re-register affected servers
        refreshed_servers: set[str] = set()
        for req_id in action.request_ids:
            if not any(f["id"] == req_id for f in result["failed"]):
                # Look up the module name and server_id for this request
                stmt = select(
                    ModuleRequestModel.module_name,
                    ModuleRequestModel.server_id,
                ).where(ModuleRequestModel.id == req_id)
                row = await db.execute(stmt)
                module_row = row.one_or_none()
                if module_row:
                    module_name, sid = module_row

                    # Install the package in the sandbox
                    install_result = await sandbox_client.install_package(module_name)
                    if install_result.get("status") == "failed":
                        logger.warning(
                            "Package installation failed for %s: %s",
                            module_name,
                            install_result.get("error_message"),
                        )

                    # Re-register affected server
                    if sid and str(sid) not in refreshed_servers:
                        if await reregister_server(sid, db):
                            refreshed_servers.add(str(sid))
    else:
        result = await service.bulk_reject_module_requests(
            request_ids=action.request_ids,
            rejected_by=admin_identity,
            reason=action.reason,
        )

    return BulkActionResponse(**result)


# =============================================================================
# Server-scoped Module History
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
