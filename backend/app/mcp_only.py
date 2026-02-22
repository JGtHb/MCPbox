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

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.mcp_gateway import router as mcp_router
from app.core import settings
from app.core.logging import get_logger
from app.core.shared_lifespan import common_shutdown, common_startup
from app.middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

# Import models for table creation
from app.models import (  # noqa: F401
    ActivityLog,
    Server,
    ServerSecret,
    Setting,
    Tool,
    ToolExecutionLog,
    ToolVersion,
    TunnelConfiguration,
)
from app.services.service_token_cache import ServiceTokenCache

logger = get_logger("mcp_gateway")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    logger.info("Starting MCP Gateway")

    # Shared startup (logging, activity logger, service token, security
    # checks, log retention, rate-limit + session cleanup, server recovery)
    tasks = await common_startup(logger)

    # Log auth mode (gateway-only)
    service_token_cache = ServiceTokenCache.get_instance()
    if await service_token_cache.is_auth_enabled():
        logger.info("MCP Gateway running in REMOTE mode (service token auth enabled)")
    else:
        logger.info("MCP Gateway running in LOCAL mode (no auth required)")

    yield

    logger.info("Shutting down MCP Gateway...")
    await common_shutdown(logger, tasks)


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

    # Middleware is LIFO in Starlette: last added = outermost = runs first.
    # Order: RateLimit (innermost) → SecurityHeaders → CORS (outermost)
    # CORS must be outermost so preflight (OPTIONS) responses and error
    # responses from inner middleware all carry correct CORS headers (SEC-024).

    # Rate limiting (innermost — runs last)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        exclude_paths=[],
    )

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS (outermost — runs first, added last)
    # Restrict to MCP client origins only (separate from admin panel CORS).
    # Configured via MCP_CORS_ORIGINS env var, defaults to claude.ai origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.mcp_cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        # SECURITY: X-MCPbox-Service-Token removed — it's a server-to-server header
        # (Worker → Gateway), not a browser CORS header (SEC-013)
        allow_headers=["Authorization", "Content-Type", "Accept"],
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

    @app.get("/health", response_model=None)
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
