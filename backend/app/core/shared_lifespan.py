"""Shared lifespan logic for main app and MCP gateway.

Both backend/app/main.py and backend/app/mcp_only.py share the same core
startup/shutdown sequence. This module extracts the common parts to avoid
duplication (see docs/CONSIDER-REMOVING.md §9a).
"""

import asyncio
import logging

from app.core import async_session_maker, settings, setup_logging
from app.core.logging import get_logger
from app.middleware import rate_limit_cleanup_loop
from app.services.activity_logger import ActivityLoggerService
from app.services.log_retention import LogRetentionService
from app.services.sandbox_client import SandboxClient
from app.services.service_token_cache import ServiceTokenCache

_logger = get_logger("lifespan")


def task_done_callback(task: asyncio.Task[None]) -> None:
    """Log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(f"Background task {task.get_name()} failed: {exc}")


async def _session_cleanup_loop(logger: logging.Logger) -> None:
    """Periodically remove expired MCP gateway sessions."""
    from app.api.mcp_gateway import cleanup_expired_sessions

    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        try:
            removed = await cleanup_expired_sessions()
            if removed > 0:
                logger.info(f"Cleaned up {removed} expired MCP sessions")
        except Exception:
            logger.exception("Error cleaning up MCP sessions")


async def common_startup(logger: logging.Logger) -> list[asyncio.Task]:
    """Shared startup sequence for both entry points.

    Initialises logging, activity logger, service token cache, security
    checks, log retention, and common background tasks (rate-limit cleanup,
    session cleanup, server recovery).

    Returns a list of managed background tasks that must be cancelled on
    shutdown via ``common_shutdown``.
    """
    # Configure logging
    setup_logging(
        level=settings.log_level,
        format_type="structured" if not settings.debug else "dev",
    )

    # Initialize activity logger with database session factory
    activity_logger = ActivityLoggerService.get_instance()
    activity_logger.set_db_session_factory(async_session_maker)

    # Load service token from database
    service_token_cache = ServiceTokenCache.get_instance()
    await service_token_cache.load()

    # Load MCP rate limit from database (falls back to default 300 if not set)
    async with async_session_maker() as db:
        from app.services.setting import SettingService

        setting_service = SettingService(db)
        mcp_rpm_str = await setting_service.get_value("mcp_rate_limit_rpm", default="300")
        mcp_rpm = int(mcp_rpm_str)  # type: ignore[arg-type]

        from app.middleware.rate_limit import RateLimiter

        RateLimiter.get_instance().update_mcp_config(mcp_rpm)
        _logger.info(f"MCP rate limit loaded from settings: {mcp_rpm} rpm")

    # Check security configuration
    security_warnings = settings.check_security_configuration()
    for warning in security_warnings:
        logger.warning(f"SECURITY: {warning}")

    # Start log retention service
    log_retention_service = LogRetentionService.get_instance()
    log_retention_service.retention_days = settings.log_retention_days
    await log_retention_service.start()

    # Background tasks (returned so callers can extend + cancel on shutdown)
    tasks: list[asyncio.Task] = []

    rate_limit_task = asyncio.create_task(rate_limit_cleanup_loop())
    rate_limit_task.add_done_callback(task_done_callback)
    tasks.append(rate_limit_task)

    session_task = asyncio.create_task(_session_cleanup_loop(logger))
    session_task.add_done_callback(task_done_callback)
    tasks.append(session_task)

    # Re-register servers that were "running" before container restart
    from app.services.server_recovery import recover_running_servers

    recovery_task = asyncio.create_task(recover_running_servers())
    recovery_task.add_done_callback(task_done_callback)
    # recovery_task is fire-and-forget — not added to managed tasks

    return tasks


async def common_shutdown(
    logger: logging.Logger,
    tasks: list[asyncio.Task],
) -> None:
    """Shared shutdown sequence for both entry points.

    Cancels managed background tasks, stops log retention, and closes
    the sandbox HTTP client.
    """
    for task in tasks:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Stop log retention service
    log_retention_service = LogRetentionService.get_instance()
    await log_retention_service.stop()

    # Close sandbox client HTTP connection
    sandbox_client = SandboxClient.get_instance()
    await sandbox_client.close()
