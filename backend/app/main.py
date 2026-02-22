"""MCPbox Backend - FastAPI Application Factory."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.mcp_gateway import router as mcp_router
from app.core import async_session_maker, settings
from app.core.logging import get_logger
from app.core.shared_lifespan import common_shutdown, common_startup, task_done_callback
from app.middleware import (
    AdminAuthMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

# Import all models to ensure they're registered with Base for Alembic
from app.models import (  # noqa: F401
    ActivityLog,
    AdminUser,
    ModuleRequest,
    NetworkAccessRequest,
    Server,
    ServerSecret,
    Setting,
    TokenBlacklist,
    Tool,
    ToolExecutionLog,
    ToolVersion,
    TunnelConfiguration,
)
from app.services.tunnel import TunnelService

logger = get_logger("main")


async def _token_blacklist_cleanup_loop() -> None:
    """Periodically remove expired entries from the token blacklist."""
    from app.api.auth import cleanup_expired_blacklist_entries

    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        try:
            async with async_session_maker() as db:
                removed = await cleanup_expired_blacklist_entries(db)
                await db.commit()
                if removed > 0:
                    logger.info(f"Cleaned up {removed} expired token blacklist entries")
        except Exception:
            logger.exception("Error cleaning up token blacklist")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Shared startup (logging, activity logger, service token, security
    # checks, log retention, rate-limit + session cleanup, server recovery)
    tasks = await common_startup(logger)
    logger.info("Activity logger initialized with database")

    # Main-only: token blacklist cleanup (admin API handles JWT auth)
    blacklist_task = asyncio.create_task(_token_blacklist_cleanup_loop())
    blacklist_task.add_done_callback(task_done_callback)
    tasks.append(blacklist_task)

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop tunnel if running (main-only)
    tunnel_service = TunnelService.get_instance()
    if tunnel_service.status == "connected":
        logger.info("Stopping Cloudflare tunnel...")
        await tunnel_service.stop()

    await common_shutdown(logger, tasks)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="Self-hosted MCP server management platform",
        version=settings.app_version,
        lifespan=lifespan,
        # SECURITY (SEC-028): Disable OpenAPI docs in production. The docs endpoint
        # sits outside /api/* and bypasses AdminAuthMiddleware, exposing the full
        # API schema (all endpoints, parameters, and Pydantic schemas) without auth.
        # Developers can re-enable via MCPBOX_DEBUG=true for local development.
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # Admin API authentication middleware (mandatory defense-in-depth for LAN security)
    # All /api/* requests require a valid JWT token in Authorization header
    app.add_middleware(AdminAuthMiddleware)

    # Security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limiting middleware - configurable via RATE_LIMIT_REQUESTS_PER_MINUTE
    # Health endpoints excluded for Kubernetes/monitoring probes
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        exclude_paths=[
            "/health",
            "/health/detail",
            "/health/services",
        ],
    )

    # CORS middleware - MUST be outermost (added last in Starlette LIFO order)
    # so that CORS headers are present on ALL responses, including 401 from AdminAuth.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
        ],
    )

    # Prometheus metrics (before routers so /metrics endpoint is registered first)
    if settings.enable_metrics:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            excluded_handlers=["/health", "/health/detail", "/health/services", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # Include routers
    app.include_router(health_router)  # Health at root level
    app.include_router(auth_router)  # Auth at root level (/auth)
    app.include_router(internal_router)  # Internal service-to-service (/internal)
    app.include_router(api_router)  # API at /api
    app.include_router(mcp_router)  # MCP gateway at root level (/mcp)

    # Root endpoint
    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint with API information."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


# Application instance
app = create_app()
