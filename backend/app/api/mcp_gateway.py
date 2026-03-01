"""MCP Gateway - routes requests to the shared sandbox service.

Also exposes MCPbox management tools that allow external LLMs
to create, update, and manage MCP servers and tools programmatically.

Authentication:
- Local mode (no service token in database): No auth required
- Remote mode: Cloudflare Worker proxy adds X-MCPbox-Service-Token header
"""

import asyncio
import json
import logging
import secrets
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_simple import AuthenticatedUser, verify_mcp_auth
from app.core.config import settings
from app.core.database import async_session_maker, get_db
from app.services.activity_logger import ActivityLoggerService, get_activity_logger
from app.services.execution_log import ExecutionLogService
from app.services.mcp_management import MCPManagementService, get_management_tools_list
from app.services.sandbox_client import SandboxClient, get_sandbox_client
from app.services.setting import SettingService

logger = logging.getLogger(__name__)

# MCP protocol version — must match what we actually implement.
# 2025-11-25 introduced tasks, elicitation, icons (all optional).
# Core Streamable HTTP transport is unchanged from 2025-03-26.
MCP_PROTOCOL_VERSION = "2025-11-25"

# Management tool prefix - all tools starting with this are handled locally
MANAGEMENT_TOOL_PREFIX = "mcpbox_"

# Management tools restricted to local access only.
# These tools perform mutations (create, update, delete, rollback) and must not
# be callable through the remote tunnel (source="worker"). This limits the blast
# radius of prompt injection attacks: if an LLM is manipulated via a tool result
# (e.g., malicious email content), it cannot create/modify tools or servers remotely.
LOCAL_ONLY_TOOLS = {
    # Destructive operations
    "mcpbox_delete_server",
    "mcpbox_delete_tool",
    # Creation operations - prevent injection-driven tool/server creation
    "mcpbox_create_server",
    "mcpbox_create_tool",
    # Modification operations - prevent injection-driven changes
    "mcpbox_update_tool",
    "mcpbox_rollback_tool",
    # External sources - prevent adding malicious MCP sources
    "mcpbox_add_external_source",
    "mcpbox_import_external_tools",
}

# Maximum concurrent SSE connections to prevent resource exhaustion
MAX_SSE_CONNECTIONS = 50
_active_sse_connections = 0

# --- Session Management ---
# Per MCP Streamable HTTP spec (2025-03-26+), servers MAY assign a session ID
# at initialization time. Clients MUST include it on all subsequent requests.
# This allows the server to correlate GET SSE streams with POST sessions.
SESSION_EXPIRY_SECONDS = 3600  # 1 hour
_active_sessions: dict[str, float] = {}  # session_id -> last_activity_timestamp
_sessions_lock = asyncio.Lock()


def _generate_session_id() -> str:
    """Generate a cryptographically secure session ID."""
    return str(uuid.uuid4())


async def cleanup_expired_sessions() -> int:
    """Remove expired sessions from the in-memory session dict. Returns count removed."""
    now = time.time()
    async with _sessions_lock:
        expired = [sid for sid, ts in _active_sessions.items() if now - ts > SESSION_EXPIRY_SECONDS]
        for sid in expired:
            del _active_sessions[sid]
        return len(expired)


async def _validate_session(session_id: str | None) -> bool:
    """Validate a session ID exists and hasn't expired."""
    if not session_id:
        return False
    async with _sessions_lock:
        last_activity = _active_sessions.get(session_id)
        if last_activity is None:
            return False
        if time.time() - last_activity > SESSION_EXPIRY_SECONDS:
            del _active_sessions[session_id]
            return False
        # Touch session
        _active_sessions[session_id] = time.time()
        return True


async def _create_session() -> str:
    """Create a new session and return the session ID."""
    session_id = _generate_session_id()
    async with _sessions_lock:
        _active_sessions[session_id] = time.time()
        # Cleanup expired sessions opportunistically
        now = time.time()
        expired = [
            sid for sid, last in _active_sessions.items() if now - last > SESSION_EXPIRY_SECONDS
        ]
        for sid in expired:
            del _active_sessions[sid]
    return session_id


async def _delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if it existed."""
    async with _sessions_lock:
        if session_id in _active_sessions:
            del _active_sessions[session_id]
            return True
        return False


# --- SSE Notification Event Bus ---
# Simple pub/sub for broadcasting notifications to active SSE connections.
# Each SSE subscriber gets its own asyncio.Queue to receive events.
_sse_subscribers: list[asyncio.Queue[str]] = []
_sse_subscribers_lock = asyncio.Lock()


async def broadcast_tools_changed() -> None:
    """Broadcast a tools/list_changed notification to all active SSE subscribers.

    This is called when tools change (approved, enabled/disabled, server start/stop)
    to tell MCP clients to re-fetch their tool list.
    """
    notification = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
        }
    )
    event_data = f"event: message\ndata: {notification}\n\n"

    async with _sse_subscribers_lock:
        subscriber_count = len(_sse_subscribers)
        for queue in _sse_subscribers:
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                logger.warning("SSE subscriber queue full, dropping notification")

    if subscriber_count > 0:
        logger.info("Broadcast tools/list_changed to %d SSE subscriber(s)", subscriber_count)


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
) -> StreamingResponse:
    """MCP Streamable HTTP SSE endpoint for server-to-client streaming.

    Per the MCP Streamable HTTP transport spec (2025-03-26+), GET to the MCP
    endpoint opens an SSE stream for server-initiated messages (notifications).

    Clients MUST include Mcp-Session-Id header (obtained from initialize).
    This stream broadcasts notifications such as notifications/tools/list_changed
    when tools are approved, enabled/disabled, or servers start/stop.
    """
    global _active_sse_connections

    # Validate session — clients must have initialized first
    session_id = request.headers.get("mcp-session-id")
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="Mcp-Session-Id header is required",
        )
    if not await _validate_session(session_id):
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired",
        )

    if _active_sse_connections >= MAX_SSE_CONNECTIONS:
        raise HTTPException(
            status_code=503,
            detail="Too many active SSE connections",
        )

    logger.info(
        "SSE stream opened (active: %d, session: %s)", _active_sse_connections + 1, session_id
    )

    # Create a subscriber queue for this SSE connection
    subscriber_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)

    async def event_generator():  # type: ignore[no-untyped-def]
        global _active_sse_connections
        _active_sse_connections += 1

        # Register subscriber
        async with _sse_subscribers_lock:
            _sse_subscribers.append(subscriber_queue)

        try:
            # Send initial keepalive to confirm the stream is working
            yield ": keepalive\n\n"
            while True:
                # Wait for either a notification event or keepalive timeout
                try:
                    event_data = await asyncio.wait_for(subscriber_queue.get(), timeout=15.0)
                    yield event_data
                except TimeoutError:
                    # No events received — send keepalive
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            logger.info("SSE stream closed by client (session: %s)", session_id)
        finally:
            # Unregister subscriber
            async with _sse_subscribers_lock:
                try:
                    _sse_subscribers.remove(subscriber_queue)
                except ValueError:
                    pass
            _active_sse_connections -= 1
            logger.info("SSE stream cleaned up (active: %d)", _active_sse_connections)

    response_headers: dict[str, str] = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Prevent nginx/proxy buffering
    }
    if session_id:
        response_headers["Mcp-Session-Id"] = session_id

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=response_headers,
    )


@router.delete("/mcp")
async def mcp_delete_session(
    request: Request,
    _user: AuthenticatedUser = Depends(verify_mcp_auth),
) -> Response:
    """MCP session termination endpoint.

    Per the MCP Streamable HTTP spec, clients SHOULD send DELETE to the
    MCP endpoint with Mcp-Session-Id to explicitly terminate a session.
    """
    session_id = request.headers.get("mcp-session-id")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Mcp-Session-Id header"
        )

    deleted = await _delete_session(session_id)
    if deleted:
        logger.info("MCP session terminated: %s", session_id)
        return Response(status_code=200)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


# --- MCP Gateway Endpoint ---


@router.post("/mcp", response_model=None)
async def mcp_gateway(
    request: MCPRequest,
    raw_request: Request,
    _user: AuthenticatedUser = Depends(verify_mcp_auth),
    db: AsyncSession = Depends(get_db),
    activity_logger: ActivityLoggerService = Depends(get_activity_logger),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> dict[str, Any] | Response | MCPResponse | JSONResponse:
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

    # Session management: validate Mcp-Session-Id on non-initialize requests
    session_id = raw_request.headers.get("mcp-session-id")
    if method != "initialize" and session_id:
        if not await _validate_session(session_id):
            raise HTTPException(
                status_code=404,
                detail="Session not found or expired. Send a new InitializeRequest.",
            )

    # Only log tools/call as mcp_request — protocol overhead (initialize,
    # notifications/*, tools/list) is not counted as a "request" in stats.
    if method == "tools/call":
        request_id = await activity_logger.log_mcp_request(
            method=method,
            params=params,
        )
    else:
        request_id = str(uuid.uuid4())[:8]

    try:
        response_result = None
        response_error = None
        new_session_id = ""  # Set during initialize

        # Log incoming request for diagnostics
        logger.info(
            "MCP %s from %s (auth_method=%s, email=%s)",
            method,
            _user.source,
            _user.auth_method,
            _user.email,
        )

        # SECURITY: Remote requests without a verified user identity are
        # restricted to protocol-level methods only (initialize, notifications).
        # Both tools/list and tools/call require a verified user email from
        # OIDC authentication at the Worker.
        #
        # With Access for SaaS (OIDC upstream), all human users authenticate
        # via OIDC and have a verified email in X-MCPbox-User-Email.
        # Tool names/descriptions are treated as sensitive for personal
        # toolsets — no anonymous enumeration is permitted.
        _is_anonymous_remote = _user.source == "worker" and not _user.email

        # Handle different MCP methods
        if method == "initialize":
            # MCP initialization handshake - required for Streamable HTTP transport.
            # Allowed without user email (needed for Cloudflare sync).
            # Create a new session for this client.
            new_session_id = await _create_session()
            logger.info("MCP session created: %s", new_session_id)

            response_result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": True},  # We support tools + change notifications
                },
                "serverInfo": {
                    "name": "mcpbox",
                    "version": "1.0.0",
                },
            }

        elif method.startswith("notifications/"):
            # Notifications are one-way messages - no response expected.
            # Allowed without user email (needed for Cloudflare sync).
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
            # SECURITY: With Access for SaaS (OIDC), all human users have
            # a verified email. Tool names/descriptions are sensitive for
            # personal toolsets — don't expose them without verified identity.
            if _is_anonymous_remote:
                logger.warning(
                    "Blocked anonymous remote tools/list from %s",
                    _user.source,
                )
                response_error = {
                    "code": -32600,
                    "message": "Tool listing requires user authentication",
                }
                duration_ms = int((time.time() - start_time) * 1000)
                await activity_logger.log_mcp_response(
                    request_id=request_id,
                    success=False,
                    duration_ms=duration_ms,
                    method=method,
                    error=str(response_error),
                )
                return MCPResponse(id=request.id, error=response_error)

            response_result = await _handle_tools_list(sandbox_client, db)

        elif method == "tools/call":
            # Tool execution requires a verified user identity for remote
            # requests. The email comes from X-MCPbox-User-Email header
            # set by the Worker from OIDC-verified OAuth token props.
            # Anonymous remote requests (Cloudflare sync) are blocked
            # from executing tools.
            if _is_anonymous_remote:
                logger.warning(
                    "Blocked anonymous remote tools/call from %s",
                    _user.source,
                )
                response_error = {
                    "code": -32600,
                    "message": "Tool execution requires user authentication via MCP Portal",
                }
                duration_ms = int((time.time() - start_time) * 1000)
                await activity_logger.log_mcp_response(
                    request_id=request_id,
                    success=False,
                    duration_ms=duration_ms,
                    method=method,
                    error=str(response_error),
                )
                return MCPResponse(id=request.id, error=response_error)

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

                # Fire-and-forget: log execution (don't block response)
                _tool_call_duration = int((time.time() - start_time) * 1000)
                asyncio.create_task(
                    _log_tool_execution(
                        tool_name=tool_name,
                        arguments=arguments,
                        sandbox_response=sandbox_response,
                        duration_ms=_tool_call_duration,
                        executed_by=_user.email if _user else None,
                    )
                )
        else:
            # Unknown methods: forward to sandbox.
            # Require authenticated user for remote requests as defense-in-depth.
            if _is_anonymous_remote:
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

        # Log response — detect both protocol errors and MCP isError results
        duration_ms = int((time.time() - start_time) * 1000)
        _is_tool_error = (
            isinstance(response.result, dict) and response.result.get("isError") is True
        )
        is_success = response.error is None and not _is_tool_error

        # Extract error message for activity log
        _log_error: str | None = None
        if response.error:
            _log_error = (
                response.error.get("message")
                if isinstance(response.error, dict)
                else str(response.error)
            )
        elif _is_tool_error and response.result is not None:
            # Extract first text content from isError result for the log
            _content = response.result.get("content", [])
            if isinstance(_content, list) and _content:
                _texts = [
                    c.get("text", "")
                    for c in _content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                _log_error = _texts[0][:500] if _texts else "Tool execution failed"

        await activity_logger.log_mcp_response(
            request_id=request_id,
            success=is_success,
            duration_ms=duration_ms,
            method=method,
            error=_log_error,
        )

        # Return response, excluding None fields for cleaner JSON-RPC
        response_body = response.model_dump(exclude_none=True)

        # For initialize responses, include Mcp-Session-Id header
        # per MCP Streamable HTTP spec (2025-03-26+)
        if method == "initialize" and is_success:
            return JSONResponse(
                content=response_body,
                headers={"Mcp-Session-Id": new_session_id},
            )

        return response_body

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
    db: AsyncSession,
) -> dict[str, Any]:
    """Handle tools/list by combining sandbox and management tools.

    Only includes tools that have been approved. Draft, pending, and rejected
    tools are filtered out from the sandbox response.

    SECURITY (F-09): db is required (not Optional) to ensure approval filtering
    always runs. Without a db session, unapproved tools would be exposed.
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
        approved_tool_names = await _get_approved_tool_names(db)
        sandbox_tools = [
            tool for tool in all_sandbox_tools if tool.get("name") in approved_tool_names
        ]

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
    # Block management tools from remote (tunnel) access unless admin has enabled it
    if tool_name in LOCAL_ONLY_TOOLS and user and user.source == "worker":
        setting_service = SettingService(db)
        remote_editing = await setting_service.get_value("remote_tool_editing", default="disabled")
        if remote_editing != "enabled":
            logger.warning(
                "Blocked remote call to local-only tool %s from %s",
                tool_name,
                user.email or "unknown",
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: {tool_name} is restricted to local access only. "
                        "An admin can enable remote tool editing in Settings > Security Policy.",
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


# --- Execution Log Capture ---


async def _log_tool_execution(
    tool_name: str,
    arguments: dict[str, Any],
    sandbox_response: dict[str, Any],
    duration_ms: int,
    executed_by: str | None = None,
) -> None:
    """Log a tool execution result to the database (fire-and-forget).

    Resolves the tool from its MCP name (ServerName__tool_name) to get
    tool_id and server_id.  Uses a fresh DB session since this runs
    as a background task after the request session is closed.
    """
    try:
        from sqlalchemy import select

        from app.models import Tool

        async with async_session_maker() as session:
            # Resolve MCP tool name → tool record
            # MCP tool name format: ServerName__tool_name
            short_name = tool_name.split("__", 1)[-1] if "__" in tool_name else tool_name

            result = await session.execute(select(Tool).where(Tool.name == short_name).limit(1))
            tool = result.scalar_one_or_none()

            if not tool:
                # Tool not found in DB — skip logging (might be a race condition)
                logger.debug(f"Tool {short_name} not found for execution logging")
                return

            # Parse sandbox response — handles both:
            # 1. JSON-RPC error (protocol-level: unknown tool, server error)
            # 2. MCP isError result (tool execution failure per MCP spec)
            has_error = "error" in sandbox_response
            error_msg = None
            tool_result = None
            stdout = None

            # Check for MCP isError tool execution failure in result
            raw_result = sandbox_response.get("result", {})
            is_tool_error = isinstance(raw_result, dict) and raw_result.get("isError") is True

            # Extract execution metadata (stdout, duration) from _meta
            # if present. The sandbox includes this so logging can capture
            # stdout and structured errors that would otherwise be lost
            # in the MCP JSON-RPC wrapping.
            if isinstance(raw_result, dict):
                meta = raw_result.get("_meta", {})
                execution_meta = meta.get("execution", {}) if isinstance(meta, dict) else {}
                stdout = execution_meta.get("stdout") if isinstance(execution_meta, dict) else None

            if has_error:
                # Protocol-level JSON-RPC error
                error_data = sandbox_response["error"]
                error_msg = (
                    error_data.get("message", str(error_data))
                    if isinstance(error_data, dict)
                    else str(error_data)
                )
            elif is_tool_error:
                # MCP tool execution error — extract error text from content
                content = raw_result.get("content", [])
                if isinstance(content, list) and content:
                    texts = [
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    error_msg = "\n".join(texts) if texts else "Tool execution failed"
                else:
                    error_msg = "Tool execution failed"
                has_error = True
            else:
                # Successful result
                if isinstance(raw_result, dict) and "content" in raw_result:
                    content = raw_result["content"]
                    if isinstance(content, list) and content:
                        texts = [
                            c.get("text", "")
                            for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        ]
                        tool_result = {"content": texts} if texts else raw_result
                    else:
                        tool_result = raw_result
                else:
                    tool_result = raw_result

            log_service = ExecutionLogService(session)
            await log_service.create_log(
                tool_id=tool.id,
                server_id=tool.server_id,
                tool_name=short_name,
                input_args=arguments,
                result=tool_result,
                error=error_msg,
                stdout=stdout,
                duration_ms=duration_ms,
                success=not has_error,
                executed_by=executed_by,
            )
            await session.commit()

    except Exception as e:
        # Never let logging failures propagate — this is fire-and-forget
        logger.warning(f"Failed to log tool execution: {e}")


# --- Health endpoint for tunnel target ---


@router.get("/mcp/health")
async def mcp_health(
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> dict[str, str]:
    """Health check endpoint for the MCP gateway.

    Used by cloudflared to verify the tunnel target is working.
    """
    sandbox_healthy = await sandbox_client.health_check()

    return {
        "status": "ok" if sandbox_healthy else "degraded",
        "sandbox": "healthy" if sandbox_healthy else "unhealthy",
    }


# --- Internal Notification Endpoint ---


async def _verify_internal_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """Verify internal service-to-service auth via SANDBOX_API_KEY.

    Defense-in-depth: even though this endpoint is only reachable on the
    Docker internal network, require the shared secret to prevent abuse
    from compromised containers.
    """
    expected_key = settings.sandbox_api_key
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Internal auth not configured"
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing Authorization header"
        )
    token = authorization[7:]
    if not secrets.compare_digest(token.encode(), expected_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal auth token"
        )


@router.post("/mcp/internal/notify-tools-changed")
async def notify_tools_changed(
    request: Request,
    _auth: None = Depends(_verify_internal_auth),
) -> dict[str, str]:
    """Internal endpoint to trigger tools/list_changed notification to all SSE clients.

    Called by the backend process when tools change (approval, enable/disable,
    server start/stop). This endpoint is internal-only — not exposed through
    the tunnel. Requires SANDBOX_API_KEY as defense-in-depth.

    The backend and MCP gateway run as separate processes, so this HTTP endpoint
    bridges the inter-process notification gap.
    """
    await broadcast_tools_changed()
    return {"status": "ok", "message": "Notification broadcast sent"}
