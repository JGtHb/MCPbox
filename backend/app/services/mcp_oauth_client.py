"""MCP OAuth 2.1 client for authenticating with external MCP servers.

Implements the MCP spec authorization flow:
1. Probe external server → get 401 + WWW-Authenticate header
2. Discover Protected Resource Metadata (RFC 9728)
3. Discover Authorization Server Metadata (RFC 8414)
4. Dynamic Client Registration (RFC 7591) if available
5. Authorization Code + PKCE flow via browser popup
6. Token exchange and encrypted storage
7. Token refresh when expired

References:
- MCP Authorization Spec: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- RFC 9728: OAuth 2.0 Protected Resource Metadata
- RFC 8414: OAuth 2.0 Authorization Server Metadata
- RFC 7591: OAuth 2.0 Dynamic Client Registration
"""

import hashlib
import json
import logging
import secrets
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import UUID

import httpx

from app.services.crypto import decrypt_from_base64, encrypt_to_base64

logger = logging.getLogger(__name__)

# In-memory store for pending OAuth flows (single-instance deployment)
_pending_flows: dict[str, "OAuthFlowState"] = {}
FLOW_EXPIRY_SECONDS = 600  # 10 minutes

# User-Agent for OAuth metadata discovery (backend, not sandbox)
OAUTH_USER_AGENT = "MCPbox/1.0.0 (OAuth Client)"

# Timeout for OAuth HTTP requests
OAUTH_TIMEOUT = 15.0


class OAuthError(Exception):
    """Error during OAuth flow."""


class OAuthDiscoveryError(OAuthError):
    """Failed to discover OAuth metadata from the external server."""


class OAuthTokenError(OAuthError):
    """Failed to exchange or refresh OAuth tokens."""


@dataclass
class OAuthMetadata:
    """Discovered OAuth configuration for an external MCP server."""

    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    resource: str | None = None
    scopes_supported: list[str] = field(default_factory=list)
    issuer: str | None = None


@dataclass
class OAuthFlowState:
    """State for a pending OAuth authorization flow."""

    source_id: UUID
    code_verifier: str
    redirect_uri: str
    token_endpoint: str
    client_id: str
    client_secret: str | None
    created_at: float


@dataclass
class OAuthTokens:
    """OAuth tokens received from the authorization server."""

    access_token: str
    refresh_token: str | None
    token_endpoint: str
    expires_at: str | None  # ISO timestamp
    scope: str | None


def _cleanup_expired_flows() -> None:
    """Remove expired pending OAuth flows."""
    now = time.time()
    expired = [k for k, v in _pending_flows.items() if now - v.created_at > FLOW_EXPIRY_SECONDS]
    for k in expired:
        del _pending_flows[k]


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns:
        Tuple of (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _get_http_client() -> httpx.AsyncClient:
    """Create an httpx client for OAuth metadata/token requests."""
    return httpx.AsyncClient(
        timeout=OAUTH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": OAUTH_USER_AGENT},
    )


async def discover_oauth_metadata(url: str) -> OAuthMetadata:
    """Discover OAuth metadata for an external MCP server.

    Follows the MCP spec discovery flow:
    1. Send a probe request to the MCP URL
    2. On 401, extract resource_metadata URL from WWW-Authenticate header
    3. Fetch Protected Resource Metadata (RFC 9728)
    4. Fetch Authorization Server Metadata (RFC 8414)

    Args:
        url: The external MCP server URL.

    Returns:
        Discovered OAuth metadata.

    Raises:
        OAuthDiscoveryError: If discovery fails at any step.
    """
    async with _get_http_client() as client:
        # Step 1: Probe the MCP endpoint
        try:
            response = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": "probe", "method": "initialize", "params": {}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            raise OAuthDiscoveryError(f"Cannot reach external server: {e}") from e

        if response.status_code == 200:
            raise OAuthDiscoveryError(
                "Server returned 200 — it does not require OAuth authentication. "
                "Use auth_type 'none', 'bearer', or 'header' instead."
            )

        if response.status_code != 401:
            raise OAuthDiscoveryError(
                f"Expected 401 Unauthorized for OAuth discovery, got {response.status_code}. "
                f"This server may not support OAuth authentication."
            )

        # Step 2: Extract resource_metadata from WWW-Authenticate
        www_auth = response.headers.get("www-authenticate", "")
        resource_metadata_url = _parse_resource_metadata_url(www_auth, url)

        # Step 3: Fetch Protected Resource Metadata (RFC 9728)
        try:
            prm_response = await client.get(resource_metadata_url)
            prm_response.raise_for_status()
            prm = prm_response.json()
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise OAuthDiscoveryError(
                f"Failed to fetch Protected Resource Metadata from {resource_metadata_url}: {e}"
            ) from e

        auth_servers = prm.get("authorization_servers", [])
        if not auth_servers:
            raise OAuthDiscoveryError(
                "Protected Resource Metadata has no authorization_servers listed."
            )

        auth_server_url = auth_servers[0]
        resource = prm.get("resource")

        # Step 4: Fetch Authorization Server Metadata (RFC 8414)
        parsed = urlparse(auth_server_url)
        asm_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"
        if parsed.path and parsed.path != "/":
            asm_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}"

        try:
            asm_response = await client.get(asm_url)
            asm_response.raise_for_status()
            asm = asm_response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise OAuthDiscoveryError(
                f"Failed to fetch Authorization Server Metadata from {asm_url}: {e}"
            ) from e

        authorization_endpoint = asm.get("authorization_endpoint")
        token_endpoint = asm.get("token_endpoint")
        if not authorization_endpoint or not token_endpoint:
            raise OAuthDiscoveryError(
                "Authorization Server Metadata missing required endpoints "
                "(authorization_endpoint, token_endpoint)."
            )

        return OAuthMetadata(
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            registration_endpoint=asm.get("registration_endpoint"),
            resource=resource,
            scopes_supported=asm.get("scopes_supported", []),
            issuer=asm.get("issuer", auth_server_url),
        )


def _parse_resource_metadata_url(www_authenticate: str, mcp_url: str) -> str:
    """Parse the resource_metadata URL from a WWW-Authenticate header.

    Falls back to constructing the well-known URL from the MCP server origin.
    """
    # Try to extract resource_metadata="..." from the header
    if "resource_metadata=" in www_authenticate:
        for part in www_authenticate.split(","):
            part = part.strip()
            if "resource_metadata=" in part:
                value = part.split("resource_metadata=", 1)[1].strip()
                # Remove surrounding quotes
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                return value

    # Fallback: try well-known URL at the MCP server origin
    parsed = urlparse(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource"


async def register_client(
    registration_endpoint: str,
    redirect_uri: str,
    client_name: str = "MCPbox",
) -> tuple[str, str | None]:
    """Register as an OAuth client via Dynamic Client Registration (RFC 7591).

    Returns:
        Tuple of (client_id, client_secret or None).
    """
    async with _get_http_client() as client:
        try:
            response = await client.post(
                registration_endpoint,
                json={
                    "client_name": client_name,
                    "redirect_uris": [redirect_uri],
                    "grant_types": ["authorization_code"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise OAuthError(f"Dynamic Client Registration failed: {e}") from e

    client_id = data.get("client_id")
    if not client_id:
        raise OAuthError("DCR response missing client_id")

    return client_id, data.get("client_secret")


async def start_oauth_flow(
    source_id: UUID,
    mcp_url: str,
    callback_url: str,
    existing_client_id: str | None = None,
) -> dict[str, str]:
    """Start the OAuth authorization flow for an external MCP source.

    Discovers OAuth metadata, registers a client if needed, generates PKCE,
    and returns the authorization URL for the browser popup.

    Args:
        source_id: The ExternalMCPSource ID.
        mcp_url: The external MCP server URL.
        callback_url: The redirect URI for the OAuth callback.
        existing_client_id: Pre-configured client ID (skips DCR).

    Returns:
        Dict with 'auth_url' and 'issuer'.
    """
    _cleanup_expired_flows()

    # Discover OAuth endpoints
    metadata = await discover_oauth_metadata(mcp_url)

    # Register client or use existing
    client_id = existing_client_id
    client_secret = None

    if not client_id:
        if metadata.registration_endpoint:
            client_id, client_secret = await register_client(
                metadata.registration_endpoint,
                callback_url,
            )
        else:
            raise OAuthError(
                "This server does not support Dynamic Client Registration and no "
                "client_id is configured. Please set a client_id on the external source."
            )

    # Generate PKCE
    code_verifier, code_challenge = _generate_pkce()

    # Generate state parameter
    state = secrets.token_urlsafe(32)

    # Store pending flow
    _pending_flows[state] = OAuthFlowState(
        source_id=source_id,
        code_verifier=code_verifier,
        redirect_uri=callback_url,
        token_endpoint=metadata.token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        created_at=time.time(),
    )

    # Build authorization URL
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback_url,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    # Add resource indicator if available (RFC 8707)
    if metadata.resource:
        params["resource"] = metadata.resource

    # Add scopes if available
    if metadata.scopes_supported:
        params["scope"] = " ".join(metadata.scopes_supported)

    auth_url = f"{metadata.authorization_endpoint}?{urlencode(params)}"

    return {
        "auth_url": auth_url,
        "issuer": metadata.issuer or "",
    }


async def exchange_code(state: str, code: str) -> tuple[UUID, OAuthTokens]:
    """Exchange an authorization code for tokens.

    Args:
        state: The state parameter from the callback.
        code: The authorization code from the callback.

    Returns:
        Tuple of (source_id, tokens).

    Raises:
        OAuthTokenError: If the exchange fails or state is invalid.
    """
    _cleanup_expired_flows()

    flow = _pending_flows.pop(state, None)
    if not flow:
        raise OAuthTokenError("Invalid or expired OAuth state parameter.")

    async with _get_http_client() as client:
        token_data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": flow.redirect_uri,
            "client_id": flow.client_id,
            "code_verifier": flow.code_verifier,
        }

        headers: dict[str, str] = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Use client_secret if we have one
        if flow.client_secret:
            token_data["client_secret"] = flow.client_secret

        try:
            response = await client.post(
                flow.token_endpoint,
                data=token_data,
                headers=headers,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            raise OAuthTokenError(
                f"Token exchange failed: HTTP {e.response.status_code}: {body}"
            ) from e
        except (httpx.HTTPError, ValueError) as e:
            raise OAuthTokenError(f"Token exchange failed: {e}") from e

    access_token = data.get("access_token")
    if not access_token:
        raise OAuthTokenError("Token response missing access_token")

    # Calculate expiry
    expires_at = None
    if "expires_in" in data:
        try:
            expires_at = datetime.now(UTC).timestamp() + int(data["expires_in"])
            expires_at_str = datetime.fromtimestamp(expires_at, tz=UTC).isoformat()
        except (ValueError, TypeError):
            expires_at_str = None
    else:
        expires_at_str = None

    tokens = OAuthTokens(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        token_endpoint=flow.token_endpoint,
        expires_at=expires_at_str,
        scope=data.get("scope"),
    )

    return flow.source_id, tokens


async def refresh_access_token(tokens_json: dict[str, Any]) -> OAuthTokens | None:
    """Refresh an expired access token using the refresh token.

    Args:
        tokens_json: Decrypted token data dict.

    Returns:
        New OAuthTokens if refresh succeeded, None if no refresh_token available.
    """
    refresh_token = tokens_json.get("refresh_token")
    token_endpoint = tokens_json.get("token_endpoint")
    client_id = tokens_json.get("client_id", "")

    if not refresh_token or not token_endpoint:
        return None

    async with _get_http_client() as client:
        try:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"Token refresh failed: {e}")
            return None

    access_token = data.get("access_token")
    if not access_token:
        return None

    expires_at_str = None
    if "expires_in" in data:
        try:
            ts = datetime.now(UTC).timestamp() + int(data["expires_in"])
            expires_at_str = datetime.fromtimestamp(ts, tz=UTC).isoformat()
        except (ValueError, TypeError):
            pass

    return OAuthTokens(
        access_token=access_token,
        refresh_token=data.get("refresh_token", refresh_token),
        token_endpoint=token_endpoint,
        expires_at=expires_at_str,
        scope=data.get("scope", tokens_json.get("scope")),
    )


def encrypt_tokens(tokens: OAuthTokens, client_id: str | None = None) -> str:
    """Encrypt OAuth tokens for database storage.

    Returns:
        Base64-encoded AES-256-GCM encrypted JSON string.
    """
    data = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_endpoint": tokens.token_endpoint,
        "expires_at": tokens.expires_at,
        "scope": tokens.scope,
    }
    if client_id:
        data["client_id"] = client_id
    return encrypt_to_base64(json.dumps(data), aad="oauth_tokens")


def decrypt_tokens(encrypted: str) -> dict[str, Any]:
    """Decrypt OAuth tokens from database storage.

    Returns:
        Dict with token fields.
    """
    return json.loads(decrypt_from_base64(encrypted, aad="oauth_tokens"))


def is_token_expired(tokens_json: dict[str, Any]) -> bool:
    """Check if the access token has expired (with 60s buffer)."""
    expires_at = tokens_json.get("expires_at")
    if not expires_at:
        return False  # No expiry info, assume valid

    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now(UTC) >= expiry - timedelta(seconds=60)
    except (ValueError, TypeError):
        return False


async def get_oauth_auth_headers(
    oauth_tokens_encrypted: str,
    source_id: UUID,
    db_update_callback: Any | None = None,
) -> dict[str, str]:
    """Get Authorization headers for an OAuth-authenticated external source.

    Handles token refresh if the access token is expired.

    Args:
        oauth_tokens_encrypted: Encrypted token blob from database.
        source_id: Source ID (for logging).
        db_update_callback: Optional async callback(new_encrypted_tokens) to persist refreshed tokens.

    Returns:
        Dict with Authorization header.
    """
    tokens_json = decrypt_tokens(oauth_tokens_encrypted)

    if is_token_expired(tokens_json):
        logger.info(f"OAuth token expired for source {source_id}, attempting refresh")
        new_tokens = await refresh_access_token(tokens_json)
        if new_tokens:
            tokens_json["access_token"] = new_tokens.access_token
            if new_tokens.refresh_token:
                tokens_json["refresh_token"] = new_tokens.refresh_token
            if new_tokens.expires_at:
                tokens_json["expires_at"] = new_tokens.expires_at

            # Persist the refreshed tokens
            if db_update_callback:
                new_encrypted = encrypt_to_base64(json.dumps(tokens_json), aad="oauth_tokens")
                await db_update_callback(new_encrypted)
        else:
            logger.warning(
                f"Token refresh failed for source {source_id}, using potentially expired token"
            )

    return {"Authorization": f"Bearer {tokens_json['access_token']}"}
