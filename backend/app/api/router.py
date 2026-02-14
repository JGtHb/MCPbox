"""MCPbox API Router - aggregates all API routes."""

from fastapi import APIRouter

from app.api import (
    activity,
    approvals,
    cloudflare,
    config,
    credentials,
    dashboard,
    export_import,
    oauth,
    sandbox,
    servers,
    settings,
    tools,
    tunnel,
)

# Main API router - all routes will be prefixed with /api
api_router = APIRouter(prefix="/api")

# Include routers
api_router.include_router(config.router)
api_router.include_router(servers.router)
api_router.include_router(tools.router)
api_router.include_router(credentials.router)
api_router.include_router(oauth.router)
api_router.include_router(sandbox.router)
api_router.include_router(tunnel.router)
api_router.include_router(cloudflare.router)
api_router.include_router(activity.router)
api_router.include_router(activity.ws_router)  # WebSocket endpoint (separate for auth handling)
api_router.include_router(settings.router)
api_router.include_router(export_import.router)
api_router.include_router(dashboard.router)
api_router.include_router(approvals.router)
