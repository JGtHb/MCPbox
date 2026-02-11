"""MCP Gateway - routes requests to the shared sandbox service.

Also exposes MCPbox management tools that allow external LLMs (like Claude Code)
to create, update, and manage MCP servers and tools programmatically.

Authentication:
- Local mode (no service token in database): No auth required
- Remote mode: Cloudflare Worker proxy adds X-MCPbox-Service-Token header
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_simple import AuthenticatedUser, verify_mcp_auth
from app.core.database import get_db
from app.services.activity_logger import ActivityLoggerService, get_activity_logger
from app.services.mcp_management import MCPManagementService, get_management_tools_list
from app.services.sandbox_client import SandboxClient, get_sandbox_client

logger = logging.getLogger(__name__)

# Management tool prefix - all tools starting with this are handled locally
MANAGEMENT_TOOL_PREFIX = "mcpbox_"

# Destructive management tools that are restricted to local access only.
# These tools perform irreversible operations and must not be callable
# through the remote tunnel (source="worker").
LOCAL_ONLY_TOOLS = {
    "mcpbox_delete_server",
    "mcpbox_delete_tool",
}

# Maximum concurrent SSE connections to prevent resource exhaustion
MAX_SSE_CONNECTIONS = 50
_active_sse_connections = 0

# MCP Gateway router - exposed at /mcp (not /api/mcp)
router = APIRouter(tags=["mcp"])


# --- MCP Protocol Models ---


class MCPRequest(BaseModel):
    """MCP JSON-RPC request or notification.

    Per JSON-RPC 2.0 spec:
    - Requests have an 'id' field and expect a response
    - Notifications do NOT have an 'id' field (one-way messages)

    MCP uses notifications for things like 'notifications/initialized'.
    """

    jsonrpc: str = "2.0"
    id: int | str | None = None  # Optional for notifications
    method: str
    params: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    """MCP JSON-RPC response.

    Responses are only sent for requests (which have an id).
    Notifications (no id) don't get responses.
    """

    jsonrpc: str = "2.0"
    id: int | str | None = None  # None for notification acknowledgments
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


# --- MCP Streamable HTTP SSE Endpoint ---


@router.get("/mcp")
async def mcp_sse(
    request: Request,
    _user: AuthenticatedUser = Depends(verify_mcp_auth),
):
    """MCP Streamable HTTP SSE endpoint for server-to-client streaming.

    Per the MCP Streamable HTTP transport spec, GET to the MCP endpoint
    opens an SSE stream for server-initiated messages (notifications, requests).
    We don't currently send server-initiated messages, so this returns a
    keep-alive stream that stays open until the client disconnects.
    """
    global _active_sse_connections

    if _active_sse_connections >= MAX_SSE_CONNECTIONS:
        raise HTTPException(
            status_code=503,
            detail="Too many active SSE connections",
        )

    logger.info("SSE stream opened (active: %d)", _active_sse_connections + 1)

    async def event_generator():
        global _active_sse_connections
        _active_sse_connections += 1
        try:
            # Send initial keepalive to confirm the stream is working
            yield ": keepalive\n\n"
            while True:
                await asyncio.sleep(15)
                yield ": keepalive\n\n"
        except asyncio.CancelledError:
            logger.info("SSE stream closed by client")
        finally:
            _active_sse_connections -= 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
        },
    )


# --- MCP Gateway Endpoint ---


@router.post("/mcp")
async def mcp_gateway(
    request: MCPRequest,
    _user: AuthenticatedUser = Depends(verify_mcp_auth),
    db: AsyncSession = Depends(get_db),
    activity_logger: ActivityLoggerService = Depends(get_activity_logger),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
):
    """MCP JSON-RPC gateway endpoint.

    Handles MCP protocol requests. Routes tool requests to the shared
    sandbox service OR handles management tools (mcpbox_*) locally.

    Supported methods:
    - tools/list: List all available tools (sandbox + management tools)
    - tools/call: Execute a tool
    """
    start_time = time.time()
    method = request.method
    params = request.params or {}

    # Log incoming request
    request_id = await activity_logger.log_mcp_request(
        method=method,
        params=params,
    )

    try:
        response_result = None
        response_error = None

        # SECURITY: Remote requests (source="worker") require JWT authentication
        # from Cloudflare Access. OAuth-only tokens (from direct Worker access
        # bypassing the Portal) are rejected. Local requests (source="local",
        # auth_method=None) are allowed — they come from Claude Desktop on the
        # same machine and don't traverse the network.
        _requires_jwt = _user.source == "worker" and _user.auth_method != "jwt"

        # Handle different MCP methods
        if method == "initialize":
            if _requires_jwt:
                response_error = {
                    "code": -32600,
                    "message": "Requires user authentication via Cloudflare Access",
                }
            else:
                # MCP initialization handshake - required for Streamable HTTP transport
                response_result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},  # We support tools
                    },
                    "serverInfo": {
                        "name": "mcpbox",
                        "version": "1.0.0",
                    },
                }

        elif method.startswith("notifications/"):
            # Notifications are one-way messages - no response expected.
            # SECURITY: Require JWT for remote requests, same as other methods.
            if _requires_jwt:
                return Response(status_code=403)
            # MCP Streamable HTTP transport spec requires 202 Accepted
            # for notifications (not 204 No Content).
            duration_ms = int((time.time() - start_time) * 1000)
            await activity_logger.log_mcp_response(
                request_id=request_id,
                success=True,
                duration_ms=duration_ms,
                method=method,
                error=None,
            )
            return Response(status_code=202)

        elif method == "tools/list":
            if _requires_jwt:
                response_error = {
                    "code": -32600,
                    "message": "Requires user authentication via Cloudflare Access",
                }
            else:
                response_result = await _handle_tools_list(sandbox_client, db)

        elif method == "tools/call":
            if _requires_jwt:
                response_error = {
                    "code": -32600,
                    "message": "Tool execution requires user authentication",
                }
            else:
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})

                if tool_name.startswith(MANAGEMENT_TOOL_PREFIX):
                    # Handle management tools locally
                    response_result = await _handle_management_tool_call(
                        db=db,
                        tool_name=tool_name,
                        arguments=arguments,
                        sandbox_client=sandbox_client,
                        user=_user,
                    )
                else:
                    # Forward to sandbox for regular tools
                    sandbox_response = await sandbox_client.mcp_request(
                        {
                            "jsonrpc": "2.0",
                            "id": request.id,
                            "method": method,
                            "params": params,
                        }
                    )
                    if "error" in sandbox_response:
                        response_error = sandbox_response["error"]
                    else:
                        response_result = sandbox_response.get("result")
        else:
            # All other methods also require JWT for remote requests.
            # This is the catch-all — no MCP functionality is accessible
            # without Cloudflare Access authentication.
            if _requires_jwt:
                response_error = {
                    "code": -32600,
                    "message": "Requires user authentication via Cloudflare Access",
                }
            else:
                # Forward other methods to sandbox
                sandbox_response = await sandbox_client.mcp_request(
                    {
                        "jsonrpc": "2.0",
                        "id": request.id,
                        "method": method,
                        "params": params,
                    }
                )
                if "error" in sandbox_response:
                    response_error = sandbox_response["error"]
                else:
                    response_result = sandbox_response.get("result")

        # Build response
        if response_error:
            response = MCPResponse(
                id=request.id,
                error=response_error,
            )
        else:
            response = MCPResponse(
                id=request.id,
                result=response_result,
            )

        # Log response
        duration_ms = int((time.time() - start_time) * 1000)
        is_success = response.error is None
        await activity_logger.log_mcp_response(
            request_id=request_id,
            success=is_success,
            duration_ms=duration_ms,
            method=method,
            error=response.error.get("message")
            if isinstance(response.error, dict)
            else str(response.error)
            if response.error
            else None,
        )

        # Return response, excluding None fields for cleaner JSON-RPC
        return response.model_dump(exclude_none=True)

    except HTTPException:
        # Log HTTP exceptions
        duration_ms = int((time.time() - start_time) * 1000)
        await activity_logger.log_mcp_response(
            request_id=request_id,
            success=False,
            duration_ms=duration_ms,
            method=method,
            error="HTTP exception",
        )
        raise
    except Exception as e:
        logger.exception(f"MCP gateway error: {e}")
        # Log error (full details for internal logging)
        duration_ms = int((time.time() - start_time) * 1000)
        await activity_logger.log_mcp_response(
            request_id=request_id,
            success=False,
            duration_ms=duration_ms,
            method=method,
            error=str(e),
        )
        # Return generic error to client (no internal details)
        return MCPResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": "Internal server error",
            },
        )


async def _handle_tools_list(
    sandbox_client: SandboxClient,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Handle tools/list by combining sandbox and management tools.

    Only includes tools that have been approved. Draft, pending, and rejected
    tools are filtered out from the sandbox response.
    """
    # Get tools from sandbox
    sandbox_response = await sandbox_client.mcp_request(
        {
            "jsonrpc": "2.0",
            "id": "list",
            "method": "tools/list",
            "params": {},
        }
    )

    # Start with sandbox tools
    sandbox_tools = []
    if "result" in sandbox_response and sandbox_response["result"]:
        all_sandbox_tools = sandbox_response["result"].get("tools", [])

        # Filter to only include approved tools
        if db:
            approved_tool_names = await _get_approved_tool_names(db)
            sandbox_tools = [
                tool for tool in all_sandbox_tools if tool.get("name") in approved_tool_names
            ]
        else:
            sandbox_tools = all_sandbox_tools

    # Add management tools (always available)
    management_tools = get_management_tools_list()

    return {
        "tools": sandbox_tools + management_tools,
    }


async def _get_approved_tool_names(db: AsyncSession) -> set[str]:
    """Get the set of approved tool names (with server prefix)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.tool import Tool

    stmt = (
        select(Tool)
        .options(selectinload(Tool.server))
        .where(Tool.approval_status == "approved")
        .where(Tool.enabled == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    tools = result.scalars().all()

    # Return set of full tool names (server_name__tool_name) matching sandbox format
    return {f"{tool.server.name}__{tool.name}" for tool in tools if tool.server}


async def _handle_management_tool_call(
    db: AsyncSession,
    tool_name: str,
    arguments: dict[str, Any],
    sandbox_client: SandboxClient,
    user: AuthenticatedUser | None = None,
) -> dict[str, Any]:
    """Handle a management tool call locally."""
    # Block destructive tools from remote (tunnel) access
    if tool_name in LOCAL_ONLY_TOOLS and user and user.source == "worker":
        logger.warning(
            "Blocked remote call to local-only tool %s from %s",
            tool_name,
            user.email or "unknown",
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: {tool_name} is restricted to local access only",
                }
            ],
            "isError": True,
        }

    management_service = MCPManagementService(db)

    try:
        result = await management_service.execute_tool(
            tool_name=tool_name,
            arguments=arguments,
            sandbox_client=sandbox_client,
        )

        # Format result for MCP protocol
        # MCP tools/call returns content array
        if result.get("error"):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: {result['error']}",
                    }
                ],
                "isError": True,
            }
        else:
            import json

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, default=str),
                    }
                ],
            }
    except Exception as e:
        logger.exception(f"Management tool {tool_name} failed: {e}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error executing {tool_name}: An internal error occurred",
                }
            ],
            "isError": True,
        }


# --- Health endpoint for tunnel target ---


@router.get("/mcp/health")
async def mcp_health(
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
):
    """Health check endpoint for the MCP gateway.

    Used by cloudflared to verify the tunnel target is working.
    """
    sandbox_healthy = await sandbox_client.health_check()

    return {
        "status": "ok" if sandbox_healthy else "degraded",
    }
