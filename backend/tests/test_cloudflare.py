"""Tests for Cloudflare remote access wizard API."""

import json
from unittest.mock import AsyncMock, Mock, patch
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
            encrypted_api_token=encrypt_to_base64(api_token),
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
        if "cfd_tunnel" in url and "/token" in url:
            response.json.return_value = {
                "success": True,
                "result": "tunnel-token-abc123",
            }
        elif "cfd_tunnel" in url:
            response.json.return_value = {
                "success": True,
                "result": {"id": "tunnel123", "name": "mcpbox-tunnel"},
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
    assert data["tunnel_token"] == "tunnel-token-abc123"


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
        if "directory/services" in url:
            response.json.return_value = {
                "success": True,
                "result": {"service_id": "vpc123"},
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

    with patch("app.services.cloudflare.subprocess.run", side_effect=mock_subprocess_run):
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


# --- Create MCP Server Tests ---


@pytest.mark.asyncio
async def test_create_mcp_server_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful MCP server creation."""
    config = await cloudflare_config_factory(
        worker_url="https://mcpbox-proxy.test.workers.dev",
        completed_step=4,
    )

    def mock_request(method, url, **kwargs):
        response = Mock()
        if "mcp/servers" in url and method == "POST":
            if "/sync" in url:
                response.json.return_value = {
                    "success": True,
                    "result": {"tools": [{"name": "tool1"}, {"name": "tool2"}]},
                }
            else:
                response.json.return_value = {
                    "success": True,
                    "result": {"id": "mcpbox"},
                }
        elif "access/apps" in url and method == "POST" and "policies" not in url:
            # Creating MCP Access Application for the server
            response.json.return_value = {
                "success": True,
                "result": {"id": "mcp-app-123", "type": "mcp"},
            }
        elif "policies" in url and method == "POST":
            # Creating Access Policy for the MCP app
            response.json.return_value = {"success": True, "result": {}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/mcp-server",
        json={
            "config_id": str(config.id),
            "server_id": "mcpbox",
            "server_name": "MCPbox",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["mcp_server_id"] == "mcpbox"
    assert data["tools_synced"] == 2


@pytest.mark.asyncio
async def test_create_mcp_server_with_email_policy(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test MCP server creation with email access policy."""
    config = await cloudflare_config_factory(
        worker_url="https://mcpbox-proxy.test.workers.dev",
        completed_step=4,
    )

    policy_request_body = None

    def mock_request(method, url, **kwargs):
        nonlocal policy_request_body
        response = Mock()
        if "mcp/servers" in url and method == "POST":
            if "/sync" in url:
                response.json.return_value = {
                    "success": True,
                    "result": {"tools": []},
                }
            else:
                response.json.return_value = {
                    "success": True,
                    "result": {"id": "mcpbox"},
                }
        elif "access/apps" in url and method == "POST" and "policies" not in url:
            response.json.return_value = {
                "success": True,
                "result": {"id": "mcp-app-123", "type": "mcp"},
            }
        elif "policies" in url and method == "POST":
            policy_request_body = kwargs.get("json", {})
            response.json.return_value = {"success": True, "result": {}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/mcp-server",
        json={
            "config_id": str(config.id),
            "server_id": "mcpbox",
            "server_name": "MCPbox",
            "access_policy": {
                "policy_type": "emails",
                "emails": ["alice@example.com", "bob@example.com"],
                "email_domain": None,
            },
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify the policy was created with correct email include rules
    assert policy_request_body is not None
    assert policy_request_body["decision"] == "allow"
    include = policy_request_body["include"]
    assert len(include) == 2
    assert {"email": {"email": "alice@example.com"}} in include
    assert {"email": {"email": "bob@example.com"}} in include


@pytest.mark.asyncio
async def test_create_mcp_server_with_domain_policy(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test MCP server creation with email domain access policy."""
    config = await cloudflare_config_factory(
        worker_url="https://mcpbox-proxy.test.workers.dev",
        completed_step=4,
    )

    policy_request_body = None

    def mock_request(method, url, **kwargs):
        nonlocal policy_request_body
        response = Mock()
        if "mcp/servers" in url and method == "POST":
            if "/sync" in url:
                response.json.return_value = {
                    "success": True,
                    "result": {"tools": []},
                }
            else:
                response.json.return_value = {
                    "success": True,
                    "result": {"id": "mcpbox"},
                }
        elif "access/apps" in url and method == "POST" and "policies" not in url:
            response.json.return_value = {
                "success": True,
                "result": {"id": "mcp-app-123", "type": "mcp"},
            }
        elif "policies" in url and method == "POST":
            policy_request_body = kwargs.get("json", {})
            response.json.return_value = {"success": True, "result": {}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/mcp-server",
        json={
            "config_id": str(config.id),
            "server_id": "mcpbox",
            "server_name": "MCPbox",
            "access_policy": {
                "policy_type": "email_domain",
                "emails": [],
                "email_domain": "company.com",
            },
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify the policy was created with correct domain include rule
    assert policy_request_body is not None
    assert policy_request_body["decision"] == "allow"
    include = policy_request_body["include"]
    assert len(include) == 1
    assert include[0] == {"email_domain": {"domain": "company.com"}}
    assert "company.com" in policy_request_body["name"]


@pytest.mark.asyncio
async def test_create_mcp_server_no_policy_defaults_to_everyone(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test MCP server creation without access_policy defaults to 'everyone'."""
    config = await cloudflare_config_factory(
        worker_url="https://mcpbox-proxy.test.workers.dev",
        completed_step=4,
    )

    policy_request_body = None

    def mock_request(method, url, **kwargs):
        nonlocal policy_request_body
        response = Mock()
        if "mcp/servers" in url and method == "POST":
            if "/sync" in url:
                response.json.return_value = {
                    "success": True,
                    "result": {"tools": []},
                }
            else:
                response.json.return_value = {
                    "success": True,
                    "result": {"id": "mcpbox"},
                }
        elif "access/apps" in url and method == "POST" and "policies" not in url:
            response.json.return_value = {
                "success": True,
                "result": {"id": "mcp-app-123", "type": "mcp"},
            }
        elif "policies" in url and method == "POST":
            policy_request_body = kwargs.get("json", {})
            response.json.return_value = {"success": True, "result": {}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    # No access_policy in request - should default to 'everyone'
    response = await async_client.post(
        "/api/cloudflare/mcp-server",
        json={
            "config_id": str(config.id),
            "server_id": "mcpbox",
            "server_name": "MCPbox",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify the policy was created with 'everyone' include rule
    assert policy_request_body is not None
    assert policy_request_body["include"] == [{"everyone": {}}]
    assert policy_request_body["name"] == "Allow Authenticated Users"


# --- Create MCP Portal Tests ---


@pytest.mark.asyncio
async def test_create_mcp_portal_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful MCP portal creation with auto-created Access App detection."""
    config = await cloudflare_config_factory(
        mcp_server_id="mcpbox",
        completed_step=5,
    )

    def mock_request(method, url, **kwargs):
        response = Mock()
        if "mcp/portals" in url and method == "POST":
            response.json.return_value = {
                "success": True,
                "result": {"id": "mcpbox-portal", "hostname": "mcp.example.com"},
            }
        elif "access/apps" in url and method == "GET" and "policies" not in url:
            # Simulate finding an auto-created MCP Portal Access App
            response.json.return_value = {
                "success": True,
                "result": [
                    {
                        "id": "app-123",
                        "type": "mcp_portal",
                        "name": "MCPbox Portal",
                        "domain": "mcp.example.com",
                        "aud": "aud123xyz",
                    },
                ],
            }
        elif "/zones" in url and method == "GET" and "dns_records" not in url:
            # Zone lookup
            response.json.return_value = {
                "success": True,
                "result": [{"id": "zone-123", "name": "example.com"}],
            }
        elif "dns_records" in url and method == "GET":
            # Check for existing DNS records
            response.json.return_value = {"success": True, "result": []}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/mcp-portal",
        json={
            "config_id": str(config.id),
            "portal_id": "mcpbox-portal",
            "portal_name": "MCPbox Portal",
            "hostname": "mcp.example.com",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["mcp_portal_id"] == "mcpbox-portal"
    assert data["mcp_portal_hostname"] == "mcp.example.com"
    assert data["portal_url"] == "https://mcp.example.com"


@pytest.mark.asyncio
async def test_create_mcp_portal_creates_mcp_portal_access_app(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test MCP portal creation creates mcp_portal type Access App."""
    config = await cloudflare_config_factory(
        mcp_server_id="mcpbox",
        completed_step=5,
    )

    access_app_created = False

    def mock_request(method, url, **kwargs):
        nonlocal access_app_created
        response = Mock()
        if "mcp/portals" in url and method == "POST":
            response.json.return_value = {
                "success": True,
                "result": {"id": "mcpbox-portal", "hostname": "mcp.example.com"},
            }
        elif "access/apps" in url and method == "GET" and "policies" not in url:
            # No existing Access Apps
            response.json.return_value = {
                "success": True,
                "result": [],
            }
        elif "access/apps" in url and method == "POST" and "policies" not in url:
            # Creating new mcp_portal type Access App
            json_data = kwargs.get("json", {})
            assert json_data.get("type") == "mcp_portal"
            assert json_data.get("domain") == "mcp.example.com"
            assert json_data.get("cors_headers") == {
                "allow_all_headers": True,
                "allow_all_methods": True,
                "allow_all_origins": True,
            }
            access_app_created = True
            response.json.return_value = {
                "success": True,
                "result": {
                    "id": "new-app-123",
                    "type": "mcp_portal",
                    "aud": "new-aud-456",
                },
            }
        elif "policies" in url and method == "POST":
            # Creating Access Policy (app-specific)
            response.json.return_value = {"success": True, "result": {}}
        elif "/zones" in url and method == "GET" and "dns_records" not in url:
            # Zone lookup
            response.json.return_value = {
                "success": True,
                "result": [{"id": "zone-123", "name": "example.com"}],
            }
        elif "dns_records" in url and method == "GET":
            # Check for existing DNS records
            response.json.return_value = {"success": True, "result": []}
        elif "dns_records" in url and method == "POST":
            # Creating DNS record
            response.json.return_value = {"success": True, "result": {}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/mcp-portal",
        json={
            "config_id": str(config.id),
            "portal_id": "mcpbox-portal",
            "portal_name": "MCPbox Portal",
            "hostname": "mcp.example.com",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["mcp_portal_aud"] == "new-aud-456"
    assert access_app_created is True


@pytest.mark.asyncio
async def test_create_mcp_portal_with_auto_jwt(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test MCP portal creation with automatic JWT configuration."""
    config = await cloudflare_config_factory(
        mcp_server_id="mcpbox",
        worker_name="mcpbox-proxy",  # Required for auto-JWT
        team_domain="myteam.cloudflareaccess.com",  # Required for auto-JWT
        completed_step=5,
    )

    def mock_request(method, url, **kwargs):
        response = Mock()
        if "mcp/portals" in url and method == "POST":
            # Portal returns AUD directly in response
            response.json.return_value = {
                "success": True,
                "result": {
                    "id": "mcpbox-portal",
                    "hostname": "mcp.example.com",
                    "aud": "aud123xyz",
                },
            }
        elif "access/apps" in url and method == "GET" and "policies" not in url:
            # Return empty - no need to check since AUD was in portal response
            response.json.return_value = {
                "success": True,
                "result": [],
            }
        elif "/zones" in url and method == "GET" and "dns_records" not in url:
            # Zone lookup
            response.json.return_value = {
                "success": True,
                "result": [{"id": "zone-123", "name": "example.com"}],
            }
        elif "dns_records" in url and method == "GET":
            # Check for existing DNS records
            response.json.return_value = {"success": True, "result": []}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    # Mock subprocess for wrangler secret commands (auto-JWT)
    def mock_subprocess_run(*args, **kwargs):
        result = Mock()
        result.returncode = 0
        result.stdout = "Secret set successfully"
        result.stderr = ""
        return result

    with patch("app.services.cloudflare.subprocess.run", side_effect=mock_subprocess_run):
        response = await async_client.post(
            "/api/cloudflare/mcp-portal",
            json={
                "config_id": str(config.id),
                "portal_id": "mcpbox-portal",
                "portal_name": "MCPbox Portal",
                "hostname": "mcp.example.com",
            },
            headers=admin_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["mcp_portal_id"] == "mcpbox-portal"
    assert data["mcp_portal_aud"] == "aud123xyz"
    assert "complete" in data["message"].lower()  # Should indicate setup is complete


# --- Sync MCP Server Tests ---


@pytest.mark.asyncio
async def test_sync_mcp_server_success(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api
):
    """Test successful MCP server tool sync."""
    config = await cloudflare_config_factory(
        mcp_server_id="mcpbox",
        completed_step=7,
        status="active",
    )

    def mock_request(method, url, **kwargs):
        response = Mock()
        if "mcp/servers" in url and "/sync" in url:
            response.json.return_value = {
                "success": True,
                "result": {
                    "tools": [
                        {"name": "tool1", "description": "First tool"},
                        {"name": "tool2", "description": "Second tool"},
                    ]
                },
            }
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        f"/api/cloudflare/sync-tools/{config.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tools_synced"] == 2
    assert len(data["tools"]) == 2


# --- Configure JWT Tests ---


@pytest.mark.asyncio
async def test_configure_jwt_success(async_client, admin_headers, cloudflare_config_factory):
    """Test successful JWT configuration."""
    config = await cloudflare_config_factory(
        worker_name="mcpbox-proxy",
        worker_url="https://mcpbox-proxy.test.workers.dev",
        team_domain="myteam.cloudflareaccess.com",
        mcp_portal_aud="aud123xyz",
        mcp_portal_id="mcpbox-portal",
        completed_step=6,
    )

    # Mock subprocess for wrangler secret commands
    def mock_subprocess_run(*args, **kwargs):
        result = Mock()
        result.returncode = 0
        result.stdout = "Secret set successfully"
        result.stderr = ""
        return result

    # Mock worker URL test - expects a network error since test Worker doesn't exist
    with (
        patch("app.services.cloudflare.subprocess.run", side_effect=mock_subprocess_run),
        patch("app.services.cloudflare.httpx.AsyncClient") as mock_client,
    ):
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_instance
        mock_instance.post.side_effect = Exception("Connection failed")

        response = await async_client.post(
            "/api/cloudflare/worker-jwt-config",
            json={"config_id": str(config.id)},
            headers=admin_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["team_domain"] == "myteam.cloudflareaccess.com"
    assert data["aud"] == "aud123xyz"


@pytest.mark.asyncio
async def test_configure_jwt_no_team_domain(async_client, admin_headers, cloudflare_config_factory):
    """Test JWT configuration without team domain."""
    config = await cloudflare_config_factory(
        team_domain=None,
        mcp_portal_aud="aud123",
        completed_step=6,
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
        mcp_server_id="mcpbox",
        mcp_portal_id="mcpbox-portal",
        completed_step=7,
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
    assert "MCP Portal" in str(data["deleted_resources"])
    assert "MCP Server" in str(data["deleted_resources"])
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
        encrypted_tunnel_token=encrypt_to_base64("my-tunnel-token-123"),
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
async def test_create_mcp_server_persists_email_policy(
    async_client, admin_headers, cloudflare_config_factory, mock_cloudflare_api, db_session
):
    """Test that creating MCP server with email policy persists it to database."""
    config = await cloudflare_config_factory(
        worker_url="https://mcpbox-proxy.test.workers.dev",
        completed_step=4,
    )

    def mock_request(method, url, **kwargs):
        response = Mock()
        if "mcp/servers" in url and method == "POST":
            if "/sync" in url:
                response.json.return_value = {"success": True, "result": {"tools": []}}
            else:
                response.json.return_value = {"success": True, "result": {"id": "mcpbox"}}
        elif "access/apps" in url and method == "POST" and "policies" not in url:
            response.json.return_value = {"success": True, "result": {"id": "mcp-app-123"}}
        else:
            response.json.return_value = {"success": True, "result": {}}
        return response

    mock_cloudflare_api.request.side_effect = mock_request

    response = await async_client.post(
        "/api/cloudflare/mcp-server",
        json={
            "config_id": str(config.id),
            "server_id": "mcpbox",
            "server_name": "MCPbox",
            "access_policy": {
                "policy_type": "emails",
                "emails": ["user@example.com", "admin@example.com"],
            },
        },
        headers=admin_headers,
    )
    assert response.status_code == 200

    # Verify policy was persisted to database
    await db_session.refresh(config)
    assert config.access_policy_type == "emails"
    assert json.loads(config.access_policy_emails) == [
        "user@example.com",
        "admin@example.com",
    ]
    assert config.access_policy_email_domain is None


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
        mcp_portal_aud="aud-123",
        completed_step=7,
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
