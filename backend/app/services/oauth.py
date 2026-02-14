"""OAuth 2.0 service for handling authorization code flow and token management."""

import base64
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Credential
from app.services.crypto import decrypt, decrypt_from_base64, encrypt, encrypt_to_base64
from app.services.url_validator import SSRFError, validate_url_with_pinning

logger = logging.getLogger(__name__)


class OAuthError(Exception):
    """Base exception for OAuth errors."""

    def __init__(self, message: str, error_code: str = "oauth_error"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class OAuthStateError(OAuthError):
    """Invalid or expired state parameter."""

    def __init__(self, message: str = "Invalid or expired OAuth state"):
        super().__init__(message, "invalid_state")


class OAuthTokenError(OAuthError):
    """Token exchange or refresh failed."""

    def __init__(self, message: str, provider_error: str | None = None):
        self.provider_error = provider_error
        super().__init__(message, "token_error")


# Common OAuth provider presets
OAUTH_PROVIDERS = {
    "google": {
        "id": "google",
        "name": "Google",
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["openid", "email", "profile"],
        "docs_url": "https://developers.google.com/identity/protocols/oauth2",
    },
    "github": {
        "id": "github",
        "name": "GitHub",
        "authorization_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["read:user", "user:email", "repo"],
        "docs_url": "https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps",
    },
    "slack": {
        "id": "slack",
        "name": "Slack",
        "authorization_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": ["channels:read", "chat:write", "users:read"],
        "docs_url": "https://api.slack.com/authentication/oauth-v2",
    },
    "microsoft": {
        "id": "microsoft",
        "name": "Microsoft",
        "authorization_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["openid", "profile", "email", "User.Read"],
        "docs_url": "https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-auth-code-flow",
    },
    "discord": {
        "id": "discord",
        "name": "Discord",
        "authorization_url": "https://discord.com/api/oauth2/authorize",
        "token_url": "https://discord.com/api/oauth2/token",
        "scopes": ["identify", "email", "guilds"],
        "docs_url": "https://discord.com/developers/docs/topics/oauth2",
    },
    "spotify": {
        "id": "spotify",
        "name": "Spotify",
        "authorization_url": "https://accounts.spotify.com/authorize",
        "token_url": "https://accounts.spotify.com/api/token",
        "scopes": ["user-read-private", "user-read-email", "playlist-read-private"],
        "docs_url": "https://developer.spotify.com/documentation/web-api/tutorials/code-flow",
    },
    "dropbox": {
        "id": "dropbox",
        "name": "Dropbox",
        "authorization_url": "https://www.dropbox.com/oauth2/authorize",
        "token_url": "https://api.dropbox.com/oauth2/token",
        "scopes": [],  # Dropbox uses access levels, not scopes
        "docs_url": "https://www.dropbox.com/developers/documentation/http/documentation#oauth2-authorize",
    },
    "notion": {
        "id": "notion",
        "name": "Notion",
        "authorization_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": [],  # Notion doesn't use scopes
        "docs_url": "https://developers.notion.com/docs/authorization",
    },
}


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate a random 43-128 character code verifier (using 64)
    code_verifier = secrets.token_urlsafe(48)

    # Create SHA256 hash and base64url encode
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    return code_verifier, code_challenge


# OAuth state expires after 10 minutes
OAUTH_STATE_EXPIRY_SECONDS = 600


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection.

    State format: {timestamp}:{random_token}
    The timestamp is used for expiration validation.
    """
    timestamp = int(datetime.now(UTC).timestamp())
    random_part = secrets.token_urlsafe(32)
    return f"{timestamp}:{random_part}"


def validate_state_not_expired(state: str) -> bool:
    """Check if OAuth state has expired.

    Args:
        state: The state parameter to validate

    Returns:
        True if state is valid (not expired), False otherwise
    """
    try:
        timestamp_str, _ = state.split(":", 1)
        timestamp = int(timestamp_str)
        now = int(datetime.now(UTC).timestamp())
        return (now - timestamp) < OAUTH_STATE_EXPIRY_SECONDS
    except (ValueError, AttributeError):
        # Invalid state format, consider it expired
        return False


class OAuthService:
    """Service for OAuth 2.0 authorization code flow."""

    def __init__(self, db: AsyncSession, redirect_uri: str):
        """Initialize OAuth service.

        Args:
            db: Database session
            redirect_uri: The callback URI for OAuth flow
        """
        self.db = db
        self.redirect_uri = redirect_uri

    async def start_authorization(
        self,
        credential: Credential,
        extra_params: dict | None = None,
    ) -> tuple[str, str]:
        """Start OAuth authorization flow.

        Generates authorization URL with state and PKCE, stores state in credential.

        Args:
            credential: The credential to authorize
            extra_params: Additional query parameters for the authorization URL

        Returns:
            Tuple of (authorization_url, state)

        Raises:
            OAuthError: If credential is not configured for authorization_code flow
        """
        if credential.auth_type != "oauth2":
            raise OAuthError("Credential is not OAuth2 type")

        if credential.oauth_grant_type != "authorization_code":
            raise OAuthError("Credential is not configured for authorization_code flow")

        if not credential.oauth_authorization_url:
            raise OAuthError("Credential missing authorization URL")

        if not credential.oauth_client_id:
            raise OAuthError("Credential missing client ID")

        # Generate state and PKCE
        state = generate_state()
        code_verifier, code_challenge = generate_pkce_pair()

        # Store state and code_verifier in credential
        # Use commit() to ensure persistence - state must survive process restarts
        # Encrypt code_verifier since it's sensitive (PKCE secret)
        credential.oauth_state = state
        credential.oauth_code_verifier = encrypt_to_base64(code_verifier)
        await self.db.commit()

        # Build authorization URL
        params = {
            "client_id": credential.oauth_client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        # Add scopes if configured
        if credential.oauth_scopes:
            params["scope"] = " ".join(credential.oauth_scopes)

        # Add any extra parameters
        if extra_params:
            params.update(extra_params)

        # Build full URL
        auth_url = f"{credential.oauth_authorization_url}?{urlencode(params)}"

        return auth_url, state

    async def handle_callback(
        self,
        credential: Credential,
        code: str,
        state: str,
    ) -> dict:
        """Handle OAuth callback and exchange code for tokens.

        Args:
            credential: The credential being authorized
            code: Authorization code from provider
            state: State parameter for validation

        Returns:
            Dict with token information

        Raises:
            OAuthStateError: If state doesn't match
            OAuthTokenError: If token exchange fails
        """
        # Validate state
        if not credential.oauth_state or credential.oauth_state != state:
            raise OAuthStateError()

        # Check state expiration (10 minute limit)
        if not validate_state_not_expired(state):
            # Clear expired state
            credential.oauth_state = None
            credential.oauth_code_verifier = None
            await self.db.commit()
            raise OAuthStateError("OAuth state has expired. Please restart the authorization flow.")

        if not credential.oauth_token_url:
            raise OAuthError("Credential missing token URL")

        if not credential.oauth_client_id:
            raise OAuthError("Credential missing client ID")

        # Build token request
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": credential.oauth_client_id,
        }

        # Add PKCE verifier if available (decrypt since it's stored encrypted)
        if credential.oauth_code_verifier:
            token_data["code_verifier"] = decrypt_from_base64(credential.oauth_code_verifier)

        # Add client secret if available (some providers require it even with PKCE)
        if credential.oauth_client_secret:
            client_secret = decrypt(credential.oauth_client_secret)
            token_data["client_secret"] = client_secret

        # Validate token URL for SSRF before making request
        try:
            validated_url = validate_url_with_pinning(credential.oauth_token_url)
        except SSRFError as e:
            logger.warning(f"SSRF blocked for token URL: {credential.oauth_token_url}")
            raise OAuthTokenError(f"Token URL blocked for security: {e}") from e

        # Exchange code for tokens using validated/pinned URL
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    validated_url.get_pinned_url(),
                    data=token_data,
                    headers={
                        "Accept": "application/json",
                        "Host": validated_url.hostname,
                    },
                    timeout=30.0,
                )
            except httpx.RequestError as e:
                raise OAuthTokenError(f"Failed to contact token endpoint: {e}") from e

            # Parse response
            if response.status_code != 200:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get(
                        "error_description", error_json.get("error", error_detail)
                    )
                except (ValueError, KeyError):
                    # JSON parsing failed, use raw text as error detail
                    pass
                raise OAuthTokenError(
                    f"Token exchange failed: {response.status_code}",
                    provider_error=error_detail,
                )

            try:
                token_response = response.json()
            except ValueError as e:
                raise OAuthTokenError(f"Invalid JSON response from token endpoint: {e}") from e

        # Extract tokens
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in")

        if not access_token:
            raise OAuthTokenError("No access token in response")

        # Calculate expiration time
        expires_at = None
        if expires_in:
            try:
                expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
            except (ValueError, TypeError):
                pass

        # Store tokens in credential
        credential.encrypted_access_token = encrypt(access_token)
        if refresh_token:
            credential.encrypted_refresh_token = encrypt(refresh_token)
        credential.access_token_expires_at = expires_at

        # Clear temporary state and code verifier
        credential.oauth_state = None
        credential.oauth_code_verifier = None

        # Use commit() to ensure tokens are persisted immediately
        await self.db.commit()

        return {
            "access_token_stored": True,
            "refresh_token_stored": bool(refresh_token),
            "expires_at": expires_at,
        }

    async def refresh_token(self, credential: Credential) -> dict:
        """Refresh an expired access token.

        Args:
            credential: The credential to refresh

        Returns:
            Dict with new token information

        Raises:
            OAuthError: If credential doesn't have refresh token
            OAuthTokenError: If refresh fails
        """
        if not credential.encrypted_refresh_token:
            raise OAuthError("No refresh token available")

        if not credential.oauth_token_url:
            raise OAuthError("Credential missing token URL")

        if not credential.oauth_client_id:
            raise OAuthError("Credential missing client ID")

        refresh_token = decrypt(credential.encrypted_refresh_token)

        # Build refresh request
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": credential.oauth_client_id,
        }

        # Add client secret if available
        if credential.oauth_client_secret:
            client_secret = decrypt(credential.oauth_client_secret)
            token_data["client_secret"] = client_secret

        # Validate token URL for SSRF before making request
        try:
            validated_url = validate_url_with_pinning(credential.oauth_token_url)
        except SSRFError as e:
            logger.warning(f"SSRF blocked for token URL: {credential.oauth_token_url}")
            raise OAuthTokenError(f"Token URL blocked for security: {e}") from e

        # Request new tokens using validated/pinned URL
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    validated_url.get_pinned_url(),
                    data=token_data,
                    headers={
                        "Accept": "application/json",
                        "Host": validated_url.hostname,
                    },
                    timeout=30.0,
                )
            except httpx.RequestError as e:
                raise OAuthTokenError(f"Failed to contact token endpoint: {e}") from e

            if response.status_code != 200:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get(
                        "error_description", error_json.get("error", error_detail)
                    )
                except (ValueError, KeyError):
                    # JSON parsing failed, use raw text as error detail
                    pass
                raise OAuthTokenError(
                    f"Token refresh failed: {response.status_code}",
                    provider_error=error_detail,
                )

            try:
                token_response = response.json()
            except ValueError as e:
                raise OAuthTokenError(f"Invalid JSON response from token endpoint: {e}") from e

        # Extract tokens
        access_token = token_response.get("access_token")
        new_refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in")

        if not access_token:
            raise OAuthTokenError("No access token in refresh response")

        # Calculate expiration time
        expires_at = None
        if expires_in:
            try:
                expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
            except (ValueError, TypeError):
                pass

        # Store new tokens
        credential.encrypted_access_token = encrypt(access_token)
        if new_refresh_token:
            # Some providers rotate refresh tokens
            credential.encrypted_refresh_token = encrypt(new_refresh_token)
        credential.access_token_expires_at = expires_at

        # Use commit() to ensure tokens are persisted immediately
        await self.db.commit()

        return {
            "access_token_refreshed": True,
            "refresh_token_rotated": bool(new_refresh_token),
            "expires_at": expires_at,
        }

    def is_token_expired(self, credential: Credential, buffer_seconds: int = 60) -> bool:
        """Check if credential's access token is expired or about to expire.

        Args:
            credential: The credential to check
            buffer_seconds: Consider token expired this many seconds before actual expiry

        Returns:
            True if token is expired or missing
        """
        if not credential.encrypted_access_token:
            return True

        if not credential.access_token_expires_at:
            # No expiration info, assume it's valid
            return False

        expiry_threshold = datetime.now(UTC) + timedelta(seconds=buffer_seconds)
        return credential.access_token_expires_at < expiry_threshold


def get_oauth_providers() -> list[dict]:
    """Get list of available OAuth provider presets."""
    return list(OAUTH_PROVIDERS.values())


def get_oauth_provider(provider_id: str) -> dict | None:
    """Get OAuth provider preset by ID."""
    return OAUTH_PROVIDERS.get(provider_id)
