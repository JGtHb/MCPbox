"""Tests for Cloudflare remote access wizard API."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from app.models.cloudflare_config import CloudflareConfig
from app.services.crypto import encrypt_to_base64

# --- Fixtures ---


@pytest.fixture
def cloudflare_config_factory(db_session):
    """Factory for creating test CloudflareConfig objects."""

    async def _create_config(
        api_token: str = "test-api-token-1234567890",
        account_id: str = "test-account-id",
        account_name: str = "Test Account",
        team_domain: str = "test.cloudflareaccess.com",
        status: str = "pending",
        completed_step: int = 0,
        **kwargs,
    ) -> CloudflareConfig:
        config = CloudflareConfig(
            encrypted_api_token=encrypt_to_base64(api_token, aad="cloudflare_api_token"),
            account_id=account_id,
            account_name=account_name,
            team_domain=team_domain,
            status=status,
            completed_step=completed_step,
            **kwargs,
        )
        db_session.add(config)
        await db_session.flush()
        await db_session.refresh(config)
        return config

    return _create_config


@pytest.fixture
def mock_cloudflare_api():
    """Mock Cloudflare API responses."""
    with patch("app.services.cloudflare.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_instance

        # Default successful responses - use Mock (not AsyncMock) for json()
        # since json() is a sync method that returns a value
        from unittest.mock import Mock

        default_response = Mock()
        default_response.json.return_value = {"success": True, "result": {}}
        mock_instance.request.return_value = default_response

        yield mock_instance


# --- Status Endpoint Tests ---


@pytest.mark.asyncio
async def test_get_wizard_status_no_config(async_client, admin_headers):
    """Test getting wizard status when no config exists."""
    response = await async_client.get("/api/cloudflare/status", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_started"
    assert data["completed_step"] == 0
    assert data["config_id"] is None


# --- Start with API Token Tests ---


@pytest.mark.asyncio
async def test_start_with_api_token_success(async_client, admin_headers, mock_cloudflare_api):
    """Test starting wizard with API token."""
    # API token must be at least 40 characters
    valid_token = "cf_" + "a" * 40

    def mock_request(method, url, **kwargs):
        response = Mock()
        if "/user/tokens/verify" in url:
            response.json.return_value = {
                "success": True,
                "result": {"status": "active"},
            }
        elif "/accounts" in url and "/access" not in url and "/zones" not in url:
            response.json.return_value = {
                "success": True,
                "result": [{"id": "account123", "name": "Test Account"}],
            }
        elif "/zones" in url:
            response.json.return_value = {
                "success": True,
                "result": [{"id": "zone123", "name": "example.com"}],
            }
        elif "/access/organizations" in url:
            response.json.return_value = {
                "success": True,
                "result": {"auth_domain": "test.cloudflareaccess.com"},
            }
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/start",
        json={"api_token": valid_token},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["config_id"] is not None
    assert data["account_id"] == "account123"
    assert data["account_name"] == "Test Account"
    assert data["team_domain"] == "test.cloudflareaccess.com"
    assert len(data["zones"]) == 1
    assert data["zones"][0]["name"] == "example.com"


@pytest.mark.asyncio
async def test_start_with_api_token_invalid(async_client, admin_headers, mock_cloudflare_api):
    """Test starting wizard with invalid API token."""
    # API token must be at least 40 characters
    invalid_token = "cf_" + "b" * 40

    def mock_request(method, url, **kwargs):
        response = Mock()
        response.json.return_value = {
            "success": False,
            "errors": [{"message": "Invalid token"}],
        }
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/start",
        json={"api_token": invalid_token},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Invalid" in data["error"]


@pytest.mark.asyncio
async def test_start_with_api_token_too_short(async_client, admin_headers):
    """Test starting wizard with API token that's too short."""
    response = await async_client.post(
        "/api/cloudflare/start",
        json={"api_token": "short"},
        headers=admin_headers,
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_get_wizard_status_with_config(
    async_client, admin_headers, cloudflare_config_factory
):
    """Test getting wizard status with existing config."""
    config = await cloudflare_config_factory(
        completed_step=3,
        tunnel_id="test-tunnel-id",
        tunnel_name="test-tunnel",
    )

    response = await async_client.get("/api/cloudflare/status", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["completed_step"] == 3
    assert data["config_id"] == str(config.id)
    assert data["tunnel_id"] == "test-tunnel-id"
    assert data["tunnel_name"] == "test-tunnel"


# --- Create Tunnel Tests ---


@pytest.mark.asyncio
async def test_create_tunnel_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful tunnel creation."""
    config = await cloudflare_config_factory()

    def mock_request(method, url, **kwargs):
        response = Mock()
        response.content = b'{"success": true}'
        response.is_success = True
        if "cfd_tunnel" in url and "/token" in url:
            response.json.return_value = {
                "success": True,
                "result": "tunnel-token-abc123",
            }
        elif "cfd_tunnel" in url and method == "POST":
            response.json.return_value = {
                "success": True,
                "result": {"id": "tunnel123", "name": "mcpbox-tunnel"},
            }
        elif "cfd_tunnel" in url and method == "GET":
            # List tunnels — result is a list, not dict
            response.json.return_value = {
                "success": True,
                "result": [],
            }
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/tunnel",
        json={"config_id": str(config.id), "name": "mcpbox-tunnel"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["tunnel_id"] == "tunnel123"
    assert data["tunnel_name"] == "mcpbox-tunnel"
    # tunnel_token is stored in DB and not returned in response (security: prevent token leakage)
    assert "tunnel_token" not in data


@pytest.mark.asyncio
async def test_create_tunnel_config_not_found(async_client, admin_headers):
    """Test tunnel creation with non-existent config."""
    response = await async_client.post(
        "/api/cloudflare/tunnel",
        json={"config_id": str(uuid4()), "name": "test-tunnel"},
        headers=admin_headers,
    )
    assert response.status_code == 400


# --- Create VPC Service Tests ---


@pytest.mark.asyncio
async def test_create_vpc_service_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful VPC service creation."""
    config = await cloudflare_config_factory(tunnel_id="tunnel123", completed_step=2)

    def mock_request(method, url, **kwargs):
        response = Mock()
        response.content = b'{"success": true}'
        response.is_success = True
        if "directory/services" in url and method == "POST":
            response.json.return_value = {
                "success": True,
                "result": {"service_id": "vpc123"},
            }
        elif "directory/services" in url and method == "GET":
            response.json.return_value = {
                "success": True,
                "result": [],
            }
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/vpc-service",
        json={"config_id": str(config.id), "name": "mcpbox-service"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["vpc_service_id"] == "vpc123"


@pytest.mark.asyncio
async def test_create_vpc_service_no_tunnel(async_client, admin_headers, cloudflare_config_factory):
    """Test VPC service creation without tunnel."""
    config = await cloudflare_config_factory(completed_step=1)  # No tunnel yet

    response = await async_client.post(
        "/api/cloudflare/vpc-service",
        json={"config_id": str(config.id), "name": "test-service"},
        headers=admin_headers,
    )
    assert response.status_code == 400


# --- Deploy Worker Tests ---


@pytest.mark.asyncio
async def test_deploy_worker_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful worker deployment."""
    config = await cloudflare_config_factory(
        tunnel_id="tunnel123",
        vpc_service_id="vpc123",
        completed_step=3,
    )

    # Mock CF API for subdomain lookup
    def mock_request(method, url, **kwargs):
        response = Mock()
        if "workers/subdomain" in url:
            response.json.return_value = {
                "success": True,
                "result": {"subdomain": "test"},
            }
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    # Mock subprocess for wrangler CLI (KV create, npm install, deploy, secret put)
    def mock_subprocess_run(*args, **kwargs):
        result = Mock()
        result.returncode = 0
        result.stderr = ""
        # wrangler kv namespace create outputs the namespace ID
        cmd = args[0] if args else kwargs.get("args", [])
        if "kv" in cmd and "create" in cmd:
            result.stdout = 'id = "kv-namespace-123"'
        else:
            result.stdout = "Deployed successfully"
        return result

    # Mock filesystem ops — the service checks /app/worker/src and
    # /app/worker/package.json (Docker-only paths). We only intercept calls
    # touching Docker paths; everything else (tmpdir) uses the real filesystem.
    _real_isdir = os.path.isdir
    _real_listdir = os.listdir
    _real_exists = os.path.exists
    _real_open = open

    def mock_isdir(path):
        if "/app/worker/src" in str(path):
            return True
        return _real_isdir(path)

    def mock_listdir(path):
        if "/app/worker/src" in str(path):
            return ["index.ts", "utils.ts"]
        return _real_listdir(path)

    def mock_exists(path):
        if "/app/worker/" in str(path):
            return True
        return _real_exists(path)

    def mock_open_fn(path, *args, **kwargs):
        if "/app/worker/" in str(path):
            from io import StringIO

            if "package.json" in str(path):
                return StringIO('{"name":"mcpbox-proxy","dependencies":{}}')
            return StringIO("// mock ts source")
        return _real_open(path, *args, **kwargs)

    with (
        patch("app.services.cloudflare.subprocess.run", side_effect=mock_subprocess_run),
        patch("os.path.isdir", side_effect=mock_isdir),
        patch("os.path.exists", side_effect=mock_exists),
        patch("os.listdir", side_effect=mock_listdir),
        patch("builtins.open", side_effect=mock_open_fn),
    ):
        response = await async_client.post(
            "/api/cloudflare/worker",
            json={"config_id": str(config.id), "name": "mcpbox-proxy"},
            headers=admin_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["worker_name"] == "mcpbox-proxy"
    assert "workers.dev" in data["worker_url"]


# --- Configure JWT Tests ---


@pytest.mark.asyncio
async def test_configure_jwt_success(async_client, admin_headers, cloudflare_config_factory):
    """Test successful JWT configuration."""
    config = await cloudflare_config_factory(
        worker_name="mcpbox-proxy",
        worker_url="https://mcpbox-proxy.test.workers.dev",
        team_domain="myteam.cloudflareaccess.com",
        completed_step=4,
    )

    # Mock subprocess for wrangler secret commands
    def mock_subprocess_run(*args, **kwargs):
        result = Mock()
        result.returncode = 0
        result.stdout = "Secret set successfully"
        result.stderr = ""
        return result

    # Build mock responses for _cf_request calls.
    # _cf_request uses `response.content`, `response.is_success`, and `response.json()`
    # — all sync attributes/methods. Must use Mock (not AsyncMock) for responses.
    def mock_request(method, url, **kwargs):
        response = Mock()
        response.is_success = True
        if "/access/apps" in url and method == "POST":
            response.content = b'{"success": true}'
            response.json.return_value = {
                "success": True,
                "result": {
                    "id": "saas-app-id-123",
                    "saas_app": {
                        "client_id": "oidc-client-id",
                        "client_secret": "oidc-client-secret",
                    },
                },
            }
        elif "/access/apps" in url and "/policies" in url:
            response.content = b'{"success": true}'
            response.json.return_value = {"success": True, "result": {"id": "policy-123"}}
        else:
            response.content = b'{"success": true}'
            response.json.return_value = {"success": True, "result": {}}
        return response

    with (
        patch("app.services.cloudflare.subprocess.run", side_effect=mock_subprocess_run),
        patch("app.services.cloudflare.httpx.AsyncClient") as mock_client,
    ):
        mock_instance = Mock()
        mock_instance.request = AsyncMock(side_effect=mock_request)
        # Mock post for the worker URL test (expects a network error)
        mock_instance.post = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        response = await async_client.post(
            "/api/cloudflare/worker-jwt-config",
            json={"config_id": str(config.id)},
            headers=admin_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["team_domain"] == "myteam.cloudflareaccess.com"


@pytest.mark.asyncio
async def test_configure_jwt_no_team_domain(async_client, admin_headers, cloudflare_config_factory):
    """Test JWT configuration without team domain."""
    config = await cloudflare_config_factory(
        team_domain=None,
        completed_step=4,
    )

    response = await async_client.post(
        "/api/cloudflare/worker-jwt-config",
        json={"config_id": str(config.id)},
        headers=admin_headers,
    )
    assert response.status_code == 400


# --- Teardown Tests ---


@pytest.mark.asyncio
async def test_teardown_success(
    async_client, admin_headers, db_session, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful teardown."""
    config = await cloudflare_config_factory(
        tunnel_id="tunnel123",
        vpc_service_id="vpc123",
        worker_name="mcpbox-proxy",
        completed_step=5,
        status="active",
    )

    teardown_response = Mock()
    teardown_response.json.return_value = {"success": True, "result": {}}
    mock_cloudflare_api.request.return_value = teardown_response

    response = await async_client.delete(
        f"/api/cloudflare/teardown/{config.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "Worker" in str(data["deleted_resources"])


@pytest.mark.asyncio
async def test_teardown_config_not_found(async_client, admin_headers):
    """Test teardown with non-existent config."""
    response = await async_client.delete(
        f"/api/cloudflare/teardown/{uuid4()}",
        headers=admin_headers,
    )
    assert response.status_code == 400


# --- Get Tunnel Token Tests ---


@pytest.mark.asyncio
async def test_get_tunnel_token_success(async_client, admin_headers, cloudflare_config_factory):
    """Test getting tunnel token."""
    config = await cloudflare_config_factory(
        encrypted_tunnel_token=encrypt_to_base64("my-tunnel-token-123", aad="tunnel_token"),
    )

    response = await async_client.get(
        f"/api/cloudflare/tunnel-token/{config.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tunnel_token"] == "my-tunnel-token-123"


@pytest.mark.asyncio
async def test_get_tunnel_token_not_found(async_client, admin_headers, cloudflare_config_factory):
    """Test getting tunnel token when none exists."""
    config = await cloudflare_config_factory()  # No tunnel token

    response = await async_client.get(
        f"/api/cloudflare/tunnel-token/{config.id}",
        headers=admin_headers,
    )
    assert response.status_code == 404


# --- Access Policy Persistence Tests ---


@pytest.mark.asyncio
async def test_wizard_status_includes_access_policy(
    async_client, admin_headers, cloudflare_config_factory
):
    """Test that wizard status response includes access policy fields."""
    await cloudflare_config_factory(
        access_policy_type="emails",
        access_policy_emails=json.dumps(["user@example.com"]),
        access_policy_email_domain=None,
    )

    response = await async_client.get("/api/cloudflare/status", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["access_policy_type"] == "emails"
    assert data["access_policy_emails"] == ["user@example.com"]
    assert data["access_policy_email_domain"] is None


@pytest.mark.asyncio
async def test_wizard_status_access_policy_domain(
    async_client, admin_headers, cloudflare_config_factory
):
    """Test wizard status with email domain access policy."""
    await cloudflare_config_factory(
        access_policy_type="email_domain",
        access_policy_email_domain="company.com",
    )

    response = await async_client.get("/api/cloudflare/status", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["access_policy_type"] == "email_domain"
    assert data["access_policy_emails"] is None
    assert data["access_policy_email_domain"] == "company.com"


# --- Update Access Policy Tests ---


@pytest.mark.asyncio
async def test_update_access_policy_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api, db_session
):
    """Test updating access policy syncs to Cloudflare Access and database."""
    config = await cloudflare_config_factory(
        status="active",
        access_app_id="app-123",
        worker_name="mcpbox-proxy",
        team_domain="test.cloudflareaccess.com",
        completed_step=5,
    )

    policies_deleted = []
    new_policy_body = None

    def mock_request(method, url, **kwargs):
        nonlocal new_policy_body
        response = Mock()
        if "policies" in url and method == "GET":
            response.json.return_value = {
                "success": True,
                "result": [{"id": "old-policy-1"}, {"id": "old-policy-2"}],
            }
        elif "policies" in url and method == "DELETE":
            policies_deleted.append(url)
            response.json.return_value = {"success": True, "result": {}}
        elif "policies" in url and method == "POST":
            new_policy_body = kwargs.get("json", {})
            response.json.return_value = {"success": True, "result": {}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    # Mock wrangler for Worker secret sync
    def mock_subprocess_run(*args, **kwargs):
        result = Mock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = "Success"
        return result

    with patch("app.services.cloudflare.subprocess.run", side_effect=mock_subprocess_run):
        response = await async_client.put(
            "/api/cloudflare/access-policy",
            json={
                "config_id": str(config.id),
                "access_policy": {
                    "policy_type": "emails",
                    "emails": ["new-user@example.com"],
                },
            },
            headers=admin_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["access_policy_synced"] is True
    assert data["worker_synced"] is True

    # Old policies should have been deleted
    assert len(policies_deleted) == 2

    # New policy should have been created with correct emails
    assert new_policy_body is not None
    assert new_policy_body["include"] == [{"email": {"email": "new-user@example.com"}}]

    # Database should be updated
    await db_session.refresh(config)
    assert config.access_policy_type == "emails"
    assert json.loads(config.access_policy_emails) == ["new-user@example.com"]


@pytest.mark.asyncio
async def test_update_access_policy_config_not_found(async_client, admin_headers):
    """Test updating access policy with non-existent config."""
    response = await async_client.put(
        "/api/cloudflare/access-policy",
        json={
            "config_id": str(uuid4()),
            "access_policy": {
                "policy_type": "everyone",
            },
        },
        headers=admin_headers,
    )
    assert response.status_code == 400
