"""Background rate limiter cleanup task shared between main app and MCP gateway."""

import asyncio
import logging

from app.middleware.rate_limit import get_rate_limiter

logger = logging.getLogger(__name__)


async def rate_limit_cleanup_loop() -> None:
    """Periodic cleanup of inactive rate limit buckets to prevent memory leaks."""
    rate_limiter = get_rate_limiter()
    while True:
        try:
            await asyncio.sleep(3600)
            removed = await rate_limiter.cleanup_inactive_buckets(inactive_seconds=86400)
            if removed > 0:
                logger.debug(f"Rate limiter cleanup: removed {removed} inactive buckets")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Rate limiter cleanup error: {e}")
