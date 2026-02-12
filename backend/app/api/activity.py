"""Activity log API endpoints for observability.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.models import ActivityLog
from app.services.activity_logger import ActivityLoggerService, get_activity_logger

logger = logging.getLogger(__name__)

# Lock to protect concurrent access to _active_connections
_connections_lock = asyncio.Lock()

router = APIRouter(
    prefix="/activity",
    tags=["activity"],
)

# Separate router for WebSocket (same endpoints - no auth needed for local-only admin)
ws_router = APIRouter(
    prefix="/activity",
    tags=["activity"],
)


# --- Response Models ---


class ActivityLogResponse(BaseModel):
    """Single activity log entry."""

    id: UUID
    server_id: UUID | None = None
    log_type: str
    level: str
    message: str
    details: dict | None = None
    request_id: str | None = None
    duration_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityLogsListResponse(BaseModel):
    """Paginated list of activity logs."""

    items: list[ActivityLogResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ActivityStatsResponse(BaseModel):
    """Aggregate activity statistics."""

    total: int
    errors: int
    avg_duration_ms: float
    by_type: dict[str, int]
    by_level: dict[str, int]
    requests_per_minute: float


class RecentActivityResponse(BaseModel):
    """Recent activity from in-memory buffer."""

    logs: list[dict]
    count: int


# --- Endpoints ---


@router.get("/logs", response_model=ActivityLogsListResponse)
async def list_activity_logs(
    db: AsyncSession = Depends(get_db),
    server_id: UUID | None = Query(None, description="Filter by server ID"),
    log_type: str | None = Query(
        None, description="Filter by log type (mcp_request, mcp_response, error, alert)"
    ),
    level: str | None = Query(None, description="Filter by level (debug, info, warning, error)"),
    request_id: str | None = Query(None, description="Filter by request ID"),
    since: datetime | None = Query(None, description="Filter logs after this time"),
    until: datetime | None = Query(None, description="Filter logs before this time"),
    search: str | None = Query(None, description="Search in message text"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
) -> ActivityLogsListResponse:
    """List activity logs with filtering and pagination.

    Returns paginated list of activity logs matching the specified filters.
    """
    # Build query
    query = select(ActivityLog)

    # Apply filters
    if server_id:
        query = query.where(ActivityLog.server_id == server_id)
    if log_type:
        query = query.where(ActivityLog.log_type == log_type)
    if level:
        query = query.where(ActivityLog.level == level)
    if request_id:
        query = query.where(ActivityLog.request_id == request_id)
    if since:
        query = query.where(ActivityLog.created_at >= since)
    if until:
        query = query.where(ActivityLog.created_at <= until)
    if search:
        # Escape LIKE special characters to prevent pattern injection
        search_escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(ActivityLog.message.ilike(f"%{search_escaped}%", escape="\\"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(desc(ActivityLog.created_at))
    query = query.offset((page - 1) * page_size).limit(page_size)

    # Execute query
    result = await db.execute(query)
    logs = result.scalars().all()

    pages = (total + page_size - 1) // page_size if total > 0 else 0

    return ActivityLogsListResponse(
        items=[ActivityLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/logs/{log_id}", response_model=ActivityLogResponse)
async def get_activity_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ActivityLogResponse:
    """Get a single activity log by ID."""
    result = await db.execute(select(ActivityLog).where(ActivityLog.id == log_id))
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity log not found")

    return ActivityLogResponse.model_validate(log)


@router.get("/stats", response_model=ActivityStatsResponse)
async def get_activity_stats(
    db: AsyncSession = Depends(get_db),
    server_id: UUID | None = Query(None, description="Filter by server ID"),
    period: str = Query(
        "1h", description="Time period: 1h, 6h, 24h, 7d", pattern="^(1h|6h|24h|7d)$"
    ),
) -> ActivityStatsResponse:
    """Get aggregate activity statistics.

    Returns counts, error rates, and timing statistics for the specified period.
    """
    # Calculate time window
    period_map = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    since = datetime.now(UTC) - period_map.get(period, timedelta(hours=1))

    # Base query conditions
    conditions = [ActivityLog.created_at >= since]
    if server_id:
        conditions.append(ActivityLog.server_id == server_id)

    # Get basic stats
    stats_query = select(
        func.count(ActivityLog.id).label("total"),
        func.count(ActivityLog.id).filter(ActivityLog.level == "error").label("errors"),
        func.avg(ActivityLog.duration_ms)
        .filter(ActivityLog.duration_ms.isnot(None))
        .label("avg_duration"),
    ).where(*conditions)

    result = await db.execute(stats_query)
    # Aggregate queries always return one row, but use first() for safety
    row = result.first()
    if not row:
        # Should never happen with COUNT, but handle gracefully
        return ActivityStatsResponse(
            total=0,
            errors=0,
            avg_duration_ms=0.0,
            by_type={},
            by_level={},
            requests_per_minute=0.0,
        )

    # Get counts by type
    type_query = (
        select(
            ActivityLog.log_type,
            func.count(ActivityLog.id).label("count"),
        )
        .where(*conditions)
        .group_by(ActivityLog.log_type)
    )
    type_result = await db.execute(type_query)
    by_type: dict[str, int] = {r.log_type: r[1] for r in type_result}  # [log_type, count]

    # Get counts by level
    level_query = (
        select(
            ActivityLog.level,
            func.count(ActivityLog.id).label("count"),
        )
        .where(*conditions)
        .group_by(ActivityLog.level)
    )
    level_result = await db.execute(level_query)
    by_level: dict[str, int] = {r.level: r[1] for r in level_result}  # [level, count]

    # Calculate requests per minute
    total_minutes = period_map.get(period, timedelta(hours=1)).total_seconds() / 60
    requests_per_minute = (row.total or 0) / total_minutes if total_minutes > 0 else 0

    return ActivityStatsResponse(
        total=row.total or 0,
        errors=row.errors or 0,
        avg_duration_ms=round(row.avg_duration or 0, 2),
        by_type=by_type,
        by_level=by_level,
        requests_per_minute=round(requests_per_minute, 2),
    )


@router.get("/recent", response_model=RecentActivityResponse)
async def get_recent_activity(
    activity_logger: ActivityLoggerService = Depends(get_activity_logger),
    count: int = Query(100, ge=1, le=1000, description="Number of recent logs"),
) -> RecentActivityResponse:
    """Get recent activity from in-memory buffer.

    Returns the most recent logs from the broadcast buffer without database query.
    Useful for real-time display before WebSocket connection is established.
    """
    logs = activity_logger.get_recent_logs(count)
    return RecentActivityResponse(logs=logs, count=len(logs))


@router.delete("/logs")
async def cleanup_old_logs(
    db: AsyncSession = Depends(get_db),
    activity_logger: ActivityLoggerService = Depends(get_activity_logger),
    retention_days: int = Query(7, ge=1, le=90, description="Days to retain logs"),
) -> dict[str, Any]:
    """Delete logs older than retention period.

    Returns the number of deleted logs.
    """
    deleted_count = await activity_logger.cleanup_old_logs(db, retention_days)
    return {"deleted_count": deleted_count, "retention_days": retention_days}


@router.get("/request/{request_id}")
async def get_request_chain(
    request_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all logs for a specific request ID.

    Returns request and response logs for correlation/debugging.
    """
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.request_id == request_id)
        .order_by(ActivityLog.created_at)
    )
    logs = result.scalars().all()

    return {
        "request_id": request_id,
        "logs": [ActivityLogResponse.model_validate(log) for log in logs],
        "count": len(logs),
    }


# --- WebSocket Live Stream ---


class WebSocketConnection:
    """Manages a single WebSocket connection with filtering."""

    def __init__(
        self,
        websocket: WebSocket,
        server_id: str | None = None,
        log_types: list[str] | None = None,
        levels: list[str] | None = None,
    ):
        self.websocket = websocket
        self.server_id = server_id
        self.log_types = log_types
        self.levels = levels
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    def matches_filter(self, log_entry: dict) -> bool:
        """Check if log entry matches this connection's filters."""
        if self.server_id and log_entry.get("server_id") != self.server_id:
            return False
        if self.log_types and log_entry.get("log_type") not in self.log_types:
            return False
        if self.levels and log_entry.get("level") not in self.levels:
            return False
        return True


# Global connection manager
_active_connections: list[WebSocketConnection] = []


async def _broadcast_log(log_entry: dict[str, Any]) -> None:
    """Broadcast log entry to all matching WebSocket connections."""
    async with _connections_lock:
        connections_snapshot = _active_connections[:]

    for conn in connections_snapshot:
        if conn.matches_filter(log_entry):
            try:
                await conn.queue.put(log_entry)
            except asyncio.QueueFull:
                # Skip if queue is full (slow consumer)
                logger.warning("WebSocket queue full, dropping log entry")
            except Exception as e:
                # Handle any other unexpected errors (closed queue, etc.)
                logger.warning(f"Failed to queue log for WebSocket connection: {e}")


def _register_websocket_listener() -> None:
    """Register the broadcast function with the activity logger."""
    activity_logger = get_activity_logger()
    activity_logger.add_listener(_broadcast_log)


# Register listener on module load
_register_websocket_listener()


@ws_router.websocket("/stream")
async def activity_stream(
    websocket: WebSocket,
    server_id: str | None = None,
    log_types: str | None = None,
    levels: str | None = None,
) -> None:
    """WebSocket endpoint for live activity log streaming.

    Query parameters:
    - server_id: Filter by server UUID
    - log_types: Comma-separated log types (e.g., "mcp_request,mcp_response")
    - levels: Comma-separated levels (e.g., "info,error")

    Messages sent are JSON objects with log entry data.

    No authentication required - admin panel is local-only (Option B architecture).
    """
    await websocket.accept()

    # Parse filters
    parsed_log_types = log_types.split(",") if log_types else None
    parsed_levels = levels.split(",") if levels else None

    conn = WebSocketConnection(
        websocket=websocket,
        server_id=server_id,
        log_types=parsed_log_types,
        levels=parsed_levels,
    )

    async with _connections_lock:
        _active_connections.append(conn)
        connection_count = len(_active_connections)
    logger.info(f"WebSocket connected, total connections: {connection_count}")

    try:
        # Send initial message
        await websocket.send_json(
            {
                "type": "connected",
                "message": "Activity stream connected",
                "filters": {
                    "server_id": server_id,
                    "log_types": parsed_log_types,
                    "levels": parsed_levels,
                },
            }
        )

        # Create tasks for receiving and sending
        async def send_logs() -> None:
            """Send logs from queue to WebSocket."""
            while True:
                log_entry = await conn.queue.get()
                try:
                    await websocket.send_json(
                        {
                            "type": "log",
                            "data": log_entry,
                        }
                    )
                except Exception as e:
                    logger.debug(f"WebSocket send failed, closing sender: {e}")
                    break

        async def receive_messages() -> None:
            """Handle incoming messages (for filter updates, ping/pong)."""
            while True:
                try:
                    data = await websocket.receive_json()
                    msg_type = data.get("type")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg_type == "filter":
                        # Update filters
                        if "server_id" in data:
                            conn.server_id = data["server_id"]
                        if "log_types" in data:
                            conn.log_types = data["log_types"]
                        if "levels" in data:
                            conn.levels = data["levels"]
                        await websocket.send_json(
                            {
                                "type": "filter_updated",
                                "filters": {
                                    "server_id": conn.server_id,
                                    "log_types": conn.log_types,
                                    "levels": conn.levels,
                                },
                            }
                        )
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.warning(f"WebSocket receive error: {e}")
                    break

        # Run both tasks concurrently with proper cleanup
        # Initialize tasks list before creating tasks to ensure cleanup on any error
        tasks: list[asyncio.Task] = []
        try:
            send_task = asyncio.create_task(send_logs())
            tasks.append(send_task)
            receive_task = asyncio.create_task(receive_messages())
            tasks.append(receive_task)

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Log exceptions from completed tasks (don't re-raise for graceful cleanup)
            for task in done:
                exc = task.exception() if not task.cancelled() else None
                if exc is not None:
                    logger.warning(f"WebSocket task exception: {exc}")

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except Exception:
            # If an exception occurs at any point, ensure all tasks are cancelled
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            raise

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        async with _connections_lock:
            if conn in _active_connections:
                _active_connections.remove(conn)
            remaining = len(_active_connections)
        logger.info(f"WebSocket closed, remaining connections: {remaining}")
