"""MCPbox Backend - FastAPI Application Factory."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.mcp_gateway import router as mcp_router
from app.core import async_session_maker, settings, setup_logging
from app.core.logging import get_logger
from app.middleware import (
    AdminAuthMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    rate_limit_cleanup_loop,
)

# Import all models to ensure they're registered with Base for Alembic
from app.models import (  # noqa: F401
    ActivityLog,
    AdminUser,
    Credential,
    ModuleRequest,
    NetworkAccessRequest,
    Server,
    Setting,
    Tool,
    ToolVersion,
    TunnelConfiguration,
)
from app.services.activity_logger import ActivityLoggerService
from app.services.log_retention import LogRetentionService
from app.services.sandbox_client import SandboxClient
from app.services.service_token_cache import ServiceTokenCache
from app.services.token_refresh import TokenRefreshService
from app.services.tunnel import TunnelService

logger = get_logger("main")

# Background task for rate limiter cleanup
_rate_limit_cleanup_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    setup_logging(
        level=settings.log_level,
        format_type="structured" if not settings.debug else "dev",
    )
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize activity logger with database session factory
    activity_logger = ActivityLoggerService.get_instance()
    activity_logger.set_db_session_factory(async_session_maker)
    logger.info("Activity logger initialized with database")

    # Load service token from database
    service_token_cache = ServiceTokenCache.get_instance()
    await service_token_cache.load()

    # Check security configuration
    security_warnings = settings.check_security_configuration()
    for warning in security_warnings:
        logger.warning(f"SECURITY: {warning}")

    # Start background token refresh service
    token_refresh_service = TokenRefreshService.get_instance()
    await token_refresh_service.start()

    # Start background log retention service
    log_retention_service = LogRetentionService.get_instance()
    log_retention_service.retention_days = settings.log_retention_days
    await log_retention_service.start()

    # Start rate limiter cleanup task
    global _rate_limit_cleanup_task
    _rate_limit_cleanup_task = asyncio.create_task(rate_limit_cleanup_loop())

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop rate limiter cleanup task
    if _rate_limit_cleanup_task:
        _rate_limit_cleanup_task.cancel()
        try:
            await _rate_limit_cleanup_task
        except asyncio.CancelledError:
            pass

    # Stop token refresh service
    await token_refresh_service.stop()

    # Stop log retention service
    await log_retention_service.stop()

    # Stop tunnel if running
    tunnel_service = TunnelService.get_instance()
    if tunnel_service.status == "connected":
        logger.info("Stopping Cloudflare tunnel...")
        await tunnel_service.stop()

    # Close sandbox client HTTP connection
    sandbox_client = SandboxClient.get_instance()
    await sandbox_client.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="Self-hosted MCP server management platform",
        version=settings.app_version,
        lifespan=lifespan,
        # Always enable docs - admin panel is local-only (Option B architecture)
        docs_url="/docs",
        redoc_url="/redoc",
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
            "/docs",
            "/redoc",
            "/openapi.json",
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
            "X-Admin-API-Key",
        ],
    )

    # Include routers
    app.include_router(health_router)  # Health at root level
    app.include_router(auth_router)  # Auth at root level (/auth)
    app.include_router(internal_router)  # Internal service-to-service (/internal)
    app.include_router(api_router)  # API at /api
    app.include_router(mcp_router)  # MCP gateway at root level (/mcp)

    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


# Application instance
app = create_app()
