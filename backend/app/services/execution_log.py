"""Execution Log Service - records tool invocation results.

Captures input args (secrets redacted), results (truncated),
errors, stdout, duration, and success status for each tool call.
"""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_execution_log import ToolExecutionLog

logger = logging.getLogger(__name__)

# Limits for stored data
MAX_RESULT_SIZE = 10_000  # chars for JSON result
MAX_STDOUT_SIZE = 10_000  # chars for stdout
MAX_ERROR_SIZE = 5_000  # chars for error message

# Sensitive keys to redact from input args
SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "key",
    "private_key",
    "access_token",
    "refresh_token",
    "bearer",
    "client_secret",
    "client_id",
    "session",
    "cookie",
}


class ExecutionLogService:
    """Service for managing tool execution logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_log(
        self,
        tool_id: UUID,
        server_id: UUID,
        tool_name: str,
        input_args: dict[str, Any] | None = None,
        result: Any | None = None,
        error: str | None = None,
        stdout: str | None = None,
        duration_ms: int | None = None,
        success: bool = False,
        executed_by: str | None = None,
        is_test: bool = False,
    ) -> ToolExecutionLog:
        """Create a new execution log entry.

        Input args are redacted for sensitive keys.
        Result and stdout are truncated if too large.
        Set is_test=True for mcpbox_test_code runs so they appear labelled
        differently from production executions in the history UI.
        """
        log = ToolExecutionLog(
            tool_id=tool_id,
            server_id=server_id,
            tool_name=tool_name,
            input_args=self._redact_args(input_args),
            result=self._truncate_result(result),
            error=error[:MAX_ERROR_SIZE] if error else None,
            stdout=stdout[:MAX_STDOUT_SIZE] if stdout else None,
            duration_ms=duration_ms,
            success=success,
            is_test=is_test,
            executed_by=executed_by,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def list_by_tool(
        self,
        tool_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ToolExecutionLog], int]:
        """List execution logs for a tool, newest first.

        Returns (logs, total_count).
        """
        # Count
        count_result = await self.db.execute(
            select(func.count(ToolExecutionLog.id)).where(ToolExecutionLog.tool_id == tool_id)
        )
        total = count_result.scalar() or 0

        # Fetch page
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(ToolExecutionLog)
            .where(ToolExecutionLog.tool_id == tool_id)
            .order_by(desc(ToolExecutionLog.created_at))
            .offset(offset)
            .limit(page_size)
        )
        logs = list(result.scalars().all())

        return logs, total

    async def list_by_server(
        self,
        server_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ToolExecutionLog], int]:
        """List execution logs for a server, newest first."""
        count_result = await self.db.execute(
            select(func.count(ToolExecutionLog.id)).where(ToolExecutionLog.server_id == server_id)
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(ToolExecutionLog)
            .where(ToolExecutionLog.server_id == server_id)
            .order_by(desc(ToolExecutionLog.created_at))
            .offset(offset)
            .limit(page_size)
        )
        logs = list(result.scalars().all())

        return logs, total

    async def list_all(
        self,
        page: int = 1,
        page_size: int = 20,
        tool_name: str | None = None,
        server_id: UUID | None = None,
        success: bool | None = None,
        executed_by: str | None = None,
    ) -> tuple[list[ToolExecutionLog], int]:
        """List all execution logs across all tools, newest first.

        Supports filtering by tool_name (contains), server_id, success, executed_by.
        Returns (logs, total_count).
        """
        base = select(ToolExecutionLog)
        count_base = select(func.count(ToolExecutionLog.id))

        # Apply filters
        if tool_name:
            base = base.where(ToolExecutionLog.tool_name.ilike(f"%{tool_name}%"))
            count_base = count_base.where(ToolExecutionLog.tool_name.ilike(f"%{tool_name}%"))
        if server_id is not None:
            base = base.where(ToolExecutionLog.server_id == server_id)
            count_base = count_base.where(ToolExecutionLog.server_id == server_id)
        if success is not None:
            base = base.where(ToolExecutionLog.success == success)
            count_base = count_base.where(ToolExecutionLog.success == success)
        if executed_by:
            base = base.where(ToolExecutionLog.executed_by == executed_by)
            count_base = count_base.where(ToolExecutionLog.executed_by == executed_by)

        # Count
        count_result = await self.db.execute(count_base)
        total = count_result.scalar() or 0

        # Fetch page
        offset = (page - 1) * page_size
        result = await self.db.execute(
            base.order_by(desc(ToolExecutionLog.created_at)).offset(offset).limit(page_size)
        )
        logs = list(result.scalars().all())

        return logs, total

    async def get_stats(self, period_hours: int = 24) -> dict:
        """Get aggregate execution statistics.

        Returns total/successful/failed counts, average duration,
        period-scoped count, unique tools, and unique users.
        """
        # Total counts
        total_result = await self.db.execute(select(func.count(ToolExecutionLog.id)))
        total = total_result.scalar() or 0

        successful_result = await self.db.execute(
            select(func.count(ToolExecutionLog.id)).where(ToolExecutionLog.success.is_(True))
        )
        successful = successful_result.scalar() or 0

        failed = total - successful

        # Average duration
        avg_result = await self.db.execute(
            select(func.avg(ToolExecutionLog.duration_ms)).where(
                ToolExecutionLog.duration_ms.isnot(None)
            )
        )
        avg_duration_ms = avg_result.scalar()
        if avg_duration_ms is not None:
            avg_duration_ms = round(float(avg_duration_ms), 1)

        # Period count
        cutoff = datetime.now(UTC) - timedelta(hours=period_hours)
        period_result = await self.db.execute(
            select(func.count(ToolExecutionLog.id)).where(ToolExecutionLog.created_at >= cutoff)
        )
        period_executions = period_result.scalar() or 0

        # Unique tools
        tools_result = await self.db.execute(
            select(func.count(func.distinct(ToolExecutionLog.tool_id)))
        )
        unique_tools = tools_result.scalar() or 0

        # Unique users
        users_result = await self.db.execute(
            select(func.count(func.distinct(ToolExecutionLog.executed_by))).where(
                ToolExecutionLog.executed_by.isnot(None)
            )
        )
        unique_users = users_result.scalar() or 0

        return {
            "total_executions": total,
            "successful": successful,
            "failed": failed,
            "avg_duration_ms": avg_duration_ms,
            "period_executions": period_executions,
            "period_hours": period_hours,
            "unique_tools": unique_tools,
            "unique_users": unique_users,
        }

    async def get_log(self, log_id: UUID) -> ToolExecutionLog | None:
        """Get a single execution log by ID."""
        result = await self.db.execute(
            select(ToolExecutionLog).where(ToolExecutionLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def cleanup(self, max_per_tool: int = 100) -> int:
        """Trim old execution logs, keeping at most max_per_tool per tool.

        Returns the number of deleted logs.
        """
        # Find tools with more than max_per_tool logs
        tool_ids_result = await self.db.execute(
            select(ToolExecutionLog.tool_id)
            .group_by(ToolExecutionLog.tool_id)
            .having(func.count(ToolExecutionLog.id) > max_per_tool)
        )
        tool_ids = [row[0] for row in tool_ids_result]

        total_deleted = 0
        for tool_id in tool_ids:
            # Get the ID of the Nth most recent log for this tool
            cutoff_result = await self.db.execute(
                select(ToolExecutionLog.id)
                .where(ToolExecutionLog.tool_id == tool_id)
                .order_by(desc(ToolExecutionLog.created_at))
                .offset(max_per_tool)
                .limit(1)
            )
            cutoff_id_row = cutoff_result.first()
            if not cutoff_id_row:
                continue

            # Get the created_at of the cutoff log
            cutoff_log = await self.db.execute(
                select(ToolExecutionLog.created_at).where(ToolExecutionLog.id == cutoff_id_row[0])
            )
            cutoff_time = cutoff_log.scalar()
            if not cutoff_time:
                continue

            # Delete logs older than cutoff
            del_result: CursorResult[Any] = await self.db.execute(  # type: ignore[assignment]
                delete(ToolExecutionLog).where(
                    ToolExecutionLog.tool_id == tool_id,
                    ToolExecutionLog.created_at <= cutoff_time,
                )
            )
            total_deleted += del_result.rowcount

        if total_deleted > 0:
            logger.info(f"Cleaned up {total_deleted} old execution logs")

        return total_deleted

    def _redact_args(self, args: dict[str, Any] | None) -> dict[str, Any] | None:
        """Redact sensitive values from input arguments."""
        if not args:
            return args

        def redact(key: str, value: Any) -> Any:
            key_lower = key.lower()
            for sensitive in SENSITIVE_KEYS:
                if sensitive in key_lower:
                    return "[REDACTED]"
            if isinstance(value, dict):
                return {k: redact(k, v) for k, v in value.items()}
            if isinstance(value, str) and len(value) > 500:
                return value[:500] + "...[truncated]"
            return value

        return {k: redact(k, v) for k, v in args.items()}

    def _truncate_result(self, result: Any) -> Any:
        """Truncate result if it's too large for storage."""
        if result is None:
            return None

        import json

        try:
            serialized = json.dumps(result)
            if len(serialized) > MAX_RESULT_SIZE:
                return {"_truncated": True, "_preview": serialized[:1000] + "..."}
            return result
        except (TypeError, ValueError):
            # Not JSON-serializable
            text = str(result)
            if len(text) > MAX_RESULT_SIZE:
                return text[:MAX_RESULT_SIZE] + "...[truncated]"
            return text


def _paginate(total: int, page: int, page_size: int) -> int:
    """Calculate total pages."""
    return max(1, math.ceil(total / page_size))
