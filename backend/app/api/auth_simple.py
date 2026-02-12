"""Simplified authentication for MCP Gateway.

MCPbox hybrid architecture:
- Local mode: No authentication needed (admin panel is local-only)
- Remote mode: Cloudflare Worker proxy adds X-MCPbox-Service-Token header

The service token is loaded from the database (CloudflareConfig) at startup
and cached in memory by ServiceTokenCache. JWT verification params (team_domain,
portal_aud) are also cached for server-side Cf-Access-Jwt-Assertion validation.
"""

import logging
import secrets
import time
from collections import defaultdict
from typing import Annotated

import httpx
import jwt as pyjwt
from fastapi import Header, HTTPException, Request, status
from jwt.exceptions import PyJWTError
from pydantic import BaseModel

from app.services.service_token_cache import ServiceTokenCache

logger = logging.getLogger(__name__)

# JWKS cache (in-memory, refreshed every 5 minutes)
_jwks_cache: dict | None = None
_jwks_cache_time: float = 0.0
_JWKS_CACHE_TTL = 300  # 5 minutes
# Maximum age for stale JWKS cache before rejecting (15 minutes)
_JWKS_MAX_STALE_AGE = 900

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


async def _get_jwks(team_domain: str) -> dict | None:
    """Fetch JWKS from Cloudflare Access with caching."""
    global _jwks_cache, _jwks_cache_time

    now = time.monotonic()
    if _jwks_cache and (now - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache

    url = f"https://{team_domain}/cdn-cgi/access/certs"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                _jwks_cache = resp.json()
                _jwks_cache_time = now
                return _jwks_cache
            else:
                logger.warning(f"JWKS fetch failed: {resp.status_code}")
                # Return stale cache if within max age, otherwise reject
                if _jwks_cache and (now - _jwks_cache_time) < _JWKS_MAX_STALE_AGE:
                    return _jwks_cache
                logger.warning("JWKS stale cache exceeded max age, rejecting")
                return None
    except Exception as e:
        logger.warning(f"JWKS fetch error: {e}")
        # Return stale cache if within max age, otherwise reject
        if _jwks_cache and (now - _jwks_cache_time) < _JWKS_MAX_STALE_AGE:
            return _jwks_cache
        logger.warning("JWKS stale cache exceeded max age, rejecting")
        return None


async def _verify_cf_access_jwt(jwt_token: str, team_domain: str, expected_aud: str) -> dict | None:
    """Verify a Cloudflare Access JWT and return the payload, or None if invalid."""
    jwks = await _get_jwks(team_domain)
    if not jwks or "keys" not in jwks:
        logger.warning("No JWKS keys available for JWT verification")
        return None

    try:
        # Get the signing key from JWKS using the JWT header's kid
        header = pyjwt.get_unverified_header(jwt_token)
        jwk_set = pyjwt.PyJWKSet.from_dict(jwks)  # type: ignore[attr-defined]

        signing_key = None
        for key in jwk_set.keys:
            if key.key_id == header.get("kid"):
                signing_key = key.key
                break

        if signing_key is None:
            logger.warning("No matching key found in JWKS for kid=%s", header.get("kid"))
            return None

        payload = pyjwt.decode(
            jwt_token,
            signing_key,
            algorithms=["RS256"],
            audience=expected_aud,
            issuer=f"https://{team_domain}",
            leeway=60,  # 60s clock skew tolerance
        )
        return payload
    except PyJWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None


class AuthenticatedUser(BaseModel):
    """User context from authentication."""

    email: str | None = None  # Optional - extracted from verified CF JWT
    source: str  # "local" or "worker"
    auth_method: str | None = None  # "jwt", "oauth", or None (local)


async def verify_mcp_auth(
    request: Request,
    x_mcpbox_service_token: Annotated[str | None, Header()] = None,
    cf_access_jwt_assertion: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """Verify MCP gateway authentication.

    Authentication methods (in order of precedence):
    1. Service token from Worker proxy (X-MCPbox-Service-Token header)
    2. No auth required if no service token in database (local-only mode)

    When a service token is present, the auth_method is determined by
    server-side JWT verification of the Cf-Access-Jwt-Assertion header
    (NOT by trusting any Worker-supplied header).
    """
    cache = ServiceTokenCache.get_instance()
    client_ip = request.client.host if request.client else "unknown"

    # If service token is configured, require it
    # Uses TTL-aware check so token changes are picked up without restart
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

        # Valid service token — now determine auth_method by verifying JWT
        # server-side instead of trusting the Worker's X-MCPbox-Auth-Method header.
        auth_method: str = "oauth"  # default: OAuth-only (no JWT)
        email: str | None = None

        team_domain = await cache.get_team_domain()
        portal_aud = await cache.get_portal_aud()

        if cf_access_jwt_assertion and team_domain and portal_aud:
            payload = await _verify_cf_access_jwt(cf_access_jwt_assertion, team_domain, portal_aud)
            if payload:
                auth_method = "jwt"
                email = payload.get("email") if isinstance(payload.get("email"), str) else None
                logger.info("MCP gateway JWT verified for %s", email)

        return AuthenticatedUser(
            email=email,
            source="worker",
            auth_method=auth_method,
        )

    # No service token configured - local-only mode, allow all
    logger.debug("MCP auth: local mode (no service token configured)")
    return AuthenticatedUser(
        email=None,
        source="local",
    )
