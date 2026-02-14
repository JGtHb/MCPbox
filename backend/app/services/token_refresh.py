"""Background token refresh service for OAuth credentials."""

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.core import async_session_maker
from app.core.logging import get_logger
from app.models import Credential
from app.services.oauth import OAuthError, OAuthService, OAuthTokenError

logger = get_logger("token_refresh")

# How often to check for expiring tokens (in seconds)
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

# Refresh tokens that expire within this window (in seconds)
EXPIRY_BUFFER_SECONDS = 600  # 10 minutes


class TokenRefreshService:
    """Background service to automatically refresh OAuth tokens."""

    _instance: Optional["TokenRefreshService"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _task: asyncio.Task | None = None

    def __init__(self) -> None:
        self._running = False

    @classmethod
    def get_instance(cls) -> "TokenRefreshService":
        """Get singleton instance of token refresh service (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        """Start the background token refresh task."""
        if self._running:
            logger.warning("Token refresh service is already running")
            return

        self._running = True
        TokenRefreshService._task = asyncio.create_task(self._refresh_loop())
        logger.info("Token refresh service started")

    async def stop(self) -> None:
        """Stop the background token refresh task."""
        self._running = False
        if TokenRefreshService._task:
            TokenRefreshService._task.cancel()
            try:
                await TokenRefreshService._task
            except asyncio.CancelledError:
                pass
            TokenRefreshService._task = None
        logger.info("Token refresh service stopped")

    async def _refresh_loop(self) -> None:
        """Main loop that periodically checks and refreshes tokens."""
        consecutive_failures = 0
        max_consecutive_failures = 5

        while self._running:
            try:
                await self._refresh_expiring_tokens()
                # Reset failure counter on success
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                logger.error(
                    f"Error in token refresh loop (failure {consecutive_failures}/{max_consecutive_failures}): {e}",
                    exc_info=True,
                )

                # If we have persistent failures, log a critical warning
                if consecutive_failures >= max_consecutive_failures:
                    logger.critical(
                        f"Token refresh service has failed {consecutive_failures} times consecutively. "
                        "This may indicate a persistent database or configuration issue. "
                        "OAuth tokens may expire without being refreshed."
                    )
                    # Reset counter but keep running - don't give up entirely
                    consecutive_failures = 0

            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _refresh_expiring_tokens(self) -> None:
        """Find and refresh all tokens that are about to expire."""
        async with async_session_maker() as db:
            try:
                # Find OAuth2 credentials with tokens expiring soon
                expiry_threshold = datetime.now(UTC) + timedelta(seconds=EXPIRY_BUFFER_SECONDS)

                query = select(Credential).where(
                    Credential.auth_type == "oauth2",
                    Credential.encrypted_refresh_token.isnot(None),
                    Credential.access_token_expires_at.isnot(None),
                    Credential.access_token_expires_at < expiry_threshold,
                )

                result = await db.execute(query)
                expiring_credentials = result.scalars().all()

                if not expiring_credentials:
                    return

                logger.info(f"Found {len(expiring_credentials)} OAuth tokens to refresh")

                # Refresh each credential
                refreshed_count = 0
                failed_count = 0

                for credential in expiring_credentials:
                    try:
                        # Use a dummy redirect_uri since we're just refreshing
                        oauth_service = OAuthService(db, redirect_uri="")
                        await oauth_service.refresh_token(credential)
                        # Commit after each successful refresh to avoid losing progress
                        # if a later refresh fails
                        await db.commit()
                        refreshed_count += 1
                        logger.info(
                            f"Refreshed token for credential '{credential.name}' "
                            f"(ID: {credential.id})"
                        )
                    except (OAuthError, OAuthTokenError) as e:
                        # Rollback any partial changes from this credential
                        await db.rollback()
                        failed_count += 1
                        logger.warning(
                            f"Failed to refresh token for credential '{credential.name}' "
                            f"(ID: {credential.id}): {e}"
                        )
                    except Exception as e:
                        # Rollback any partial changes from this credential
                        await db.rollback()
                        failed_count += 1
                        logger.error(
                            f"Unexpected error refreshing credential '{credential.name}' "
                            f"(ID: {credential.id}): {e}"
                        )

                if refreshed_count > 0 or failed_count > 0:
                    logger.info(
                        f"Token refresh complete: {refreshed_count} refreshed, "
                        f"{failed_count} failed"
                    )

            except Exception as e:
                logger.error(f"Error querying expiring credentials: {e}")
                await db.rollback()
