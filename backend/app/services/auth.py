"""Authentication service for JWT-based authentication."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jwt.exceptions import PyJWTError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.models.admin_user import AdminUser

logger = logging.getLogger(__name__)

# Argon2 password hasher with recommended parameters
# Memory: 64 MiB, Time: 3 iterations, Parallelism: 4
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


class AuthError(Exception):
    """Base authentication error."""

    pass


class InvalidCredentialsError(AuthError):
    """Invalid username or password."""

    pass


class UserInactiveError(AuthError):
    """User account is deactivated."""

    pass


class TokenError(AuthError):
    """JWT token error."""

    pass


class TokenExpiredError(TokenError):
    """JWT token has expired."""

    pass


class InvalidTokenError(TokenError):
    """JWT token is invalid."""

    pass


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash using constant-time comparison."""
    try:
        ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(user_id: UUID, password_version: int) -> str:
    """Create a short-lived access token."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
        "pv": password_version,  # Password version for invalidation
    }
    token = jwt.encode(
        payload,
        settings.effective_jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    # PyJWT 2.x returns str; older type stubs may declare bytes
    return str(token)


def create_refresh_token(user_id: UUID, password_version: int) -> str:
    """Create a long-lived refresh token."""
    expire = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)
    # Add jti for token uniqueness (enables future revocation)
    jti = secrets.token_hex(16)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "pv": password_version,
        "jti": jti,
    }
    token = jwt.encode(
        payload,
        settings.effective_jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    # PyJWT 2.x returns str; older type stubs may declare bytes
    return str(token)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.effective_jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Token has expired") from e
    except PyJWTError as e:
        raise InvalidTokenError(f"Invalid token: {e}") from e


def validate_access_token(token: str) -> dict[str, Any]:
    """Validate an access token and return its payload."""
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise InvalidTokenError("Not an access token")
    return payload


def validate_refresh_token(token: str) -> dict[str, Any]:
    """Validate a refresh token and return its payload."""
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise InvalidTokenError("Not a refresh token")
    return payload


class AuthService:
    """Service for authentication operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def admin_exists(self) -> bool:
        """Check if any admin user exists."""
        result = await self.session.execute(select(func.count(AdminUser.id)))
        count = result.scalar()
        return (count or 0) > 0

    async def get_user_by_username(self, username: str) -> AdminUser | None:
        """Get user by username."""
        result = await self.session.execute(select(AdminUser).where(AdminUser.username == username))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> AdminUser | None:
        """Get user by ID."""
        result = await self.session.execute(select(AdminUser).where(AdminUser.id == user_id))
        return result.scalar_one_or_none()

    async def create_admin_user(self, username: str, password: str) -> AdminUser:
        """Create a new admin user."""
        # Check if admin already exists
        if await self.admin_exists():
            raise AuthError("Admin user already exists")

        user = AdminUser(
            username=username,
            password_hash=hash_password(password),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)

        logger.info(f"Created admin user: {username}")
        return user

    async def authenticate(self, username: str, password: str) -> AdminUser:
        """Authenticate a user and return the user object.

        Raises InvalidCredentialsError for both "user not found" and
        "wrong password" to prevent user enumeration.
        """
        user = await self.get_user_by_username(username)

        if user is None:
            # Perform a dummy hash to prevent timing attacks
            verify_password(password, hash_password("dummy"))
            raise InvalidCredentialsError("Invalid username or password")

        if not user.is_active:
            raise UserInactiveError("User account is deactivated")

        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid username or password")

        # Update last login time
        user.last_login_at = datetime.now(UTC)
        await self.session.commit()

        return user

    async def change_password(
        self, user: AdminUser, current_password: str, new_password: str
    ) -> None:
        """Change a user's password and invalidate all existing tokens."""
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Current password is incorrect")

        user.password_hash = hash_password(new_password)
        user.password_version += 1  # Invalidate all existing tokens
        await self.session.commit()

        logger.info(f"Password changed for user: {user.username}")

    async def validate_token_user(self, payload: dict[str, Any]) -> AdminUser:
        """Validate that a token's user exists and password version matches."""
        user_id = payload.get("sub")
        password_version = payload.get("pv")

        if not user_id:
            raise InvalidTokenError("Token missing user ID")

        user = await self.get_user_by_id(UUID(user_id))

        if user is None:
            raise InvalidTokenError("User not found")

        if not user.is_active:
            raise UserInactiveError("User account is deactivated")

        if user.password_version != password_version:
            raise InvalidTokenError("Token invalidated by password change")

        return user

    def create_tokens(self, user: AdminUser) -> dict[str, Any]:
        """Create access and refresh tokens for a user."""
        return {
            "access_token": create_access_token(user.id, user.password_version),
            "refresh_token": create_refresh_token(user.id, user.password_version),
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
        }
