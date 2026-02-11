"""Tests for TunnelService - cloudflared tunnel management."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tunnel import TunnelService, get_tunnel_service


@pytest.fixture
def reset_tunnel_singleton():
    """Reset TunnelService singleton state before each test."""
    # Reset the singleton
    TunnelService._instance = None
    TunnelService._process = None
    TunnelService._url = None
    TunnelService._status = "disconnected"
    TunnelService._error = None
    TunnelService._started_at = None
    TunnelService._status_callbacks = []
    TunnelService._named_tunnel_url = None
    TunnelService._lock = None
    yield
    # Clean up after test
    TunnelService._instance = None
    TunnelService._process = None
    TunnelService._url = None
    TunnelService._status = "disconnected"
    TunnelService._error = None
    TunnelService._started_at = None
    TunnelService._status_callbacks = []
    TunnelService._named_tunnel_url = None
    TunnelService._lock = None


class TestTunnelServiceSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self, reset_tunnel_singleton):
        """Multiple instantiations return the same instance."""
        service1 = TunnelService()
        service2 = TunnelService()
        assert service1 is service2

    def test_get_instance_creates_instance(self, reset_tunnel_singleton):
        """get_instance creates a new instance if none exists."""
        service = TunnelService.get_instance()
        assert service is not None
        assert TunnelService._instance is service

    def test_get_tunnel_service_returns_singleton(self, reset_tunnel_singleton):
        """get_tunnel_service convenience function returns singleton."""
        service = get_tunnel_service()
        assert service is TunnelService.get_instance()


class TestTunnelServiceStatus:
    """Test status properties and methods."""

    def test_initial_status_is_disconnected(self, reset_tunnel_singleton):
        """Initial status is disconnected."""
        service = TunnelService()
        assert service.status == "disconnected"
        assert service.url is None
        assert service.error is None
        assert service.started_at is None

    def test_get_status_returns_dict(self, reset_tunnel_singleton):
        """get_status returns a dict with all status fields."""
        service = TunnelService()
        status = service.get_status()
        assert isinstance(status, dict)
        assert "status" in status
        assert "url" in status
        assert "started_at" in status
        assert "error" in status
        assert status["status"] == "disconnected"


class TestTunnelServiceStatusCallbacks:
    """Test status callback functionality."""

    def test_add_callback(self, reset_tunnel_singleton):
        """Can add a status callback."""
        service = TunnelService()
        callback = MagicMock()
        service.add_status_callback(callback)
        assert callback in service._status_callbacks

    def test_remove_callback(self, reset_tunnel_singleton):
        """Can remove a status callback."""
        service = TunnelService()
        callback = MagicMock()
        service.add_status_callback(callback)
        service.remove_status_callback(callback)
        assert callback not in service._status_callbacks

    def test_remove_nonexistent_callback_no_error(self, reset_tunnel_singleton):
        """Removing a nonexistent callback doesn't raise an error."""
        service = TunnelService()
        callback = MagicMock()
        # Should not raise
        service.remove_status_callback(callback)

    @pytest.mark.asyncio
    async def test_notify_calls_sync_callback(self, reset_tunnel_singleton):
        """Sync callbacks are called on status change."""
        service = TunnelService()
        callback = MagicMock()
        service.add_status_callback(callback)
        await service._notify_status_change()
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_calls_async_callback(self, reset_tunnel_singleton):
        """Async callbacks are awaited on status change."""
        service = TunnelService()
        callback = AsyncMock()
        service.add_status_callback(callback)
        await service._notify_status_change()
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_error_logged_not_raised(self, reset_tunnel_singleton):
        """Callback errors are logged but don't stop notification."""
        service = TunnelService()

        def failing_callback(status):
            raise ValueError("Test error")

        service.add_status_callback(failing_callback)
        # Should not raise
        await service._notify_status_change()


class TestTunnelServiceStart:
    """Test tunnel start functionality."""

    @pytest.mark.asyncio
    async def test_start_requires_token(self, reset_tunnel_singleton):
        """Start raises error if no token provided."""
        service = TunnelService()
        with pytest.raises(RuntimeError, match="Tunnel token is required"):
            await service.start(tunnel_token="")

    @pytest.mark.asyncio
    async def test_start_raises_if_already_running(self, reset_tunnel_singleton):
        """Start raises error if tunnel already running."""
        service = TunnelService()
        service._status = "connected"
        service._process = MagicMock()

        with pytest.raises(RuntimeError, match="already running"):
            await service.start(tunnel_token="test-token")

    @pytest.mark.asyncio
    async def test_start_raises_if_connecting(self, reset_tunnel_singleton):
        """Start raises error if tunnel is already starting."""
        service = TunnelService()
        service._status = "connecting"

        with pytest.raises(RuntimeError, match="already starting"):
            await service.start(tunnel_token="test-token")

    @pytest.mark.asyncio
    async def test_start_cloudflared_not_found(self, reset_tunnel_singleton):
        """Start raises error if cloudflared not installed."""
        service = TunnelService()

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            with pytest.raises(RuntimeError, match="cloudflared not installed"):
                await service.start(tunnel_token="test-token")

        assert service.status == "error"
        assert "cloudflared not installed" in service.error

    @pytest.mark.asyncio
    async def test_start_successful_with_named_url(self, reset_tunnel_singleton):
        """Successful start with named tunnel URL."""
        service = TunnelService()

        # Create a mock process
        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.stdout = AsyncMock()

        # Simulate connection success message
        async def mock_readline():
            return b"INF Registered tunnel connection\n"

        mock_process.stdout.readline = mock_readline

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await service.start(
                tunnel_token="test-token",
                named_tunnel_url="https://mcpbox.example.com",
            )

        assert result["status"] == "connected"
        assert result["url"] == "https://mcpbox.example.com"
        assert service.started_at is not None

    @pytest.mark.asyncio
    async def test_start_sets_placeholder_url_if_no_named_url(self, reset_tunnel_singleton):
        """Start sets placeholder URL if no named URL provided."""
        service = TunnelService()

        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.stdout = AsyncMock()

        async def mock_readline():
            return b"INF Connection registered\n"

        mock_process.stdout.readline = mock_readline

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await service.start(tunnel_token="test-token")

        assert result["status"] == "connected"
        assert "Cloudflare Dashboard" in result["url"]

    @pytest.mark.asyncio
    async def test_start_connection_failure(self, reset_tunnel_singleton):
        """Start handles connection failure when process dies."""
        service = TunnelService()

        mock_process = AsyncMock()
        mock_process.returncode = 1  # Process died immediately
        mock_process.stdout = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        async def mock_readline():
            return b"some unrecognized output\n"

        mock_process.stdout.readline = mock_readline

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await service.start(tunnel_token="test-token")

        assert result["status"] == "error"
        assert "Failed to establish tunnel connection" in result["error"]


class TestTunnelServiceStop:
    """Test tunnel stop functionality."""

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, reset_tunnel_singleton):
        """Stop when tunnel not running just resets state."""
        service = TunnelService()
        result = await service.stop()

        assert result["status"] == "disconnected"
        assert result["url"] is None

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self, reset_tunnel_singleton):
        """Stop terminates the tunnel process."""
        service = TunnelService()

        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()

        service._process = mock_process
        service._status = "connected"

        result = await service.stop()

        mock_process.terminate.assert_called_once()
        assert result["status"] == "disconnected"
        assert service._process is None

    @pytest.mark.asyncio
    async def test_stop_force_kills_on_timeout(self, reset_tunnel_singleton):
        """Stop force kills if terminate times out."""
        service = TunnelService()

        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()

        async def slow_wait():
            raise asyncio.TimeoutError()

        mock_process.wait = slow_wait

        service._process = mock_process
        service._status = "connected"

        # Replace wait after kill to not timeout
        async def wait_after_kill():
            if mock_process.kill.called:
                return
            raise asyncio.TimeoutError()

        mock_process.wait = wait_after_kill

        result = await service.stop()

        mock_process.kill.assert_called_once()
        assert result["status"] == "disconnected"


class TestTunnelServiceHealthCheck:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_disconnected(self, reset_tunnel_singleton):
        """Health check returns False when disconnected."""
        service = TunnelService()
        assert await service.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_no_process(self, reset_tunnel_singleton):
        """Health check returns False when no process."""
        service = TunnelService()
        service._status = "connected"
        assert await service.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self, reset_tunnel_singleton):
        """Health check returns True when connected with running process."""
        service = TunnelService()
        service._status = "connected"

        mock_process = MagicMock()
        mock_process.returncode = None  # Still running
        service._process = mock_process

        assert await service.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_detects_dead_process(self, reset_tunnel_singleton):
        """Health check detects when process has died."""
        service = TunnelService()
        service._status = "connected"

        mock_process = MagicMock()
        mock_process.returncode = 1  # Process died
        service._process = mock_process

        result = await service.health_check()

        assert result is False
        assert service.status == "disconnected"
        assert service._process is None


class TestTunnelServiceConcurrency:
    """Test concurrent access and race condition prevention."""

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_starts(self, reset_tunnel_singleton):
        """Lock prevents race condition in concurrent start calls."""
        service = TunnelService()

        start_count = 0
        start_completed = asyncio.Event()

        async def slow_start(*args, **kwargs):
            nonlocal start_count
            start_count += 1
            # Simulate slow startup
            await asyncio.sleep(0.1)
            start_completed.set()
            mock_process = AsyncMock()
            mock_process.returncode = None
            mock_process.stdout = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"Connection registered\n")
            return mock_process

        with patch("asyncio.create_subprocess_exec", side_effect=slow_start):
            # Start two concurrent calls
            task1 = asyncio.create_task(service.start(tunnel_token="token1"))
            # Small delay to ensure task1 starts first
            await asyncio.sleep(0.01)
            task2 = asyncio.create_task(service.start(tunnel_token="token2"))

            # First should succeed
            result1 = await task1

            # Second should fail because tunnel is now running
            with pytest.raises(RuntimeError, match="already"):
                await task2

        # Only one actual start should have happened
        assert start_count == 1
        assert result1["status"] == "connected"

    @pytest.mark.asyncio
    async def test_lock_is_created_lazily(self, reset_tunnel_singleton):
        """Lock is created on first use."""
        service = TunnelService()
        assert service._lock is None

        lock = service._get_lock()
        assert lock is not None
        assert service._lock is lock

        # Same lock returned on subsequent calls
        assert service._get_lock() is lock
