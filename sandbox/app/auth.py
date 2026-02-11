"""Sandbox authentication - API key verification for internal communication.

SECURITY: SANDBOX_API_KEY must always be set. There is no bypass mechanism.
"""

import hmac
import logging
import os
from typing import Optional

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# API key for sandbox authentication (set by backend when communicating)
SANDBOX_API_KEY = os.environ.get("SANDBOX_API_KEY", "")


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> None:
    """Verify the API key for sandbox access.

    The sandbox only accepts requests from the backend service,
    which must provide the correct API key.

    SECURITY: SANDBOX_API_KEY must always be configured. There is no bypass.

    Raises:
        HTTPException: If the API key is missing or invalid.
    """
    if not SANDBOX_API_KEY:
        logger.error(
            "SANDBOX_API_KEY not configured. This is required for sandbox authentication. "
            'Generate a secure key with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox not properly configured - missing SANDBOX_API_KEY",
        )

    # Reject weak API keys - minimum 32 characters required for security
    if len(SANDBOX_API_KEY) < 32:
        logger.error(
            "SANDBOX_API_KEY is too short (minimum 32 characters required). "
            'Generate a secure key with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox not properly configured - SANDBOX_API_KEY must be at least 32 characters",
        )

    if not x_api_key:
        logger.warning("Rejected request: missing X-API-Key header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(x_api_key, SANDBOX_API_KEY):
        logger.warning("Rejected request: invalid API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
