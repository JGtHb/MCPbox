"""Cloudflared tunnel service - manages named tunnel processes."""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TunnelService:
    """Manages cloudflared tunnel process.

    Singleton service that handles starting/stopping cloudflared
    for named tunnels (requires Cloudflare account, persistent URL).
    Authentication is handled by Cloudflare MCP Server Portals.
    """

    _instance: Optional["TunnelService"] = None
    _process: asyncio.subprocess.Process | None = None
    _url: str | None = None
    _status: str = "disconnected"
    _error: str | None = None
    _started_at: datetime | None = None
    _status_callbacks: list = []
    _named_tunnel_url: str | None = None  # User-configured URL for named tunnel
    _lock: asyncio.Lock | None = None  # Protects start/stop operations

    def __new__(cls) -> "TunnelService":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "TunnelService":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_lock(self) -> asyncio.Lock:
        """Get or create the asyncio lock (lazy initialization)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def url(self) -> str | None:
        """Get current tunnel URL."""
        return self._url

    @property
    def status(self) -> str:
        """Get current tunnel status."""
        return self._status

    @property
    def error(self) -> str | None:
        """Get current error message."""
        return self._error

    @property
    def started_at(self) -> datetime | None:
        """Get tunnel start time."""
        return self._started_at

    def add_status_callback(self, callback: Callable[..., Any]) -> None:
        """Add a callback for status changes."""
        self._status_callbacks.append(callback)

    def remove_status_callback(self, callback: Callable[..., Any]) -> None:
        """Remove a status callback."""
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)

    async def _notify_status_change(self) -> None:
        """Notify all callbacks of status change."""
        for callback in self._status_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self.get_status())
                else:
                    callback(self.get_status())
            except Exception as e:
                logger.warning(f"Status callback error: {e}")

    def get_status(self) -> dict:
        """Get current tunnel status as dict."""
        return {
            "status": self._status,
            "url": self._url,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "error": self._error,
        }

    async def start(
        self,
        tunnel_token: str,
        named_tunnel_url: str | None = None,
    ) -> dict:
        """Start cloudflared named tunnel.

        Args:
            tunnel_token: Cloudflare tunnel token (required)
            named_tunnel_url: Pre-configured URL for named tunnel

        Returns:
            Status dict with URL on success

        Raises:
            RuntimeError: If tunnel already running or cloudflared not found
        """
        async with self._get_lock():
            if self._status == "connected" and self._process:
                raise RuntimeError("Tunnel is already running")

            if self._status == "connecting":
                raise RuntimeError("Tunnel is already starting")

            if not tunnel_token:
                raise RuntimeError("Tunnel token is required")

            # Reset state
            self._url = None
            self._error = None
            self._status = "connecting"
            self._named_tunnel_url = named_tunnel_url
            await self._notify_status_change()

            try:
                self._process = await asyncio.create_subprocess_exec(
                    "cloudflared",
                    "tunnel",
                    "--no-autoupdate",
                    "run",
                    "--token",
                    tunnel_token,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )

                # Wait for connection confirmation
                connected = await self._wait_for_tunnel_connection(timeout=30)

                if connected:
                    # Use the pre-configured URL or a placeholder
                    if self._named_tunnel_url:
                        self._url = self._named_tunnel_url
                    else:
                        # Named tunnels don't output URLs like quick tunnels
                        # User must provide the URL from their Cloudflare dashboard
                        self._url = "Configured in Cloudflare Dashboard"

                    self._status = "connected"
                    self._started_at = datetime.now(UTC)
                    logger.info(f"Tunnel connected: {self._url}")
                else:
                    self._status = "error"
                    self._error = "Failed to establish tunnel connection"
                    # Clean up process without resetting error state
                    if self._process:
                        try:
                            self._process.terminate()
                            await asyncio.wait_for(self._process.wait(), timeout=5.0)
                        except (TimeoutError, Exception):
                            try:
                                self._process.kill()
                            except Exception:
                                pass
                        self._process = None

                await self._notify_status_change()
                return self.get_status()

            except FileNotFoundError:
                self._status = "error"
                self._error = "cloudflared not installed. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
                # Ensure process is cleaned up
                if self._process:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                    self._process = None
                await self._notify_status_change()
                raise RuntimeError(self._error) from None

            except Exception as e:
                self._status = "error"
                self._error = str(e)
                # Ensure process is cleaned up
                if self._process:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                    self._process = None
                await self._notify_status_change()
                raise

    async def _wait_for_tunnel_connection(self, timeout: int = 30) -> bool:
        """Wait for tunnel to establish connection.

        Cloudflared outputs messages like:
        - Connection registered with ID xxx
        - Registered tunnel connection
        """
        if not self._process or not self._process.stdout:
            return False

        # Patterns indicating successful connection
        success_patterns = [
            re.compile(r"connection.*registered", re.IGNORECASE),
            re.compile(r"registered.*connection", re.IGNORECASE),
            re.compile(r"tunnel.*connected", re.IGNORECASE),
            re.compile(r"serving.*https", re.IGNORECASE),
        ]

        # Patterns indicating errors
        error_patterns = [
            re.compile(r"failed to connect", re.IGNORECASE),
            re.compile(r"error.*tunnel", re.IGNORECASE),
            re.compile(r"authentication.*failed", re.IGNORECASE),
            re.compile(r"invalid.*token", re.IGNORECASE),
        ]

        start_time = time.monotonic()

        try:
            while True:
                # Check timeout
                if time.monotonic() - start_time > timeout:
                    logger.error("Timeout waiting for tunnel connection")
                    return False

                # Check if process died
                if self._process.returncode is not None:
                    logger.error(f"cloudflared exited with code {self._process.returncode}")
                    return False

                # Read line with timeout
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=1.0,
                    )
                except TimeoutError:
                    continue

                if not line:
                    continue

                line_str = line.decode("utf-8", errors="replace").strip()
                logger.debug(f"cloudflared: {line_str}")

                # Check for errors first
                for pattern in error_patterns:
                    if pattern.search(line_str):
                        self._error = f"Tunnel error: {line_str}"
                        logger.error(self._error)
                        return False

                # Check for success
                for pattern in success_patterns:
                    if pattern.search(line_str):
                        logger.info(f"Tunnel connected: {line_str}")
                        return True

        except Exception as e:
            logger.error(f"Error reading cloudflared output: {e}")
            return False

    async def _stop_internal(self) -> dict:
        """Internal stop implementation (must be called with lock held).

        Returns:
            Status dict
        """
        if self._process:
            try:
                # Try graceful termination first
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except TimeoutError:
                    # Force kill if needed
                    self._process.kill()
                    await self._process.wait()
            except Exception as e:
                logger.warning(f"Error stopping tunnel process: {e}")
            finally:
                self._process = None

        self._url = None
        self._status = "disconnected"
        self._error = None
        self._started_at = None

        await self._notify_status_change()
        logger.info("Tunnel stopped")

        return self.get_status()

    async def stop(self) -> dict:
        """Stop the cloudflared tunnel.

        Returns:
            Status dict
        """
        async with self._get_lock():
            return await self._stop_internal()

    async def get_effective_status(self) -> dict:
        """Get tunnel status, checking Docker-based tunnel if subprocess not running.

        The subprocess-based tunnel is managed by TunnelService.start()/stop().
        Docker-based tunnels (started via docker compose with cloudflared) are
        invisible to TunnelService. This method checks the database for an active
        TunnelConfiguration to detect Docker-based tunnels.

        Note: cloudflared metrics bind to 127.0.0.1:20241 (container-local),
        so we can't probe from the backend. The config-based check is reliable
        because cloudflared is restart: unless-stopped with Docker healthchecks.
        """
        # If subprocess tunnel is connected, use that
        if self._status == "connected" and self._process:
            await self.health_check()
            return self.get_status()

        # Check for Docker-based tunnel (wizard-configured)
        from app.core.database import async_session_maker
        from app.models.tunnel_configuration import TunnelConfiguration

        try:
            from sqlalchemy import select

            async with async_session_maker() as session:
                result = await session.execute(
                    select(TunnelConfiguration).where(
                        TunnelConfiguration.is_active == True  # noqa: E712
                    )
                )
                config = result.scalar_one_or_none()
        except Exception:
            return self.get_status()  # Fall back to subprocess status

        if config:
            return {
                "status": "connected",
                "url": config.public_url,
                "started_at": config.created_at.isoformat() if config.created_at else None,
                "error": None,
            }

        return self.get_status()

    async def health_check(self) -> bool:
        """Check if tunnel process is still running.

        Returns:
            True if tunnel is healthy
        """
        if self._status != "connected":
            return False

        if not self._process:
            return False

        # Check if process is still running
        if self._process.returncode is not None:
            # Process died
            logger.warning(f"Tunnel process died with code {self._process.returncode}")
            self._status = "disconnected"
            self._url = None
            self._process = None
            await self._notify_status_change()
            return False

        return True


# Convenience function for dependency injection
def get_tunnel_service() -> TunnelService:
    """Get the tunnel service singleton."""
    return TunnelService.get_instance()
