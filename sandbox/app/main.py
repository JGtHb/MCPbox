"""MCPbox Shared Sandbox Service.

A lightweight FastAPI service that dynamically loads and executes MCP tools.
Tools are registered via HTTP API and execute user-provided Python code.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.registry import tool_registry
from app.routes import router
from app.package_sync import startup_sync

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Sandbox service starting up")
    _check_security_configuration()

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


app = FastAPI(
    title="MCPbox Sandbox",
    description="Shared sandbox for executing MCP tools",
    version="0.1.0",
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
