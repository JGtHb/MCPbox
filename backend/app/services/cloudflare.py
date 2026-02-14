"""Cloudflare service - business logic for remote access wizard."""

import base64
import json
import logging
import os
import re
import secrets
import subprocess
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cloudflare_config import CloudflareConfig
from app.models.tunnel_configuration import TunnelConfiguration
from app.schemas.cloudflare import (
    AccessPolicyConfig,
    ConfigureJwtResponse,
    CreateMcpPortalResponse,
    CreateMcpServerResponse,
    CreateTunnelResponse,
    CreateVpcServiceResponse,
    DeployWorkerResponse,
    SetApiTokenResponse,
    StartWithApiTokenResponse,
    TeardownResponse,
    UpdateAccessPolicyResponse,
    WizardStatusResponse,
    Zone,
)
from app.services.crypto import (
    DecryptionError,
    decrypt_from_base64,
    encrypt_to_base64,
)

logger = logging.getLogger(__name__)

# Cloudflare API base URL
CF_API_BASE = "https://api.cloudflare.com/client/v4"

# Regex for safe resource names (defense-in-depth, also validated at schema level)
_SAFE_RESOURCE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_safe_name(name: str, field: str) -> str:
    """Validate a resource name is safe for use in TOML templates and URLs.

    Defense-in-depth: schema validation should catch this first, but this
    prevents injection if a code path bypasses schema validation.
    """
    if not _SAFE_RESOURCE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid {field}: must contain only alphanumeric characters, hyphens, and underscores"
        )
    if len(name) > 63:
        raise ValueError(f"Invalid {field}: must be 63 characters or fewer")
    return name


class CloudflareAPIError(Exception):
    """Raised when Cloudflare API returns an error."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


class ResourceConflictError(Exception):
    """Raised when existing Cloudflare resources would be overwritten."""

    def __init__(self, existing_resources: list[dict]):
        self.existing_resources = existing_resources
        names = ", ".join(f"{r['resource_type']}: {r['name']}" for r in existing_resources)
        super().__init__(f"Existing resources found: {names}")


class CloudflareService:
    """Service for interacting with Cloudflare API and managing wizard state."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Configuration Management
    # =========================================================================

    async def get_config(self) -> CloudflareConfig | None:
        """Get the current (most recent) Cloudflare configuration."""
        result = await self.db.execute(
            select(CloudflareConfig).order_by(CloudflareConfig.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_config_by_id(self, config_id: UUID) -> CloudflareConfig | None:
        """Get a configuration by ID."""
        result = await self.db.execute(
            select(CloudflareConfig).where(CloudflareConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    async def get_status(self) -> WizardStatusResponse:
        """Get current wizard status."""
        config = await self.get_config()

        if not config:
            return WizardStatusResponse()

        # Parse stored access policy emails (JSON array or None)
        access_policy_emails = None
        if config.access_policy_emails:
            try:
                access_policy_emails = json.loads(config.access_policy_emails)
            except (json.JSONDecodeError, TypeError):
                pass

        return WizardStatusResponse(
            config_id=config.id,
            status=config.status,
            completed_step=config.completed_step,
            error_message=config.error_message,
            account_id=config.account_id,
            account_name=config.account_name,
            team_domain=config.team_domain,
            tunnel_id=config.tunnel_id,
            tunnel_name=config.tunnel_name,
            has_tunnel_token=config.encrypted_tunnel_token is not None,
            vpc_service_id=config.vpc_service_id,
            vpc_service_name=config.vpc_service_name,
            worker_name=config.worker_name,
            worker_url=config.worker_url,
            mcp_server_id=config.mcp_server_id,
            mcp_portal_id=config.mcp_portal_id,
            mcp_portal_hostname=config.mcp_portal_hostname,
            mcp_portal_aud=config.mcp_portal_aud,
            access_policy_type=config.access_policy_type,
            access_policy_emails=access_policy_emails,
            access_policy_email_domain=config.access_policy_email_domain,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    async def _get_decrypted_token(self, config: CloudflareConfig) -> str | None:
        """Get decrypted API token from config, or from wrangler OAuth if not stored."""
        # First try to get from our encrypted storage
        if config.encrypted_api_token:
            try:
                return decrypt_from_base64(config.encrypted_api_token)
            except DecryptionError as e:
                logger.warning(f"Failed to decrypt API token: {e}")

        # No token available
        return None

    async def _get_decrypted_tunnel_token(self, config: CloudflareConfig) -> str | None:
        """Get decrypted tunnel token from config."""
        if not config.encrypted_tunnel_token:
            return None
        try:
            return decrypt_from_base64(config.encrypted_tunnel_token)
        except DecryptionError as e:
            logger.warning(f"Failed to decrypt tunnel token: {e}")
            return None

    async def get_zones(self, config_id: UUID) -> list[Zone]:
        """Get zones for a config's account."""
        config = await self.get_config_by_id(config_id)
        if not config or not config.account_id:
            return []

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            return []

        try:
            data = await self._cf_request(
                "GET",
                f"/zones?account.id={config.account_id}&per_page=50",
                api_token,
            )
            zones = data.get("result", [])
            return [Zone(id=z["id"], name=z["name"]) for z in zones]
        except Exception as e:
            logger.warning(f"Could not get zones: {e}")
            return []

    async def set_api_token(self, config_id: UUID, api_token: str) -> SetApiTokenResponse:
        """Set an API token for operations requiring higher permissions.

        Verifies the token works and stores it encrypted.
        """
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        # Verify the token works by checking accounts
        try:
            await self._cf_request("GET", "/user/tokens/verify", api_token)
        except CloudflareAPIError as e:
            raise ValueError(f"Invalid API token: {e}") from e

        # Store the token
        config.encrypted_api_token = encrypt_to_base64(api_token)
        await self.db.flush()

        return SetApiTokenResponse(
            success=True,
            message="API token verified and stored successfully.",
        )

    async def start_with_api_token(self, api_token: str) -> StartWithApiTokenResponse:
        """Start the wizard with an API token.

        This is the primary authentication method. Creates a new config,
        verifies the token, and retrieves account information.

        Required token permissions:
        - Account > Cloudflare Tunnel > Edit
        - Account > Access: Apps and Policies > Edit
        - Account > Workers Scripts > Edit
        - Account > Workers KV Storage > Edit
        - Zone > Zone > Read (for all zones)
        """
        # Verify the token works
        try:
            await self._cf_request("GET", "/user/tokens/verify", api_token)
        except CloudflareAPIError as e:
            return StartWithApiTokenResponse(
                success=False,
                error=f"Invalid API token: {e}",
            )

        # Get account information
        try:
            accounts_data = await self._cf_request("GET", "/accounts", api_token)
            accounts = accounts_data.get("result", [])
            if not accounts:
                return StartWithApiTokenResponse(
                    success=False,
                    error="No accounts found for this API token",
                )

            # Use the first account (most users have one)
            account = accounts[0]
            account_id = account.get("id")
            account_name = account.get("name")

        except CloudflareAPIError as e:
            return StartWithApiTokenResponse(
                success=False,
                error=f"Failed to get account information: {e}",
            )

        # Get team domain for Zero Trust
        team_domain = None
        try:
            team_domain = await self._get_team_domain(account_id, api_token)
        except Exception as e:
            logger.warning(f"Could not get team domain: {e}")

        # Get zones for the account
        zones: list[Zone] = []
        try:
            zones_data = await self._cf_request(
                "GET",
                f"/zones?account.id={account_id}&per_page=50",
                api_token,
            )
            zones_list = zones_data.get("result", [])
            zones = [Zone(id=z["id"], name=z["name"]) for z in zones_list]
        except CloudflareAPIError as e:
            logger.warning(f"Could not get zones: {e}")

        # Create the config
        config = CloudflareConfig(
            encrypted_api_token=encrypt_to_base64(api_token),
            account_id=account_id,
            account_name=account_name,
            team_domain=team_domain,
            status="pending",
            completed_step=1,
        )
        self.db.add(config)
        await self.db.flush()

        return StartWithApiTokenResponse(
            success=True,
            config_id=config.id,
            account_id=account_id,
            account_name=account_name,
            team_domain=team_domain,
            zones=zones,
            message="API token verified. Ready to create tunnel.",
        )

    async def _get_team_domain(self, account_id: str, api_token: str) -> str | None:
        """Get the Zero Trust team domain for an account."""
        try:
            data = await self._cf_request(
                "GET",
                f"/accounts/{account_id}/access/organizations",
                api_token,
            )
            org = data.get("result", {})
            # Team domain is either auth_domain or name.cloudflareaccess.com
            auth_domain: str | None = org.get("auth_domain")
            if auth_domain:
                return auth_domain
            org_name: str | None = org.get("name")
            if org_name:
                return f"{org_name}.cloudflareaccess.com"
        except CloudflareAPIError:
            pass
        return None

    # =========================================================================
    # Cloudflare API Helpers
    # =========================================================================

    def _get_headers(self, api_token: str) -> dict[str, str]:
        """Get headers for Cloudflare API requests."""
        return {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    async def _cf_request(
        self,
        method: str,
        path: str,
        api_token: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to the Cloudflare API."""
        url = f"{CF_API_BASE}{path}"
        headers = self._get_headers(api_token)

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=30.0,
            )

            # Some CF API responses (e.g. DELETE 202) have empty bodies
            if not response.content or not response.content.strip():
                if response.is_success:
                    return {"success": True, "result": {}}
                raise CloudflareAPIError(
                    f"Cloudflare API error: HTTP {response.status_code} (empty response)"
                )

            data: dict[str, Any] = response.json()

            if not data.get("success", False):
                errors = data.get("errors", [])
                error_messages = [e.get("message", str(e)) for e in errors]
                raise CloudflareAPIError(
                    f"Cloudflare API error: {', '.join(error_messages)}",
                    errors=errors,
                )

            return data

    # =========================================================================
    # Step 2: Create Tunnel
    # =========================================================================

    async def create_tunnel(
        self, config_id: UUID, name: str, force: bool = False
    ) -> CreateTunnelResponse:
        """Create a Cloudflare tunnel."""
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError(
                "API token not available. Please set an API token with tunnel permissions."
            )

        try:
            # Check for existing tunnels with the same name
            conflicts: list[dict] = []
            existing_tunnels: list[dict] = []
            try:
                tunnels_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/cfd_tunnel?name={name}&is_deleted=false",
                    api_token,
                )
                for t in tunnels_data.get("result", []):
                    existing_tunnels.append(t)
                    conflicts.append(
                        {
                            "resource_type": "tunnel",
                            "name": t.get("name", name),
                            "id": t.get("id", ""),
                        }
                    )
            except CloudflareAPIError:
                pass  # No existing tunnel, that's fine

            if conflicts and not force:
                raise ResourceConflictError(conflicts)

            # If forcing, delete existing tunnels
            for t in existing_tunnels:
                old_id = t.get("id")
                logger.info(f"Deleting existing tunnel '{name}' ({old_id}) before recreation")
                try:
                    await self._cf_request(
                        "DELETE",
                        f"/accounts/{config.account_id}/cfd_tunnel/{old_id}/connections",
                        api_token,
                    )
                except CloudflareAPIError:
                    pass
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/cfd_tunnel/{old_id}",
                    api_token,
                )

            # Generate a tunnel secret (32 bytes, standard base64 encoded)
            tunnel_secret = secrets.token_bytes(32)
            tunnel_secret_b64 = base64.b64encode(tunnel_secret).decode("utf-8")

            # Create tunnel via REST API
            data = await self._cf_request(
                "POST",
                f"/accounts/{config.account_id}/cfd_tunnel",
                api_token,
                json={
                    "name": name,
                    "tunnel_secret": tunnel_secret_b64,
                },
            )

            tunnel = data.get("result", {})
            tunnel_id = tunnel.get("id")
            tunnel_name = tunnel.get("name")

            # Get tunnel token
            token_data = await self._cf_request(
                "GET",
                f"/accounts/{config.account_id}/cfd_tunnel/{tunnel_id}/token",
                api_token,
            )
            tunnel_token = token_data.get("result", "")

            # Update config
            config.tunnel_id = tunnel_id
            config.tunnel_name = tunnel_name
            config.encrypted_tunnel_token = encrypt_to_base64(tunnel_token)
            config.completed_step = max(config.completed_step, 2)

            # Deactivate any existing tunnel configurations
            existing_configs = (
                (
                    await self.db.execute(
                        select(TunnelConfiguration).where(
                            TunnelConfiguration.is_active == True  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )
            for existing in existing_configs:
                existing.is_active = False

            # Create a TunnelConfiguration for the start/stop API
            tunnel_config = TunnelConfiguration(
                name=f"Wizard: {tunnel_name}",
                description=f"Created by Cloudflare wizard for tunnel {tunnel_id}",
                tunnel_token=encrypt_to_base64(tunnel_token),
                public_url=None,  # Will be set when MCP Portal is created
                is_active=True,
            )
            self.db.add(tunnel_config)

            await self.db.flush()

            return CreateTunnelResponse(
                success=True,
                tunnel_id=tunnel_id,
                tunnel_name=tunnel_name,
                tunnel_token=tunnel_token,
                message="Tunnel created. Use 'Start Tunnel' button or the Tunnel page to connect.",
            )

        except CloudflareAPIError as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise

    # =========================================================================
    # Step 3: Create VPC Service
    # =========================================================================

    async def create_vpc_service(
        self, config_id: UUID, name: str, force: bool = False
    ) -> CreateVpcServiceResponse:
        """Create a VPC service (connectivity directory service) for the tunnel.

        Uses the Cloudflare Connectivity Directory REST API:
        POST /accounts/{account_id}/connectivity/directory/services

        See: https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/
        """
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        if not config.tunnel_id:
            raise ValueError("Tunnel must be created first")

        try:
            # Check for existing VPC service with the same name
            conflicts: list[dict] = []
            existing_services: list[dict] = []
            try:
                services_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/connectivity/directory/services",
                    api_token,
                )
                for svc in services_data.get("result", []):
                    if svc.get("name") == name:
                        existing_services.append(svc)
                        conflicts.append(
                            {
                                "resource_type": "vpc_service",
                                "name": svc.get("name", name),
                                "id": svc.get("service_id", ""),
                            }
                        )
            except CloudflareAPIError:
                pass  # No existing service, that's fine

            if conflicts and not force:
                raise ResourceConflictError(conflicts)

            # If forcing, delete existing services
            for svc in existing_services:
                old_id = svc.get("service_id")
                logger.info(f"Deleting existing VPC service '{name}' ({old_id}) before recreation")
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/connectivity/directory/services/{old_id}",
                    api_token,
                )

            # Create VPC Service via Connectivity Directory API
            # This creates a service that routes through the tunnel to mcp-gateway:8002
            data = await self._cf_request(
                "POST",
                f"/accounts/{config.account_id}/connectivity/directory/services",
                api_token,
                json={
                    "name": name,
                    "type": "http",
                    "http_port": 8002,
                    "host": {
                        "hostname": "mcp-gateway",
                        "resolver_network": {
                            "tunnel_id": config.tunnel_id,
                        },
                    },
                },
            )

            service = data.get("result", {})
            vpc_service_id = service.get("service_id")

            # Update config
            config.vpc_service_id = vpc_service_id
            config.vpc_service_name = name
            config.completed_step = max(config.completed_step, 3)

            await self.db.flush()

            return CreateVpcServiceResponse(
                success=True,
                vpc_service_id=vpc_service_id,
                vpc_service_name=name,
                message="VPC service created and linked to tunnel.",
            )

        except CloudflareAPIError as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise

    # =========================================================================
    # Step 4: Deploy Worker
    # =========================================================================

    async def deploy_worker(self, config_id: UUID, name: str) -> DeployWorkerResponse:
        """Deploy the MCPbox proxy Worker using wrangler CLI.

        Uses wrangler deploy to properly configure VPC bindings, which are
        not supported via the REST API. The worker is deployed with:
        - VPC service binding for private tunnel access
        - Service token for MCPbox authentication
        - JWT verification secrets (if configured)
        """
        import os
        import tempfile

        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        if not config.vpc_service_id:
            raise ValueError("VPC service must be created first")

        try:
            # Validate name for TOML safety (defense-in-depth, schema also validates)
            _validate_safe_name(name, "worker name")

            # Generate a service token for MCPbox authentication
            service_token = secrets.token_hex(32)

            # Validate VPC service ID format (should be a UUID from Cloudflare API)
            vpc_service_id = config.vpc_service_id
            if not re.match(r"^[a-zA-Z0-9-]+$", vpc_service_id):
                raise ValueError("Invalid VPC service ID format")

            # Create a temporary directory for wrangler deployment
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write the worker TypeScript code in src/ subdirectory
                src_dir = os.path.join(tmpdir, "src")
                os.makedirs(src_dir, exist_ok=True)
                worker_code = self._get_worker_code()
                worker_path = os.path.join(src_dir, "index.ts")
                with open(worker_path, "w") as f:
                    f.write(worker_code)

                # Write package.json for npm dependencies
                package_json = self._get_worker_package_json()
                package_json_path = os.path.join(tmpdir, "package.json")
                with open(package_json_path, "w") as f:
                    f.write(package_json)

                # Only pass required environment variables to wrangler subprocess
                # (avoid leaking DATABASE_URL, MCPBOX_ENCRYPTION_KEY, etc.)
                env = {
                    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "HOME": os.environ.get("HOME", "/root"),
                    "CLOUDFLARE_API_TOKEN": api_token,
                    "CLOUDFLARE_ACCOUNT_ID": config.account_id,
                }

                # Create OAUTH_KV namespace if not yet created (via wrangler CLI,
                # which uses the same API token auth as wrangler deploy)
                kv_namespace_id = config.kv_namespace_id
                if not kv_namespace_id:
                    # Write a minimal wrangler.toml so wrangler knows the account
                    minimal_toml = f'name = "{name}"\nmain = "src/index.ts"\ncompatibility_date = "2025-03-01"\n'
                    minimal_toml_path = os.path.join(tmpdir, "wrangler.toml")
                    with open(minimal_toml_path, "w") as f:
                        f.write(minimal_toml)

                    kv_result = subprocess.run(
                        [
                            "wrangler",
                            "kv",
                            "namespace",
                            "create",
                            "OAUTH_KV",
                            "--config",
                            minimal_toml_path,
                        ],
                        cwd=tmpdir,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if kv_result.returncode != 0:
                        # Check both stdout and stderr (wrangler splits output)
                        combined_output = (kv_result.stderr or "") + (kv_result.stdout or "")
                        if "Authentication error" in combined_output or "10000" in combined_output:
                            raise CloudflareAPIError(
                                "Failed to create KV namespace: API token missing "
                                "'Workers KV Storage: Edit' permission. "
                                "Update your token at https://dash.cloudflare.com/profile/api-tokens"
                            )
                        # If namespace already exists, look it up via API
                        if "already exists" in combined_output:
                            logger.info("KV namespace 'OAUTH_KV' already exists, looking up ID...")
                            kv_data = await self._cf_request(
                                "GET",
                                f"/accounts/{config.account_id}/storage/kv/namespaces",
                                api_token,
                            )
                            # Wrangler may title it "OAUTH_KV" or "{name}-OAUTH_KV"
                            for ns in kv_data.get("result", []):
                                title = ns.get("title", "")
                                if title == "OAUTH_KV" or title == f"{name}-OAUTH_KV":
                                    kv_namespace_id = ns["id"]
                                    config.kv_namespace_id = kv_namespace_id
                                    logger.info(
                                        f"Found existing KV namespace '{title}': {kv_namespace_id}"
                                    )
                                    break
                            if not kv_namespace_id:
                                raise CloudflareAPIError(
                                    "KV namespace 'OAUTH_KV' exists but could not find its ID"
                                )
                        else:
                            raise CloudflareAPIError(
                                f"Failed to create KV namespace: {combined_output}"
                            )
                    else:
                        # Parse KV namespace ID from wrangler output
                        # Output contains: id = "<namespace-id>"
                        kv_match = re.search(r'id\s*=\s*"([^"]+)"', kv_result.stdout)
                        if not kv_match:
                            raise CloudflareAPIError(
                                f"Could not parse KV namespace ID from wrangler output: {kv_result.stdout}"
                            )
                        kv_namespace_id = kv_match.group(1)
                        config.kv_namespace_id = kv_namespace_id
                        logger.info(f"Created KV namespace via wrangler: {kv_namespace_id}")

                # Generate wrangler.toml with VPC service ID and KV binding
                wrangler_toml = f"""# MCPbox MCP Proxy Worker (generated)
name = "{name}"
main = "src/index.ts"
compatibility_date = "2025-03-01"
compatibility_flags = ["nodejs_compat"]

[observability]
enabled = true

# Workers VPC Service binding for private tunnel access
[[vpc_services]]
binding = "MCPBOX_TUNNEL"
service_id = "{vpc_service_id}"

# KV namespace for OAuth token/grant storage
[[kv_namespaces]]
binding = "OAUTH_KV"
id = "{kv_namespace_id}"
"""
                wrangler_path = os.path.join(tmpdir, "wrangler.toml")
                with open(wrangler_path, "w") as f:
                    f.write(wrangler_toml)

                # Install npm dependencies (required for @cloudflare/workers-oauth-provider)
                npm_result = subprocess.run(
                    ["npm", "install", "--production"],
                    cwd=tmpdir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if npm_result.returncode != 0:
                    error_msg = npm_result.stderr or npm_result.stdout or "Unknown error"
                    raise CloudflareAPIError(f"npm install failed: {error_msg}")
                logger.info("npm install completed successfully")

                # Run wrangler deploy
                result = subprocess.run(
                    ["wrangler", "deploy", "--config", wrangler_path],
                    cwd=tmpdir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout or "Unknown error"
                    raise CloudflareAPIError(f"Wrangler deploy failed: {error_msg}")

                logger.info(f"Wrangler deploy output: {result.stdout}")

                # Set the service token on the Worker.
                # JWT secrets (CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD) are not
                # available yet at step 4 — they're set at step 7 when
                # _sync_worker_secrets() pushes all secrets from the DB.
                secret_result = subprocess.run(
                    [
                        "wrangler",
                        "secret",
                        "put",
                        "MCPBOX_SERVICE_TOKEN",
                        "--config",
                        wrangler_path,
                    ],
                    cwd=tmpdir,
                    env=env,
                    input=service_token,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if secret_result.returncode != 0:
                    logger.warning(f"Failed to set MCPBOX_SERVICE_TOKEN: {secret_result.stderr}")

            # Get the actual worker URL from the subdomain
            worker_url = f"https://{name}.workers.dev"
            try:
                subdomain_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/workers/subdomain",
                    api_token,
                )
                subdomain = subdomain_data.get("result", {}).get("subdomain")
                if subdomain:
                    worker_url = f"https://{name}.{subdomain}.workers.dev"
            except CloudflareAPIError:
                pass

            # Store the service token encrypted for reference
            config.encrypted_service_token = encrypt_to_base64(service_token)
            config.worker_name = name
            config.worker_url = worker_url
            config.completed_step = max(config.completed_step, 4)

            await self.db.flush()

            # Update in-memory cache so auth picks up the new token immediately
            from app.services.service_token_cache import ServiceTokenCache

            cache = ServiceTokenCache.get_instance()
            cache.invalidate()
            await cache.load()

            return DeployWorkerResponse(
                success=True,
                worker_name=name,
                worker_url=worker_url,
                service_token=service_token,
                message="Worker deployed with VPC binding. Service token stored securely.",
            )

        except CloudflareAPIError as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise

    def _get_worker_code(self) -> str:
        """Get the Worker TypeScript source code.

        Reads the worker source from the mounted volume.
        Wrangler will compile TypeScript to JavaScript during deployment.
        """
        import os

        worker_path = "/app/worker/src/index.ts"
        if os.path.exists(worker_path):
            with open(worker_path) as f:
                return f.read()

        # Fallback: minimal embedded worker if source not found
        logger.warning("Worker source not found at %s, using embedded fallback", worker_path)
        return """
// MCPbox MCP Proxy Worker (fallback - source file not found)
export default {
  async fetch(request, env) {
    const corsHeaders = {
      'Access-Control-Allow-Origin': 'https://mcp.claude.ai',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, Cf-Access-Jwt-Assertion',
    };
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }
    if (!env.MCPBOX_TUNNEL || !env.MCPBOX_SERVICE_TOKEN) {
      return new Response(JSON.stringify({ error: 'Worker not configured' }), {
        status: 500, headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }
    const url = new URL(request.url);
    const path = url.pathname;
    if (!path.startsWith('/mcp') && !path.startsWith('/health')) {
      return new Response(JSON.stringify({ error: 'Not found' }), {
        status: 404, headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }
    const headers = new Headers(request.headers);
    headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
    try {
      const response = await env.MCPBOX_TUNNEL.fetch(`http://mcp-gateway:8002${path}${url.search}`, {
        method: request.method, headers, body: request.body,
      });
      const responseHeaders = new Headers(response.headers);
      Object.entries(corsHeaders).forEach(([k, v]) => responseHeaders.set(k, v));
      return new Response(response.body, { status: response.status, headers: responseHeaders });
    } catch (error) {
      return new Response(JSON.stringify({ error: 'Failed to connect to MCPbox' }), {
        status: 502, headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }
  },
};
"""

    def _get_worker_package_json(self) -> str:
        """Get the Worker package.json source.

        Reads from the mounted volume. Contains dependencies like
        @cloudflare/workers-oauth-provider.
        """
        package_path = "/app/worker/package.json"
        if os.path.exists(package_path):
            with open(package_path) as f:
                return f.read()

        # Fallback: minimal package.json if source not found
        logger.warning("Worker package.json not found at %s, using embedded fallback", package_path)
        return '{"name":"mcpbox-proxy","version":"1.0.0","dependencies":{"@cloudflare/workers-oauth-provider":"0.2.2"}}'

    # =========================================================================
    # Step 5: Create MCP Server
    # =========================================================================

    async def create_mcp_server(
        self,
        config_id: UUID,
        server_id: str,
        server_name: str,
        access_policy: AccessPolicyConfig | None = None,
        force: bool = False,
    ) -> CreateMcpServerResponse:
        """Create an MCP Server in Cloudflare."""
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        if not config.worker_url:
            raise ValueError("Worker must be deployed first")

        try:
            # Check for existing MCP Server and Access Apps
            conflicts: list[dict] = []
            existing_server = False
            existing_access_apps: list[dict] = []

            # Check for existing MCP Server by ID
            try:
                server_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/access/ai-controls/mcp/servers/{server_id}",
                    api_token,
                )
                result = server_data.get("result", {})
                if result:
                    existing_server = True
                    conflicts.append(
                        {
                            "resource_type": "mcp_server",
                            "name": result.get("name", server_id),
                            "id": result.get("id", server_id),
                        }
                    )
            except CloudflareAPIError:
                pass  # Doesn't exist

            # Check for existing MCP Access Apps with the same name
            try:
                apps_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/access/apps",
                    api_token,
                )
                for app in apps_data.get("result", []):
                    if app.get("name") == server_name and app.get("type") == "mcp":
                        existing_access_apps.append(app)
                        conflicts.append(
                            {
                                "resource_type": "access_app",
                                "name": f"{app.get('name', '')} (mcp)",
                                "id": app.get("id", ""),
                            }
                        )
            except CloudflareAPIError:
                pass  # Best-effort check

            if conflicts and not force:
                raise ResourceConflictError(conflicts)

            # If forcing, delete existing resources
            if existing_server:
                try:
                    await self._cf_request(
                        "DELETE",
                        f"/accounts/{config.account_id}/access/ai-controls/mcp/servers/{server_id}",
                        api_token,
                    )
                    logger.info(f"Deleted existing MCP Server '{server_id}' before recreation")
                except CloudflareAPIError:
                    pass

            for app in existing_access_apps:
                old_id = app.get("id")
                logger.info(f"Deleting stale MCP Access App: {old_id}")
                try:
                    await self._cf_request(
                        "DELETE",
                        f"/accounts/{config.account_id}/access/apps/{old_id}",
                        api_token,
                    )
                except CloudflareAPIError:
                    pass

            # Create MCP Server with OAuth auth_type. The Worker serves
            # OAuth 2.1 endpoints (/.well-known/oauth-authorization-server,
            # /token, /register, /authorize) via @cloudflare/workers-oauth-provider.
            # With auth_type "oauth", Cloudflare performs the full OAuth 2.1
            # discovery and authorization flow to get an access token for /mcp.
            # Note: "bearer" means static token (not OAuth), "oauth" means
            # full OAuth 2.1 flow — which matches our OAuthProvider setup.
            mcp_server_payload: dict = {
                "id": server_id,
                "name": server_name,
                "hostname": config.worker_url,
                "description": "MCPbox MCP Server",
                "auth_type": "oauth",
            }

            logger.info(
                f"Creating MCP Server: id={server_id}, hostname={mcp_server_payload['hostname']}"
            )
            data = await self._cf_request(
                "POST",
                f"/accounts/{config.account_id}/access/ai-controls/mcp/servers",
                api_token,
                json=mcp_server_payload,
            )

            server = data.get("result", {})
            mcp_server_id = server.get("id")
            logger.info(f"MCP Server created: {server}")

            # Create Access Application with type "mcp" for the server.
            logger.info(f"Creating Access Application (type: mcp) for server {mcp_server_id}...")
            try:
                access_app_data = await self._cf_request(
                    "POST",
                    f"/accounts/{config.account_id}/access/apps",
                    api_token,
                    json={
                        "name": server_name,
                        "type": "mcp",
                        "destinations": [
                            {
                                "type": "via_mcp_server_portal",
                                "mcp_server_id": mcp_server_id,
                            }
                        ],
                    },
                )
                access_app = access_app_data.get("result", {})
                mcp_access_app_id = access_app.get("id", "")
                config.access_app_id = mcp_access_app_id
                logger.info(f"Created MCP Access Application: {mcp_access_app_id}")

                # Add Access Policy to the MCP Access Application
                await self._create_access_policy(
                    api_token, config.account_id, mcp_access_app_id, access_policy
                )
            except CloudflareAPIError as e:
                logger.warning(f"Failed to create MCP Access Application: {e}")
                # Continue - the portal creation may still work

            # Sync tools
            tools_synced = 0
            try:
                sync_data = await self._cf_request(
                    "POST",
                    f"/accounts/{config.account_id}/access/ai-controls/mcp/servers/{mcp_server_id}/sync",
                    api_token,
                )
                sync_result = sync_data.get("result", {})
                tools_synced = len(sync_result.get("tools", []))
            except CloudflareAPIError:
                # Sync may fail if Worker isn't accessible yet
                pass

            # Persist access policy to database for Worker sync
            self._save_access_policy_to_config(config, access_policy)

            # Update config
            config.mcp_server_id = mcp_server_id
            config.completed_step = max(config.completed_step, 5)

            await self.db.flush()

            return CreateMcpServerResponse(
                success=True,
                mcp_server_id=mcp_server_id,
                tools_synced=tools_synced,
                message=f"MCP Server created with {tools_synced} tools discovered.",
            )

        except CloudflareAPIError as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise

    # =========================================================================
    # Step 6: Create MCP Portal
    # =========================================================================

    async def create_mcp_portal(
        self,
        config_id: UUID,
        portal_id: str,
        portal_name: str,
        hostname: str,
        access_policy: AccessPolicyConfig | None = None,
        force: bool = False,
    ) -> CreateMcpPortalResponse:
        """Create an MCP Portal in Cloudflare.

        The correct flow is:
        1. Create Access Application with self_hosted type and via_mcp_server_portal destination
        2. Create MCP Portal - it will link to the Access App via the destination
        """
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        if not config.mcp_server_id:
            raise ValueError("MCP Server must be created first")

        try:
            mcp_portal_aud = ""

            # Check for existing portal and Access Apps
            conflicts: list[dict] = []
            existing_portal = False
            existing_portal_apps: list[dict] = []

            # Check for existing MCP Portal by ID
            try:
                portal_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/access/ai-controls/mcp/portals/{portal_id}",
                    api_token,
                )
                result = portal_data.get("result", {})
                if result:
                    existing_portal = True
                    conflicts.append(
                        {
                            "resource_type": "mcp_portal",
                            "name": result.get("name", portal_id),
                            "id": result.get("id", portal_id),
                        }
                    )
            except CloudflareAPIError:
                pass  # Doesn't exist

            # Check for existing mcp_portal Access Apps with the same name
            try:
                apps_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/access/apps",
                    api_token,
                )
                for app in apps_data.get("result", []):
                    if app.get("name") == portal_name and app.get("type") == "mcp_portal":
                        existing_portal_apps.append(app)
                        conflicts.append(
                            {
                                "resource_type": "access_app",
                                "name": f"{app.get('name', '')} (mcp_portal)",
                                "id": app.get("id", ""),
                            }
                        )
            except CloudflareAPIError:
                pass  # Best-effort check

            if conflicts and not force:
                raise ResourceConflictError(conflicts)

            # If forcing, delete existing resources
            if existing_portal:
                try:
                    await self._cf_request(
                        "DELETE",
                        f"/accounts/{config.account_id}/access/ai-controls/mcp/portals/{portal_id}",
                        api_token,
                    )
                    logger.info(f"Deleted existing MCP Portal '{portal_id}' before recreation")
                except CloudflareAPIError:
                    pass

            for app in existing_portal_apps:
                old_id = app.get("id")
                logger.info(f"Deleting stale mcp_portal Access App: {old_id}")
                try:
                    await self._cf_request(
                        "DELETE",
                        f"/accounts/{config.account_id}/access/apps/{old_id}",
                        api_token,
                    )
                except CloudflareAPIError:
                    pass

            logger.info(f"Creating MCP Portal on hostname {hostname}...")
            data = await self._cf_request(
                "POST",
                f"/accounts/{config.account_id}/access/ai-controls/mcp/portals",
                api_token,
                json={
                    "id": portal_id,
                    "name": portal_name,
                    "hostname": hostname,
                    "description": "MCPbox remote access portal",
                    "servers": [
                        {
                            "server_id": config.mcp_server_id,
                            "default_disabled": False,
                            "on_behalf": True,
                        }
                    ],
                    "secure_web_gateway": False,
                },
            )

            portal = data.get("result", {})
            mcp_portal_id = portal.get("id")
            mcp_portal_hostname = portal.get("hostname", hostname)
            logger.info(f"MCP Portal created: {portal}")

            # Check if portal response has AUD (unlikely but check anyway)
            if not mcp_portal_aud:
                mcp_portal_aud = portal.get("aud", "")

            # If still no AUD, check for any Access App linked to our portal
            if not mcp_portal_aud:
                logger.info("Checking for linked Access App...")
                try:
                    apps_data = await self._cf_request(
                        "GET",
                        f"/accounts/{config.account_id}/access/apps",
                        api_token,
                    )
                    apps = apps_data.get("result", [])
                    for app in apps:
                        # Only match mcp_portal type apps (skip mcp type apps)
                        if app.get("type") not in ("mcp_portal", "self_hosted"):
                            continue
                        # Check destinations for via_mcp_server_portal linking to our server
                        destinations = app.get("destinations", [])
                        for dest in destinations:
                            if (
                                dest.get("type") == "via_mcp_server_portal"
                                and dest.get("mcp_server_id") == config.mcp_server_id
                            ):
                                mcp_portal_aud = app.get("aud", "")
                                config.access_app_id = app.get("id", "")
                                logger.info(
                                    f"Found linked Access App: id={config.access_app_id}, "
                                    f"aud={mcp_portal_aud[:20] if mcp_portal_aud else 'none'}..."
                                )
                                break
                        if mcp_portal_aud:
                            break
                        # Also check domain match
                        if app.get("domain") == mcp_portal_hostname:
                            mcp_portal_aud = app.get("aud", "")
                            config.access_app_id = app.get("id", "")
                            logger.info(f"Found Access App by domain: id={config.access_app_id}")
                            break
                except CloudflareAPIError as e:
                    logger.warning(f"Failed to check for Access App: {e}")

            # Step 2: If still no AUD, create an mcp_portal Access App
            # This is the correct type for MCP Portal Access Applications
            if not mcp_portal_aud:
                logger.info(f"Creating mcp_portal Access Application on {mcp_portal_hostname}...")
                try:
                    access_app_data = await self._cf_request(
                        "POST",
                        f"/accounts/{config.account_id}/access/apps",
                        api_token,
                        json={
                            "name": portal_name,
                            "domain": mcp_portal_hostname,
                            "type": "mcp_portal",
                            "session_duration": "24h",
                            "auto_redirect_to_identity": False,
                            "http_only_cookie_attribute": False,
                            "cors_headers": {
                                "allowed_headers": [
                                    "Content-Type",
                                    "Authorization",
                                    "Cf-Access-Jwt-Assertion",
                                ],
                                "allowed_methods": ["GET", "POST", "OPTIONS"],
                                "allowed_origins": [
                                    "https://mcp.claude.ai",
                                    "https://claude.ai",
                                ],
                            },
                        },
                    )
                    access_app = access_app_data.get("result", {})
                    mcp_portal_aud = access_app.get("aud", "")
                    access_app_id = access_app.get("id", "")
                    logger.info(
                        f"Created mcp_portal Access Application: id={access_app_id}, "
                        f"aud={mcp_portal_aud[:20] if mcp_portal_aud else 'none'}..."
                    )
                    config.access_app_id = access_app_id

                    # Step 3: Create Access Policy
                    await self._create_access_policy(
                        api_token, config.account_id, access_app_id, access_policy
                    )
                except CloudflareAPIError as e:
                    logger.warning(f"Failed to create Access Application: {e}")
                    # Continue without AUD - user can configure manually

            # Step 4: Create DNS record for the portal hostname
            await self._create_dns_record(api_token, mcp_portal_hostname)

            # Persist access policy to database (may already be set from step 5)
            if access_policy:
                self._save_access_policy_to_config(config, access_policy)

            # Update config
            config.mcp_portal_id = mcp_portal_id
            config.mcp_portal_hostname = mcp_portal_hostname
            config.mcp_portal_aud = mcp_portal_aud

            portal_url = f"https://{mcp_portal_hostname}"

            # Update the active TunnelConfiguration with the portal URL
            active_tunnel_config = (
                await self.db.execute(
                    select(TunnelConfiguration).where(
                        TunnelConfiguration.is_active == True  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
            if active_tunnel_config:
                active_tunnel_config.public_url = portal_url

            # Auto-sync all Worker secrets if we have the required values
            jwt_configured = False
            if config.worker_name and mcp_portal_aud and config.team_domain:
                try:
                    # Decrypt service token from DB to re-sync with Worker
                    svc_token = None
                    if config.encrypted_service_token:
                        svc_token = decrypt_from_base64(config.encrypted_service_token)

                    # Build access policy from DB fields for Worker sync
                    sync_policy = access_policy
                    if not sync_policy and config.access_policy_type:
                        sync_policy = AccessPolicyConfig(
                            policy_type=config.access_policy_type,  # type: ignore[arg-type]
                            emails=(
                                json.loads(config.access_policy_emails)
                                if config.access_policy_emails
                                else []
                            ),
                            email_domain=config.access_policy_email_domain,
                        )

                    await self._sync_worker_secrets(
                        api_token,
                        config.account_id,
                        config.worker_name,
                        config.team_domain,
                        mcp_portal_aud,
                        service_token=svc_token,
                        portal_hostname=config.mcp_portal_hostname,
                        access_policy=sync_policy,
                    )
                    jwt_configured = True
                    config.completed_step = 7
                    config.status = "active"
                    logger.info("Worker secrets synced automatically")
                except Exception as e:
                    logger.warning(f"Failed to auto-configure JWT: {e}")
                    config.completed_step = max(config.completed_step, 6)
            else:
                config.completed_step = max(config.completed_step, 6)
                missing = []
                if not config.worker_name:
                    missing.append("worker_name")
                if not mcp_portal_aud:
                    missing.append("mcp_portal_aud")
                if not config.team_domain:
                    missing.append("team_domain")
                logger.warning(f"Cannot auto-configure JWT, missing: {missing}")

            await self.db.flush()

            # Trigger MCP server re-sync. The initial sync at step 5 often
            # fails because the tunnel isn't fully propagated yet. A PUT to
            # the MCP server triggers Cloudflare to retry the sync now that
            # everything (tunnel, Worker secrets, portal) is in place.
            if config.mcp_server_id and jwt_configured:
                try:
                    await self._cf_request(
                        "PUT",
                        f"/accounts/{config.account_id}/access/ai-controls/mcp/servers/{config.mcp_server_id}",
                        api_token,
                        json={
                            "id": config.mcp_server_id,
                            "name": "MCPbox",
                            "hostname": config.worker_url,
                            "description": "MCPbox MCP Server",
                            "auth_type": "oauth",
                        },
                    )
                    logger.info("Triggered MCP server re-sync")
                except CloudflareAPIError as e:
                    logger.warning(f"Failed to trigger MCP server re-sync: {e}")

            message = (
                "Setup complete!"
                if jwt_configured
                else "MCP Portal created. JWT configuration may need manual setup."
            )
            return CreateMcpPortalResponse(
                success=True,
                mcp_portal_id=mcp_portal_id,
                mcp_portal_hostname=mcp_portal_hostname,
                portal_url=portal_url,
                mcp_portal_aud=mcp_portal_aud,
                message=message,
            )

        except CloudflareAPIError as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise

    async def _create_access_policy(
        self,
        api_token: str,
        account_id: str,
        access_app_id: str,
        access_policy: AccessPolicyConfig | None = None,
    ) -> None:
        """Create an Access Policy for an Access Application.

        Builds include rules based on the provided AccessPolicyConfig:
        - everyone (default): allows any authenticated user
        - emails: allows only specific email addresses
        - email_domain: allows any email from a specific domain

        This is required for the MCP Portal to work - without a policy,
        no users can authenticate.
        """
        # Build include rules based on policy config
        if access_policy and access_policy.policy_type == "emails" and access_policy.emails:
            include = [{"email": {"email": email}} for email in access_policy.emails]
            policy_name = f"Allow specific emails ({len(access_policy.emails)})"
        elif (
            access_policy
            and access_policy.policy_type == "email_domain"
            and access_policy.email_domain
        ):
            include = [{"email_domain": {"domain": access_policy.email_domain}}]
            policy_name = f"Allow {access_policy.email_domain} domain"
        else:
            include = [{"everyone": {}}]
            policy_name = "Allow Authenticated Users"

        try:
            await self._cf_request(
                "POST",
                f"/accounts/{account_id}/access/apps/{access_app_id}/policies",
                api_token,
                json={
                    "name": policy_name,
                    "decision": "allow",
                    "include": include,
                    "precedence": 1,
                },
            )
            logger.info(f"Created Access Policy for app {access_app_id}: {policy_name}")
        except CloudflareAPIError as e:
            logger.warning(f"Failed to create Access Policy: {e}")
            # Non-fatal - user can add policy manually

    def _save_access_policy_to_config(
        self,
        config: CloudflareConfig,
        access_policy: AccessPolicyConfig | None,
    ) -> None:
        """Persist access policy configuration to the database.

        Stores the policy type, emails (as JSON), and email domain so they
        can be synced to both Cloudflare Access and the Worker's ALLOWED_EMAILS.
        """
        if not access_policy:
            return
        config.access_policy_type = access_policy.policy_type
        if access_policy.policy_type == "emails" and access_policy.emails:
            config.access_policy_emails = json.dumps(access_policy.emails)
        else:
            config.access_policy_emails = None
        if access_policy.policy_type == "email_domain":
            config.access_policy_email_domain = access_policy.email_domain
        else:
            config.access_policy_email_domain = None

    async def _replace_access_policy(
        self,
        api_token: str,
        account_id: str,
        access_app_id: str,
        access_policy: AccessPolicyConfig,
    ) -> None:
        """Replace all existing Access Policies on an app with a new one.

        Deletes all existing policies first, then creates the new one.
        This is used when updating the access policy after initial setup.
        """
        # List existing policies
        try:
            policies_data = await self._cf_request(
                "GET",
                f"/accounts/{account_id}/access/apps/{access_app_id}/policies",
                api_token,
            )
            existing_policies = policies_data.get("result", [])
            for policy in existing_policies:
                policy_id = policy.get("id")
                if policy_id:
                    try:
                        await self._cf_request(
                            "DELETE",
                            f"/accounts/{account_id}/access/apps/{access_app_id}/policies/{policy_id}",
                            api_token,
                        )
                        logger.info(f"Deleted existing Access Policy: {policy_id}")
                    except CloudflareAPIError as e:
                        logger.warning(f"Failed to delete policy {policy_id}: {e}")
        except CloudflareAPIError as e:
            logger.warning(f"Failed to list existing policies: {e}")

        # Create the new policy
        await self._create_access_policy(api_token, account_id, access_app_id, access_policy)

    async def update_access_policy(
        self,
        config_id: UUID,
        access_policy: AccessPolicyConfig,
    ) -> UpdateAccessPolicyResponse:
        """Update the access policy for both Cloudflare Access and the Worker.

        1. Persists the new policy in the database
        2. Replaces the Cloudflare Access Policy on the Access App
        3. Syncs ALLOWED_EMAILS / ALLOWED_EMAIL_DOMAIN to the Worker
        """
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        # 1. Save to database
        self._save_access_policy_to_config(config, access_policy)
        await self.db.flush()

        access_policy_synced = False
        worker_synced = False
        errors: list[str] = []

        # 2. Update Cloudflare Access Policy
        if config.access_app_id:
            try:
                await self._replace_access_policy(
                    api_token, config.account_id, config.access_app_id, access_policy
                )
                access_policy_synced = True
            except CloudflareAPIError as e:
                errors.append(f"Access Policy update failed: {e}")
                logger.warning(f"Failed to update Access Policy: {e}")

        # 3. Sync to Worker
        if config.worker_name and config.team_domain and config.mcp_portal_aud:
            try:
                svc_token = None
                if config.encrypted_service_token:
                    svc_token = decrypt_from_base64(config.encrypted_service_token)

                await self._sync_worker_secrets(
                    api_token,
                    config.account_id,
                    config.worker_name,
                    config.team_domain,
                    config.mcp_portal_aud,
                    service_token=svc_token,
                    portal_hostname=config.mcp_portal_hostname,
                    access_policy=access_policy,
                )
                worker_synced = True
            except Exception as e:
                errors.append(f"Worker sync failed: {e}")
                logger.warning(f"Failed to sync Worker secrets: {e}")

        message = "Access policy updated"
        if errors:
            message += f" (warnings: {'; '.join(errors)})"

        return UpdateAccessPolicyResponse(
            success=True,
            access_policy_synced=access_policy_synced,
            worker_synced=worker_synced,
            message=message,
        )

    async def _create_dns_record(
        self,
        api_token: str,
        hostname: str,
    ) -> None:
        """Create a DNS record for the MCP Portal hostname.

        Creates a proxied CNAME record pointing to the Cloudflare Access
        endpoint. If the record already exists, this is a no-op.
        """
        # Extract subdomain and domain from hostname (e.g., "mcp.example.com")
        parts = hostname.split(".")
        if len(parts) < 2:
            logger.warning(f"Invalid hostname for DNS: {hostname}")
            return

        # Get the zone for this domain
        try:
            # Try to find the zone - could be example.com or sub.example.com
            zone_id = None
            for i in range(len(parts) - 1):
                domain = ".".join(parts[i:])
                try:
                    zones_data = await self._cf_request(
                        "GET",
                        "/zones",
                        api_token,
                        params={"name": domain},
                    )
                    zones = zones_data.get("result", [])
                    if zones:
                        zone_id = zones[0].get("id")
                        break
                except CloudflareAPIError:
                    continue

            if not zone_id:
                logger.warning(f"Could not find Cloudflare zone for {hostname}")
                return

            # Check if record already exists
            records_data = await self._cf_request(
                "GET",
                f"/zones/{zone_id}/dns_records",
                api_token,
                params={"name": hostname, "type": "CNAME"},
            )
            existing_records = records_data.get("result", [])

            if existing_records:
                logger.info(f"DNS record for {hostname} already exists")
                return

            # Create CNAME record pointing to Cloudflare Access
            # The target doesn't matter much since Access intercepts the request
            await self._cf_request(
                "POST",
                f"/zones/{zone_id}/dns_records",
                api_token,
                json={
                    "type": "CNAME",
                    "name": hostname,
                    "content": "access.cloudflare.com",
                    "proxied": True,
                    "ttl": 1,  # Auto TTL
                },
            )
            logger.info(f"Created DNS record for {hostname}")

        except CloudflareAPIError as e:
            logger.warning(f"Failed to create DNS record: {e}")
            # Non-fatal - user can add DNS manually

    # =========================================================================
    # Step 7: Configure Worker JWT
    # =========================================================================

    async def _sync_worker_secrets(
        self,
        api_token: str,
        account_id: str,
        worker_name: str,
        team_domain: str,
        aud: str,
        service_token: str | None = None,
        portal_hostname: str | None = None,
        access_policy: AccessPolicyConfig | None = None,
    ) -> None:
        """Sync all Worker secrets from the database using wrangler CLI.

        Pushes CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD, MCP_PORTAL_HOSTNAME,
        ALLOWED_EMAILS, ALLOWED_EMAIL_DOMAIN, and (if provided)
        MCPBOX_SERVICE_TOKEN to the Worker. This ensures the Worker always
        has the current values from the database — the single source of truth.

        Raises an exception if any secret fails to set.
        """
        import tempfile

        # Validate worker_name for TOML safety (defense-in-depth)
        _validate_safe_name(worker_name, "worker name")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal wrangler.toml for secrets
            wrangler_toml = f"""name = "{worker_name}"
main = "src/index.ts"
compatibility_date = "2025-03-01"
compatibility_flags = ["nodejs_compat"]
"""
            wrangler_path = os.path.join(tmpdir, "wrangler.toml")
            with open(wrangler_path, "w") as f:
                f.write(wrangler_toml)

            # Only pass required environment variables to wrangler subprocess
            # (avoid leaking DATABASE_URL, MCPBOX_ENCRYPTION_KEY, etc.)
            env = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", "/root"),
                "CLOUDFLARE_API_TOKEN": api_token,
                "CLOUDFLARE_ACCOUNT_ID": account_id,
            }

            # Sync all Worker secrets from DB values
            secrets_to_set = {
                "CF_ACCESS_TEAM_DOMAIN": team_domain,
                "CF_ACCESS_AUD": aud,
            }
            if service_token:
                secrets_to_set["MCPBOX_SERVICE_TOKEN"] = service_token
            if portal_hostname:
                secrets_to_set["MCP_PORTAL_HOSTNAME"] = portal_hostname

            # Sync allowed emails/domain to Worker for authorization enforcement.
            # Use a placeholder value "_none_" to clear secrets — wrangler
            # doesn't support deleting secrets, and empty strings cause errors.
            if access_policy:
                if access_policy.policy_type == "emails" and access_policy.emails:
                    secrets_to_set["ALLOWED_EMAILS"] = ",".join(access_policy.emails)
                else:
                    secrets_to_set["ALLOWED_EMAILS"] = "_none_"

                if access_policy.policy_type == "email_domain" and access_policy.email_domain:
                    secrets_to_set["ALLOWED_EMAIL_DOMAIN"] = access_policy.email_domain
                else:
                    secrets_to_set["ALLOWED_EMAIL_DOMAIN"] = "_none_"

            secrets_failed = []

            for secret_name, secret_value in secrets_to_set.items():
                result = subprocess.run(
                    ["wrangler", "secret", "put", secret_name, "--config", wrangler_path],
                    cwd=tmpdir,
                    env=env,
                    input=secret_value,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    logger.info(f"Set secret {secret_name} successfully")
                else:
                    secrets_failed.append(f"{secret_name}: {result.stderr}")
                    logger.warning(f"Failed to set secret {secret_name}: {result.stderr}")

            if secrets_failed:
                raise CloudflareAPIError(f"Failed to set secrets: {'; '.join(secrets_failed)}")

    async def configure_worker_jwt(
        self, config_id: UUID, aud: str | None = None
    ) -> ConfigureJwtResponse:
        """Configure Worker JWT verification settings using wrangler CLI.

        Args:
            config_id: The configuration ID
            aud: Optional Application Audience Tag. If not provided, will attempt to fetch from API.
        """
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        if not config.worker_name:
            raise ValueError("Worker must be deployed first")

        if not config.mcp_portal_id:
            raise ValueError("MCP Portal must be created first")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        # Try to fetch missing values
        team_domain = config.team_domain
        # Use provided AUD or fall back to stored value
        mcp_portal_aud = aud or config.mcp_portal_aud

        # If AUD was provided manually, save it to config
        if aud and not config.mcp_portal_aud:
            config.mcp_portal_aud = aud
            logger.info(f"Saved manually provided AUD: {aud[:20]}...")

        # Fetch team_domain if missing
        if not team_domain:
            logger.info("team_domain missing, attempting to fetch...")
            try:
                team_domain = await self._get_team_domain(config.account_id, api_token)
                if team_domain:
                    config.team_domain = team_domain
                    logger.info(f"Fetched team_domain: {team_domain}")
            except Exception as e:
                logger.warning(f"Could not fetch team_domain: {e}")

        # Fetch mcp_portal_aud if missing
        if not mcp_portal_aud:
            logger.info("mcp_portal_aud missing, attempting to fetch...")
            import asyncio

            # Try fetching portal details
            try:
                portal_data = await self._cf_request(
                    "GET",
                    f"/accounts/{config.account_id}/access/ai-controls/mcp/portals/{config.mcp_portal_id}",
                    api_token,
                )
                portal_details = portal_data.get("result", {})
                logger.info(f"Portal details: {portal_details}")
                mcp_portal_aud = portal_details.get("aud", "")
                if mcp_portal_aud:
                    config.mcp_portal_aud = mcp_portal_aud
                    logger.info(f"Fetched mcp_portal_aud from portal: {mcp_portal_aud[:20]}...")
            except CloudflareAPIError as e:
                logger.warning(f"Failed to get portal details: {e}")

            # If still missing, try Access apps with different filters
            if not mcp_portal_aud:
                for attempt in range(3):
                    if attempt > 0:
                        await asyncio.sleep(2)
                    try:
                        apps_data = await self._cf_request(
                            "GET",
                            f"/accounts/{config.account_id}/access/apps",
                            api_token,
                        )
                        apps = apps_data.get("result", [])
                        logger.info(f"Access apps (attempt {attempt + 1}): {len(apps)} apps found")
                        for app in apps:
                            logger.debug(f"Access app: {app}")
                            if (
                                app.get("type") == "mcp"
                                or app.get("domain") == config.mcp_portal_hostname
                            ):
                                mcp_portal_aud = app.get("aud", "")
                                if mcp_portal_aud:
                                    config.mcp_portal_aud = mcp_portal_aud
                                    logger.info(
                                        f"Fetched mcp_portal_aud from Access app: {mcp_portal_aud[:20]}..."
                                    )
                                    break
                        if mcp_portal_aud:
                            break
                    except CloudflareAPIError as e:
                        logger.warning(f"Failed to get Access apps (attempt {attempt + 1}): {e}")

            # Try listing all Access apps types including self-hosted and SaaS
            if not mcp_portal_aud:
                try:
                    # Try self-hosted apps endpoint with hostname filter
                    apps_data = await self._cf_request(
                        "GET",
                        f"/accounts/{config.account_id}/access/apps?domain={config.mcp_portal_hostname}",
                        api_token,
                    )
                    apps = apps_data.get("result", [])
                    logger.info(f"Filtered Access apps by domain: {len(apps)} apps found")
                    for app in apps:
                        mcp_portal_aud = app.get("aud", "")
                        if mcp_portal_aud:
                            config.mcp_portal_aud = mcp_portal_aud
                            logger.info(f"Found AUD from filtered apps: {mcp_portal_aud[:20]}...")
                            break
                except CloudflareAPIError as e:
                    logger.warning(f"Failed to get filtered Access apps: {e}")

        # Validate we have the required values
        if not team_domain:
            raise ValueError(
                "Could not get team_domain. Ensure your API token has "
                "'Access: Organizations, Identity Providers, and Groups > Read' permission."
            )

        if not mcp_portal_aud:
            raise ValueError(
                "Could not get MCP Portal AUD. Ensure your API token has "
                "'Access: Apps and Policies > Read' permission."
            )

        try:
            # Decrypt service token from DB to re-sync with Worker
            svc_token = None
            if config.encrypted_service_token:
                svc_token = decrypt_from_base64(config.encrypted_service_token)

            # Build access policy from DB for Worker sync
            sync_policy = None
            if config.access_policy_type:
                sync_policy = AccessPolicyConfig(
                    policy_type=config.access_policy_type,  # type: ignore[arg-type]
                    emails=(
                        json.loads(config.access_policy_emails)
                        if config.access_policy_emails
                        else []
                    ),
                    email_domain=config.access_policy_email_domain,
                )

            # Sync all Worker secrets (JWT + service token + portal hostname + access policy)
            await self._sync_worker_secrets(
                api_token,
                config.account_id,
                config.worker_name,
                team_domain,
                mcp_portal_aud,
                service_token=svc_token,
                portal_hostname=config.mcp_portal_hostname,
                access_policy=sync_policy,
            )

            # Wait a moment for secrets to propagate, then test direct Worker access
            import asyncio

            await asyncio.sleep(2)

            worker_test_result = "Not tested"
            if config.worker_url:
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            f"{config.worker_url}/mcp",
                            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            timeout=10.0,
                        )
                        if response.status_code == 401:
                            worker_test_result = (
                                "401 Unauthorized (expected - JWT verification active)"
                            )
                        else:
                            worker_test_result = (
                                f"{response.status_code} (secrets may need more time to propagate)"
                            )
                except Exception as e:
                    worker_test_result = f"Connection test failed: {e}"

            # Update config
            config.completed_step = 7
            config.status = "active"
            config.error_message = None

            await self.db.flush()

            return ConfigureJwtResponse(
                success=True,
                team_domain=config.team_domain or "",
                aud=config.mcp_portal_aud or "",
                worker_test_result=worker_test_result,
                message="JWT verification secrets set successfully: CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD",
            )

        except CloudflareAPIError as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise
        except Exception as e:
            config.status = "error"
            config.error_message = str(e)
            await self.db.flush()
            raise

    # =========================================================================
    # Sync MCP Server Tools
    # =========================================================================

    async def sync_mcp_server(self, config_id: UUID) -> dict:
        """Manually sync MCP server tools with Cloudflare.

        This should be called after JWT is configured to allow Cloudflare
        to enumerate the tools from the Worker endpoint.

        Returns:
            dict with 'tools_synced' count and 'tools' list
        """
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        if not config.mcp_server_id:
            raise ValueError("MCP Server must be created first")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        try:
            sync_data = await self._cf_request(
                "POST",
                f"/accounts/{config.account_id}/access/ai-controls/mcp/servers/{config.mcp_server_id}/sync",
                api_token,
            )
            sync_result = sync_data.get("result", {})
            tools = sync_result.get("tools", [])
            logger.info(f"Synced MCP Server, discovered {len(tools)} tools")
            return {
                "tools_synced": len(tools),
                "tools": tools,
                "message": f"Successfully synced {len(tools)} tools",
            }
        except CloudflareAPIError as e:
            logger.warning(f"Failed to sync MCP Server: {e}")
            raise

    # =========================================================================
    # Teardown
    # =========================================================================

    async def teardown(self, config_id: UUID) -> TeardownResponse:
        """Remove all Cloudflare resources created by the wizard."""
        config = await self.get_config_by_id(config_id)
        if not config:
            raise ValueError("Configuration not found")

        api_token = await self._get_decrypted_token(config)
        if not api_token:
            raise ValueError("API token not available")

        deleted_resources: list[str] = []
        errors: list[str] = []

        # Delete MCP Portal
        if config.mcp_portal_id:
            try:
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/access/ai-controls/mcp/portals/{config.mcp_portal_id}",
                    api_token,
                )
                deleted_resources.append(f"MCP Portal: {config.mcp_portal_id}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete MCP Portal: {e}")

        # Delete Access Applications (Portal + MCP Server types)
        # The wizard creates two Access Apps: mcp_portal (for the Portal) and
        # mcp (for the MCP Server). Both need to be cleaned up.
        if config.access_app_id:
            try:
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/access/apps/{config.access_app_id}",
                    api_token,
                )
                deleted_resources.append(f"Access Application (portal): {config.access_app_id}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete Access Application: {e}")

        # Find and delete all Access Apps created by the wizard:
        # - "mcp" type: linked to MCP server via destinations
        # - "mcp_portal" type: linked to portal via domain or destinations
        deleted_app_ids = set()
        if config.access_app_id:
            deleted_app_ids.add(config.access_app_id)
        try:
            apps_data = await self._cf_request(
                "GET",
                f"/accounts/{config.account_id}/access/apps",
                api_token,
            )
            for app in apps_data.get("result", []):
                app_id = app.get("id", "")
                app_type = app.get("type", "")

                # Skip if already deleted above
                if app_id in deleted_app_ids:
                    continue

                should_delete = False

                # Match "mcp" type apps linked to our MCP server
                if app_type == "mcp" and config.mcp_server_id:
                    for dest in app.get("destinations", []):
                        if dest.get("mcp_server_id") == config.mcp_server_id:
                            should_delete = True
                            break

                # Match "mcp_portal" type apps linked to our portal
                if app_type == "mcp_portal":
                    # Match by domain
                    if (
                        config.mcp_portal_hostname
                        and app.get("domain") == config.mcp_portal_hostname
                    ):
                        should_delete = True
                    # Match by name
                    if config.worker_name and config.worker_name in app.get("name", ""):
                        should_delete = True
                    # Match by destinations referencing our MCP server
                    for dest in app.get("destinations", []):
                        if dest.get("mcp_server_id") == config.mcp_server_id:
                            should_delete = True
                            break

                if should_delete:
                    try:
                        await self._cf_request(
                            "DELETE",
                            f"/accounts/{config.account_id}/access/apps/{app_id}",
                            api_token,
                        )
                        deleted_resources.append(f"Access Application ({app_type}): {app_id}")
                        deleted_app_ids.add(app_id)
                    except CloudflareAPIError as e:
                        errors.append(f"Failed to delete {app_type} Access App: {e}")
        except CloudflareAPIError as e:
            errors.append(f"Failed to list Access Apps for cleanup: {e}")

        # Delete MCP Server
        if config.mcp_server_id:
            try:
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/access/ai-controls/mcp/servers/{config.mcp_server_id}",
                    api_token,
                )
                deleted_resources.append(f"MCP Server: {config.mcp_server_id}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete MCP Server: {e}")

        # Delete Worker via REST API
        if config.worker_name:
            try:
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/workers/scripts/{config.worker_name}",
                    api_token,
                )
                deleted_resources.append(f"Worker: {config.worker_name}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete Worker: {e}")

        # Delete KV namespace used for OAuth token storage
        if config.kv_namespace_id:
            try:
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/storage/kv/namespaces/{config.kv_namespace_id}",
                    api_token,
                )
                deleted_resources.append(f"KV Namespace: {config.kv_namespace_id}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete KV namespace: {e}")

        # Delete VPC Service via Connectivity Directory API
        if config.vpc_service_id:
            try:
                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/connectivity/directory/services/{config.vpc_service_id}",
                    api_token,
                )
                deleted_resources.append(f"VPC Service: {config.vpc_service_id}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete VPC Service: {e}")

        # Delete Tunnel (clean up active connections first)
        if config.tunnel_id:
            try:
                # Clean up active connections so the tunnel can be deleted.
                # Without this, deletion fails if cloudflared is/was connected.
                try:
                    await self._cf_request(
                        "DELETE",
                        f"/accounts/{config.account_id}/cfd_tunnel/{config.tunnel_id}/connections",
                        api_token,
                    )
                    logger.info(f"Cleaned up tunnel connections for {config.tunnel_id}")
                except CloudflareAPIError:
                    pass  # Connection cleanup is best-effort

                await self._cf_request(
                    "DELETE",
                    f"/accounts/{config.account_id}/cfd_tunnel/{config.tunnel_id}",
                    api_token,
                )
                deleted_resources.append(f"Tunnel: {config.tunnel_id}")
            except CloudflareAPIError as e:
                errors.append(f"Failed to delete Tunnel: {e}")

        # Delete the configuration from database
        await self.db.delete(config)
        await self.db.flush()
        deleted_resources.append("Local configuration")

        return TeardownResponse(
            success=len(errors) == 0,
            deleted_resources=deleted_resources,
            errors=errors,
            message="Teardown complete" if not errors else "Teardown completed with errors",
        )

    # =========================================================================
    # Get Tunnel Token (for display)
    # =========================================================================

    async def get_tunnel_token(self, config_id: UUID) -> str | None:
        """Get the decrypted tunnel token for display/copy."""
        config = await self.get_config_by_id(config_id)
        if not config:
            return None
        return await self._get_decrypted_tunnel_token(config)
