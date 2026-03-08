"""Approval API endpoints for admin review of tools and requests.

Protected by admin API key authentication via AdminAuthMiddleware.
Admin identity is extracted from JWT token claims for audit trail integrity.

This module contains shared schemas, the dashboard stats endpoint,
and registers domain-specific sub-routers for tools, modules, and network.
"""

import logging

from fastapi import APIRouter, Depends

from app.api.approvals_modules import router as modules_router
from app.api.approvals_network import router as network_router
from app.api.approvals_tools import router as tools_router
from app.api.deps import get_approval_service
from app.schemas.approval import ApprovalDashboardStats
from app.services.approval import ApprovalService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
)


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
# Include domain-specific sub-routers
# =============================================================================

router.include_router(tools_router)
router.include_router(modules_router)
router.include_router(network_router)
