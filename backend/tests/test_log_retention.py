"""Tests for log retention service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.log_retention import (
    CLEANUP_INTERVAL_SECONDS,
    DEFAULT_RETENTION_DAYS,
    LogRetentionService,
)


class TestLogRetentionServiceSingleton:
    """Tests for singleton pattern and thread safety."""

    def test_get_instance_returns_same_instance(self):
        """Test that get_instance returns the same instance."""
        # Reset singleton for test
        LogRetentionService._instance = None

        instance1 = LogRetentionService.get_instance()
        instance2 = LogRetentionService.get_instance()

        assert instance1 is instance2

    def test_singleton_thread_safety(self):
        """Test that singleton is thread-safe."""
        import threading

        # Reset singleton for test
        LogRetentionService._instance = None

        instances = []
        errors = []

        def get_instance():
            try:
                instances.append(LogRetentionService.get_instance())
            except Exception as e:
                errors.append(e)

        # Create multiple threads trying to get the instance
        threads = [threading.Thread(target=get_instance) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(instances) == 10
        # All instances should be the same
        assert all(inst is instances[0] for inst in instances)

    def test_default_retention_days(self):
        """Test default retention days value."""
        LogRetentionService._instance = None
        service = LogRetentionService()
        assert service.retention_days == DEFAULT_RETENTION_DAYS


class TestLogRetentionServiceConfiguration:
    """Tests for service configuration."""

    def test_retention_days_getter_setter(self):
        """Test retention days property."""
        service = LogRetentionService()

        service.retention_days = 14
        assert service.retention_days == 14

        service.retention_days = 60
        assert service.retention_days == 60

    def test_retention_days_minimum_enforced(self):
        """Test that retention days cannot be less than 1."""
        service = LogRetentionService()

        service.retention_days = 0
        assert service.retention_days == 1

        service.retention_days = -5
        assert service.retention_days == 1

    def test_custom_retention_days_in_constructor(self):
        """Test custom retention days in constructor."""
        service = LogRetentionService(retention_days=7)
        assert service.retention_days == 7


class TestLogRetentionServiceLifecycle:
    """Tests for service start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self):
        """Test that start sets the running flag."""
        service = LogRetentionService()
        service._running = False

        with patch.object(service, "_cleanup_loop", new_callable=AsyncMock):
            await service.start()

        assert service._running is True
        await service.stop()

    @pytest.mark.asyncio
    async def test_start_twice_logs_warning(self):
        """Test that starting twice logs a warning."""
        service = LogRetentionService()
        service._running = False

        with patch.object(service, "_cleanup_loop", new_callable=AsyncMock):
            await service.start()

            # Second start should log warning
            with patch("app.services.log_retention.logger") as mock_logger:
                await service.start()
                mock_logger.warning.assert_called()

        await service.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Test that stop cancels the cleanup task."""
        service = LogRetentionService()

        # Create a proper mock task - needs to be awaitable and have cancel()
        # Use a real asyncio task that we can cancel
        async def never_ending():
            try:
                await asyncio.sleep(1000)
            except asyncio.CancelledError:
                raise

        # Create and start the task
        real_task = asyncio.create_task(never_ending())

        # Set up the service as if it's running with a task
        service._running = True
        LogRetentionService._task = real_task

        await service.stop()

        assert service._running is False
        assert real_task.cancelled() or real_task.done()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test that stop works when not running."""
        service = LogRetentionService()
        service._running = False
        LogRetentionService._task = None

        # Should not raise
        await service.stop()
        assert service._running is False


class TestLogRetentionCleanup:
    """Tests for cleanup functionality."""

    @pytest.mark.asyncio
    async def test_run_cleanup_now(self):
        """Test manual cleanup trigger."""
        service = LogRetentionService(retention_days=7)

        mock_activity_logger = MagicMock()
        mock_activity_logger.cleanup_old_logs = AsyncMock(return_value=42)

        mock_db = AsyncMock()

        with patch(
            "app.services.log_retention.ActivityLoggerService.get_instance",
            return_value=mock_activity_logger,
        ):
            with patch(
                "app.services.log_retention.async_session_maker",
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_db)),
            ):
                deleted_count = await service.run_cleanup_now()

        assert deleted_count == 42
        mock_activity_logger.cleanup_old_logs.assert_called_once_with(
            db=mock_db,
            retention_days=7,
        )

    @pytest.mark.asyncio
    async def test_cleanup_loop_handles_errors(self):
        """Test that cleanup loop handles errors gracefully."""
        service = LogRetentionService()
        service._running = True

        call_count = 0

        async def mock_run_cleanup():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Test error")
            # Stop after second call
            service._running = False

        with patch.object(service, "_run_cleanup", side_effect=mock_run_cleanup):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("app.services.log_retention.logger") as mock_logger:
                    await service._cleanup_loop()

                    # Error should be logged
                    mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_run_cleanup_logs_deleted_count(self):
        """Test that cleanup logs the deleted count when > 0."""
        service = LogRetentionService(retention_days=7)

        mock_activity_logger = MagicMock()
        mock_activity_logger.cleanup_old_logs = AsyncMock(return_value=100)

        mock_db = AsyncMock()
        mock_db.rollback = AsyncMock()

        with patch(
            "app.services.log_retention.ActivityLoggerService.get_instance",
            return_value=mock_activity_logger,
        ):
            with patch(
                "app.services.log_retention.async_session_maker",
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_db)),
            ):
                with patch("app.services.log_retention.logger") as mock_logger:
                    await service._run_cleanup()

                    # Should log the deleted count
                    mock_logger.info.assert_called()
                    call_args = str(mock_logger.info.call_args)
                    assert "100" in call_args

    @pytest.mark.asyncio
    async def test_run_cleanup_handles_db_error(self):
        """Test that cleanup handles database errors."""
        service = LogRetentionService()

        mock_activity_logger = MagicMock()
        mock_activity_logger.cleanup_old_logs = AsyncMock(side_effect=Exception("DB error"))

        mock_db = AsyncMock()
        mock_db.rollback = AsyncMock()

        with patch(
            "app.services.log_retention.ActivityLoggerService.get_instance",
            return_value=mock_activity_logger,
        ):
            with patch(
                "app.services.log_retention.async_session_maker",
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_db)),
            ):
                with pytest.raises(Exception, match="DB error"):
                    await service._run_cleanup()

                # Rollback should be called
                mock_db.rollback.assert_called_once()


class TestLogRetentionConstants:
    """Tests for service constants."""

    def test_cleanup_interval_seconds(self):
        """Test that cleanup interval is reasonable."""
        assert CLEANUP_INTERVAL_SECONDS >= 60  # At least 1 minute
        assert CLEANUP_INTERVAL_SECONDS <= 86400  # At most 24 hours

    def test_default_retention_days(self):
        """Test that default retention is reasonable."""
        assert DEFAULT_RETENTION_DAYS >= 1
        assert DEFAULT_RETENTION_DAYS <= 365
