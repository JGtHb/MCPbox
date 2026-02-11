"""Log retention service - automatically cleans up old activity logs."""

import asyncio
import threading
from typing import Optional

from app.core import async_session_maker
from app.core.logging import get_logger
from app.services.activity_logger import ActivityLoggerService

logger = get_logger("log_retention")

# How often to run cleanup (in seconds)
CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour

# Default retention period (can be overridden via API)
DEFAULT_RETENTION_DAYS = 30


class LogRetentionService:
    """Background service to automatically clean up old activity logs."""

    _instance: Optional["LogRetentionService"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _task: asyncio.Task | None = None

    def __init__(self, retention_days: int = DEFAULT_RETENTION_DAYS):
        self._running = False
        self._retention_days = retention_days

    @classmethod
    def get_instance(cls) -> "LogRetentionService":
        """Get singleton instance of log retention service (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def retention_days(self) -> int:
        """Get current retention period in days."""
        return self._retention_days

    @retention_days.setter
    def retention_days(self, value: int) -> None:
        """Set retention period in days (minimum 1 day)."""
        self._retention_days = max(1, value)
        logger.info(f"Log retention period set to {self._retention_days} days")

    async def start(self):
        """Start the background log retention task."""
        if self._running:
            logger.warning("Log retention service is already running")
            return

        self._running = True
        LogRetentionService._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"Log retention service started (retention: {self._retention_days} days, "
            f"interval: {CLEANUP_INTERVAL_SECONDS}s)"
        )

    async def stop(self):
        """Stop the background log retention task."""
        self._running = False
        if LogRetentionService._task:
            LogRetentionService._task.cancel()
            try:
                await LogRetentionService._task
            except asyncio.CancelledError:
                pass
            LogRetentionService._task = None
        logger.info("Log retention service stopped")

    async def _cleanup_loop(self):
        """Main loop that periodically cleans up old logs."""
        # Wait a bit before first cleanup to let the app start up
        await asyncio.sleep(60)

        while self._running:
            try:
                await self._run_cleanup()
            except Exception as e:
                logger.error(f"Error in log retention cleanup: {e}")

            # Wait before next cleanup
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    async def _run_cleanup(self):
        """Execute a single cleanup run."""
        activity_logger = ActivityLoggerService.get_instance()

        async with async_session_maker() as db:
            try:
                deleted_count = await activity_logger.cleanup_old_logs(
                    db=db,
                    retention_days=self._retention_days,
                )

                if deleted_count > 0:
                    logger.info(
                        f"Log retention cleanup: deleted {deleted_count} logs "
                        f"older than {self._retention_days} days"
                    )

            except Exception as e:
                logger.exception(f"Error during log cleanup: {e}")
                await db.rollback()
                raise  # Propagate to _cleanup_loop which handles logging

    async def run_cleanup_now(self) -> int:
        """Manually trigger a cleanup run.

        Returns:
            Number of logs deleted
        """
        activity_logger = ActivityLoggerService.get_instance()

        async with async_session_maker() as db:
            deleted_count = await activity_logger.cleanup_old_logs(
                db=db,
                retention_days=self._retention_days,
            )
            return deleted_count
