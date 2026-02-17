"""Server recovery - re-registers running servers with sandbox on startup.

After a sandbox container restart, all in-memory tool registrations are lost.
Servers still show "running" in the database but their tools aren't registered.
This module re-registers them automatically on backend/mcp-gateway startup.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.models import Server
from app.services.sandbox_client import SandboxClient

logger = logging.getLogger(__name__)

# Wait for sandbox to be healthy before attempting recovery
RECOVERY_RETRY_DELAY = 3  # seconds
RECOVERY_MAX_RETRIES = 10  # 10 retries * 3 seconds = 30 seconds max wait


async def recover_running_servers() -> None:
    """Background task: re-register all 'running' servers with sandbox.

    Called from lifespan handlers in main.py and mcp_only.py.
    Waits for sandbox to be healthy, then re-registers each running server.
    """
    # Small delay to let services start
    await asyncio.sleep(3)

    sandbox_client = SandboxClient.get_instance()

    # Wait for sandbox to be healthy
    for attempt in range(1, RECOVERY_MAX_RETRIES + 1):
        if await sandbox_client.health_check():
            break
        if attempt < RECOVERY_MAX_RETRIES:
            logger.info(
                f"Sandbox not ready for recovery, retrying in {RECOVERY_RETRY_DELAY}s "
                f"(attempt {attempt}/{RECOVERY_MAX_RETRIES})"
            )
            await asyncio.sleep(RECOVERY_RETRY_DELAY)
    else:
        logger.warning("Sandbox not available for server recovery after all retries")
        return

    try:
        async with async_session_maker() as db:
            # Find all servers marked as "running"
            result = await db.execute(
                select(Server).options(selectinload(Server.tools)).where(Server.status == "running")
            )
            running_servers = result.scalars().all()

            if not running_servers:
                logger.info("No running servers to recover")
                return

            logger.info(f"Recovering {len(running_servers)} running server(s)")

            for server in running_servers:
                await _register_server(db, server, sandbox_client)

    except Exception as e:
        logger.error(f"Error during server recovery: {e}")


async def _register_server(db, server: Server, sandbox_client: SandboxClient) -> None:
    """Re-register a single server with the sandbox."""
    # Build tool definitions (only enabled + approved)
    tool_defs = []
    for tool in server.tools:
        if not tool.enabled:
            continue
        if tool.approval_status != "approved":
            continue
        tool_def = {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema or {},
            "timeout_ms": tool.timeout_ms or 30000,
            "python_code": tool.python_code,
            "tool_type": getattr(tool, "tool_type", "python_code"),
        }
        if tool_def["tool_type"] == "mcp_passthrough":
            tool_def["external_source_id"] = (
                str(tool.external_source_id) if tool.external_source_id else None
            )
            tool_def["external_tool_name"] = tool.external_tool_name
        tool_defs.append(tool_def)

    if not tool_defs:
        logger.info(f"Server '{server.name}' has no approved tools, skipping")
        return

    # Get secrets for injection
    from app.services.server_secret import ServerSecretService

    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(server.id)

    # Get allowed modules
    from app.services.global_config import GlobalConfigService

    config_service = GlobalConfigService(db)
    allowed_modules = await config_service.get_allowed_modules()

    # Build external MCP source configs
    from app.services.external_mcp_source import ExternalMCPSourceService

    source_service = ExternalMCPSourceService(db)
    sources = await source_service.list_by_server(server.id)
    external_sources_data = []
    for source in sources:
        if source.status == "disabled":
            continue
        auth_headers = await source_service._build_auth_headers(source, secrets)
        external_sources_data.append(
            {
                "source_id": str(source.id),
                "url": source.url,
                "auth_headers": auth_headers,
                "transport_type": source.transport_type,
            }
        )

    # Determine allowed hosts for network access enforcement
    allowed_hosts = server.allowed_hosts if server.network_mode == "allowlist" else None

    result = await sandbox_client.register_server(
        server_id=str(server.id),
        server_name=server.name,
        tools=tool_defs,
        helper_code=server.helper_code,
        allowed_modules=allowed_modules,
        secrets=secrets,
        external_sources=external_sources_data,
        allowed_hosts=allowed_hosts,
    )

    if result.get("success"):
        logger.info(
            f"Recovered server '{server.name}' with {result.get('tools_registered', 0)} tools"
        )
    else:
        logger.error(f"Failed to recover server '{server.name}': {result.get('error')}")
