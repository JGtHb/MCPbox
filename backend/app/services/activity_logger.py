"""Activity Logger Service - async logging for MCP activity and observability."""

import asyncio
import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog

logger = logging.getLogger(__name__)


class ActivityLoggerService:
    """Async activity logging service with batching and broadcast.

    Features:
    - Non-blocking async logging
    - Batch database inserts for efficiency
    - In-memory buffer for WebSocket broadcasting
    - Log retention cleanup
    - Listener callbacks for real-time streaming
    """

    _instance: Optional["ActivityLoggerService"] = None
    _instance_lock: threading.Lock = threading.Lock()

    # Buffer settings
    BATCH_SIZE = 100
    BATCH_INTERVAL_MS = 100
    BROADCAST_BUFFER_SIZE = 1000

    # Maximum concurrent notification tasks to prevent unbounded task creation
    MAX_NOTIFICATION_TASKS = 100

    def __init__(self):
        self._pending_logs: list[dict] = []
        self._batch_lock = asyncio.Lock()
        self._batch_task: asyncio.Task | None = None
        self._batch_task_scheduled = False  # Flag to prevent race condition
        self._listeners: list[Callable] = []
        self._broadcast_buffer: deque = deque(maxlen=self.BROADCAST_BUFFER_SIZE)
        self._db_session_factory: Callable | None = None
        self._notification_tasks: set[asyncio.Task] = set()  # Track active notification tasks

    @classmethod
    def get_instance(cls) -> "ActivityLoggerService":
        """Get or create singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_db_session_factory(self, factory: Callable) -> None:
        """Set the database session factory for async operations."""
        self._db_session_factory = factory

    def add_listener(self, callback: Callable) -> None:
        """Add listener for real-time log events.

        Callback receives log dict when new logs are created.
        """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        """Remove a listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def get_recent_logs(self, count: int = 100) -> list[dict]:
        """Get recent logs from broadcast buffer."""
        return list(self._broadcast_buffer)[-count:]

    async def log(
        self,
        log_type: str,
        message: str,
        server_id: UUID | None = None,
        level: str = "info",
        details: dict | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
    ) -> dict:
        """Log an activity event.

        Args:
            log_type: Type of log (mcp_request, mcp_response, network, alert, error, system)
            message: Human-readable log message
            server_id: Associated server UUID (optional)
            level: Log level (debug, info, warning, error)
            details: Structured details as dict (optional)
            request_id: Correlation ID for request/response pairs
            duration_ms: Request duration in milliseconds

        Returns:
            Log entry dict with generated ID and timestamp
        """
        log_entry = {
            "id": str(uuid.uuid4()),
            "server_id": str(server_id) if server_id else None,
            "log_type": log_type,
            "level": level,
            "message": message,
            "details": details,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "created_at": datetime.now(UTC).isoformat(),
        }

        # Add to pending batch and broadcast buffer atomically
        async with self._batch_lock:
            self._pending_logs.append(log_entry)
            # Add to broadcast buffer inside lock for consistency
            self._broadcast_buffer.append(log_entry)

            # Start batch task if not already scheduled (race-safe via flag)
            if not self._batch_task_scheduled:
                self._batch_task_scheduled = True
                self._batch_task = asyncio.create_task(self._flush_batch_safe())

        # Notify listeners (non-blocking, with error handling and task limiting)
        try:
            # Clean up completed tasks
            self._notification_tasks = {t for t in self._notification_tasks if not t.done()}

            # Only create new task if under the limit to prevent unbounded task growth
            if len(self._notification_tasks) < self.MAX_NOTIFICATION_TASKS:
                task = asyncio.create_task(self._notify_listeners_safe(log_entry))
                self._notification_tasks.add(task)
                # Auto-remove task from set when done
                task.add_done_callback(lambda t: self._notification_tasks.discard(t))
            else:
                logger.warning(
                    f"Notification task limit reached ({self.MAX_NOTIFICATION_TASKS}), "
                    "skipping listener notification"
                )
        except Exception as e:
            logger.warning(f"Failed to create listener notification task: {e}")

        return log_entry

    def _sanitize_params_for_logging(self, params: dict | None) -> dict | None:
        """Sanitize parameters to prevent logging sensitive data.

        Redacts values for keys that commonly contain secrets.
        Only logs parameter names, not full values for potentially sensitive fields.
        """
        if not params:
            return params

        sensitive_keys = {
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

        def redact_value(key: str, value: Any) -> Any:
            key_lower = key.lower()
            # Check if key contains any sensitive pattern
            for sensitive in sensitive_keys:
                if sensitive in key_lower:
                    return "[REDACTED]"
            # Recursively sanitize nested dicts
            if isinstance(value, dict):
                return {k: redact_value(k, v) for k, v in value.items()}
            # Truncate long string values to prevent log bloat
            if isinstance(value, str) and len(value) > 200:
                return value[:200] + "...[truncated]"
            return value

        return {k: redact_value(k, v) for k, v in params.items()}

    async def log_mcp_request(
        self,
        method: str,
        params: dict | None = None,
        server_id: UUID | None = None,
    ) -> str:
        """Log an MCP request.

        Args:
            method: MCP method name (e.g., tools/list, tools/call)
            params: Request parameters (will be sanitized to remove secrets)
            server_id: Server handling the request

        Returns:
            Request ID for correlation with response
        """
        request_id = str(uuid.uuid4())[:8]

        # Extract tool name if this is a tool call
        tool_name = None
        if method == "tools/call" and params:
            tool_name = params.get("name", "unknown")

        message = f"{method}"
        if tool_name:
            message = f"{method}: {tool_name}"

        # Sanitize params to prevent logging secrets
        sanitized_params = self._sanitize_params_for_logging(params)

        details = {
            "method": method,
            "params": sanitized_params,
        }
        if tool_name:
            details["tool_name"] = tool_name

        await self.log(
            log_type="mcp_request",
            message=message,
            server_id=server_id,
            level="info",
            details=details,
            request_id=request_id,
        )

        return request_id

    async def log_mcp_response(
        self,
        request_id: str,
        success: bool,
        duration_ms: int,
        server_id: UUID | None = None,
        result_size: int | None = None,
        error: str | None = None,
        method: str | None = None,
    ) -> None:
        """Log an MCP response.

        Args:
            request_id: Correlation ID from request
            success: Whether the request succeeded
            duration_ms: Request duration in milliseconds
            server_id: Server that handled the request
            result_size: Size of result in bytes (optional)
            error: Error message if failed
            method: MCP method name for context
        """
        if success:
            message = f"completed in {duration_ms}ms"
            level = "info"
        else:
            message = f"failed after {duration_ms}ms: {error or 'unknown error'}"
            level = "error"

        if method:
            message = f"{method} {message}"

        details = {
            "success": success,
            "duration_ms": duration_ms,
        }
        if result_size is not None:
            details["result_size"] = result_size
        if error:
            details["error"] = error
        if method:
            details["method"] = method

        await self.log(
            log_type="mcp_response",
            message=message,
            server_id=server_id,
            level=level,
            details=details,
            request_id=request_id,
            duration_ms=duration_ms,
        )

    async def log_alert(
        self,
        alert_type: str,
        message: str,
        server_id: UUID | None = None,
        details: dict | None = None,
    ) -> None:
        """Log an alert event.

        Args:
            alert_type: Type of alert (error_spike, high_latency, etc.)
            message: Alert message
            server_id: Related server (optional)
            details: Additional context
        """
        await self.log(
            log_type="alert",
            message=message,
            server_id=server_id,
            level="warning",
            details={"alert_type": alert_type, **(details or {})},
        )

    async def log_error(
        self,
        message: str,
        server_id: UUID | None = None,
        error: Exception | None = None,
        details: dict | None = None,
    ) -> None:
        """Log an error event.

        Args:
            message: Error description
            server_id: Related server (optional)
            error: Exception object (optional)
            details: Additional context
        """
        error_details = details or {}
        if error:
            error_details["error_type"] = type(error).__name__
            error_details["error_message"] = str(error)

        await self.log(
            log_type="error",
            message=message,
            server_id=server_id,
            level="error",
            details=error_details,
        )

    async def _flush_batch(self) -> None:
        """Flush pending logs to database in batch.

        Uses locking to prevent race conditions during batch processing.
        On failure, logs are re-added to the front of the queue (preserving order)
        and a retry is scheduled.
        """
        try:
            # Wait for batch interval
            await asyncio.sleep(self.BATCH_INTERVAL_MS / 1000)

            async with self._batch_lock:
                if not self._pending_logs:
                    return

                logs_to_write = self._pending_logs.copy()
                self._pending_logs.clear()

            if not self._db_session_factory:
                logger.warning("No database session factory configured, logs not persisted")
                return

            try:
                async with self._db_session_factory() as db:
                    try:
                        for log_entry in logs_to_write:
                            activity_log = ActivityLog(
                                id=uuid.UUID(log_entry["id"]),
                                server_id=uuid.UUID(log_entry["server_id"])
                                if log_entry["server_id"]
                                else None,
                                log_type=log_entry["log_type"],
                                level=log_entry["level"],
                                message=log_entry["message"],
                                details=log_entry["details"],
                                request_id=log_entry["request_id"],
                                duration_ms=log_entry["duration_ms"],
                            )
                            db.add(activity_log)

                        await db.commit()
                        logger.debug(f"Flushed {len(logs_to_write)} logs to database")
                    except Exception as inner_exc:
                        # Explicit rollback before re-queuing to ensure clean session state
                        await db.rollback()
                        logger.error(f"Database error during log flush: {inner_exc}")
                        raise

            except Exception as e:
                logger.error(f"Failed to flush logs to database: {e}")
                # Re-add logs to the FRONT of pending (preserving chronological order)
                # with limit to prevent memory issues
                async with self._batch_lock:
                    max_pending = self.BATCH_SIZE * 10
                    current_count = len(self._pending_logs)

                    if current_count < max_pending:
                        # Calculate how many failed logs we can re-add
                        available_slots = max_pending - current_count
                        logs_to_readd = logs_to_write[:available_slots]

                        # Prepend failed logs to maintain order (older logs first)
                        self._pending_logs = logs_to_readd + self._pending_logs

                        logger.warning(
                            f"Re-queued {len(logs_to_readd)} logs for retry "
                            f"({len(logs_to_write) - len(logs_to_readd)} dropped due to capacity)"
                        )

                        # Schedule a retry - flag will be reset in finally block
                        # and new task will be created if there are pending logs
                    else:
                        logger.error(
                            f"Dropping {len(logs_to_write)} logs - pending queue at capacity ({max_pending})"
                        )
        finally:
            # Reset flag and schedule new task if there are pending logs
            # This must be done atomically under the lock to prevent race conditions
            async with self._batch_lock:
                self._batch_task_scheduled = False
                self._batch_task = None
                # If there are still pending logs (from re-queue or new logs), schedule another flush
                if self._pending_logs:
                    self._batch_task_scheduled = True
                    self._batch_task = asyncio.create_task(self._flush_batch_safe())

    async def _notify_listeners(self, log_entry: dict) -> None:
        """Notify all listeners of new log entry."""
        for listener in self._listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(log_entry)
                else:
                    listener(log_entry)
            except Exception as e:
                logger.warning(f"Listener error: {e}")

    async def _flush_batch_safe(self) -> None:
        """Safe wrapper for _flush_batch that catches unhandled exceptions."""
        try:
            await self._flush_batch()
        except Exception as e:
            logger.error(f"Unhandled error in log flush task: {e}")

    async def _notify_listeners_safe(self, log_entry: dict) -> None:
        """Safe wrapper for _notify_listeners that catches unhandled exceptions."""
        try:
            await self._notify_listeners(log_entry)
        except Exception as e:
            logger.error(f"Unhandled error in listener notification task: {e}")

    async def cleanup_old_logs(
        self,
        db: AsyncSession,
        retention_days: int = 7,
    ) -> int:
        """Delete logs older than retention period.

        Args:
            db: Database session
            retention_days: Number of days to keep logs

        Returns:
            Number of deleted logs
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        result = await db.execute(delete(ActivityLog).where(ActivityLog.created_at < cutoff))
        await db.commit()

        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} logs older than {retention_days} days")

        return deleted_count

    async def get_stats(
        self,
        db: AsyncSession,
        server_id: UUID | None = None,
        since: datetime | None = None,
    ) -> dict:
        """Get aggregate statistics for logs.

        Args:
            db: Database session
            server_id: Filter by server (optional)
            since: Only count logs after this time

        Returns:
            Statistics dict
        """
        from sqlalchemy import func

        # Base query
        query = select(
            func.count(ActivityLog.id).label("total"),
            func.count(ActivityLog.id).filter(ActivityLog.level == "error").label("errors"),
            func.avg(ActivityLog.duration_ms)
            .filter(ActivityLog.duration_ms.isnot(None))
            .label("avg_duration"),
        )

        if server_id:
            query = query.where(ActivityLog.server_id == server_id)
        if since:
            query = query.where(ActivityLog.created_at >= since)

        result = await db.execute(query)
        row = result.first()

        # Get counts by type
        type_query = select(
            ActivityLog.log_type,
            func.count(ActivityLog.id).label("count"),
        ).group_by(ActivityLog.log_type)

        if server_id:
            type_query = type_query.where(ActivityLog.server_id == server_id)
        if since:
            type_query = type_query.where(ActivityLog.created_at >= since)

        type_result = await db.execute(type_query)
        by_type = {r.log_type: r.count for r in type_result}

        # Handle case where avg_duration is None (no records with duration)
        avg_duration = row.avg_duration if row and row.avg_duration is not None else 0
        return {
            "total": row.total if row else 0,
            "errors": row.errors if row else 0,
            "avg_duration_ms": round(avg_duration, 2),
            "by_type": by_type,
        }


# Convenience function for dependency injection
def get_activity_logger() -> ActivityLoggerService:
    """Get the activity logger singleton."""
    return ActivityLoggerService.get_instance()
