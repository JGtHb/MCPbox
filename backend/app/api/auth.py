"""Authentication API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.auth import (
    AuthStatusResponse,
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    SetupRequest,
    SetupResponse,
    TokenResponse,
    UserResponse,
)
from app.services.auth import (
    AuthError,
    AuthService,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    UserInactiveError,
    validate_access_token,
    validate_refresh_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """Dependency to get auth service."""
    return AuthService(db)


async def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Dependency to get the current authenticated user from JWT token."""
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]  # Remove "Bearer " prefix

    try:
        payload = validate_access_token(token)
        user = await auth_service.validate_token_user(payload)
        return user
    except TokenExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except (InvalidTokenError, UserInactiveError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status(
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthStatusResponse:
    """Check authentication status.

    Returns whether setup is required (no admin user exists).
    This endpoint does not require authentication.
    """
    admin_exists = await auth_service.admin_exists()
    return AuthStatusResponse(setup_required=not admin_exists)


@router.post(
    "/setup",
    response_model=SetupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def setup_admin(
    request: SetupRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> SetupResponse:
    """Create the initial admin user.

    This endpoint only works when no admin user exists.
    Returns 409 Conflict if an admin already exists.
    """
    try:
        user = await auth_service.create_admin_user(
            username=request.username,
            password=request.password,
        )
        logger.info(f"Admin user created: {user.username}")
        return SetupResponse(
            message="Admin user created successfully",
            username=user.username,
        )
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Authenticate and get JWT tokens.

    Returns access and refresh tokens on successful authentication.
    """
    try:
        user = await auth_service.authenticate(
            username=request.username,
            password=request.password,
        )
        tokens = auth_service.create_tokens(user)
        logger.info(f"User logged in: {user.username}")
        return TokenResponse(**tokens)
    except InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        ) from e
    except UserInactiveError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated",
        ) from e


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    request: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Refresh access token using refresh token.

    Returns new access and refresh tokens (token rotation).
    """
    try:
        payload = validate_refresh_token(request.refresh_token)
        user = await auth_service.validate_token_user(payload)
        tokens = auth_service.create_tokens(user)
        return TokenResponse(**tokens)
    except TokenExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        ) from e
    except (InvalidTokenError, UserInactiveError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_user=Depends(get_current_user),
) -> MessageResponse:
    """Log out the current user.

    This is a client-side operation - the client should discard the tokens.
    The endpoint exists for API consistency and potential future token blacklisting.
    """
    logger.info(f"User logged out: {current_user.username}")
    return MessageResponse(message="Logged out successfully")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Change the current user's password.

    Invalidates all existing tokens by incrementing password_version.
    The user must re-login after changing password.
    """
    try:
        await auth_service.change_password(
            user=current_user,
            current_password=request.current_password,
            new_password=request.new_password,
        )
        logger.info(f"Password changed for user: {current_user.username}")
        return MessageResponse(message="Password changed successfully")
    except InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        ) from e


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user=Depends(get_current_user),
) -> UserResponse:
    """Get the current user's information."""
    return UserResponse.model_validate(current_user)
