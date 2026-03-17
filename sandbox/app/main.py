"""MCPbox Shared Sandbox Service.

A lightweight FastAPI service that dynamically loads and executes MCP tools.
Tools are registered via HTTP API and execute user-provided Python code.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.registry import tool_registry
from app.routes import router
from app.package_sync import startup_sync
from app.socket_patch import patch_socket

# Monkey-patch socket module so third-party libraries and stdlib (asyncio)
# route TCP through the SOCKS5 proxy during tool execution.
# Must happen after framework imports (FastAPI, uvicorn, httpx).
patch_socket()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Allowed origins for CORS - only accept from backend service
# NOTE: In production, set SANDBOX_CORS_ORIGINS explicitly. Default only allows
# Docker internal network (http://backend:8000) - no localhost for security.
ALLOWED_ORIGINS = os.environ.get("SANDBOX_CORS_ORIGINS", "http://backend:8000").split(
    ","
)

# Rate limiting configuration
RATE_LIMIT_PER_MINUTE = int(os.environ.get("SANDBOX_RATE_LIMIT_PER_MINUTE", "120"))

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": f"Too many requests. Limit: {RATE_LIMIT_PER_MINUTE}/minute",
            "retry_after": 60,
        },
        headers={"Retry-After": "60"},
    )


def _check_security_configuration():
    """Check security configuration and abort on critical issues.

    Validates required environment variables at startup so misconfigurations
    surface immediately rather than at runtime when a request hits.
    """
    sandbox_api_key = os.environ.get("SANDBOX_API_KEY", "")

    errors: list[str] = []

    if not sandbox_api_key:
        errors.append(
            "SANDBOX_API_KEY is required but not set. "
            'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    elif len(sandbox_api_key) < 32:
        errors.append(
            f"SANDBOX_API_KEY must be at least 32 characters, got {len(sandbox_api_key)}. "
            'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    if errors:
        for error in errors:
            logger.error(f"STARTUP FATAL: {error}")
        raise SystemExit(
            "Sandbox startup aborted due to configuration errors. "
            f"Fix the {len(errors)} error(s) above and restart."
        )


def _check_proxy_acl_volume():
    """Verify the proxy ACL shared volume is writable at startup.

    The sandbox writes approved-host entries to this volume so
    the SOCKS5 proxy can allow connections to approved hosts.  If
    the volume has stale permissions (e.g. from a pre-fix image), the
    sandbox cannot write and all approved LAN access will be blocked.
    """
    from app.registry import _PROXY_ACL_PATH

    acl_dir = _PROXY_ACL_PATH.parent
    if not acl_dir.exists():
        logger.debug(
            "Proxy ACL volume not mounted at %s (expected in dev/test)", acl_dir
        )
        return

    # Try writing a probe file to verify write access
    probe = acl_dir / ".write-probe"
    try:
        probe.write_text("")
        probe.unlink()
        logger.info("Proxy ACL volume at %s is writable", acl_dir)
    except OSError as e:
        logger.error(
            "STARTUP WARNING: Proxy ACL volume at %s is NOT writable: %s. "
            "Approved LAN network access will be blocked by the proxy. "
            "Fix: run 'docker compose down && docker compose up -d' to "
            "recreate containers, or manually run "
            "'docker run --rm -v mcpbox-proxy-acl:/vol alpine chmod 1777 /vol' "
            "to fix volume permissions.",
            acl_dir,
            e,
        )


def _patch_sys_modules_socket():
    """Replace ``sys.modules['socket']`` with SafeSocket for third-party libs.

    Third-party libraries imported during tool execution (e.g., paho-mqtt)
    do ``import socket`` via the real Python import system, which checks
    ``sys.modules``.  Without this patch they get the real socket module,
    whose connections fail because the sandbox container has no direct
    network access — all traffic must go through the SOCKS5 proxy.

    By replacing ``sys.modules['socket']`` *after* all framework imports
    are done (uvicorn, FastAPI, httpx already hold references to the real
    module), only newly imported libraries pick up the SafeSocket wrapper.
    This wrapper routes all TCP through the SOCKS5 proxy sidecar.

    The SafeSocket installed here uses ``allowed_hosts=None`` (no
    Python-level host restriction).  The SOCKS5 proxy ACL file is the
    authoritative enforcement layer.  Tool code's *direct* ``import socket``
    still goes through ``safe_import``, which creates a per-execution
    SafeSocket with proper ``allowed_hosts``.
    """
    import sys

    from app.executor import _parse_socks_proxy_env
    from app.safe_socket import create_safe_socket_module

    proxy_addr = _parse_socks_proxy_env()
    if proxy_addr is None:
        logger.warning(
            "SOCKS_PROXY not configured — third-party library TCP connections "
            "will fail in the sandbox.  Set SOCKS_PROXY=socks5://socks-proxy:1080"
        )
        return

    safe_mod = create_safe_socket_module(
        allowed_hosts=None,  # Proxy ACL is authoritative
        socks_proxy_addr=proxy_addr,
    )
    sys.modules["socket"] = safe_mod
    logger.info(
        "Patched sys.modules['socket'] with SafeSocket → SOCKS5 proxy at %s:%d",
        proxy_addr[0],
        proxy_addr[1],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Sandbox service starting up")
    _check_security_configuration()
    _check_proxy_acl_volume()

    # Patch sys.modules['socket'] so third-party libraries (e.g., paho-mqtt)
    # loaded during tool execution use SafeSocket → SOCKS5 proxy routing.
    # Must happen after all framework imports but before any tool execution.
    _patch_sys_modules_socket()

    # Start background task to sync packages with backend
    # This runs asynchronously so the service can start accepting requests immediately
    sync_task = asyncio.create_task(startup_sync())

    yield

    logger.info("Sandbox service shutting down")
    # Cancel sync task if still running
    if not sync_task.done():
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
    # Clean up any resources
    await tool_registry.clear_all()


def _read_version() -> str:
    """Read version from the VERSION file (single source of truth)."""
    candidates = [
        Path("/app/VERSION"),
        Path(__file__).resolve().parents[2] / "VERSION",
    ]
    for p in candidates:
        if p.is_file():
            return p.read_text().strip()
    return "0.0.0-unknown"


app = FastAPI(
    title="MCPbox Sandbox",
    description="Shared sandbox for executing MCP tools",
    version=_read_version(),
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS - restricted to backend service only
# Note: allow_credentials=False because this is internal service-to-service communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,  # Sandbox doesn't need credentials
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# Include routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "sandbox",
        "registered_servers": len(tool_registry.servers),
        "total_tools": tool_registry.tool_count,
    }
