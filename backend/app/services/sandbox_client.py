"""Sandbox Client - communicates with the shared sandbox service."""

import asyncio
import logging
import threading
from typing import Any, Optional

import httpx

from app.core import settings
from app.core.retry import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    RetryConfig,
    retry_async,
)

logger = logging.getLogger(__name__)

# Retry configuration for sandbox communication
SANDBOX_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=0.5,
    max_delay=10.0,
    exponential_base=2.0,
    jitter=True,
)

# Circuit breaker configuration for sandbox
SANDBOX_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=30.0,  # Shorter timeout since sandbox is local
)


class SandboxClient:
    """Client for communicating with the shared sandbox service.

    Replaces DockerService - instead of spawning containers, we register
    tools with the shared sandbox service.

    Includes retry logic with exponential backoff and circuit breaker
    for resilience against transient failures.
    """

    _instance: Optional["SandboxClient"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self, sandbox_url: str = "http://sandbox:8001"):
        self.sandbox_url = sandbox_url
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._api_key = settings.sandbox_api_key
        self._circuit_breaker = CircuitBreaker.get_or_create(
            "sandbox",
            SANDBOX_CIRCUIT_CONFIG,
        )

    def _get_headers(self) -> dict[str, str]:
        """Get headers for sandbox requests including API key."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    @classmethod
    def get_instance(cls, sandbox_url: str = "http://sandbox:8001") -> "SandboxClient":
        """Get or create singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls(sandbox_url)
        return cls._instance

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client.

        Uses a singleton pattern with proper cleanup of stale clients.
        Thread-safe via asyncio.Lock to prevent race conditions.

        Note: Returns a client that may be shared across requests. Callers should
        handle the case where the client might be closed between getting it and
        using it (e.g., by catching httpx.CloseError and retrying).
        """
        async with self._client_lock:
            if self._client is not None:
                try:
                    # Check if client is still usable
                    if self._client.is_closed:
                        self._client = None
                except Exception:
                    # Client in bad state, recreate
                    self._client = None

            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=settings.http_timeout,
                    # Use connection pooling with limits to prevent resource exhaustion
                    limits=httpx.Limits(
                        max_keepalive_connections=settings.http_keepalive_connections,
                        max_connections=settings.http_max_connections,
                        keepalive_expiry=settings.http_timeout,
                    ),
                )

            return self._client

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make HTTP request with automatic client recovery on connection errors.

        Handles the case where the shared client is closed between getting it
        and using it by recreating the client and retrying.
        """
        max_retries = 2
        for attempt in range(max_retries):
            try:
                client = await self._get_client()
                return await client.request(method, url, **kwargs)
            except (httpx.CloseError, httpx.RemoteProtocolError) as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"HTTP client error on attempt {attempt + 1}, recreating client: {e}"
                    )
                    async with self._client_lock:
                        # Force client recreation
                        if self._client is not None:
                            try:
                                await self._client.aclose()
                            except Exception:
                                pass
                            self._client = None
                else:
                    raise

    def get_circuit_state(self) -> dict:
        """Get current circuit breaker state."""
        return self._circuit_breaker.get_state()

    async def reset_circuit(self) -> None:
        """Reset circuit breaker to closed state."""
        await self._circuit_breaker.reset()

    async def health_check(self) -> bool:
        """Check if sandbox service is healthy."""
        try:

            async def do_health_check():
                client = await self._get_client()
                response = await client.get(
                    f"{self.sandbox_url}/health",
                    headers=self._get_headers(),
                )
                return response.status_code == 200

            return await retry_async(
                do_health_check,
                config=RetryConfig(max_retries=2, base_delay=0.5),
                circuit_breaker=self._circuit_breaker,
            )
        except CircuitBreakerOpen as e:
            logger.warning(f"Sandbox circuit breaker open: {e}")
            return False
        except Exception as e:
            logger.warning(f"Sandbox health check failed: {e}")
            return False

    async def register_server(
        self,
        server_id: str,
        server_name: str,
        tools: list[dict[str, Any]],
        credentials: list[dict[str, Any]],
        helper_code: str | None = None,
        allowed_modules: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a server with its tools in the sandbox.

        Args:
            server_id: Unique server ID
            server_name: Human-readable server name
            tools: List of tool definitions (with python_code for execution)
            credentials: List of credential dicts with auth_type metadata and encrypted values
            helper_code: Optional shared Python code for all tools
            allowed_modules: Custom list of allowed Python modules (None = use defaults)

        Returns:
            Registration result with success status and tool count
        """
        try:

            async def do_register():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/servers/register",
                    headers=self._get_headers(),
                    json={
                        "server_id": server_id,
                        "server_name": server_name,
                        "tools": tools,
                        "credentials": credentials,
                        "helper_code": helper_code,
                        "allowed_modules": allowed_modules,
                    },
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError as e:
                        logger.error(f"Invalid JSON response from sandbox: {e}")
                        return {
                            "success": False,
                            "error": "Invalid JSON response from sandbox",
                        }
                    logger.info(
                        f"Registered server {server_name} with {data.get('tools_registered', 0)} tools"
                    )
                    return {
                        "success": True,
                        "tools_registered": data.get("tools_registered", 0),
                    }
                else:
                    logger.error(f"Failed to register server: {response.text}")
                    return {
                        "success": False,
                        "error": response.text,
                    }

            return await retry_async(
                do_register,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            logger.error(f"Cannot register server - circuit breaker open: {e}")
            return {
                "success": False,
                "error": f"Sandbox temporarily unavailable: {e}",
                "circuit_breaker_open": True,
            }
        except Exception as e:
            logger.exception(f"Error registering server: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def unregister_server(self, server_id: str) -> dict[str, Any]:
        """Unregister a server from the sandbox.

        Args:
            server_id: Server ID to unregister

        Returns:
            Result with success status
        """
        try:

            async def do_unregister():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/servers/{server_id}/unregister",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    logger.info(f"Unregistered server {server_id}")
                    return {"success": True}
                elif response.status_code == 404:
                    # Not registered, that's fine
                    return {"success": True, "note": "Server was not registered"}
                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("detail", response.text)
                    except ValueError:
                        error_msg = response.text
                    return {"success": False, "error": error_msg}

            return await retry_async(
                do_unregister,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            logger.error(f"Cannot unregister server - circuit breaker open: {e}")
            return {
                "success": False,
                "error": f"Sandbox temporarily unavailable: {e}",
                "circuit_breaker_open": True,
            }
        except Exception as e:
            logger.exception(f"Error unregistering server: {e}")
            return {"success": False, "error": str(e)}

    async def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        """List all registered tools.

        Args:
            server_id: Optional filter by server

        Returns:
            List of tool definitions in MCP format
        """
        try:

            async def do_list():
                client = await self._get_client()
                params = {"server_id": server_id} if server_id else {}
                response = await client.get(
                    f"{self.sandbox_url}/tools",
                    headers=self._get_headers(),
                    params=params,
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        logger.warning("Invalid JSON response from sandbox list_tools")
                        return []
                    return data.get("tools", [])
                return []

            return await retry_async(
                do_list,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen:
            logger.warning("Cannot list tools - circuit breaker open")
            return []
        except Exception as e:
            logger.warning(f"Error listing tools: {e}")
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        debug_mode: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool in the sandbox.

        Args:
            tool_name: Full tool name (servername__toolname)
            arguments: Tool arguments
            debug_mode: If True, capture detailed debug info

        Returns:
            Execution result with optional debug info
        """
        try:

            async def do_call():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/tools/{tool_name}/call",
                    headers=self._get_headers(),
                    json={
                        "arguments": arguments,
                        "debug_mode": debug_mode,
                    },
                )
                # Check status before parsing JSON
                if response.status_code >= 500:
                    logger.error(f"Sandbox server error on tool call: {response.status_code}")
                    return {
                        "success": False,
                        "error": f"Sandbox server error: {response.status_code}",
                    }
                try:
                    return response.json()
                except ValueError as e:
                    logger.error(f"Invalid JSON response from tool call: {e}")
                    return {"success": False, "error": "Invalid JSON response from sandbox"}

            return await retry_async(
                do_call,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            logger.error(f"Cannot call tool - circuit breaker open: {e}")
            return {
                "success": False,
                "error": f"Sandbox temporarily unavailable: {e}",
            }
        except Exception as e:
            logger.exception(f"Error calling tool {tool_name}: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def mcp_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send an MCP JSON-RPC request to the sandbox.

        Args:
            request: MCP JSON-RPC request

        Returns:
            MCP JSON-RPC response
        """
        try:

            async def do_request():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/mcp",
                    headers=self._get_headers(),
                    json=request,
                )
                # Check status before parsing JSON
                if response.status_code >= 500:
                    logger.error(f"Sandbox server error on MCP request: {response.status_code}")
                    return {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32603,
                            "message": f"Sandbox server error: {response.status_code}",
                        },
                    }
                try:
                    return response.json()
                except ValueError as e:
                    logger.error(f"Invalid JSON response from MCP request: {e}")
                    return {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {"code": -32603, "message": "Invalid JSON response from sandbox"},
                    }

            return await retry_async(
                do_request,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            logger.error(f"Cannot process MCP request - circuit breaker open: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Sandbox temporarily unavailable: {e}",
                },
            }
        except Exception as e:
            logger.exception(f"Error with MCP request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Sandbox communication error: {e}",
                },
            }

    async def execute_code(
        self,
        code: str,
        arguments: dict[str, Any] | None = None,
        credentials: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        allowed_modules: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute Python code directly in the sandbox.

        This is used for testing code without registering it as a tool.

        Args:
            code: Python code with async def main() or result assignment
            arguments: Arguments to pass to the code
            credentials: Credential values to make available via os.environ
            timeout_seconds: Execution timeout
            allowed_modules: Custom list of allowed Python modules (None = use defaults)

        Returns:
            Execution result with success, result, error, and stdout
        """
        try:

            async def do_execute():
                client = await self._get_client()
                payload = {
                    "code": code,
                    "arguments": arguments or {},
                    "credentials": credentials or {},
                    "timeout_seconds": timeout_seconds,
                }
                if allowed_modules is not None:
                    payload["allowed_modules"] = allowed_modules
                response = await client.post(
                    f"{self.sandbox_url}/execute",
                    headers=self._get_headers(),
                    json=payload,
                )
                # Check status before parsing JSON
                if response.status_code >= 500:
                    logger.error(f"Sandbox server error on code execution: {response.status_code}")
                    return {
                        "success": False,
                        "error": f"Sandbox server error: {response.status_code}",
                    }
                try:
                    return response.json()
                except ValueError as e:
                    logger.error(f"Invalid JSON response from code execution: {e}")
                    return {"success": False, "error": "Invalid JSON response from sandbox"}

            return await retry_async(
                do_execute,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            logger.error(f"Cannot execute code - circuit breaker open: {e}")
            return {
                "success": False,
                "error": f"Sandbox temporarily unavailable: {e}",
            }
        except Exception as e:
            logger.exception(f"Error executing code: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- Package Management Methods ---

    async def install_package(
        self,
        module_name: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Install a package in the sandbox.

        Args:
            module_name: Module/import name to install
            version: Optional specific version

        Returns:
            Install result with status and details
        """
        try:

            async def do_install():
                client = await self._get_client()
                payload = {"module_name": module_name}
                if version:
                    payload["version"] = version

                response = await client.post(
                    f"{self.sandbox_url}/packages/install",
                    headers=self._get_headers(),
                    json=payload,
                    timeout=120.0,  # Package installation can take time
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        return {"success": False, "error": "Invalid JSON response"}
                else:
                    return {"success": False, "error": response.text}

            return await retry_async(
                do_install,
                config=RetryConfig(max_retries=2, base_delay=1.0),
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            return {"success": False, "error": f"Sandbox unavailable: {e}"}
        except Exception as e:
            logger.exception(f"Error installing package {module_name}: {e}")
            return {"success": False, "error": str(e)}

    async def sync_packages(self, modules: list[str]) -> dict[str, Any]:
        """Sync packages in the sandbox with the given module list.

        Args:
            modules: List of module names to ensure are installed

        Returns:
            Sync result with counts of installed/failed/stdlib packages
        """
        try:

            async def do_sync():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/packages/sync",
                    headers=self._get_headers(),
                    json={"modules": modules},
                    timeout=300.0,  # Sync can take a long time
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        return {"success": False, "error": "Invalid JSON response"}
                else:
                    return {"success": False, "error": response.text}

            return await retry_async(
                do_sync,
                config=RetryConfig(max_retries=2, base_delay=2.0),
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            return {"success": False, "error": f"Sandbox unavailable: {e}"}
        except Exception as e:
            logger.exception(f"Error syncing packages: {e}")
            return {"success": False, "error": str(e)}

    async def get_package_status(self, module_name: str) -> dict[str, Any]:
        """Get the installation status of a package.

        Args:
            module_name: Module name to check

        Returns:
            Status info including is_stdlib, is_installed, version
        """
        try:

            async def do_status():
                client = await self._get_client()
                response = await client.get(
                    f"{self.sandbox_url}/packages/status/{module_name}",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        return {"error": "Invalid JSON response"}
                else:
                    return {"error": response.text}

            return await retry_async(
                do_status,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen as e:
            return {"error": f"Sandbox unavailable: {e}"}
        except Exception as e:
            logger.warning(f"Error getting package status for {module_name}: {e}")
            return {"error": str(e)}

    async def list_installed_packages(self) -> list[dict[str, str]]:
        """List all packages installed in the sandbox.

        Returns:
            List of packages with name and version
        """
        try:

            async def do_list():
                client = await self._get_client()
                response = await client.get(
                    f"{self.sandbox_url}/packages",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                        return data.get("packages", [])
                    except ValueError:
                        return []
                return []

            return await retry_async(
                do_list,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except CircuitBreakerOpen:
            return []
        except Exception as e:
            logger.warning(f"Error listing installed packages: {e}")
            return []

    async def classify_modules(self, modules: list[str]) -> dict[str, list[str]]:
        """Classify modules as stdlib or third-party.

        Args:
            modules: List of module names

        Returns:
            Dict with 'stdlib' and 'third_party' lists
        """
        try:

            async def do_classify():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/packages/classify",
                    headers=self._get_headers(),
                    json={"modules": modules},
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        return {"stdlib": [], "third_party": []}
                return {"stdlib": [], "third_party": []}

            return await retry_async(
                do_classify,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except Exception as e:
            logger.warning(f"Error classifying modules: {e}")
            return {"stdlib": [], "third_party": []}

    async def get_pypi_info(self, module_name: str) -> dict[str, Any]:
        """Get PyPI information for a module.

        Args:
            module_name: Module name to look up

        Returns:
            PyPI info including package name, version, description
        """
        try:

            async def do_pypi():
                client = await self._get_client()
                response = await client.post(
                    f"{self.sandbox_url}/packages/pypi-info",
                    headers=self._get_headers(),
                    json={"module_name": module_name},
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        return {"error": "Invalid JSON response"}
                return {"error": response.text}

            return await retry_async(
                do_pypi,
                config=SANDBOX_RETRY_CONFIG,
                circuit_breaker=self._circuit_breaker,
            )

        except Exception as e:
            logger.warning(f"Error getting PyPI info for {module_name}: {e}")
            return {"error": str(e)}


# Dependency injection helper
def get_sandbox_client() -> SandboxClient:
    """Get the sandbox client singleton."""
    return SandboxClient.get_instance()
