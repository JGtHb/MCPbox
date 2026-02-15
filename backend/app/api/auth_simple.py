"""Simplified authentication for MCP Gateway.

MCPbox hybrid architecture:
- Local mode: No authentication needed (admin panel is local-only)
- Remote mode: Cloudflare Worker proxy adds X-MCPbox-Service-Token header

With Access for SaaS (OIDC upstream), all remote users are authenticated
via OIDC at the Worker. User identity (email) comes from the Worker-supplied
X-MCPbox-User-Email header, which is set from OIDC-verified OAuth token props.
No server-side JWT verification is needed — the Worker handles that at
authorization time via the OIDC id_token from Cloudflare Access.
"""

import logging
import secrets
import time
from collections import defaultdict
from typing import Annotated

from fastapi import Header, HTTPException, Request, status
from pydantic import BaseModel

from app.services.service_token_cache import ServiceTokenCache

logger = logging.getLogger(__name__)

# Rate limiting for failed service token attempts
_failed_auth_attempts: dict[str, list[float]] = defaultdict(list)
_FAILED_AUTH_WINDOW = 60  # 1-minute window
_FAILED_AUTH_MAX = 10  # Max failures per window


def _check_auth_rate_limit(client_ip: str) -> None:
    """Check if a client IP has exceeded the failed auth rate limit."""
    now = time.monotonic()
    attempts = _failed_auth_attempts[client_ip]
    # Prune old entries
    _failed_auth_attempts[client_ip] = [t for t in attempts if now - t < _FAILED_AUTH_WINDOW]
    if len(_failed_auth_attempts[client_ip]) >= _FAILED_AUTH_MAX:
        logger.warning(f"Auth rate limit exceeded for {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication failures",
        )


def _record_auth_failure(client_ip: str) -> None:
    """Record a failed authentication attempt for rate limiting."""
    _failed_auth_attempts[client_ip].append(time.monotonic())


class AuthenticatedUser(BaseModel):
    """User context from authentication."""

    email: str | None = None  # From OIDC (all OIDC-authenticated remote users have this)
    source: str  # "local" or "worker"
    auth_method: str | None = None  # "oidc" or None (local)


async def verify_mcp_auth(
    request: Request,
    x_mcpbox_service_token: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """Verify MCP gateway authentication.

    Authentication methods (in order of precedence):
    1. Service token from Worker proxy (X-MCPbox-Service-Token header)
    2. No auth required if no service token in database (local-only mode)

    With Access for SaaS, user identity comes from the Worker-supplied
    X-MCPbox-User-Email header. The Worker verified the user's identity
    via OIDC id_token from Cloudflare Access at authorization time and
    stored it in encrypted OAuth token props.
    """
    cache = ServiceTokenCache.get_instance()
    client_ip = request.client.host if request.client else "unknown"

    # If service token is configured, require it
    if await cache.is_auth_enabled():
        # Check rate limit before attempting auth
        _check_auth_rate_limit(client_ip)

        if not x_mcpbox_service_token:
            logger.warning("MCP request missing service token from %s", client_ip)
            _record_auth_failure(client_ip)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed",
            )

        # Use constant-time comparison to prevent timing attacks
        cached_token = await cache.get_token()
        if not cached_token or not secrets.compare_digest(
            x_mcpbox_service_token.encode(),
            cached_token.encode(),
        ):
            logger.warning("MCP request with invalid service token from %s", client_ip)
            _record_auth_failure(client_ip)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed",
            )

        # Valid service token — extract user email from Worker-supplied header.
        # The Worker verified identity via OIDC at authorization time.
        email: str | None = None
        forwarded_email = request.headers.get("X-MCPbox-User-Email")
        if forwarded_email:
            email = forwarded_email
            logger.info("MCP gateway: OIDC-verified email from Worker: %s", email)

        return AuthenticatedUser(
            email=email,
            source="worker",
            auth_method="oidc",
        )

    # No service token configured - local-only mode, allow all
    logger.debug("MCP auth: local mode (no service token configured)")
    return AuthenticatedUser(
        email=None,
        source="local",
    )
