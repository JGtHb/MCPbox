"""Tool Registry - manages tool definitions and execution."""

import asyncio
import ipaddress
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from app.executor import python_executor

logger = logging.getLogger(__name__)

# Maximum concurrent tool executions.  Prevents memory exhaustion when
# multiple heavy tools (e.g. fetching 20+ RSS feeds) run simultaneously
# inside the memory-constrained sandbox container.
MAX_CONCURRENT_EXECUTIONS = int(
    os.environ.get("SANDBOX_MAX_CONCURRENT_EXECUTIONS", "3")
)

# How long a request will wait for a semaphore slot before giving up.
EXECUTION_QUEUE_TIMEOUT = float(
    os.environ.get("SANDBOX_EXECUTION_QUEUE_TIMEOUT", "120")
)

# Module-level semaphore — created lazily on first use so that it binds
# to the running event loop (avoids "attached to a different loop" errors).
_execution_semaphore: asyncio.Semaphore | None = None


def _get_execution_semaphore() -> asyncio.Semaphore:
    """Return the module-level execution semaphore, creating it on first call."""
    global _execution_semaphore
    if _execution_semaphore is None:
        _execution_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXECUTIONS)
        logger.info(
            f"Execution semaphore initialized: max_concurrent={MAX_CONCURRENT_EXECUTIONS}, "
            f"queue_timeout={EXECUTION_QUEUE_TIMEOUT}s"
        )
    return _execution_semaphore


# Path where approved private hosts are written for the SOCKS5 proxy ACL.
# Must match the shared volume mount in docker-compose.yml.
# The SOCKS5 proxy reads this file to allow connections to private IPs.
_PROXY_ACL_PATH = Path(
    os.environ.get("PROXY_ACL_PATH", "/shared/proxy-acl/approved-private.txt")
)


@dataclass
class ExternalSourceConfig:
    """Connection config for an external MCP server."""

    source_id: str
    url: str
    auth_headers: dict[str, str] = field(default_factory=dict)
    transport_type: str = "streamable_http"


@dataclass
class Tool:
    """A registered tool - either Python code or MCP passthrough."""

    name: str
    description: str
    server_id: str
    server_name: str
    parameters: dict[str, Any]
    python_code: Optional[str] = None
    timeout_ms: int = 30000
    # MCP passthrough fields
    tool_type: str = "python_code"
    external_source_id: Optional[str] = None
    external_tool_name: Optional[str] = None

    @property
    def full_name(self) -> str:
        """Full tool name with server prefix."""
        return f"{self.server_name}__{self.name}"

    @property
    def is_passthrough(self) -> bool:
        """Whether this tool proxies to an external MCP server."""
        return self.tool_type == "mcp_passthrough"


@dataclass
class RegisteredServer:
    """A registered server with its tools."""

    server_id: str
    server_name: str
    allowed_modules: Optional[list[str]] = None  # Custom modules or None for defaults
    tools: dict[str, Tool] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)  # Decrypted key-value secrets
    # External MCP source configs (source_id → config)
    external_sources: dict[str, ExternalSourceConfig] = field(default_factory=dict)
    # Network access control: None = no restriction, set = only these hosts allowed
    allowed_hosts: Optional[set[str]] = None


def _parse_host_from_entry(entry: str) -> str:
    """Extract the bare host from an allowed_hosts entry.

    Entries may be ``host`` (any port) or ``host:port`` (specific port).
    Returns the host part only, used for private-IP / LAN detection.
    """
    if ":" in entry:
        # Could be host:port — split on the LAST colon so IPv6 literals
        # like ``[::1]:8080`` are handled (though those are blocked by
        # _ALWAYS_BLOCKED_NETWORKS anyway).
        host, _, maybe_port = entry.rpartition(":")
        if maybe_port.isdigit():
            return host
    return entry


def _filter_private_hosts(hosts: set[str]) -> list[str]:
    """Filter a set of allowed_hosts entries to those that look private/LAN.

    .. deprecated::
        No longer used in ACL write paths.  Kept for backward compatibility
        with tests / callers that may still reference it.

    Entries can be ``host`` or ``host:port``.  The host part is checked
    against private IP ranges and common LAN suffixes; the full entry
    (including ``:port`` if present) is returned so port enforcement
    flows through to the proxy ACL helper.

    Public hostnames (e.g. ``api.example.com``) are omitted — the proxy
    already allows those.

    .. note::
        This heuristic cannot detect public-looking hostnames that
        resolve to private IPs (e.g. ``zigbee.example.com`` → 192.168.x.x).
        Use :func:`_normalise_hosts_for_acl` instead, which writes *all*
        approved hosts to the ACL file so the proxy can make the final decision
        after DNS resolution.
    """
    private: list[str] = []
    for entry in sorted(hosts):
        host = _parse_host_from_entry(entry).lower()
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private:
                private.append(entry.lower())
            continue
        except ValueError:
            pass
        if host.endswith((".local", ".lan", ".home", ".internal")) or "." not in host:
            private.append(entry.lower())
    return private


def _normalise_hosts_for_acl(hosts: set[str]) -> list[str]:
    """Normalise approved hosts for writing to the proxy ACL file.

    Returns *all* approved hosts (lowercased, sorted) so the SOCKS5
    proxy can allowlist them before blocking private IP destinations.

    Previous versions filtered to only "obviously private" entries, but
    that missed public-looking hostnames that resolve to private IPs
    (e.g. ``zigbee.myhome.me`` → 192.168.1.50).  Since the ACL helper
    only matters for destinations that would otherwise hit ``blocked_dst``,
    including public hosts is harmless — the proxy already allows them.
    """
    return sorted(entry.lower() for entry in hosts)


def _write_proxy_acl(approved_hosts: list[str]) -> None:
    """Write approved hosts to the proxy ACL file (low-level)."""
    try:
        _PROXY_ACL_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROXY_ACL_PATH.write_text(
            "\n".join(approved_hosts) + "\n" if approved_hosts else ""
        )
        logger.debug(
            "Updated proxy ACL file with %d approved host(s)",
            len(approved_hosts),
        )
    except OSError as e:
        if not _PROXY_ACL_PATH.parent.exists():
            logger.debug("Proxy ACL volume not mounted, skipping: %s", e)
        else:
            logger.error(
                "Failed to write proxy ACL file %s: %s. "
                "Approved private hosts will be blocked by the proxy. "
                "Check volume permissions (sandbox user needs write access).",
                _PROXY_ACL_PATH,
                e,
            )


def ensure_private_hosts_in_proxy_acl(hosts: list[str] | None) -> None:
    """Ensure the given hosts are present in the proxy ACL file.

    Merges *hosts* with any existing entries so that hosts from
    registered servers are not removed.  Used by the ``/execute``
    endpoint which bypasses the registry and therefore doesn't
    trigger ``_update_proxy_approved_hosts``.

    The file is rebuilt from scratch on the next ``register_server``
    or ``unregister_server`` call, so temporary entries added here
    are cleaned up naturally.

    All approved hosts are written (not just obviously-private ones)
    so that hostnames resolving to private IPs are also covered.
    """
    if not hosts:
        return

    new_entries = set(_normalise_hosts_for_acl(set(hosts)))
    if not new_entries:
        return

    # Read existing entries to avoid clobbering hosts from running servers.
    existing: set[str] = set()
    try:
        if _PROXY_ACL_PATH.exists():
            existing = set(_PROXY_ACL_PATH.read_text().strip().split("\n")) - {""}
    except OSError:
        pass

    merged = existing | new_entries
    if merged != existing:
        _write_proxy_acl(sorted(merged))


class ToolRegistry:
    """Registry for managing MCP tools.

    Handles:
    - Tool registration/unregistration
    - Tool execution via Python code
    - Tool execution via MCP passthrough to external servers
    """

    def __init__(self):
        self.servers: dict[str, RegisteredServer] = {}

    @property
    def tool_count(self) -> int:
        """Total number of registered tools."""
        return sum(len(s.tools) for s in self.servers.values())

    def register_server(
        self,
        server_id: str,
        server_name: str,
        tools: list[dict[str, Any]],
        allowed_modules: Optional[list[str]] = None,
        secrets: dict[str, str] | None = None,
        external_sources: list[dict[str, Any]] | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> int:
        """Register a server with its tools.

        Args:
            server_id: Unique server identifier
            server_name: Human-readable server name
            tools: List of tool definitions
            allowed_modules: Custom list of allowed Python modules (None = defaults)
            secrets: Dict of secret key→value pairs for injection into tool namespace
            external_sources: List of external MCP source configs for passthrough tools
            allowed_hosts: List of approved network hostnames (None = no restriction)

        Returns:
            The number of tools registered.
        """
        if server_id in self.servers:
            # Unregister existing first
            self.unregister_server(server_id)

        server = RegisteredServer(
            server_id=server_id,
            server_name=server_name,
            allowed_modules=allowed_modules,
            secrets=secrets or {},
            allowed_hosts=set(allowed_hosts) if allowed_hosts is not None else None,
        )

        # Register external MCP sources
        for source_data in external_sources or []:
            source = ExternalSourceConfig(
                source_id=source_data["source_id"],
                url=source_data["url"],
                auth_headers=source_data.get("auth_headers", {}),
                transport_type=source_data.get("transport_type", "streamable_http"),
            )
            server.external_sources[source.source_id] = source

        for tool_def in tools:
            tool = Tool(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                server_id=server_id,
                server_name=server_name,
                parameters=tool_def.get("parameters", {}),
                python_code=tool_def.get("python_code"),
                timeout_ms=tool_def.get("timeout_ms", 30000),
                tool_type=tool_def.get("tool_type", "python_code"),
                external_source_id=tool_def.get("external_source_id"),
                external_tool_name=tool_def.get("external_tool_name"),
            )
            server.tools[tool.name] = tool

        self.servers[server_id] = server
        logger.info(
            f"Registered server {server_name} ({server_id}) with {len(server.tools)} tools"
            f" ({len(server.external_sources)} external sources)"
        )
        self._update_proxy_approved_hosts()
        return len(server.tools)

    def _update_proxy_approved_hosts(self) -> None:
        """Rebuild the proxy ACL file from all registered servers.

        The SOCKS5 proxy reads this file to decide whether to allow
        connections to private IP destinations that would otherwise be
        blocked.

        This is a full rebuild (not a merge) so that host removals from
        server unregistration or revocation are reflected immediately.
        """
        all_hosts: set[str] = set()
        for server in self.servers.values():
            if server.allowed_hosts:
                all_hosts.update(server.allowed_hosts)

        _write_proxy_acl(_normalise_hosts_for_acl(all_hosts))

    def update_secrets(self, server_id: str, secrets: dict[str, str]) -> bool:
        """Update secrets for a running server.

        Replaces the server's entire secrets dict with the new one.
        This is called when an admin sets, updates, or deletes a secret
        so the sandbox always has the latest decrypted values.

        Args:
            server_id: Server to update
            secrets: New complete dict of secret key→value pairs

        Returns:
            True if server was found and updated, False if not found.
        """
        if server_id not in self.servers:
            return False
        self.servers[server_id].secrets = secrets
        logger.info(
            f"Updated secrets for server {self.servers[server_id].server_name}"
            f" ({server_id}): {len(secrets)} secret(s)"
        )
        return True

    def unregister_server(self, server_id: str) -> bool:
        """Unregister a server and all its tools."""
        if server_id in self.servers:
            server = self.servers.pop(server_id)
            logger.info(f"Unregistered server {server.server_name} ({server_id})")
            self._update_proxy_approved_hosts()
            return True
        return False

    def get_tool(self, full_name: str) -> Optional[Tool]:
        """Get a tool by its full name (servername__toolname)."""
        for server in self.servers.values():
            for tool in server.tools.values():
                if tool.full_name == full_name:
                    return tool
        return None

    def get_server_for_tool(self, full_name: str) -> Optional[RegisteredServer]:
        """Get the server that owns a tool."""
        for server in self.servers.values():
            for tool in server.tools.values():
                if tool.full_name == full_name:
                    return server
        return None

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools in MCP format."""
        tools = []
        for server in self.servers.values():
            for tool in server.tools.values():
                tools.append(
                    {
                        "name": tool.full_name,
                        "description": tool.description,
                        "inputSchema": tool.parameters,
                    }
                )
        return tools

    def list_tools_for_server(self, server_id: str) -> list[dict[str, Any]]:
        """List tools for a specific server."""
        server = self.servers.get(server_id)
        if not server:
            return []

        return [
            {
                "name": tool.full_name,
                "description": tool.description,
                "inputSchema": tool.parameters,
            }
            for tool in server.tools.values()
        ]

    async def execute_tool(
        self,
        full_name: str,
        arguments: dict[str, Any],
        debug_mode: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool with the given arguments.

        Routes to Python execution or MCP passthrough based on tool_type.
        Concurrent Python executions are limited by a semaphore to prevent
        memory exhaustion in the sandbox container.
        """
        tool = self.get_tool(full_name)
        if not tool:
            return {
                "error": f"Tool not found: {full_name}",
                "success": False,
            }

        if tool.is_passthrough:
            return await self._execute_passthrough_tool(tool, arguments)

        # Acquire the concurrency semaphore for Python tool execution.
        # Passthrough tools proxy to external servers and don't consume
        # sandbox memory, so they skip the semaphore.
        sem = _get_execution_semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=EXECUTION_QUEUE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(
                f"Execution queue timeout for {full_name} after "
                f"{EXECUTION_QUEUE_TIMEOUT}s (max_concurrent={MAX_CONCURRENT_EXECUTIONS})"
            )
            return {
                "success": False,
                "error": (
                    f"Sandbox busy: {MAX_CONCURRENT_EXECUTIONS} tools are already running. "
                    f"Timed out after {EXECUTION_QUEUE_TIMEOUT}s waiting for a slot."
                ),
                "error_category": "sandbox_error",
            }

        try:
            return await self._execute_python_tool(tool, arguments, debug_mode)
        finally:
            sem.release()

    async def _execute_python_tool(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        debug_mode: bool = False,
    ) -> dict[str, Any]:
        """Execute a python_code mode tool."""
        if not tool.python_code:
            return {
                "success": False,
                "error": "Tool has no Python code defined",
            }

        # Get the server for allowed modules, secrets, and network config
        server = self.get_server_for_tool(tool.full_name)
        allowed_modules = (
            set(server.allowed_modules) if server and server.allowed_modules else None
        )
        secrets = server.secrets if server else {}
        allowed_hosts = server.allowed_hosts if server else None

        # Build HTTP client (unauthenticated — tools use secrets for auth)
        http_client = httpx.AsyncClient(
            timeout=tool.timeout_ms / 1000,
            follow_redirects=False,
        )

        try:
            # Execute the Python code
            result = await python_executor.execute(
                python_code=tool.python_code,
                arguments=arguments,
                http_client=http_client,
                timeout=tool.timeout_ms / 1000,
                debug_mode=debug_mode,
                allowed_modules=allowed_modules,
                secrets=secrets,
                allowed_hosts=allowed_hosts,
            )

            return result.to_dict()

        finally:
            # Always close the per-request client.
            # Catch exceptions to prevent aclose() failures from
            # suppressing the execution result (the finally block
            # would replace a successful return with an exception).
            try:
                await http_client.aclose()
            except Exception as e:
                logger.warning(f"Error closing HTTP client: {e}")

    async def _execute_passthrough_tool(
        self,
        tool: Tool,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a passthrough tool by proxying to an external MCP server.

        Uses the MCP session pool for connection reuse and automatic retry
        on transient errors (timeouts, 502/503/504, connection resets).

        SECURITY: Validates the external source URL through SSRF checks at call
        time (not just registration time) to catch DNS changes that could route
        traffic to internal infrastructure.
        """
        from app.mcp_session_pool import mcp_session_pool
        from app.ssrf import SSRFError, validate_url_with_pinning

        server = self.get_server_for_tool(tool.full_name)
        if not server:
            return {
                "success": False,
                "error": "Server not found for passthrough tool",
            }

        # Look up the external source config
        if not tool.external_source_id:
            return {
                "success": False,
                "error": "Passthrough tool has no external source configured",
            }

        source = server.external_sources.get(tool.external_source_id)
        if not source:
            return {
                "success": False,
                "error": f"External source {tool.external_source_id} not found",
            }

        # SECURITY: Validate external URL doesn't resolve to internal IPs.
        # DNS can change between registration and call time; re-validate now.
        try:
            validate_url_with_pinning(source.url)
        except SSRFError as e:
            logger.warning(
                f"Blocked passthrough tool {tool.full_name}: "
                f"external source URL {source.url} failed SSRF validation: {e}"
            )
            return {
                "success": False,
                "error": f"External source URL blocked: {e}",
            }

        external_name = tool.external_tool_name or tool.name

        logger.info(
            f"Proxying tool call: {tool.full_name} → {external_name}@{source.url}"
        )

        result = await mcp_session_pool.call_tool(
            url=source.url,
            tool_name=external_name,
            arguments=arguments,
            auth_headers=source.auth_headers,
        )

        return result

    async def clear_all(self):
        """Clear all registrations."""
        self.servers.clear()


# Global registry instance
tool_registry = ToolRegistry()
