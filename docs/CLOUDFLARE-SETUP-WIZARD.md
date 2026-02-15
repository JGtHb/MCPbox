# Cloudflare Remote Access Setup Wizard

This document describes the automated setup wizard for configuring MCPbox remote access via Cloudflare. The wizard is fully implemented and accessible at `/tunnel/setup`.

## Overview

The wizard automates the entire remote access setup process, replacing the manual steps in `REMOTE-ACCESS-SETUP.md` with a guided UI experience. It configures a Cloudflare tunnel, Workers VPC, Worker deployment, and Access for SaaS (OIDC) authentication in 6 steps.

## Architecture

```
+---------------------------------------------------------------------------+
|                              YOUR LAN (Docker)                             |
|                                                                            |
|  +--------------+     +--------------+     +--------------+               |
|  |   Frontend   |     |   Backend    |     |  PostgreSQL  |               |
|  |   :3000      |---->|   :8000      |---->|   :5432      |               |
|  |  (React UI)  |     |  /api/*      |     |              |               |
|  +--------------+     +--------------+     +--------------+               |
|        |                     |                                             |
|        |              +------+-------+                                     |
|        |              |   Sandbox    |                                     |
|        |              |   :8001      |                                     |
|        |              | (Python exec)|                                     |
|        |              +--------------+                                     |
|        |                     ^                                             |
|        v                     |                                             |
|  127.0.0.1 ONLY        +----+----------+     +--------------+             |
|  (local access)         | MCP Gateway  |<----| cloudflared  |             |
|                         |   :8002      |     |  (tunnel)    |             |
|                         |  /mcp ONLY   |     +------+-------+             |
|                         +--------------+            |                     |
|                                                     | QUIC (UDP 7844)     |
+-----------------------------------------------------+---------------------+
                                                      |
                                                      | Persistent outbound
                                                      | connection (no inbound
                                                      | ports needed!)
                                                      |
+-----------------------------------------------------+---------------------+
|                         CLOUDFLARE EDGE                                    |
|                                                     |                      |
|                              +----------------------+--------------------+ |
|                              |         Cloudflare Tunnel                 | |
|                              |    (created via API)                      | |
|                              |                                           | |
|                              |  NO PUBLIC HOSTNAME                       | |
|                              |  Cannot be accessed directly!             | |
|                              +----------------------+--------------------+ |
|                                                     |                      |
|                                                     | Workers VPC          |
|                                                     | (private binding)    |
|                                                     |                      |
|                              +----------------------+--------------------+ |
|                              |           VPC Service                     | |
|                              |    (created via wrangler)                 | |
|                              |    Routes to: mcp-gateway:8002           | |
|                              +----------------------+--------------------+ |
|                                                     |                      |
|                                                     | env.MCPBOX_TUNNEL    |
|                                                     | .fetch()             |
|                                                     |                      |
|  +--------------------------------------------------+--------------------+ |
|  |                    Cloudflare Worker                                   | |
|  |              (deployed via wrangler)                                   | |
|  |              wrapped with @cloudflare/workers-oauth-provider          | |
|  |                                                                       | |
|  |  Security:                                                            | |
|  |  + Path validation (only /mcp, /health allowed)                      | |
|  |  + OAuth 2.1 (all requests require valid token)                      | |
|  |  + OIDC upstream to Cloudflare Access for SaaS (user identity)       | |
|  |  + id_token verification (RS256, iss, aud, nonce, exp, nbf)          | |
|  |  + Adds X-MCPbox-Service-Token header (defense-in-depth)             | |
|  |  + Sets X-MCPbox-User-Email from OIDC-verified id_token              | |
|  |  + Auth method always "oidc"                                         | |
|  |  + CORS restricted to claude.ai domains                              | |
|  |  + OAuth tokens stored in KV namespace (OAUTH_KV)                    | |
|  +--------------------------------------------------+--------------------+ |
|                                                     |                      |
|                                                     | MCP Protocol (HTTPS) |
|                                                     |                      |
+-----------------------------------------------------+----------------------+
                                                      |
                                                      v
                                               +--------------+
                                               |  MCP Clients |
                                               | (Claude Web, |
                                               |  etc.)       |
                                               +--------------+
```

MCP clients connect directly to the Worker URL (e.g., `https://mcpbox-proxy.you.workers.dev/mcp`). No MCP Server or Portal objects are needed.

## Security at Each Layer

| Layer | Component | Security Mechanism | What It Protects Against |
|-------|-----------|-------------------|--------------------------|
| **1** | MCP Client -> Worker | **OAuth 2.1** (all requests require valid token) | Unauthenticated access |
| **2** | Worker -> Cloudflare Access | **OIDC upstream** (Access for SaaS) | Unverified user identity |
| **3** | Worker | **id_token verification** (RS256, JWKS, iss/aud/nonce/exp/nbf) | Token forgery, replay |
| **3b** | MCP Gateway | **Email-based authorization**: no email = sync-only (no tools/call) | Tool execution via sync path |
| **4** | Worker | **Path validation** (`/mcp`, `/health` only) | Admin API access via tunnel |
| **5** | Worker | **CORS whitelist** (`claude.ai` domains) | Cross-origin abuse |
| **6** | Worker -> Tunnel | **Workers VPC** (private binding) | Public tunnel exposure |
| **7** | Tunnel -> MCP Gateway | **Service Token** (`X-MCPbox-Service-Token`) | Defense in depth |
| **8** | MCP Gateway | **Token validation** | Requests bypassing Worker |
| **9** | Docker network | **Internal networks** | Container-to-container isolation |
| **10** | Frontend/Backend | **127.0.0.1 binding** | WAN access to admin API |

### Authentication Flow Detail

```
1. MCP client connects to Worker URL (e.g., https://mcpbox-proxy.you.workers.dev/mcp)
2. Worker returns 401 with OAuth discovery metadata (RFC 9728)
3. MCP client discovers OAuth endpoints and starts authorization
4. Worker redirects to Cloudflare Access OIDC authorize endpoint
5. User authenticates via Cloudflare Access (email OTP, SSO, etc.)
6. Access redirects back to Worker /callback with authorization code
7. Worker exchanges code for id_token + access_token at Access token endpoint
8. Worker verifies id_token:
   - RS256 signature (against Cloudflare JWKS)
   - Audience (matches ACCESS_CLIENT_ID)
   - Issuer (matches team domain)
   - Nonce (matches stored nonce)
   - Expiration (not expired, 60s clock skew)
9. Worker stores verified email in encrypted OAuth token props
10. Worker issues OAuth token to MCP client
11. MCP client sends requests with OAuth token
12. Worker adds X-MCPbox-Service-Token + X-MCPbox-User-Email headers
13. Worker proxies to MCPbox via VPC binding
14. MCPbox validates service token (defense in depth)
15. MCPbox executes tool and returns response
```

## Cloudflare API Endpoints

All endpoints require an API token with the following permissions:

| Permission | Level | Purpose |
|------------|-------|---------|
| `Access: Apps and Policies` | Edit | Create Access for SaaS OIDC application |
| `Access: Organizations, Identity Providers, and Groups` | Read | Get team domain for OIDC URLs |
| `Cloudflare Tunnel` | Edit | Create and manage tunnels |
| `Workers Scripts` | Edit | Deploy Worker |
| `Workers KV Storage` | Edit | Create KV namespace for OAuth token storage |

### Access for SaaS OIDC Application

The wizard creates a SaaS Access Application that acts as the OIDC identity provider for the Worker. This replaces the previous MCP Server/Portal approach.

**Endpoint:** `POST /accounts/{account_id}/access/apps`

```json
{
  "type": "saas",
  "name": "MCPbox OIDC",
  "saas_app": {
    "auth_type": "oidc",
    "redirect_uris": ["https://mcpbox-proxy.you.workers.dev/callback"],
    "grant_types": ["authorization_code"],
    "scopes": ["openid", "email", "profile"],
    "app_launcher_visible": false
  }
}
```

**Response includes:**
```json
{
  "result": {
    "id": "...",
    "saas_app": {
      "client_id": "...",
      "client_secret": "...",
      "public_key": "..."
    }
  }
}
```

The `client_id` and `client_secret` are used as `ACCESS_CLIENT_ID` and `ACCESS_CLIENT_SECRET` Worker secrets.

### Get Zero Trust Organization (for Team Domain)

**Endpoint:** `GET /accounts/{account_id}/access/organizations`

**Response:**
```json
{
  "success": true,
  "result": {
    "auth_domain": "yourteam.cloudflareaccess.com",
    "name": "Your Team",
    ...
  }
}
```

The `auth_domain` is used to derive OIDC endpoint URLs:
```
Token URL:    https://{auth_domain}/cdn-cgi/access/sso/oidc/{client_id}/token
Auth URL:     https://{auth_domain}/cdn-cgi/access/sso/oidc/{client_id}/authorize
JWKS URL:     https://{auth_domain}/cdn-cgi/access/certs
```

### Other Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/accounts/{id}/access/apps` | GET | List Access Applications |
| `/accounts/{id}/access/apps` | POST | Create Access Application |
| `/accounts/{id}/access/apps/{app_id}` | GET | Get Access Application details |
| `/accounts/{id}/access/apps/{app_id}` | PUT | Update Access Application |
| `/accounts/{id}/access/apps/{app_id}` | DELETE | Delete Access Application |
| `/accounts/{id}/access/apps/{app_id}/policies` | POST | Add Access Policy |
| `/accounts/{id}/access/organizations` | GET | Get organization (team domain) |

## Wizard Implementation

### UI Flow (6 Steps)

```
+---------------------------------------------+
|  Remote Access Setup Wizard                 |
+---------------------------------------------+
| Step 1: Cloudflare API Token               |
|   [Enter API Token]                         |
|   Required permissions:                     |
|   - Access: Apps and Policies (Edit)       |
|   - Access: Organizations (Read)           |
|   - Workers Scripts (Edit)                  |
|   - Workers KV Storage (Edit)              |
|   - Cloudflare Tunnel (Edit)               |
|   [Verify Token] +                          |
+---------------------------------------------+
| Step 2: Create Tunnel                       |
|   Tunnel Name: [mcpbox-tunnel]              |
|   [Create Tunnel] +                         |
|   Token: xxxxxxxx [copy]                    |
|   Add to .env and restart Docker            |
+---------------------------------------------+
| Step 3: Create VPC Service                  |
|   Service Name: [mcpbox-service]            |
|   Tunnel: mcpbox-tunnel                     |
|   Target: mcp-gateway:8002                  |
|   [Create VPC Service] +                    |
+---------------------------------------------+
| Step 4: Deploy Worker                       |
|   Worker Name: [mcpbox-proxy]               |
|   VPC Service ID: auto-filled              |
|   [Deploy Worker] +                         |
|   URL: mcpbox-proxy.you.workers.dev         |
|   + Generates service token                 |
|   + Sets MCPBOX_SERVICE_TOKEN secret        |
+---------------------------------------------+
| Step 5: Configure Access (OIDC)            |
|   [Automatic - minimal user input]          |
|   + Creates SaaS OIDC Access Application    |
|   + Fetches team domain for OIDC URLs       |
|   + Generates COOKIE_ENCRYPTION_KEY          |
|   + Sets all Worker secrets:                |
|     - ACCESS_CLIENT_ID                      |
|     - ACCESS_CLIENT_SECRET                  |
|     - ACCESS_TOKEN_URL                      |
|     - ACCESS_AUTHORIZATION_URL              |
|     - ACCESS_JWKS_URL                       |
|     - COOKIE_ENCRYPTION_KEY                 |
|     - MCPBOX_SERVICE_TOKEN (re-synced)      |
|   + Adds Access Policy (Allow Everyone)     |
+---------------------------------------------+
| Step 6: Connect                             |
|   + Setup Complete!                         |
|                                             |
|   Worker URL:                               |
|   https://mcpbox-proxy.you.workers.dev/mcp  |
|                                             |
|   Next steps:                               |
|   1. Start tunnel: docker compose --profile |
|      remote up -d cloudflared               |
|   2. Add Worker URL to Claude Web settings  |
|   3. Complete OIDC authentication           |
+---------------------------------------------+
```

### Backend API Endpoints

Endpoints in `backend/app/api/cloudflare.py`:

```python
@router.post("/api/cloudflare/verify-token")
async def verify_token(token: str) -> AccountInfo:
    """Verify API token and return account info."""

@router.post("/api/cloudflare/tunnel")
async def create_tunnel(token: str, name: str) -> TunnelInfo:
    """Create a new Cloudflare Tunnel."""

@router.post("/api/cloudflare/vpc-service")
async def create_vpc_service(
    token: str,
    name: str,
    tunnel_id: str,
    hostname: str = "mcp-gateway",
    port: int = 8002
) -> VpcServiceInfo:
    """Create a VPC Service for the tunnel."""

@router.post("/api/cloudflare/worker")
async def deploy_worker(
    token: str,
    name: str,
    vpc_service_id: str,
    service_token: str
) -> WorkerInfo:
    """Deploy the MCPbox proxy Worker."""

@router.post("/api/cloudflare/access")
async def configure_access(
    token: str,
    worker_url: str
) -> AccessInfo:
    """Create Access for SaaS OIDC application and set Worker secrets."""
```

### Frontend Components

```
frontend/src/pages/
+-- RemoteAccessWizard.tsx      # Main wizard page
+-- remote-access/
    +-- Step1Token.tsx          # API token input/verification
    +-- Step2Tunnel.tsx         # Tunnel creation
    +-- Step3VpcService.tsx     # VPC service creation
    +-- Step4Worker.tsx         # Worker deployment
    +-- Step5Access.tsx         # Access for SaaS OIDC configuration
    +-- Step6Connect.tsx        # Connection instructions
```

### Database Schema

Store Cloudflare configuration for reconnection/updates:

```python
# backend/app/models/cloudflare_config.py

class CloudflareConfig(Base):
    __tablename__ = "cloudflare_configs"

    id = Column(UUID, primary_key=True)

    # Encrypted API token
    encrypted_api_token = Column(String, nullable=False)

    # Account info
    account_id = Column(String, nullable=False)
    account_name = Column(String)

    # Tunnel info
    tunnel_id = Column(String)
    tunnel_name = Column(String)
    tunnel_token = Column(String)  # Encrypted

    # VPC Service info
    vpc_service_id = Column(String)
    vpc_service_name = Column(String)

    # Worker info
    worker_name = Column(String)
    worker_url = Column(String)

    # Access for SaaS OIDC info
    access_app_id = Column(String)       # SaaS OIDC Access Application ID
    access_client_id = Column(String)    # OIDC client ID
    access_client_secret = Column(String) # Encrypted OIDC client secret

    # Status
    status = Column(Enum("pending", "active", "error"), default="pending")
    error_message = Column(String)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
```

## Manual Testing Steps

Before implementing the wizard, verify the API flow works:

### 1. Create API Token

Go to Cloudflare Dashboard -> My Profile -> API Tokens -> Create Token

Required permissions:
- Account -> Cloudflare Tunnel -> Edit
- Account -> Workers Scripts -> Edit
- Account -> Workers KV Storage -> Edit
- Account -> Access: Apps and Policies -> Edit
- Account -> Access: Organizations, Identity Providers, and Groups -> Read

### 2. Test API Endpoints

```bash
# Set variables
export CF_API_TOKEN="your-api-token"
export CF_ACCOUNT_ID="your-account-id"

# Verify token
curl -s "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq .

# Get team domain
curl -s "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/organizations" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq '.result.auth_domain'

# Create SaaS OIDC Access Application
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "saas",
    "name": "MCPbox OIDC",
    "saas_app": {
      "auth_type": "oidc",
      "redirect_uris": ["https://mcpbox-proxy.your-account.workers.dev/callback"],
      "grant_types": ["authorization_code"],
      "scopes": ["openid", "email", "profile"],
      "app_launcher_visible": false
    }
  }' | jq .
```

### 3. Verify Worker Auth

```bash
# Direct Worker access should return 401 (expected - no OAuth token)
curl -s "https://mcpbox-proxy.your-account.workers.dev/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' | jq .
# Expected: 401 Unauthorized

# Health check is public (returns 200)
curl -s "https://mcpbox-proxy.your-account.workers.dev/health" | jq .
# Expected: {"status":"ok"}

# Verify Worker secrets are set
cd worker && npx wrangler secret list
# Should show: MCPBOX_SERVICE_TOKEN, ACCESS_CLIENT_ID, ACCESS_CLIENT_SECRET,
# ACCESS_TOKEN_URL, ACCESS_AUTHORIZATION_URL, ACCESS_JWKS_URL, COOKIE_ENCRYPTION_KEY
```

### 4. Test Full Flow with Claude Web

1. Deploy Worker with VPC binding and `@cloudflare/workers-oauth-provider` wrapper
2. Create Access for SaaS OIDC application with Worker callback URL
3. Set all OIDC Worker secrets (ACCESS_CLIENT_ID, etc.)
4. Redeploy Worker
5. Verify direct Worker access returns 401 (no valid OAuth 2.1 token)
6. Configure identity provider in Zero Trust dashboard (if not already)
7. Add Worker URL (`https://mcpbox-proxy.your-account.workers.dev/mcp`) to Claude Web
8. Complete OIDC authentication (redirected to Cloudflare Access)
9. Test MCP tools (OIDC-authenticated users can list + execute)
10. Verify sync still works (OAuth-only, can only list)

## Worker Secrets Reference

| Secret | Set at Step | Source |
|--------|------------|--------|
| `MCPBOX_SERVICE_TOKEN` | Step 4 (deploy Worker), re-synced at step 5 | Generated in `deploy_worker()` |
| `ACCESS_CLIENT_ID` | Step 5 (configure access) | From SaaS OIDC app (created in step 5) |
| `ACCESS_CLIENT_SECRET` | Step 5 (configure access) | From SaaS OIDC app (created in step 5) |
| `ACCESS_TOKEN_URL` | Step 5 (configure access) | Derived from team_domain + client_id |
| `ACCESS_AUTHORIZATION_URL` | Step 5 (configure access) | Derived from team_domain + client_id |
| `ACCESS_JWKS_URL` | Step 5 (configure access) | Derived from team_domain |
| `COOKIE_ENCRYPTION_KEY` | Step 5 (configure access) | Generated (32-byte hex) |

Step 5 creates the SaaS OIDC Access Application, stores the credentials, and syncs all secrets to the Worker in a single operation. The deploy script (`scripts/deploy-worker.sh --set-secrets`) can also push them for re-deployment after code changes.

**Important:** After the wizard regenerates a service token (e.g., re-running setup), you must either re-run step 5 or run `deploy-worker.sh --set-secrets` to sync the new token to the Worker.

## Implementation Status

All phases are complete:

1. **Phase 1: Backend API** - Cloudflare API wrapper endpoints in `backend/app/api/cloudflare.py`
2. **Phase 2: Database** - CloudflareConfig model with full state persistence
3. **Phase 3: Frontend Wizard** - 6-step UI at `/tunnel/setup`
4. **Phase 4: Status/Health** - Status displayed on `/tunnel` page
5. **Phase 5: Teardown** - Clean removal of all resources including Access Application

## Notes

- Identity provider configuration (Google, GitHub, etc.) must still be done in the Zero Trust dashboard
- The tunnel token must be added to `.env` and Docker restarted manually
- The Access for SaaS OIDC application and Access Policy are created automatically by the wizard
- Step 5 (Configure Access) is fully automatic -- creates the OIDC app, derives URLs, and syncs all secrets
- MCP clients connect directly to the Worker URL -- no MCP Server or Portal objects are needed
