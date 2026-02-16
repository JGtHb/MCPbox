"""Dashboard API endpoints for aggregated statistics.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.models import ActivityLog, Server, Tool

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
)


# --- Response Models ---


class ServerSummary(BaseModel):
    """Summary of a server for dashboard display."""

    id: UUID
    name: str
    status: str
    tool_count: int
    requests_24h: int
    errors_24h: int


class TimeSeriesPoint(BaseModel):
    """Single point in a time series."""

    timestamp: datetime
    value: int


class DashboardStats(BaseModel):
    """Overall dashboard statistics."""

    total_servers: int = 0
    active_servers: int = 0
    total_tools: int = 0
    enabled_tools: int = 0
    total_requests_24h: int = 0
    total_errors_24h: int = 0
    error_rate_24h: float = 0.0
    avg_response_time_ms: float = 0.0


class TopTool(BaseModel):
    """Top tool by usage."""

    tool_name: str
    server_name: str
    invocations: int
    avg_duration_ms: float


class RecentError(BaseModel):
    """Recent error for display."""

    timestamp: datetime
    server_name: str | None
    message: str
    tool_name: str | None


class DashboardResponse(BaseModel):
    """Complete dashboard data response."""

    stats: DashboardStats
    servers: list[ServerSummary] = Field(default_factory=list)
    requests_over_time: list[TimeSeriesPoint] = Field(default_factory=list)
    errors_over_time: list[TimeSeriesPoint] = Field(default_factory=list)
    top_tools: list[TopTool] = Field(default_factory=list)
    recent_errors: list[RecentError] = Field(default_factory=list)


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    period: str = Query(
        "24h", description="Time period: 1h, 6h, 24h, 7d", pattern="^(1h|6h|24h|7d)$"
    ),
) -> DashboardResponse:
    """Get comprehensive dashboard statistics.

    Returns aggregated stats, server summaries, time series data, and recent errors.
    """
    # Calculate time window
    period_map = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    delta = period_map.get(period, timedelta(hours=24))
    since = datetime.now(UTC) - delta

    # Get basic counts
    server_count_result = await db.execute(select(func.count(Server.id)))
    total_servers = server_count_result.scalar() or 0

    active_servers_result = await db.execute(
        select(func.count(Server.id)).where(Server.status == "running")
    )
    active_servers = active_servers_result.scalar() or 0

    tool_count_result = await db.execute(select(func.count(Tool.id)))
    total_tools = tool_count_result.scalar() or 0

    enabled_tools_result = await db.execute(
        select(func.count(Tool.id)).where(Tool.enabled.is_(True))
    )
    enabled_tools = enabled_tools_result.scalar() or 0

    # Get activity stats for period
    activity_stats = await db.execute(
        select(
            func.count(ActivityLog.id).label("total"),
            func.count(ActivityLog.id).filter(ActivityLog.level == "error").label("errors"),
            func.avg(ActivityLog.duration_ms)
            .filter(ActivityLog.duration_ms.isnot(None))
            .label("avg_duration"),
        ).where(ActivityLog.created_at >= since)
    )
    activity_row = activity_stats.first()
    total_requests = activity_row.total if activity_row else 0
    total_errors = activity_row.errors if activity_row else 0
    avg_duration = (
        activity_row.avg_duration if activity_row and activity_row.avg_duration is not None else 0
    )

    error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

    stats = DashboardStats(
        total_servers=total_servers,
        active_servers=active_servers,
        total_tools=total_tools,
        enabled_tools=enabled_tools,
        total_requests_24h=total_requests,
        total_errors_24h=total_errors,
        error_rate_24h=round(error_rate, 2),
        avg_response_time_ms=round(avg_duration, 2),
    )

    # Get server summaries with request counts (optimized: 4 queries instead of N+1)
    servers_result = await db.execute(select(Server).order_by(desc(Server.created_at)).limit(10))
    servers = servers_result.scalars().all()
    server_ids = [s.id for s in servers]

    # Batch query: tool counts per server
    tool_counts_result = await db.execute(
        select(Tool.server_id, func.count(Tool.id).label("count"))
        .where(Tool.server_id.in_(server_ids))
        .group_by(Tool.server_id)
    )
    tool_counts: dict[UUID, int] = {
        row.server_id: row[1]
        for row in tool_counts_result  # [server_id, count]
    }

    # Batch query: request counts per server
    request_counts_result = await db.execute(
        select(ActivityLog.server_id, func.count(ActivityLog.id).label("count"))
        .where(
            ActivityLog.server_id.in_(server_ids),
            ActivityLog.created_at >= since,
        )
        .group_by(ActivityLog.server_id)
    )
    request_counts: dict[UUID, int] = {
        row.server_id: row[1]
        for row in request_counts_result  # [server_id, count]
    }

    # Batch query: error counts per server
    error_counts_result = await db.execute(
        select(ActivityLog.server_id, func.count(ActivityLog.id).label("count"))
        .where(
            ActivityLog.server_id.in_(server_ids),
            ActivityLog.level == "error",
            ActivityLog.created_at >= since,
        )
        .group_by(ActivityLog.server_id)
    )
    error_counts: dict[UUID, int] = {
        row.server_id: row[1]
        for row in error_counts_result  # [server_id, count]
    }

    server_summaries = [
        ServerSummary(
            id=server.id,
            name=server.name,
            status=server.status or "unknown",
            tool_count=tool_counts.get(server.id, 0),
            requests_24h=request_counts.get(server.id, 0),
            errors_24h=error_counts.get(server.id, 0),
        )
        for server in servers
    ]

    # Get time series data (hourly buckets for 24h, 10-minute for shorter)
    bucket_minutes = 60 if period in ("24h", "7d") else 10
    time_series_points = []
    error_series_points = []

    # Generate time buckets
    current = since.replace(minute=0, second=0, microsecond=0)
    while current <= datetime.now(UTC):
        bucket_end = current + timedelta(minutes=bucket_minutes)

        request_count = await db.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.created_at >= current,
                ActivityLog.created_at < bucket_end,
            )
        )

        error_count = await db.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.created_at >= current,
                ActivityLog.created_at < bucket_end,
                ActivityLog.level == "error",
            )
        )

        time_series_points.append(
            TimeSeriesPoint(timestamp=current, value=request_count.scalar() or 0)
        )
        error_series_points.append(
            TimeSeriesPoint(timestamp=current, value=error_count.scalar() or 0)
        )

        current = bucket_end

    # Get top tools by invocation count
    # Use a labeled expression for consistent GROUP BY handling in PostgreSQL
    tool_name_expr = ActivityLog.details["tool_name"].astext
    top_tools_query = (
        select(
            tool_name_expr.label("tool_name"),
            func.count(ActivityLog.id).label("invocations"),
            func.avg(ActivityLog.duration_ms).label("avg_duration"),
        )
        .where(
            ActivityLog.created_at >= since,
            ActivityLog.log_type == "mcp_response",
            tool_name_expr.isnot(None),
        )
        .group_by(tool_name_expr)
        .order_by(desc("invocations"))
        .limit(5)
    )

    top_tools_result = await db.execute(top_tools_query)
    top_tools = []
    for row in top_tools_result:
        if row.tool_name:
            top_tools.append(
                TopTool(
                    tool_name=row.tool_name,
                    server_name="",  # Would need join to get server name
                    invocations=row.invocations,
                    avg_duration_ms=round(row.avg_duration or 0, 2),
                )
            )

    # Get recent errors
    recent_errors_result = await db.execute(
        select(ActivityLog)
        .where(
            ActivityLog.level == "error",
            ActivityLog.created_at >= since,
        )
        .order_by(desc(ActivityLog.created_at))
        .limit(10)
    )
    recent_errors = []
    for log in recent_errors_result.scalars():
        tool_name = None
        if log.details and "tool_name" in log.details:
            tool_name = log.details["tool_name"]

        recent_errors.append(
            RecentError(
                timestamp=log.created_at,
                server_name=None,  # Would need join
                message=log.message[:200] if len(log.message) > 200 else log.message,
                tool_name=tool_name,
            )
        )

    return DashboardResponse(
        stats=stats,
        servers=server_summaries,
        requests_over_time=time_series_points,
        errors_over_time=error_series_points,
        top_tools=top_tools,
        recent_errors=recent_errors,
    )
