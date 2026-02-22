"""Tests for authentication endpoints."""

import pytest


@pytest.mark.asyncio
async def test_auth_status_no_admin(async_client):
    """Test auth status when no admin user exists."""
    response = await async_client.get("/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["setup_required"] is True
    assert data["onboarding_completed"] is False


@pytest.mark.asyncio
async def test_auth_status_with_admin(async_client, admin_user):
    """Test auth status when admin user exists."""
    response = await async_client.get("/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["setup_required"] is False
    assert data["onboarding_completed"] is False


@pytest.mark.asyncio
async def test_auth_status_onboarding_completed(async_client, admin_user, admin_headers):
    """Test auth status reflects onboarding_completed after it's set."""
    # Complete onboarding
    response = await async_client.post("/api/settings/onboarding-complete", headers=admin_headers)
    assert response.status_code == 200

    # Check status reflects it
    response = await async_client.get("/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["onboarding_completed"] is True


@pytest.mark.asyncio
async def test_setup_creates_admin(async_client):
    """Test initial admin setup."""
    response = await async_client.post(
        "/auth/setup",
        json={
            "username": "newadmin",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "newadmin"
    assert "message" in data


@pytest.mark.asyncio
async def test_setup_fails_if_admin_exists(async_client, admin_user):
    """Test setup fails when admin already exists."""
    response = await async_client.post(
        "/auth/setup",
        json={
            "username": "anotheradmin",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_setup_validates_username(async_client):
    """Test setup validates username format."""
    # Too short
    response = await async_client.post(
        "/auth/setup",
        json={
            "username": "ab",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 422

    # Invalid characters
    response = await async_client.post(
        "/auth/setup",
        json={
            "username": "admin@user",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 422

    # Starts with number
    response = await async_client.post(
        "/auth/setup",
        json={
            "username": "123admin",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_setup_validates_password(async_client):
    """Test setup validates password length."""
    response = await async_client.post(
        "/auth/setup",
        json={
            "username": "validuser",
            "password": "short",  # Less than 12 chars
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(async_client, admin_user):
    """Test successful login."""
    from tests.conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME

    response = await async_client.post(
        "/auth/login",
        json={
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password(async_client, admin_user):
    """Test login with wrong password."""
    from tests.conftest import TEST_ADMIN_USERNAME

    response = await async_client.post(
        "/auth/login",
        json={
            "username": TEST_ADMIN_USERNAME,
            "password": "wrongpassword123",
        },
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_wrong_username(async_client, admin_user):
    """Test login with wrong username."""
    response = await async_client.post(
        "/auth/login",
        json={
            "username": "nonexistent",
            "password": "somepassword123",
        },
    )
    assert response.status_code == 401
    # Should not reveal whether user exists
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_tokens(async_client, admin_user, auth_tokens):
    """Test token refresh."""
    response = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": auth_tokens["refresh_token"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # New tokens should be different (rotation)
    assert data["refresh_token"] != auth_tokens["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_with_invalid_token(async_client, admin_user):
    """Test refresh with invalid token."""
    response = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": "invalid.token.here"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user(async_client, admin_user, admin_headers):
    """Test getting current user info."""
    response = await async_client.get("/auth/me", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == admin_user.username
    assert data["is_active"] is True
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_get_current_user_unauthorized(async_client):
    """Test getting current user without auth."""
    response = await async_client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_change_password(async_client, admin_user, admin_headers):
    """Test password change."""
    from tests.conftest import TEST_ADMIN_PASSWORD

    response = await async_client.post(
        "/auth/change-password",
        headers=admin_headers,
        json={
            "current_password": TEST_ADMIN_PASSWORD,
            "new_password": "newpassword12345",
        },
    )
    assert response.status_code == 200
    assert "success" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_change_password_wrong_current(async_client, admin_user, admin_headers):
    """Test password change with wrong current password."""
    response = await async_client.post(
        "/auth/change-password",
        headers=admin_headers,
        json={
            "current_password": "wrongpassword123",
            "new_password": "newpassword12345",
        },
    )
    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_change_password_invalidates_tokens(
    async_client, admin_user, admin_headers, db_session
):
    """Test that password change invalidates old tokens."""
    from tests.conftest import TEST_ADMIN_PASSWORD

    # Change password
    response = await async_client.post(
        "/auth/change-password",
        headers=admin_headers,
        json={
            "current_password": TEST_ADMIN_PASSWORD,
            "new_password": "newpassword12345",
        },
    )
    assert response.status_code == 200

    # Old token should no longer work
    response = await async_client.get("/auth/me", headers=admin_headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout(async_client, admin_user, admin_headers):
    """Test logout."""
    response = await async_client.post("/auth/logout", headers=admin_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logout_blacklists_token(async_client, admin_user, admin_headers, auth_tokens):
    """SEC-009: After logout, the same access token should be rejected."""
    # Verify token works before logout
    response = await async_client.get("/auth/me", headers=admin_headers)
    assert response.status_code == 200

    # Logout
    response = await async_client.post("/auth/logout", headers=admin_headers)
    assert response.status_code == 200

    # Same token should now be rejected
    response = await async_client.get("/auth/me", headers=admin_headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(async_client, admin_user):
    """Test that protected endpoints require authentication."""
    response = await async_client.get("/api/servers")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_auth(async_client, admin_user, admin_headers):
    """Test that protected endpoints work with valid auth."""
    response = await async_client.get("/api/servers", headers=admin_headers)
    assert response.status_code == 200
