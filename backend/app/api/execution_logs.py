"""Execution Log API endpoints.

Provides read-only access to tool execution logs for debugging.
"""

import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.execution_log import (
    ExecutionLogListResponse,
    ExecutionLogResponse,
)
from app.services.execution_log import ExecutionLogService

router = APIRouter(tags=["execution-logs"])


@router.get(
    "/tools/{tool_id}/logs",
    response_model=ExecutionLogListResponse,
)
async def list_tool_logs(
    tool_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ExecutionLogListResponse:
    """List execution logs for a specific tool."""
    service = ExecutionLogService(db)
    logs, total = await service.list_by_tool(tool_id, page=page, page_size=page_size)

    return ExecutionLogListResponse(
        items=[ExecutionLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get(
    "/servers/{server_id}/execution-logs",
    response_model=ExecutionLogListResponse,
)
async def list_server_logs(
    server_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ExecutionLogListResponse:
    """List execution logs for all tools in a server."""
    service = ExecutionLogService(db)
    logs, total = await service.list_by_server(server_id, page=page, page_size=page_size)

    return ExecutionLogListResponse(
        items=[ExecutionLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get(
    "/logs/{log_id}",
    response_model=ExecutionLogResponse,
)
async def get_execution_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ExecutionLogResponse:
    """Get a single execution log entry."""
    service = ExecutionLogService(db)
    log = await service.get_log(log_id)

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution log {log_id} not found",
        )

    return ExecutionLogResponse.model_validate(log)
