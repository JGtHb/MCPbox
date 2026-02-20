"""Tests for the ActivityLoggerService."""

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog
from app.services.activity_logger import ActivityLoggerService, get_activity_logger

# --- Test Utilities ---


async def wait_for_condition(
    condition_fn,
    timeout: float = 2.0,
    poll_interval: float = 0.01,
    description: str = "condition",
):
    """Wait for a condition to become true with polling.

    More reliable than fixed sleep() calls for async tests on slow CI systems.

    Args:
        condition_fn: Callable that returns True when condition is met
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds
        description: Description for error message

    Raises:
        TimeoutError: If condition not met within timeout
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if condition_fn():
            return
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Timed out waiting for {description}")


# --- Test Fixtures ---


@pytest.fixture
def activity_logger():
    """Create a fresh ActivityLoggerService instance for testing."""
    # Reset singleton for testing
    ActivityLoggerService._instance = None
    service = ActivityLoggerService()
    yield service
    # Reset after test
    ActivityLoggerService._instance = None


@pytest.fixture
def mock_db_session():
    """Create a mock database session factory."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def session_factory():
        return mock_session

    # Create async context manager
    class MockContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    return MagicMock(return_value=MockContextManager())


# --- Test Singleton Pattern ---


def test_get_instance_returns_singleton():
    """Test that get_instance returns the same instance."""
    ActivityLoggerService._instance = None

    instance1 = ActivityLoggerService.get_instance()
    instance2 = ActivityLoggerService.get_instance()

    assert instance1 is instance2

    ActivityLoggerService._instance = None


def test_get_activity_logger_helper():
    """Test the convenience function returns singleton."""
    ActivityLoggerService._instance = None

    logger1 = get_activity_logger()
    logger2 = get_activity_logger()

    assert logger1 is logger2

    ActivityLoggerService._instance = None


# --- Test Listener Management ---


def test_add_listener(activity_logger):
    """Test adding a listener."""
    callback = MagicMock()

    activity_logger.add_listener(callback)

    assert callback in activity_logger._listeners


def test_add_listener_no_duplicates(activity_logger):
    """Test that the same listener isn't added twice."""
    callback = MagicMock()

    activity_logger.add_listener(callback)
    activity_logger.add_listener(callback)

    assert activity_logger._listeners.count(callback) == 1


def test_remove_listener(activity_logger):
    """Test removing a listener."""
    callback = MagicMock()
    activity_logger.add_listener(callback)

    activity_logger.remove_listener(callback)

    assert callback not in activity_logger._listeners


def test_remove_nonexistent_listener(activity_logger):
    """Test removing a listener that doesn't exist doesn't raise."""
    callback = MagicMock()

    # Should not raise
    activity_logger.remove_listener(callback)


# --- Test Log Entry Creation ---


@pytest.mark.asyncio
async def test_log_creates_entry(activity_logger):
    """Test that log() creates a log entry."""
    entry = await activity_logger.log(
        log_type="system",
        message="Test message",
        level="info",
    )

    assert entry["log_type"] == "system"
    assert entry["message"] == "Test message"
    assert entry["level"] == "info"
    assert "id" in entry
    assert "created_at" in entry


@pytest.mark.asyncio
async def test_log_with_server_id(activity_logger):
    """Test log entry with server_id."""
    server_id = uuid4()

    entry = await activity_logger.log(
        log_type="mcp_request",
        message="Test",
        server_id=server_id,
    )

    assert entry["server_id"] == str(server_id)


@pytest.mark.asyncio
async def test_log_with_details(activity_logger):
    """Test log entry with details dict."""
    details = {"key": "value", "nested": {"data": 123}}

    entry = await activity_logger.log(
        log_type="system",
        message="Test",
        details=details,
    )

    assert entry["details"] == details


@pytest.mark.asyncio
async def test_log_with_request_id(activity_logger):
    """Test log entry with request correlation ID."""
    entry = await activity_logger.log(
        log_type="mcp_request",
        message="Test",
        request_id="abc123",
    )

    assert entry["request_id"] == "abc123"


@pytest.mark.asyncio
async def test_log_with_duration_ms(activity_logger):
    """Test log entry with duration."""
    entry = await activity_logger.log(
        log_type="mcp_response",
        message="Test",
        duration_ms=150,
    )

    assert entry["duration_ms"] == 150


@pytest.mark.asyncio
async def test_log_adds_to_broadcast_buffer(activity_logger):
    """Test that logs are added to the broadcast buffer."""
    await activity_logger.log(log_type="system", message="Test 1")
    await activity_logger.log(log_type="system", message="Test 2")

    recent = activity_logger.get_recent_logs(10)

    assert len(recent) == 2
    assert recent[0]["message"] == "Test 1"
    assert recent[1]["message"] == "Test 2"


@pytest.mark.asyncio
async def test_broadcast_buffer_max_size(activity_logger):
    """Test that broadcast buffer respects max size."""
    # Override buffer size for test
    activity_logger._broadcast_buffer = deque(maxlen=5)

    for i in range(10):
        await activity_logger.log(log_type="system", message=f"Test {i}")

    recent = activity_logger.get_recent_logs(100)

    assert len(recent) == 5
    # Should have newest entries
    assert recent[0]["message"] == "Test 5"
    assert recent[4]["message"] == "Test 9"


# --- Test MCP Request/Response Logging ---


@pytest.mark.asyncio
async def test_log_mcp_request(activity_logger):
    """Test logging an MCP request (tools/call only)."""
    request_id = await activity_logger.log_mcp_request(
        method="tools/call",
        params={"name": "some_tool", "arguments": {}},
    )

    assert request_id is not None
    assert len(request_id) == 8  # Short UUID

    recent = activity_logger.get_recent_logs(1)
    assert recent[0]["log_type"] == "mcp_request"
    assert recent[0]["details"]["method"] == "tools/call"


@pytest.mark.asyncio
async def test_log_mcp_request_with_tool_call(activity_logger):
    """Test logging a tool call request."""
    await activity_logger.log_mcp_request(
        method="tools/call",
        params={"name": "my_tool", "arguments": {}},
    )

    recent = activity_logger.get_recent_logs(1)
    assert "my_tool" in recent[0]["message"]
    assert recent[0]["details"]["tool_name"] == "my_tool"


@pytest.mark.asyncio
async def test_log_mcp_response_success(activity_logger):
    """Test logging a successful MCP response."""
    await activity_logger.log_mcp_response(
        request_id="abc123",
        success=True,
        duration_ms=50,
        method="tools/list",
    )

    recent = activity_logger.get_recent_logs(1)
    assert recent[0]["log_type"] == "mcp_response"
    assert recent[0]["level"] == "info"
    assert "completed" in recent[0]["message"]
    assert recent[0]["duration_ms"] == 50


@pytest.mark.asyncio
async def test_log_mcp_response_error(activity_logger):
    """Test logging a failed MCP response."""
    await activity_logger.log_mcp_response(
        request_id="abc123",
        success=False,
        duration_ms=100,
        error="Something went wrong",
    )

    recent = activity_logger.get_recent_logs(1)
    assert recent[0]["level"] == "error"
    assert "failed" in recent[0]["message"]
    assert recent[0]["details"]["error"] == "Something went wrong"


# --- Test Alert and Error Logging ---


@pytest.mark.asyncio
async def test_log_alert(activity_logger):
    """Test logging an alert."""
    await activity_logger.log_alert(
        alert_type="high_latency",
        message="Latency exceeded threshold",
        details={"latency_ms": 5000},
    )

    recent = activity_logger.get_recent_logs(1)
    assert recent[0]["log_type"] == "alert"
    assert recent[0]["level"] == "warning"
    assert recent[0]["details"]["alert_type"] == "high_latency"


@pytest.mark.asyncio
async def test_log_error(activity_logger):
    """Test logging an error."""
    exc = ValueError("Test exception")

    await activity_logger.log_error(
        message="An error occurred",
        error=exc,
    )

    recent = activity_logger.get_recent_logs(1)
    assert recent[0]["log_type"] == "error"
    assert recent[0]["level"] == "error"
    assert recent[0]["details"]["error_type"] == "ValueError"
    assert recent[0]["details"]["error_message"] == "Test exception"


# --- Test Parameter Sanitization ---


@pytest.mark.asyncio
async def test_sanitize_params_redacts_sensitive_keys(activity_logger):
    """Test that sensitive parameter values are redacted."""
    params = {
        "username": "testuser",
        "password": "secret123",
        "api_key": "sk-abc123",
        "data": "not sensitive",
    }

    sanitized = activity_logger._sanitize_params_for_logging(params)

    assert sanitized["username"] == "testuser"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["data"] == "not sensitive"


@pytest.mark.asyncio
async def test_sanitize_params_redacts_nested_sensitive_keys(activity_logger):
    """Test that nested sensitive values are redacted."""
    params = {
        "config": {  # "config" is not sensitive, but nested keys may be
            "api_token": "bearer-token",
            "user": "admin",
        }
    }

    sanitized = activity_logger._sanitize_params_for_logging(params)

    # "api_token" contains "token" which is sensitive
    assert sanitized["config"]["api_token"] == "[REDACTED]"
    # "user" is not sensitive
    assert sanitized["config"]["user"] == "admin"


@pytest.mark.asyncio
async def test_sanitize_params_truncates_long_values(activity_logger):
    """Test that long string values are truncated."""
    long_value = "x" * 300
    params = {"data": long_value}

    sanitized = activity_logger._sanitize_params_for_logging(params)

    assert len(sanitized["data"]) == 200 + len("...[truncated]")
    assert sanitized["data"].endswith("...[truncated]")


@pytest.mark.asyncio
async def test_sanitize_params_handles_none(activity_logger):
    """Test that None params are handled."""
    assert activity_logger._sanitize_params_for_logging(None) is None


# --- Test Listener Notification ---


@pytest.mark.asyncio
async def test_notify_listeners_async(activity_logger):
    """Test that async listeners are called."""
    received = []

    async def async_listener(log_entry):
        received.append(log_entry)

    activity_logger.add_listener(async_listener)

    await activity_logger.log(log_type="system", message="Test")

    # Wait for notification task with polling (more reliable than fixed sleep)
    await wait_for_condition(
        lambda: len(received) >= 1,
        description="async listener notification",
    )

    assert len(received) == 1
    assert received[0]["message"] == "Test"


@pytest.mark.asyncio
async def test_notify_listeners_sync(activity_logger):
    """Test that sync listeners are called."""
    received = []

    def sync_listener(log_entry):
        received.append(log_entry)

    activity_logger.add_listener(sync_listener)

    await activity_logger.log(log_type="system", message="Test")

    # Wait for notification task with polling (more reliable than fixed sleep)
    await wait_for_condition(
        lambda: len(received) >= 1,
        description="sync listener notification",
    )

    assert len(received) == 1


@pytest.mark.asyncio
async def test_notify_listeners_handles_errors(activity_logger):
    """Test that listener errors don't break logging."""

    def bad_listener(log_entry):
        raise ValueError("Listener error")

    activity_logger.add_listener(bad_listener)

    # Should not raise
    await activity_logger.log(log_type="system", message="Test")


# --- Test Database Batch Flushing ---


@pytest.mark.asyncio
async def test_batch_flush_schedules_task(activity_logger, mock_db_session):
    """Test that logging schedules a batch flush task."""
    activity_logger.set_db_session_factory(mock_db_session)

    await activity_logger.log(log_type="system", message="Test")

    assert activity_logger._batch_task_scheduled


@pytest.mark.asyncio
async def test_batch_flush_writes_to_db(activity_logger):
    """Test that batch flush writes logs to database."""
    # Create a mock session that tracks added logs
    added_logs = []

    mock_session = AsyncMock()
    mock_session.add = lambda log: added_logs.append(log)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    class MockContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    activity_logger.set_db_session_factory(lambda: MockContextManager())

    # Add a log and wait for flush
    await activity_logger.log(log_type="system", message="Test")

    # Wait for batch flush with polling (more reliable than fixed sleep)
    await wait_for_condition(
        lambda: len(added_logs) >= 1,
        description="batch flush to database",
    )

    assert len(added_logs) >= 1
    assert added_logs[0].message == "Test"


@pytest.mark.asyncio
async def test_batch_flush_handles_db_error(activity_logger):
    """Test that database errors don't lose logs."""
    commit_called = []
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    async def mock_commit():
        commit_called.append(True)
        raise Exception("DB Error")

    mock_session.commit = mock_commit
    mock_session.rollback = AsyncMock()

    class MockContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            pass

    activity_logger.set_db_session_factory(lambda: MockContextManager())

    # Add a log
    await activity_logger.log(log_type="system", message="Test")

    # Wait for flush attempt with polling (more reliable than fixed sleep)
    await wait_for_condition(
        lambda: len(commit_called) >= 1,
        description="batch flush attempt",
    )

    # Log should be re-queued
    async with activity_logger._batch_lock:
        assert len(activity_logger._pending_logs) > 0


# --- Test Log Cleanup ---


@pytest.mark.asyncio
async def test_cleanup_old_logs(activity_logger, db_session):
    """Test cleaning up old logs."""
    # Create an old log
    old_log = ActivityLog(
        id=uuid4(),
        log_type="system",
        level="info",
        message="Old log",
        created_at=datetime.now(UTC) - timedelta(days=10),
    )
    db_session.add(old_log)

    # Create a recent log
    recent_log = ActivityLog(
        id=uuid4(),
        log_type="system",
        level="info",
        message="Recent log",
        created_at=datetime.now(UTC),
    )
    db_session.add(recent_log)
    await db_session.flush()

    # Cleanup logs older than 7 days
    deleted = await activity_logger.cleanup_old_logs(db_session, retention_days=7)

    assert deleted == 1

    # Verify only recent log remains
    result = await db_session.execute(select(ActivityLog))
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].message == "Recent log"


# --- Test Statistics ---


@pytest.mark.asyncio
async def test_get_stats(activity_logger, db_session, server_factory):
    """Test getting log statistics."""
    # Create a real server to satisfy foreign key constraint
    server = await server_factory()
    server_id = server.id

    # Create test logs
    logs = [
        ActivityLog(
            id=uuid4(),
            server_id=server_id,
            log_type="mcp_request",
            level="info",
            message="Request 1",
            duration_ms=50,
        ),
        ActivityLog(
            id=uuid4(),
            server_id=server_id,
            log_type="mcp_response",
            level="info",
            message="Response 1",
            duration_ms=100,
        ),
        ActivityLog(
            id=uuid4(),
            server_id=server_id,
            log_type="error",
            level="error",
            message="Error 1",
        ),
    ]

    for log in logs:
        db_session.add(log)
    await db_session.flush()

    stats = await activity_logger.get_stats(db_session, server_id=server_id)

    assert stats["total"] == 3
    assert stats["errors"] == 1
    assert stats["avg_duration_ms"] == 75.0  # (50 + 100) / 2
    assert stats["by_type"]["mcp_request"] == 1
    assert stats["by_type"]["mcp_response"] == 1
    assert stats["by_type"]["error"] == 1


@pytest.mark.asyncio
async def test_get_stats_with_since_filter(activity_logger, db_session):
    """Test getting stats with time filter."""
    # Create an old log
    old_log = ActivityLog(
        id=uuid4(),
        log_type="system",
        level="info",
        message="Old",
        created_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db_session.add(old_log)

    # Create a recent log
    recent_log = ActivityLog(
        id=uuid4(),
        log_type="system",
        level="info",
        message="Recent",
        created_at=datetime.now(UTC),
    )
    db_session.add(recent_log)
    await db_session.flush()

    since = datetime.now(UTC) - timedelta(hours=1)
    stats = await activity_logger.get_stats(db_session, since=since)

    assert stats["total"] == 1


# --- Test Get Recent Logs ---


def test_get_recent_logs_count(activity_logger):
    """Test getting a specific count of recent logs."""
    # Populate buffer
    for i in range(20):
        activity_logger._broadcast_buffer.append({"message": f"Log {i}"})

    recent = activity_logger.get_recent_logs(5)

    assert len(recent) == 5
    # Should be last 5 logs
    assert recent[0]["message"] == "Log 15"
    assert recent[4]["message"] == "Log 19"


def test_get_recent_logs_empty(activity_logger):
    """Test getting recent logs when buffer is empty."""
    recent = activity_logger.get_recent_logs(10)

    assert recent == []


def test_get_recent_logs_less_than_requested(activity_logger):
    """Test when buffer has fewer logs than requested."""
    activity_logger._broadcast_buffer.append({"message": "Only one"})

    recent = activity_logger.get_recent_logs(100)

    assert len(recent) == 1
