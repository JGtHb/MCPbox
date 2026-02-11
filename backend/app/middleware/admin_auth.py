"""Admin API authentication middleware using JWT.

Provides mandatory defense-in-depth authentication for the admin API (/api/*) endpoints.
All requests to /api/* must include a valid JWT token in the Authorization header.

This protects against lateral movement attacks where an attacker on the same
LAN could access the admin API without proper authorization.
"""

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.services.auth import (
    InvalidTokenError,
    TokenExpiredError,
    UserInactiveError,
    validate_access_token,
)

logger = logging.getLogger(__name__)

# Paths that don't require admin auth (even when enabled)
# Only read-only health endpoints are excluded - circuit breaker reset requires auth
EXCLUDED_PATHS = [
    "/config",  # Frontend needs to check if auth is required
    "/mcp",  # MCP gateway has its own auth via Cloudflare
    "/auth",  # Auth endpoints handle their own authentication
    "/internal",  # Service-to-service endpoints (Docker internal network only)
]

# Read-only health check paths (no auth required)
READ_ONLY_HEALTH_PATHS = [
    "/health",
    "/health/detail",
    "/health/services",
    "/health/circuits",
    "/api/health",
    "/api/health/detail",
    "/api/health/services",
    "/api/health/circuits",
]


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to authenticate admin API requests using JWT.

    All /api/* requests must include a valid JWT token:
    - Token must be in: Authorization: Bearer <token>
    - Returns 401 Unauthorized if token is missing or invalid
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip auth for CORS preflight requests (OPTIONS)
        # These are handled by CORSMiddleware and should never require auth
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for excluded paths (prefix match)
        for excluded in EXCLUDED_PATHS:
            if path.startswith(excluded):
                return await call_next(request)

        # Skip auth for read-only health endpoints (exact match)
        if path in READ_ONLY_HEALTH_PATHS:
            return await call_next(request)

        # Only protect /api/* and /health/* mutating paths
        if not path.startswith("/api") and not path.startswith("/health"):
            return await call_next(request)

        # Extract JWT token from request
        token = self._extract_token(request)

        if not token:
            logger.warning(f"Admin API request without token: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. Include JWT token in Authorization: Bearer <token> header."
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate JWT token
        try:
            validate_access_token(token)
        except TokenExpiredError:
            logger.debug(f"Expired token for: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Token has expired"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        except (InvalidTokenError, UserInactiveError) as e:
            logger.warning(f"Invalid token for: {request.method} {path} - {e}")
            return JSONResponse(
                status_code=401,
                content={"detail": str(e)},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Token is valid, proceed
        return await call_next(request)

    def _extract_token(self, request: Request) -> str | None:
        """Extract JWT token from request headers.

        Checks Authorization: Bearer <token> header.
        """
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None
