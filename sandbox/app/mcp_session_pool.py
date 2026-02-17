"""MCP Session Pool - connection reuse and retry for external MCP servers.

Maintains initialized MCP client sessions for reuse across tool calls,
avoiding the overhead of TCP+TLS handshake and MCP initialize per request.

Features:
- Per-URL+auth session pooling with automatic expiry
- Retry with exponential backoff for transient errors
- Broken session eviction and transparent recreation
- Health check support for connectivity monitoring
"""

import asyncio
import hashlib
import logging
import time
from typing import Any

from app.mcp_client import CloudflareChallengeError, MCPClient, MCPClientError

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds
RETRY_MAX_DELAY = 5.0  # seconds

# Pool configuration
SESSION_MAX_AGE = 300.0  # 5 minutes
MAX_POOL_SIZE = 50

# HTTP status codes that indicate transient errors worth retrying
_TRANSIENT_PATTERNS = ["timed out", "timeout", "connection refused", "connection reset"]
_TRANSIENT_HTTP_CODES = [429, 502, 503, 504]


def _pool_key(url: str, auth_headers: dict[str, str]) -> str:
    """Generate a unique pool key for a URL + auth combination."""
    headers_str = str(sorted(auth_headers.items())) if auth_headers else ""
    h = hashlib.sha256(f"{url}|{headers_str}".encode()).hexdigest()[:16]
    return f"{url}#{h}"


def _is_transient_error(error: MCPClientError) -> bool:
    """Classify whether an MCP error is transient and worth retrying."""
    # Cloudflare challenges are never transient — retrying won't help
    if isinstance(error, CloudflareChallengeError):
        return False

    msg = str(error).lower()

    # Check for known transient patterns
    for pattern in _TRANSIENT_PATTERNS:
        if pattern in msg:
            return True

    # Check for transient HTTP status codes
    for code in _TRANSIENT_HTTP_CODES:
        if f"http {code}" in msg:
            return True

    return False


class _PoolEntry:
    """A pooled MCP client session with lifecycle management."""

    def __init__(self, url: str, auth_headers: dict[str, str]):
        self.url = url
        self.auth_headers = auth_headers
        self.client = MCPClient(url, auth_headers=auth_headers)
        self.initialized = False
        self.created_at = time.monotonic()
        self.last_used_at = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def age(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def is_expired(self) -> bool:
        return self.age > SESSION_MAX_AGE

    async def ensure_initialized(self) -> None:
        """Open and initialize the MCP session if not already done."""
        if not self.initialized:
            await self.client.open()
            await self.client.initialize()
            self.initialized = True
        self.last_used_at = time.monotonic()

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        try:
            self.client.close()
        except Exception:
            pass
        self.initialized = False

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool with session-level locking."""
        async with self._lock:
            await self.ensure_initialized()
            return await self.client.call_tool(tool_name, arguments)

    async def list_tools(self) -> list[dict[str, Any]]:
        """List tools with session-level locking."""
        async with self._lock:
            await self.ensure_initialized()
            return await self.client.list_tools()

    async def health_check(self) -> dict[str, Any]:
        """Check if the external server is reachable via MCP initialize."""
        async with self._lock:
            start = time.monotonic()
            try:
                await self.client.open()
                await self.client.initialize()
                self.initialized = True
                latency_ms = int((time.monotonic() - start) * 1000)
                return {"healthy": True, "latency_ms": latency_ms}
            except MCPClientError as e:
                latency_ms = int((time.monotonic() - start) * 1000)
                return {"healthy": False, "latency_ms": latency_ms, "error": str(e)}


class MCPSessionPool:
    """Connection pool for external MCP server sessions.

    Provides session reuse, automatic retry with exponential backoff,
    and health checking for external MCP server connections.
    """

    def __init__(
        self,
        max_age: float = SESSION_MAX_AGE,
        max_size: int = MAX_POOL_SIZE,
    ):
        self._entries: dict[str, _PoolEntry] = {}
        self._lock = asyncio.Lock()
        self._max_age = max_age
        self._max_size = max_size

    async def _get_or_create(
        self, url: str, auth_headers: dict[str, str]
    ) -> _PoolEntry:
        """Get an existing pool entry or create a new one."""
        key = _pool_key(url, auth_headers)

        async with self._lock:
            entry = self._entries.get(key)

            if entry and entry.age > self._max_age:
                await entry.close()
                del self._entries[key]
                entry = None
                logger.debug(f"Expired pool entry for {url}")

            if entry is None:
                # Evict LRU if at capacity
                if len(self._entries) >= self._max_size:
                    await self._evict_lru()

                entry = _PoolEntry(url, auth_headers)
                self._entries[key] = entry

            return entry

    async def _evict_lru(self) -> None:
        """Evict the least recently used entry. Must hold self._lock."""
        if not self._entries:
            return

        lru_key = min(self._entries, key=lambda k: self._entries[k].last_used_at)
        entry = self._entries.pop(lru_key)
        await entry.close()
        logger.debug(f"Evicted LRU pool entry: {entry.url}")

    async def _evict(self, url: str, auth_headers: dict[str, str]) -> None:
        """Evict a specific entry (e.g., after a connection error)."""
        key = _pool_key(url, auth_headers)
        async with self._lock:
            entry = self._entries.pop(key, None)
            if entry:
                await entry.close()

    async def call_tool(
        self,
        url: str,
        tool_name: str,
        arguments: dict[str, Any],
        auth_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Call a tool on an external MCP server with session reuse and retries.

        On transient errors (timeouts, 502/503/504, connection resets),
        retries with exponential backoff up to MAX_RETRIES times.
        Non-transient errors (401, 403, CF challenges) fail immediately.
        """
        headers = auth_headers or {}
        last_error: MCPClientError | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                entry = await self._get_or_create(url, headers)
                return await entry.call_tool(tool_name, arguments)
            except MCPClientError as e:
                last_error = e
                await self._evict(url, headers)

                if not _is_transient_error(e) or attempt == MAX_RETRIES:
                    break

                delay = min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)
                logger.warning(
                    f"Transient error calling {tool_name}@{url} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)
            except Exception as e:
                await self._evict(url, headers)
                logger.exception(f"Unexpected error calling {tool_name}@{url}: {e}")
                return {"success": False, "error": f"Unexpected error: {e}"}

        error_msg = str(last_error) if last_error else "Unknown error"
        logger.error(f"All retries exhausted for {tool_name}@{url}: {error_msg}")
        return {"success": False, "error": error_msg}

    async def discover_tools(
        self,
        url: str,
        auth_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Discover tools with session reuse and retries."""
        headers = auth_headers or {}
        last_error: MCPClientError | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                entry = await self._get_or_create(url, headers)
                tools = await entry.list_tools()
                return {"success": True, "tools": tools}
            except MCPClientError as e:
                last_error = e
                await self._evict(url, headers)

                if not _is_transient_error(e) or attempt == MAX_RETRIES:
                    break

                delay = min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)
                logger.warning(
                    f"Transient error discovering tools at {url} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)
            except Exception as e:
                await self._evict(url, headers)
                logger.exception(f"Unexpected error discovering tools at {url}: {e}")
                return {
                    "success": False,
                    "error": f"Unexpected error: {e}",
                    "tools": [],
                }

        error_msg = str(last_error) if last_error else "Unknown error"
        logger.error(f"All retries exhausted for discovery at {url}: {error_msg}")
        return {"success": False, "error": error_msg, "tools": []}

    async def health_check(
        self,
        url: str,
        auth_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Check connectivity to an external MCP server.

        Returns dict with 'healthy' (bool), 'latency_ms' (int),
        and optional 'error' (str).
        """
        headers = auth_headers or {}
        entry = await self._get_or_create(url, headers)
        result = await entry.health_check()

        if not result["healthy"]:
            await self._evict(url, headers)

        return result

    async def evict_by_source_url(self, source_url: str) -> None:
        """Evict all sessions for a specific source URL."""
        async with self._lock:
            keys_to_remove = [
                k for k, v in self._entries.items() if v.url == source_url
            ]
            for key in keys_to_remove:
                entry = self._entries.pop(key)
                await entry.close()
                logger.debug(f"Evicted pool entry for source: {entry.url}")

    async def close_all(self) -> None:
        """Close all pooled sessions."""
        async with self._lock:
            for entry in self._entries.values():
                await entry.close()
            self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        """Get pool statistics for monitoring."""
        return {
            "pool_size": self.size,
            "max_size": self._max_size,
            "sessions": [
                {
                    "url": entry.url,
                    "initialized": entry.initialized,
                    "age_seconds": round(entry.age, 1),
                    "idle_seconds": round(time.monotonic() - entry.last_used_at, 1),
                }
                for entry in self._entries.values()
            ],
        }


# Global session pool singleton
mcp_session_pool = MCPSessionPool()
