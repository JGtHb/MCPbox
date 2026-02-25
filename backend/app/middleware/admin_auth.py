"""Admin API authentication middleware using JWT.

Provides mandatory defense-in-depth authentication for the admin API (/api/*) endpoints.
All requests to /api/* must include a valid JWT token in the Authorization header.

This protects against lateral movement attacks where an attacker on the same
LAN could access the admin API without proper authorization.
"""

import logging
import threading
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.services.auth import (
    InvalidTokenError,
    TokenExpiredError,
    UserInactiveError,
    validate_access_token,
)

logger = logging.getLogger(__name__)


# --- In-memory JTI blacklist cache (SEC-009 / F-02) ---
# The database-backed blacklist is the source of truth, but middleware cannot
# perform async DB queries. This cache is populated by blacklist_jti() (called
# from the logout endpoint) and checked here for O(1) lookups.
# Entries auto-expire based on the token's original expiry time.
_blacklisted_jtis: dict[str, float] = {}  # jti -> expiry_timestamp
_blacklist_lock = threading.Lock()


def blacklist_jti(jti: str, exp: float) -> None:
    """Add a JTI to the in-memory blacklist cache.

    Called from the logout endpoint after writing to the database.
    exp is the Unix timestamp when the token expires (auto-cleanup).
    """
    with _blacklist_lock:
        _blacklisted_jtis[jti] = exp


def is_jti_blacklisted(jti: str) -> bool:
    """Check if a JTI is in the in-memory blacklist cache."""
    with _blacklist_lock:
        exp = _blacklisted_jtis.get(jti)
        if exp is None:
            return False
        # Auto-cleanup expired entries
        if time.time() > exp:
            del _blacklisted_jtis[jti]
            return False
        return True


def cleanup_expired_jti_cache() -> int:
    """Remove expired entries from the in-memory cache. Returns count removed."""
    now = time.time()
    with _blacklist_lock:
        expired = [jti for jti, exp in _blacklisted_jtis.items() if now > exp]
        for jti in expired:
            del _blacklisted_jtis[jti]
        return len(expired)


# Paths that don't require admin auth (even when enabled)
# Only read-only health endpoints are excluded - circuit breaker reset requires auth
EXCLUDED_PATHS = [
    "/api/config",  # Frontend needs to check if auth is required
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
    - Checks in-memory JTI blacklist for revoked tokens (F-02)
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip auth for CORS preflight requests (OPTIONS)
        # These are handled by CORSMiddleware and should never require auth
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for excluded paths (exact or segment-boundary match)
        for excluded in EXCLUDED_PATHS:
            if path == excluded or path.startswith(excluded + "/"):
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
            payload = validate_access_token(token)
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

        # SECURITY (F-02): Check in-memory JTI blacklist for revoked tokens.
        # This catches tokens that were blacklisted via logout but haven't
        # expired yet. The in-memory cache is populated by blacklist_jti()
        # called from the logout endpoint.
        jti = payload.get("jti")
        if jti and is_jti_blacklisted(jti):
            logger.warning(f"Revoked token used for: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Token has been revoked"},
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
