# Cloudflare Remote Access Setup Wizard

This document describes the automated setup wizard for configuring MCPbox remote access via Cloudflare. The wizard is fully implemented and accessible at `/tunnel/setup`.

## Overview

The wizard will automate the entire remote access setup process, replacing the manual steps in `REMOTE-ACCESS-SETUP.md` with a guided UI experience.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              YOUR LAN (Docker)                                   │
│                                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                     │
│  │   Frontend   │     │   Backend    │     │  PostgreSQL  │                     │
│  │   :3000      │────▶│   :8000      │────▶│   :5432      │                     │
│  │  (React UI)  │     │  /api/*      │     │              │                     │
│  └──────────────┘     └──────────────┘     └──────────────┘                     │
│        │                     │                                                   │
│        │              ┌──────┴───────┐                                          │
│        │              │   Sandbox    │                                          │
│        │              │   :8001      │                                          │
│        │              │ (Python exec)│                                          │
│        │              └──────────────┘                                          │
│        │                     ▲                                                   │
│        ▼                     │                                                   │
│  127.0.0.1 ONLY        ┌─────┴────────┐     ┌──────────────┐                    │
│  (local access)        │ MCP Gateway  │◀────│ cloudflared  │                    │
│                        │   :8002      │     │  (tunnel)    │                    │
│                        │  /mcp ONLY   │     └──────┬───────┘                    │
│                        └──────────────┘            │                            │
│                                                    │ QUIC (UDP 7844)            │
└────────────────────────────────────────────────────┼────────────────────────────┘
                                                     │
                                                     │ Persistent outbound
                                                     │ connection (no inbound
                                                     │ ports needed!)
                                                     │
┌────────────────────────────────────────────────────┼────────────────────────────┐
│                         CLOUDFLARE EDGE                                          │
│                                                    │                             │
│                              ┌─────────────────────┴──────────────────────┐     │
│                              │         Cloudflare Tunnel                   │     │
│                              │    (created via API)                        │     │
│                              │                                             │     │
│                              │  ⚠️  NO PUBLIC HOSTNAME                     │     │
│                              │     Cannot be accessed directly!            │     │
│                              └─────────────────────┬──────────────────────┘     │
│                                                    │                             │
│                                                    │ Workers VPC                 │
│                                                    │ (private binding)           │
│                                                    │                             │
│                              ┌─────────────────────┴──────────────────────┐     │
│                              │           VPC Service                       │     │
│                              │    (created via wrangler)                   │     │
│                              │    Routes to: mcp-gateway:8002             │     │
│                              └─────────────────────┬──────────────────────┘     │
│                                                    │                             │
│                                                    │ env.MCPBOX_TUNNEL.fetch()  │
│                                                    │                             │
│  ┌─────────────────────────────────────────────────┴──────────────────────────┐ │
│  │                    Cloudflare Worker                                        │ │
│  │              (deployed via wrangler)                                        │ │
│  │              wrapped with @cloudflare/workers-oauth-provider               │ │
│  │                                                                             │ │
│  │  Security:                                                                  │ │
│  │  ✓ Path validation (only /mcp, /health allowed)                            │ │
│  │  ✓ OAuth 2.1 (all requests) + JWT (user identity via Cf-Access-Jwt-Assertion) │ │
│  │  ✓ Adds X-MCPbox-Service-Token header                                       │ │
│  │  ✓ Extracts user email from JWT for audit logging                          │ │
│  │  ✓ OAuth-only path: sync-only (no tool execution)                          │ │
│  │  ✓ CORS restricted to claude.ai domains                                     │ │
│  │  ✓ OAuth tokens stored in KV namespace (OAUTH_KV)                          │ │
│  └─────────────────────────────────────────────────┬──────────────────────────┘ │
│                                                    │                             │
│                                                    │ Cf-Access-Jwt-Assertion    │
│                                                    │                             │
│  ┌─────────────────────────────────────────────────┴──────────────────────────┐ │
│  │                   MCP Server Portal                                         │ │
│  │              (created via API)                                              │ │
│  │                                                                             │ │
│  │  Security:                                                                  │ │
│  │  ✓ OAuth 2.1 authentication (Google, GitHub, etc.)                         │ │
│  │  ✓ Issues signed JWT after successful auth                                  │ │
│  │  ✓ Only authenticated users can reach the Worker                           │ │
│  └─────────────────────────────────────────────────┬──────────────────────────┘ │
│                                                    │                             │
└────────────────────────────────────────────────────┼────────────────────────────┘
                                                     │
                                                     │ MCP Protocol (HTTPS)
                                                     │
                                                     ▼
                                              ┌──────────────┐
                                              │  Claude Web  │
                                              │   (User)     │
                                              └──────────────┘
```

## Security at Each Layer

| Layer | Component | Security Mechanism | What It Protects Against |
|-------|-----------|-------------------|--------------------------|
| **1** | Claude Web → MCP Portal | **OAuth 2.1** (Google/GitHub) | Unauthenticated access |
| **2** | MCP Portal → Worker | **Signed JWT** (`Cf-Access-Jwt-Assertion`) | Token forgery |
| **3** | Worker | **OAuth 2.1** (all requests) + **JWT** (user identity) | Direct Worker access bypass |
| **3b** | MCP Gateway | **OAuth-only restriction**: sync-only (no tools/call) | Tool execution via sync path |
| **4** | Worker | **Path validation** (`/mcp`, `/health` only) | Admin API access via tunnel |
| **5** | Worker | **CORS whitelist** (`claude.ai` domains) | Cross-origin abuse |
| **6** | Worker → Tunnel | **Workers VPC** (private binding) | Public tunnel exposure |
| **7** | Tunnel → MCP Gateway | **Service Token** (`X-MCPbox-Service-Token`) | Defense in depth |
| **8** | MCP Gateway | **Token validation** | Requests bypassing Worker |
| **9** | Docker network | **Internal networks** | Container-to-container isolation |
| **10** | Frontend/Backend | **127.0.0.1 binding** | WAN access to admin API |

### Authentication Flow Detail

```
1. User connects Claude Web to MCP Portal URL
2. MCP Portal redirects to OAuth provider (Google/GitHub)
3. User authenticates with identity provider
4. MCP Portal issues signed JWT (Cf-Access-Jwt-Assertion)
5. Cloudflare discovers Worker OAuth endpoints:
   - /.well-known/oauth-authorization-server
   - /.well-known/oauth-protected-resource
6. Cloudflare completes full OAuth 2.1 flow with Worker
7. Worker receives request with valid OAuth 2.1 token
8. For user requests, Worker also verifies Cf-Access-Jwt-Assertion:
   - JWT signature (against Cloudflare JWKS)
   - Audience claim (matches CF_ACCESS_AUD)
   - Issuer claim (matches CF_ACCESS_TEAM_DOMAIN)
   - Expiration (not expired)
9. Worker adds X-MCPbox-Service-Token + user email headers
10. Worker proxies to MCPbox via VPC binding
11. MCPbox validates service token (defense in depth)
12. MCPbox executes tool and returns response
```

**Note:** The MCP Server is configured with `auth_type: "oauth"`. Cloudflare discovers the Worker's OAuth endpoints (via `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`) and completes the full OAuth 2.1 flow. OAuth tokens are stored in a KV namespace (`OAUTH_KV`). User requests additionally carry a `Cf-Access-Jwt-Assertion` header for identity verification.

## Cloudflare API Endpoints

All endpoints require an API token with the following permissions:

| Permission | Level | Purpose |
|------------|-------|---------|
| `Access: Apps and Policies` | Read | Get MCP Portal AUD for JWT verification |
| `Access: Organizations, Identity Providers, and Groups` | Read | Get team domain for JWT verification |
| `Cloudflare Tunnel` | Edit | Create and manage tunnels |
| `Workers Scripts` | Edit | Deploy Worker |
| `Workers KV Storage` | Edit | Create KV namespace for OAuth token storage |
| `Zone (DNS)` | Read | List available domains for MCP Portal |
| `com.cloudflare.api.account.mcp_portals` | Edit | Create MCP Server and Portal |

### MCP Server

Creates a reference to the MCPbox Worker URL.

**Endpoint:** `POST /accounts/{account_id}/access/ai-controls/mcp/servers`

```json
{
  "id": "mcpbox",
  "name": "MCPbox",
  "hostname": "https://mcpbox-proxy.your-account.workers.dev/mcp",
  "auth_type": "oauth",
  "description": "MCPbox MCP Server"
}
```

With `auth_type: "oauth"`, Cloudflare will discover the Worker's OAuth endpoints and complete the full OAuth 2.1 flow to authenticate. No `auth_credentials` field is needed.

**Response:**
```json
{
  "success": true,
  "result": {
    "id": "mcpbox",
    "name": "MCPbox",
    "hostname": "https://mcpbox-proxy.your-account.workers.dev/mcp",
    "auth_type": "oauth",
    "status": "waiting",
    "tools": [],
    "prompts": [],
    "created_at": "2026-01-31T12:00:00Z"
  }
}
```

### MCP Portal

Creates the OAuth-protected portal that users connect to.

**Endpoint:** `POST /accounts/{account_id}/access/ai-controls/mcp/portals`

```json
{
  "id": "mcpbox-portal",
  "name": "MCPbox Portal",
  "hostname": "your-domain.com",
  "description": "MCPbox remote access portal",
  "servers": [
    {
      "server_id": "mcpbox",
      "default_disabled": false,
      "on_behalf": true
    }
  ],
  "secure_web_gateway": false
}
```

**Response:**
```json
{
  "success": true,
  "result": {
    "id": "mcpbox-portal",
    "name": "MCPbox Portal",
    "hostname": "your-domain.com",
    "created_at": "2026-01-31T12:00:00Z"
  }
}
```

### Get MCP Portal Application (for AUD)

After creating the MCP Portal, get its AUD for Worker JWT verification.

**Endpoint:** `GET /accounts/{account_id}/access/apps/{app_id}`

**Response:**
```json
{
  "success": true,
  "result": {
    "id": "b592188e-9780-4848-a671-c2af9912d1a5",
    "uid": "b592188e-9780-4848-a671-c2af9912d1a5",
    "type": "mcp",
    "name": "MCPbox",
    "aud": "8e10972f81919346f325c3c25caf4a715726e5c7ade45e3c0e6750ee84901c32",
    "destinations": [
      {
        "type": "via_mcp_server_portal",
        "mcp_server_id": "mcpbox"
      }
    ],
    "policies": [...]
  }
}
```

The `aud` field is the Application Audience Tag needed for JWT verification in the Worker. Set this as `CF_ACCESS_AUD` in Worker secrets.

**Important Note:** The Cloudflare API requires two separate Access Applications for a working MCP Portal setup:
1. **MCP type** Access App (for the server) - Created in Step 5 with `type: "mcp"` and `destinations: [{type: "via_mcp_server_portal", mcp_server_id: "..."}]`
2. **MCP Portal type** Access App (for the portal) - Created in Step 6 with `type: "mcp_portal"` and `domain` matching the portal hostname

The wizard creates both automatically. The Cloudflare Dashboard also creates both when using the UI.

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

The `auth_domain` is the team domain needed for JWT verification.

### Other Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/accounts/{id}/access/apps` | GET | List Access Applications |
| `/accounts/{id}/access/apps` | POST | Create Access Application |
| `/accounts/{id}/access/apps/{app_id}` | GET | Get Access Application (includes AUD) |
| `/accounts/{id}/access/apps/{app_id}` | PUT | Update Access Application |
| `/accounts/{id}/access/apps/{app_id}` | DELETE | Delete Access Application |
| `/accounts/{id}/access/organizations` | GET | Get organization (team domain) |
| `/accounts/{id}/access/ai-controls/mcp/servers` | GET | List MCP servers |
| `/accounts/{id}/access/ai-controls/mcp/servers/{server_id}` | GET | Get server details |
| `/accounts/{id}/access/ai-controls/mcp/servers/{server_id}` | PUT | Update server |
| `/accounts/{id}/access/ai-controls/mcp/servers/{server_id}` | DELETE | Delete server |
| `/accounts/{id}/access/ai-controls/mcp/servers/{server_id}/sync` | POST | Sync server tools |
| `/accounts/{id}/access/ai-controls/mcp/portals` | GET | List portals |
| `/accounts/{id}/access/ai-controls/mcp/portals/{portal_id}` | GET | Get portal details |
| `/accounts/{id}/access/ai-controls/mcp/portals/{portal_id}` | PUT | Update portal |
| `/accounts/{id}/access/ai-controls/mcp/portals/{portal_id}` | DELETE | Delete portal |

## Wizard Implementation Plan

### UI Flow

```
┌─────────────────────────────────────────────┐
│  Remote Access Setup Wizard                 │
├─────────────────────────────────────────────┤
│ Step 1: Cloudflare API Token               │
│   [Enter API Token]                         │
│   Required permissions:                     │
│   - com.cloudflare.api.account.mcp_portals │
│   - Workers Scripts Write                   │
│   - Workers KV Storage Write                │
│   - Cloudflare Tunnel Edit                  │
│   [Verify Token] ✓                          │
├─────────────────────────────────────────────┤
│ Step 2: Create Tunnel                       │
│   Tunnel Name: [mcpbox-tunnel]              │
│   [Create Tunnel] ✓                         │
│   Token: ●●●●●●●● [copy]                   │
│   ⚠️ Add to .env and restart Docker        │
├─────────────────────────────────────────────┤
│ Step 3: Create VPC Service                  │
│   Service Name: [mcpbox-service]            │
│   Tunnel: mcpbox-tunnel                     │
│   Target: mcp-gateway:8002                  │
│   [Create VPC Service] ✓                    │
├─────────────────────────────────────────────┤
│ Step 4: Deploy Worker                       │
│   Worker Name: [mcpbox-proxy]               │
│   VPC Service ID: auto-filled              │
│   [Deploy Worker] ✓                         │
│   URL: mcpbox-proxy.you.workers.dev         │
├─────────────────────────────────────────────┤
│ Step 5: Create MCP Server                   │
│   Server ID: [mcpbox]                       │
│   Worker URL: auto-filled                   │
│   Auth Type: oauth (auto-configured)        │
│   (OAuth 2.1 endpoints discovered by CF)    │
│   [Create MCP Server] ✓                     │
│   + Creates MCP Access Application          │
│   + Adds Access Policy (Allow Everyone)     │
│   [Sync Tools] ✓ - 19 tools discovered      │
├─────────────────────────────────────────────┤
│ Step 6: Create MCP Portal                   │
│   Portal ID: [mcpbox-portal]                │
│   Portal Domain: [select from zones]        │
│   Portal Subdomain: [mcp]                   │
│   [Create Portal] ✓                         │
│                                             │
│   Portal URL: mcp.yourdomain.com            │
│   AUD: abc123... (auto-created via          │
│         Access Application)                 │
│                                             │
│   Note: Access Application created          │
│   automatically for JWT verification        │
├─────────────────────────────────────────────┤
│ Step 7: Configure Worker JWT Verification   │
│   [Automatic - no user input required]      │
│   ✓ Team Domain fetched from API            │
│   ✓ AUD from Access Application             │
│   ✓ Worker secrets configured via wrangler  │
│                                             │
│   Direct Worker access now returns 401      │
├─────────────────────────────────────────────┤
│ ✅ Setup Complete!                           │
│                                             │
│ Your MCP Portal: https://mcp.yourdomain.com/mcp │
│                                             │
│ Next steps:                                 │
│ 1. Authenticate MCP Server in Cloudflare    │
│    dashboard (triggers tool sync)           │
│ 2. Deploy Worker: ./scripts/deploy-worker.sh│
│ 3. Start tunnel: docker compose --profile   │
│    remote up -d cloudflared                 │
│ 4. Add portal URL to Claude Web settings    │
└─────────────────────────────────────────────┘
```

### Backend API Endpoints

New endpoints needed in MCPbox backend:

```python
# backend/app/api/cloudflare.py

@router.post("/api/cloudflare/verify-token")
async def verify_token(token: str) -> AccountInfo:
    """Verify API token and return account info."""

@router.get("/api/cloudflare/zones")
async def list_zones(token: str) -> list[Zone]:
    """List available domains in the account."""

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

@router.post("/api/cloudflare/mcp-server")
async def create_mcp_server(
    token: str,
    id: str,
    name: str,
    worker_url: str
) -> McpServerInfo:
    """Create an MCP Server pointing to the Worker."""

@router.post("/api/cloudflare/mcp-portal")
async def create_mcp_portal(
    token: str,
    id: str,
    name: str,
    hostname: str,
    server_ids: list[str]
) -> McpPortalInfo:
    """Create an MCP Portal grouping servers."""

@router.get("/api/cloudflare/identity-providers")
async def list_identity_providers(token: str) -> list[IdentityProvider]:
    """List configured identity providers."""
```

### Frontend Components

```
frontend/src/pages/
├── RemoteAccessWizard.tsx      # Main wizard page
└── remote-access/
    ├── Step1Token.tsx          # API token input/verification
    ├── Step2Tunnel.tsx         # Tunnel creation
    ├── Step3VpcService.tsx     # VPC service creation
    ├── Step4Worker.tsx         # Worker deployment
    ├── Step5McpServer.tsx      # MCP server creation
    ├── Step6McpPortal.tsx      # MCP portal creation
    └── WizardComplete.tsx      # Success summary
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

    # MCP Server info
    mcp_server_id = Column(String)

    # MCP Portal info
    mcp_portal_id = Column(String)
    mcp_portal_hostname = Column(String)
    mcp_portal_aud = Column(String)  # Application Audience Tag for JWT verification

    # Access Application ID (created separately from MCP Portal via API)
    access_app_id = Column(String)  # For cleanup during teardown

    # Status
    status = Column(Enum("pending", "active", "error"), default="pending")
    error_message = Column(String)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
```

## Manual Testing Steps

Before implementing the wizard, verify the API flow works:

### 1. Create API Token

Go to Cloudflare Dashboard → My Profile → API Tokens → Create Token

Required permissions:
- Account → Cloudflare Tunnel → Edit
- Account → Workers Scripts → Edit
- Account → Workers KV Storage → Edit
- Account → Access: Apps and Policies → Edit
- Account → Zero Trust → Edit (for MCP portals)

### 2. Test API Endpoints

```bash
# Set variables
export CF_API_TOKEN="your-api-token"
export CF_ACCOUNT_ID="your-account-id"

# Verify token
curl -s "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq .

# List zones (for portal hostname)
curl -s "https://api.cloudflare.com/client/v4/zones" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq '.result[].name'

# Create MCP Server (with OAuth 2.1 auth for sync)
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/ai-controls/mcp/servers" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "mcpbox",
    "name": "MCPbox",
    "hostname": "https://mcpbox-proxy.your-account.workers.dev/mcp",
    "auth_type": "oauth"
  }' | jq .

# Create MCP Portal
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/ai-controls/mcp/portals" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "mcpbox-portal",
    "name": "MCPbox Portal",
    "hostname": "your-domain.com",
    "servers": [{"server_id": "mcpbox"}]
  }' | jq .
```

### 3. Verify Worker Auth

```bash
# Direct Worker access should return 401 (expected - no OAuth token)
curl -s "https://mcpbox-proxy.your-account.workers.dev/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' | jq .
# Expected: {"error":"Unauthorized","details":"Authentication required."}

# Health check should also return 401
curl -s "https://mcpbox-proxy.your-account.workers.dev/health" | jq .
# Expected: {"error":"Unauthorized","details":"Authentication required."}

# Verify Worker secrets are set
cd worker && npx wrangler secret list
# Should show: MCPBOX_SERVICE_TOKEN, CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD
```

### 4. Test Full Flow with Claude Web

1. Deploy Worker with VPC binding and `@cloudflare/workers-oauth-provider` wrapper
2. Create MCP Server pointing to Worker (`auth_type: "oauth"`)
3. Create MCP Portal with the server (includes Access Policy for OAuth)
4. Get AUD from MCP Portal and set `CF_ACCESS_AUD` Worker secret
5. Get team domain and set `CF_ACCESS_TEAM_DOMAIN` Worker secret
6. Redeploy Worker
7. Verify direct Worker access returns 401 (no valid OAuth 2.1 token)
8. **Authenticate MCP Server** in Cloudflare dashboard (triggers OAuth flow + tool sync)
9. Configure identity provider in Zero Trust dashboard (if not already)
10. Add portal URL (`https://mcp.yourdomain.com/mcp`) to Claude Web
11. Complete OAuth authentication
12. Test MCP tools (OAuth-authenticated users with JWT can list + execute)
13. Verify sync still works (OAuth-only, can only list)

## Implementation Status

All phases are complete:

1. **Phase 1: Backend API** - Cloudflare API wrapper endpoints in `backend/app/api/cloudflare.py`
2. **Phase 2: Database** - CloudflareConfig model with full state persistence
3. **Phase 3: Frontend Wizard** - Step-by-step UI at `/tunnel/setup`
4. **Phase 4: Status/Health** - Status displayed on `/tunnel` page
5. **Phase 5: Teardown** - Clean removal of all resources including Access Application

## Notes

- The wizard requires a domain in the Cloudflare account for the MCP Portal hostname
- Identity provider configuration (Google, GitHub, etc.) must still be done in the Zero Trust dashboard
- The tunnel token must be added to `.env` and Docker restarted manually
- Both Access Applications (MCP type and MCP Portal type) are created automatically by the wizard
- Access Policies are added to both Access Applications automatically
- Step 7 (JWT Configuration) is fully automatic - no manual AUD entry required
