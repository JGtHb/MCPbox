"""MCPbox MCP Gateway - Minimal FastAPI app exposing ONLY /mcp endpoints.

This is the tunnel-exposed entry point. It cannot serve /api/* endpoints
because those routes don't exist in this app.

Architecture:
  - This app runs on port 8002 (internal to Docker network)
  - Tunnel points to this service
  - The main backend (port 8000) remains local-only with full /api/* access
  - Both apps share the same database and services

Authentication (Hybrid Model):
  - Local mode (no service token in database): No auth required
  - Remote mode: Validates X-MCPbox-Service-Token from Cloudflare Worker
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.mcp_gateway import router as mcp_router
from app.core import settings, setup_logging
from app.core.logging import get_logger
from app.middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    rate_limit_cleanup_loop,
)

# Import models for table creation
from app.models import (  # noqa: F401
    ActivityLog,
    Credential,
    Server,
    Setting,
    Tool,
    ToolVersion,
    TunnelConfiguration,
)
from app.services.log_retention import LogRetentionService
from app.services.sandbox_client import SandboxClient
from app.services.service_token_cache import ServiceTokenCache
from app.services.token_refresh import TokenRefreshService

logger = get_logger("mcp_gateway")

# Background task for rate limiter cleanup
_rate_limit_cleanup_task: asyncio.Task | None = None


def _task_done_callback(task: asyncio.Task[None]) -> None:
    """Log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"Background task {task.get_name()} failed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    setup_logging(
        level=settings.log_level,
        format_type="structured" if not settings.debug else "dev",
    )
    logger.info("Starting MCP Gateway")

    # Load service token from database
    service_token_cache = ServiceTokenCache.get_instance()
    await service_token_cache.load()

    if await service_token_cache.is_auth_enabled():
        logger.info("MCP Gateway running in REMOTE mode (service token auth enabled)")
    else:
        logger.info("MCP Gateway running in LOCAL mode (no auth required)")

    # Check security configuration
    security_warnings = settings.check_security_configuration()
    for warning in security_warnings:
        logger.warning(f"SECURITY: {warning}")

    # Start background services
    token_refresh_service = TokenRefreshService.get_instance()
    await token_refresh_service.start()

    log_retention_service = LogRetentionService.get_instance()
    log_retention_service.retention_days = settings.log_retention_days
    await log_retention_service.start()

    global _rate_limit_cleanup_task
    _rate_limit_cleanup_task = asyncio.create_task(rate_limit_cleanup_loop())
    _rate_limit_cleanup_task.add_done_callback(_task_done_callback)

    yield

    # Shutdown
    logger.info("Shutting down MCP Gateway...")

    if _rate_limit_cleanup_task:
        _rate_limit_cleanup_task.cancel()
        try:
            await _rate_limit_cleanup_task
        except asyncio.CancelledError:
            pass

    await token_refresh_service.stop()
    await log_retention_service.stop()

    sandbox_client = SandboxClient.get_instance()
    await sandbox_client.close()


def create_mcp_app() -> FastAPI:
    """Create the MCP-only FastAPI application."""
    app = FastAPI(
        title="MCPbox MCP Gateway",
        description="MCP protocol gateway",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # CORS - restrict to MCP client origins only (separate from admin panel CORS)
    # Configured via MCP_CORS_ORIGINS env var, defaults to claude.ai origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.mcp_cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-MCPbox-Service-Token"],
    )

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        exclude_paths=[],
    )

    # Prometheus metrics (localhost-only, not exposed through tunnel)
    if settings.enable_metrics:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            excluded_handlers=["/health", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # MCP router
    app.include_router(mcp_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint — minimal response, no service identification."""
        return {"status": "ok"}

    @app.get("/health")
    async def health(request: Request) -> dict[str, str] | JSONResponse:
        """Health check — only responds to localhost (Docker healthcheck).

        Requests from other IPs are rejected to avoid leaking service
        existence through the tunnel.
        """
        client_ip = request.client.host if request.client else None
        if client_ip not in ("127.0.0.1", "::1"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return {"status": "ok"}

    return app


# Application instance
app = create_mcp_app()
