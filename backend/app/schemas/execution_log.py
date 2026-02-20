"""Pydantic schemas for tool execution logs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExecutionLogResponse(BaseModel):
    """Schema for a single execution log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: UUID
    server_id: UUID
    tool_name: str
    input_args: dict[str, Any] | None = None
    result: Any | None = None
    error: str | None = None
    stdout: str | None = None
    duration_ms: int | None = None
    success: bool
    is_test: bool = False
    executed_by: str | None = None
    created_at: datetime


class ExecutionLogListResponse(BaseModel):
    """Schema for paginated execution log list."""

    items: list[ExecutionLogResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ExecutionStatsResponse(BaseModel):
    """Aggregate execution statistics."""

    total_executions: int
    successful: int
    failed: int
    avg_duration_ms: float | None
    period_executions: int
    period_hours: int
    unique_tools: int
    unique_users: int


class ExecutionLogSummary(BaseModel):
    """Abbreviated log entry for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_name: str
    success: bool
    duration_ms: int | None = None
    error: str | None = None
    executed_by: str | None = None
    created_at: datetime
