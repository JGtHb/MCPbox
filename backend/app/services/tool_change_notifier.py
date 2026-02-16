"""Tool change notifier — broadcasts tools/list_changed to MCP SSE clients.

This module provides two notification paths:

1. **Same-process (MCP Gateway)**: Calls broadcast_tools_changed() directly
   when the gateway itself makes tool changes (e.g., via MCP management tools).

2. **Cross-process (Backend → MCP Gateway)**: Makes a fire-and-forget HTTP POST
   to the MCP Gateway's internal endpoint when the backend admin API makes
   tool changes (approvals, server start/stop).

Both paths are idempotent and safe to call multiple times — they simply tell
connected MCP clients to re-fetch their tool list.
"""

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

# MCP Gateway URL for cross-process notifications.
# In Docker, this is the mcp-gateway service. In dev, it's localhost:8002.
MCP_GATEWAY_URL = os.environ.get("MCP_GATEWAY_INTERNAL_URL", "http://mcp-gateway:8002")


async def notify_tools_changed_via_gateway() -> None:
    """Notify the MCP gateway that the tool list has changed.

    Makes a fire-and-forget HTTP POST to the gateway's internal endpoint.
    Failures are logged but never propagated — this should never block
    the calling operation.

    Used by the backend process (admin API, approval endpoints).
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{MCP_GATEWAY_URL}/mcp/internal/notify-tools-changed",
                timeout=2.0,
            )
            if response.status_code == 200:
                logger.debug("Successfully notified MCP gateway of tool change")
            else:
                logger.warning(
                    "MCP gateway notification returned %d: %s",
                    response.status_code,
                    response.text[:200],
                )
    except httpx.ConnectError:
        # MCP gateway not running — this is normal in local-only mode
        logger.debug("MCP gateway not reachable, skipping tool change notification")
    except Exception as e:
        logger.warning("Failed to notify MCP gateway of tool change: %s", e)


def fire_and_forget_notify() -> None:
    """Schedule a tool change notification as a fire-and-forget background task.

    Safe to call from any async context. Creates an asyncio task that runs
    in the background without blocking the caller.
    """
    try:
        asyncio.create_task(notify_tools_changed_via_gateway())
    except RuntimeError:
        # No running event loop (shouldn't happen in FastAPI, but defensive)
        logger.debug("No event loop, skipping tool change notification")


async def notify_tools_changed_local() -> None:
    """Notify tools changed within the same process (MCP gateway process).

    Calls broadcast_tools_changed() directly without HTTP.
    Used when the MCP gateway itself processes tool changes via management tools.
    """
    from app.api.mcp_gateway import broadcast_tools_changed

    await broadcast_tools_changed()
