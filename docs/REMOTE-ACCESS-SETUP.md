# Remote Access Setup (Claude Web via Cloudflare)

This guide explains how to expose your MCPbox instance to Claude Web using Cloudflare Workers VPC. The tunnel has **no public hostname** - it's only accessible via your Worker.

> **Recommended:** Use the [Setup Wizard](/tunnel/setup) for automated configuration. This manual guide is provided for reference and troubleshooting. See [CLOUDFLARE-SETUP-WIZARD.md](./CLOUDFLARE-SETUP-WIZARD.md) for wizard documentation.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Your Network                                    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        MCPbox (Docker)                                │   │
│  │                                                                       │   │
│  │   ┌──────────────┐     ┌──────────────────┐                          │   │
│  │   │ MCP Gateway  │◄────┤  cloudflared     │◄─── Private tunnel       │   │
│  │   │ :8002        │     │  (tunnel agent)  │     (no public hostname) │   │
│  │   └──────────────┘     └──────────────────┘                          │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        │ Workers VPC (private)
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                            Cloudflare                                        │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Cloudflare Worker                                  │   │
│  │                 (mcpbox-proxy.you.workers.dev)                        │   │
│  │                                                                       │   │
│  │  - @cloudflare/workers-oauth-provider wrapper                       │   │
│  │  - OAuth 2.1 (all requests) + JWT (user identity)                   │   │
│  │  - Accesses tunnel via Workers VPC binding (private)                 │   │
│  │  - Adds X-MCPbox-Service-Token header                                │   │
│  │  - Extracts user email for audit logging (JWT path)                  │   │
│  │  - OAuth-only: sync-only (no tool execution)                         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                        ▲                                     │
│                                        │ OAuth 2.1                           │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                   MCP Server Portal                                   │   │
│  │              (Cloudflare Zero Trust)                                  │   │
│  │                                                                       │   │
│  │  - Handles OAuth with users (Google, GitHub, etc.)                   │   │
│  │  - Issues Cf-Access-Jwt-Assertion to Worker                          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                        ▲                                     │
└────────────────────────────────────────┼────────────────────────────────────┘
                                         │
                                         │ MCP Protocol
                                         │
                                    Claude Web
```

## Security Model

MCPbox uses a **defense-in-depth** architecture with multiple security layers.

### Security Layers (11 Total)

| Layer | Component | Security Mechanism | What It Protects Against |
|-------|-----------|-------------------|--------------------------|
| **1** | Claude Web → MCP Portal | OAuth 2.1 (Google/GitHub/SAML) | Unauthenticated access |
| **2** | MCP Portal → Worker | Signed JWT (`Cf-Access-Jwt-Assertion`) | Token forgery, replay attacks |
| **3** | Worker | OAuth 2.1 token verification (all requests) | Unauthenticated access |
| **3b** | Worker | JWT verification (user identity, when present) | Direct Worker URL access bypass |
| **4** | Worker | Path validation (`/mcp`, `/health` only) | Admin API access via tunnel |
| **5** | Worker | CORS whitelist (`claude.ai` domains) | Cross-origin request abuse |
| **6** | Worker → Tunnel | Workers VPC (private binding) | Public tunnel exposure |
| **7** | Tunnel → MCP Gateway | Service Token header | Defense in depth |
| **8** | MCP Gateway | Token validation | Requests bypassing Worker |
| **8b** | MCP Gateway | OAuth-only auth method restriction | Tool execution via sync path |
| **9** | Docker network | Internal bridge networks | Container-to-container isolation |
| **10** | Frontend/Backend | 127.0.0.1 binding | WAN access to admin API |

### Worker Auth Model

| Request source | Auth | Worker validates | Allowed operations |
|---|---|---|---|
| User via MCP Portal | OAuth 2.1 token + `Cf-Access-Jwt-Assertion` | OAuth token + JWT (RS256, JWKS, audience/issuer) | All (list + execute) |
| Cloudflare sync | OAuth 2.1 token (no JWT) | OAuth token valid | Sync only (list, initialize) |
| Random internet | No valid OAuth token | Rejected 403 | None |

### Attack Surface Analysis

**Publicly Accessible:**
- Worker URL (`mcpbox-proxy.*.workers.dev`) - Protected by OAuth 2.1 (all requests). Unauthenticated requests rejected with 403.
- MCP Portal URL (`mcp.yourdomain.com`) - Protected by Cloudflare Access OAuth

**NOT Publicly Accessible:**
- Tunnel endpoint - No public hostname, only reachable via Workers VPC binding
- MCPbox admin API (`:8000`) - Bound to 127.0.0.1
- MCPbox frontend (`:3000`) - Bound to 127.0.0.1
- MCP Gateway (`:8002`) - Only reachable via tunnel
- Sandbox (`:8001`) - Internal Docker network only
- PostgreSQL (`:5432`) - Internal Docker network only

### JWT Verification Details

The Worker performs cryptographic JWT verification per [RFC 8725 (JWT Best Current Practices)](https://datatracker.ietf.org/doc/html/rfc8725):

1. **Algorithm Validation** - Explicitly requires RS256; rejects all other algorithms (prevents algorithm confusion attacks)
2. **Signature Verification** - Fetches public keys from JWKS endpoint with 5-minute caching
3. **Audience Claim** - Must match the MCP Portal's Application Audience Tag
4. **Issuer Claim** - Must match `https://{team}.cloudflareaccess.com`
5. **Subject Claim** - Token must have a valid `sub` claim (user identity)
6. **Expiration** - Token must not be expired (`exp` claim), with 60-second clock skew tolerance
7. **Not Before** - Token must be valid (`nbf` claim), with 60-second clock skew tolerance
8. **Issued At** - Token must not be issued in the future (`iat` claim)

**Clock Skew Tolerance:** A 60-second tolerance is applied to time-based claims (`exp`, `nbf`, `iat`) to handle clock drift between distributed systems. This is standard practice for JWT validation in distributed environments.

**JWKS Caching:** Public keys are cached for 5 minutes to reduce latency. If a key ID (`kid`) is not found in cache, a fresh fetch is attempted to handle Cloudflare's 6-week key rotation.

**If any verification fails**, the Worker returns 401 Unauthorized.

### Known Limitations & Considerations

1. **Worker URL is technically public** - Anyone can send requests to the Worker URL, but without a valid OAuth 2.1 token (all requests) and JWT (user identity), requests are rejected. OAuth-only requests (no JWT) are restricted to sync operations (tool discovery), never tool execution.

2. **Service Token is defense-in-depth** - The `X-MCPbox-Service-Token` header is validated by MCPbox even though the tunnel is already private. This protects against potential VPC binding misconfigurations. Service token failures return 403 Forbidden.

3. **CORS provides zero protection against non-browser attackers** - CORS headers are set to `claude.ai` domains. However:
   - CORS is purely a browser-enforced policy, not a server-side security control
   - Any non-browser client (`curl`, Python scripts, custom tools) can freely ignore CORS headers
   - When an attacker runs `curl -X POST https://your-worker.workers.dev/mcp`, CORS has no effect
   - The actual security boundary is OAuth 2.1 verification - without a valid OAuth token, all requests are rejected
   - CORS should be considered defense-in-depth against browser-based XSS exploitation only

4. **JWT key rotation** - Cloudflare rotates signing keys every 6 weeks. The Worker caches JWKS for 5 minutes and automatically refreshes when an unknown key ID is encountered.

### Threat Model

| Threat | Mitigation | Residual Risk |
|--------|------------|---------------|
| Unauthenticated access | OAuth 2.1 via MCP Portal + Worker OAuth verification | Depends on IdP security |
| JWT forgery | RSA-SHA256 signature verification | None (cryptographically secure) |
| JWT replay | Expiration checking | Short window before expiry |
| Direct Worker access | OAuth 2.1 required (all requests), returns 403 | None |
| OAuth-only tool execution | Gateway blocks tools/call for OAuth-only auth | None |
| Direct tunnel access | No public hostname, VPC binding | None |
| Admin API access via tunnel | Path validation in Worker | None |
| SSRF via tunnel | Path validation, VPC isolation | None |
| Service token brute force | 256-bit entropy (64 hex chars) | Computationally infeasible |

### Security Guarantees

This architecture provides:
- **Authentication** - Users must authenticate via OAuth
- **Authorization** - Access policies control who can connect
- **Confidentiality** - All traffic is TLS-encrypted
- **Integrity** - JWT signatures prevent tampering
- **Audit logging** - User email extracted from JWT for logs
- **Network isolation** - Tunnel has no public attack surface

## Prerequisites

- A Cloudflare account (Workers VPC may require a paid plan)
- MCPbox running locally
- `cloudflared` version **2025.7.0 or later**
- Wrangler CLI installed (`npm install -g wrangler`)

## Step 1: Create Cloudflare Tunnel (Private - No Public Hostname)

1. Install cloudflared (version 2025.7.0+):
   ```bash
   # macOS
   brew install cloudflared

   # Or download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
   ```

2. Authenticate with Cloudflare:
   ```bash
   cloudflared tunnel login
   ```

3. Create a tunnel (without a public hostname):
   ```bash
   cloudflared tunnel create mcpbox
   ```

   Note the **Tunnel ID** from the output (e.g., `a1b2c3d4-e5f6-...`)

4. Get the tunnel token for Docker:
   ```bash
   cloudflared tunnel token mcpbox
   ```

   The token is stored in the database when you use the setup wizard.
   If setting up manually, add the token via the Tunnel Configurations UI page.

5. Start the tunnel with Docker:
   ```bash
   docker compose --profile remote up -d
   ```

**Important**: Do NOT configure a public hostname for this tunnel. It will only be accessible via Workers VPC.

## Step 2: Create Workers VPC Service

Create a VPC Service that connects your Worker to the tunnel:

```bash
npx wrangler vpc service create mcpbox-service \
  --type http \
  --tunnel-id <YOUR_TUNNEL_ID> \
  --hostname mcp-gateway \
  --http-port 8002
```

Note the **Service ID** from the output.

## Step 3: Configure and Deploy the Worker

The deploy script fetches configuration from the backend database and generates
`wrangler.toml` automatically. No manual configuration needed.

1. Install Worker dependencies:
   ```bash
   cd worker && npm install && cd ..
   ```

2. Deploy with the automated script:
   ```bash
   ./scripts/deploy-worker.sh --set-secrets
   ```

   This will:
   - Fetch the active VPC service ID from the backend
   - Generate `worker/wrangler.toml` with the correct binding
   - Deploy the Worker via `wrangler deploy`
   - Set `MCPBOX_SERVICE_TOKEN`, `CF_ACCESS_TEAM_DOMAIN`, and `CF_ACCESS_AUD` secrets

   The service token is fetched from the database (generated by the wizard) and
   pushed to the Worker automatically — no manual token management needed.

   Note your Worker URL (e.g., `https://mcpbox-proxy.yourname.workers.dev`)

## Step 4: Create MCP Server Portal

The MCP Server Portal handles OAuth authentication with users and issues JWTs that your Worker will verify.

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to **Access** → **AI Controls** → **MCP Servers**
3. Click **Add an MCP server**:
   - **Name**: MCPbox
   - **Server ID**: `mcpbox` (or your preferred ID)
   - **HTTP URL**: Your Worker URL (e.g., `https://mcpbox-proxy.yourname.workers.dev/mcp`)
   - **Authentication**: The wizard configures `auth_type: "oauth"` automatically. Cloudflare discovers the OAuth endpoints from the Worker's `@cloudflare/workers-oauth-provider` wrapper — no manual credentials needed.
4. Click **Save** and then **Sync** to discover available tools
5. Go to **MCP Portals** tab and click **Add MCP server portal**:
   - **Name**: MCPbox Portal
   - **Portal ID**: `mcpbox-portal`
   - **Domain**: Select a domain from your Cloudflare zones
   - **Subdomain**: `mcp` (creates `mcp.yourdomain.com`)
   - **MCP Servers**: Select your MCPbox server
6. Configure an **Access Policy** to control who can use the portal:
   - **Policy name**: Allow authenticated users
   - **Action**: Allow
   - **Include**: Configure who can access (e.g., specific emails or email domains)
7. Click **Save**
8. Note the **Application Audience (AUD) Tag** from the application overview

## Step 5: Configure Worker JWT Verification

Now configure the Worker to verify JWTs from the MCP Server Portal. This ensures only authenticated requests from the Portal can reach your MCPbox instance.

```bash
cd worker

# Set your team domain (find in Zero Trust Dashboard → Settings → Custom Pages)
# Example: "yourteam.cloudflareaccess.com"
wrangler secret put CF_ACCESS_TEAM_DOMAIN

# Set the AUD from the MCP Portal application (Access → Applications → Your Portal → Overview)
wrangler secret put CF_ACCESS_AUD

# Redeploy to apply changes
wrangler deploy
```

After this configuration:
- Direct access to the Worker URL will return **401 Unauthorized**
- Only requests with valid JWTs from the MCP Portal will be accepted
- User emails are extracted from the JWT for audit logging

## Step 6: Authenticate MCP Server

After setup is complete, you need to trigger the initial authentication so Cloudflare can discover and sync your MCP tools.

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to **Access** → **AI Controls** → **MCP Servers**
3. Click on your MCPbox server
4. On the **Overview** tab, click **Authenticate**
5. This triggers Cloudflare to complete the OAuth 2.1 flow with your Worker and sync tools
6. After a few seconds, your tools should appear under the server listing

If the sync fails, verify that the tunnel is running (`docker compose --profile remote logs cloudflared`) and the Worker is deployed.

## Step 7: Connect Claude Web

1. In Claude Web, go to **Settings** → **Integrations** → **MCP Servers**
2. Click **Add Server** and enter your MCP Portal URL **with `/mcp` path** (e.g., `https://mcp.yourdomain.com/mcp`)
3. Complete OAuth authentication with your identity provider (Google, GitHub, etc.)
4. Your MCPbox tools should now appear in Claude's tool list

**Note:** The URL must include `/mcp` — entering just the domain without the path will return a 404.

## Verification

```bash
# Direct Worker access should be BLOCKED (returns 401/403)
curl -s https://mcpbox-proxy.yourname.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
# Expected: {"error":"Unauthorized","details":"Authentication required."}

# Health check should also be BLOCKED (returns 401/403)
curl -s https://mcpbox-proxy.yourname.workers.dev/health
# Expected: {"error":"Unauthorized","details":"Authentication required."}

# The tunnel has no public URL - there's nothing to curl directly!
# Only the Worker (via VPC) can reach the tunnel.

# Check tunnel is running
docker compose --profile remote logs cloudflared

# Check MCP gateway is healthy
docker compose logs mcp-gateway | tail -20
```

## Troubleshooting

### "Failed to connect to MCPbox"

- Check that the tunnel is running: `docker compose --profile remote logs cloudflared`
- Verify cloudflared version is 2025.7.0+: `cloudflared --version`
- Re-run the deploy script to update the VPC binding: `./scripts/deploy-worker.sh`

### "MCPBOX_TUNNEL VPC binding not configured"

- Re-run `./scripts/deploy-worker.sh` to regenerate `wrangler.toml` with the correct VPC service ID and redeploy

### "Invalid service token"

- Re-run `./scripts/deploy-worker.sh --set-secrets` to sync the token from the database to the Worker
- The token is generated by the wizard and stored in the database — the deploy script pushes it to the Worker
- Service token failures return 403 Forbidden

### "401 Unauthorized" when accessing Worker directly

This is **expected behavior**. The Worker requires a valid OAuth 2.1 token for all requests. User requests additionally carry a JWT from the MCP Portal for identity. Unauthenticated requests are always rejected.

To verify auth is working:
```bash
# This should return 401/403 (expected - no OAuth token)
curl -s https://mcpbox-proxy.yourname.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
# Expected: {"error":"Unauthorized","details":"Authentication required."}
```

### "McpAuthorizationError: Your account was authorized but the integration rejected the credentials"

This is usually caused by **Cloudflare AI Crawl Control** blocking claude.ai's requests. If you have AI Crawl Control enabled on your zone, disable it: Cloudflare Dashboard → your zone → **Security** → **Bots** → **AI Crawlers** → Disable. Most accounts won't have this enabled by default.

### "401 Unauthorized" in Claude Web

- Verify the MCP Server Portal URL is correct in Claude settings (must include `/mcp` path)
- Try disconnecting and reconnecting the MCP server in Claude
- Check that you've completed OAuth with your identity provider
- Verify the Worker URL in the MCP Server configuration matches your deployed Worker

### "Invalid or expired JWT token"

- Check that `CF_ACCESS_TEAM_DOMAIN` matches your Zero Trust team domain
- Verify `CF_ACCESS_AUD` matches the Application Audience Tag from the MCP Portal
- The JWT may have expired - try reconnecting in Claude

### Checking Service Status

```bash
# Check tunnel status
docker compose --profile remote logs cloudflared

# Check MCP gateway status
docker compose logs mcp-gateway

# List VPC services
npx wrangler vpc service list

# List Worker secrets (to verify they're set)
cd worker && npx wrangler secret list
```

## Environment Variables Reference

| Variable | Location | Description |
|----------|----------|-------------|
| Service Token | Database | Generated by wizard, loaded at startup by MCPbox, pushed to Worker by deploy script |
| Tunnel Token | Database | Managed via UI wizard, fetched by cloudflared at startup |
| `MCPBOX_SERVICE_TOKEN` | Worker secret | Set automatically by `./scripts/deploy-worker.sh --set-secrets` |
| `CF_ACCESS_TEAM_DOMAIN` | Worker secret | Your Zero Trust team domain (e.g., `yourteam.cloudflareaccess.com`) |
| `CF_ACCESS_AUD` | Worker secret | Application Audience (AUD) Tag from MCP Portal |

### Finding Your Team Domain

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to **Settings** → **Custom Pages**
3. Your team domain is shown at the top (e.g., `yourteam.cloudflareaccess.com`)

### Finding the Application AUD

1. Go to **Access** → **Applications**
2. Click on your MCP Portal application
3. The **Application Audience (AUD) Tag** is shown in the Overview section

## Local vs Remote Mode

| Mode | Service Token | Tunnel | Use Case |
|------|---------------|--------|----------|
| **Local** | Not in database | Not needed | Claude Desktop only |
| **Remote** | Generated by wizard, stored in DB | Required (private) | Claude Web + Desktop |

When a service token exists in the database (created by the wizard), MCPbox requires the `X-MCPbox-Service-Token` header on all MCP requests. The Worker adds this header automatically. For Claude Desktop in remote mode, you'd need to configure it to include this header.

## Authentication Flow

Understanding how authentication works helps with troubleshooting:

```
┌─────────────┐    ┌─────────────────┐    ┌────────────────┐    ┌─────────────┐
│ Claude Web  │───►│ MCP Portal      │───►│ Worker         │───►│ MCPbox      │
│             │    │ (OAuth + JWT)   │    │ (OAuth verify) │    │ (token)     │
└─────────────┘    └─────────────────┘    └────────────────┘    └─────────────┘
      │                    │                      │                    │
      │ 1. Connect         │                      │                    │
      ├───────────────────►│                      │                    │
      │                    │                      │                    │
      │ 2. OAuth redirect  │                      │                    │
      │◄───────────────────┤                      │                    │
      │                    │                      │                    │
      │ 3. User logs in    │                      │                    │
      ├───────────────────►│                      │                    │
      │                    │                      │                    │
      │ 4. MCP request + OAuth token + JWT        │                    │
      │◄──────────────────►├─────────────────────►│                    │
      │                    │                      │                    │
      │                    │ 5. Verify OAuth      │                    │
      │                    │    + verify JWT      │                    │
      │                    │    (signature, aud,  │                    │
      │                    │     issuer, expiry)  │                    │
      │                    │                      │                    │
      │                    │ 6. Add service token │                    │
      │                    │    + user email      ├───────────────────►│
      │                    │                      │                    │
      │                    │                      │ 7. Validate token  │
      │                    │                      │    Execute tool    │
      │                    │                      │◄───────────────────┤
      │                    │                      │                    │
      │ 8. Response        │◄─────────────────────┤                    │
      │◄───────────────────┤                      │                    │
```

**Security layers:**
1. **MCP Portal OAuth** - User authenticates with Google/GitHub/etc.
2. **Worker OAuth 2.1** - Worker verifies OAuth 2.1 token (all requests) + JWT for user identity (when present)
3. **Sync Restriction** - OAuth-only requests (no JWT) can only list tools, not execute them
4. **Service Token** - MCPbox validates the shared secret (defense in depth)
5. **Private Tunnel** - VPC binding ensures only the Worker can reach MCPbox

## Why Workers VPC?

Unlike a traditional public tunnel setup where you'd need Cloudflare Access to protect a public hostname, Workers VPC creates a **truly private** connection:

- No public DNS entry for your tunnel
- No attack surface for hostname discovery
- No need for Access policies on the tunnel itself
- The tunnel literally cannot be reached except through your Worker

## MCP Server Authentication

The MCP Server is created with `auth_type: "oauth"`. The Worker is wrapped with `@cloudflare/workers-oauth-provider`, which exposes standard OAuth 2.1 discovery endpoints. This means:
- **Cloudflare discovers** the OAuth endpoints automatically and completes the full OAuth flow when syncing tools
- **All /mcp requests require** a valid OAuth 2.1 token
- **OAuth-only requests are sync-only** - they can list tools and initialize, but cannot execute tools

User requests additionally carry a JWT for identity:
- **MCP Portal** handles user OAuth (users log in here)
- **Worker** verifies the JWT from the Portal (presence of JWT grants full access including tool execution)
- **MCPbox** validates the service token (defense-in-depth)

## Worker Security Implementation

The Worker (`worker/src/index.ts`) implements the following security controls:

### Path Validation
```typescript
const ALLOWED_PATH_PREFIXES = ['/mcp', '/health'];

function isPathAllowed(path: string): boolean {
  return ALLOWED_PATH_PREFIXES.some(prefix =>
    path === prefix || path.startsWith(prefix + '/')
  );
}
```
Only `/mcp` and `/health` paths are proxied. All other paths (including `/api/*`) return 404.

### JWT Verification
The Worker verifies JWTs using Cloudflare's JWKS endpoint:

1. Extracts `kid` (key ID) from JWT header
2. Fetches public keys from `https://{team}.cloudflareaccess.com/cdn-cgi/access/certs`
3. Imports RSA public key using Web Crypto API
4. Verifies signature using `crypto.subtle.verify('RSASSA-PKCS1-v1_5', ...)`
5. Validates `aud`, `iss`, `exp`, and `nbf` claims

### CORS Configuration
```typescript
const allowedOrigins = [
  'https://mcp.claude.ai',
  'https://claude.ai',
];
```
CORS headers restrict browser-based access to Claude domains only.

### Headers Added to Backend Requests
```typescript
headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
headers.set('X-Forwarded-Host', url.host);
headers.set('X-Forwarded-Proto', 'https');
headers.set('X-MCPbox-User-Email', userEmail);    // From verified JWT (if present)
headers.set('X-MCPbox-Auth-Method', authMethod);   // 'jwt' or 'oauth'
```

The `X-MCPbox-Auth-Method` header is stripped from client requests (defense-in-depth) and set by the Worker based on the verified auth path. The MCP Gateway uses this to restrict OAuth-only requests (no JWT) to sync-only operations.

### Configuration (Worker Secrets)

| Secret | Required | Purpose |
|--------|----------|---------|
| `MCPBOX_SERVICE_TOKEN` | Yes | Shared secret with MCPbox backend (defense-in-depth) |
| `CF_ACCESS_TEAM_DOMAIN` | Yes* | Team domain for JWT verification |
| `CF_ACCESS_AUD` | Yes* | Application audience for JWT verification |

*If `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` are not set, JWT verification cannot be performed. Requests with a `Cf-Access-Jwt-Assertion` header but missing config will be rejected with 401. OAuth 2.1 auth still works for Cloudflare sync.

## Alternative Architectures Considered

### Access for SaaS (Not Used)
Cloudflare documents an alternative approach using `workers-oauth-provider` without the MCP Portal. While we now use `@cloudflare/workers-oauth-provider` to wrap the Worker for OAuth 2.1 compliance, we still rely on the MCP Portal for user-facing OAuth and JWT issuance. This hybrid approach gives us:
- OAuth 2.1 compliance for Cloudflare's MCP Server sync
- User identity via MCP Portal JWTs
- Simpler user management through Cloudflare Access policies

### Self-Hosted Access Application (Not Used)
We initially considered creating a `self_hosted` Access Application to protect the Worker URL. However:
- This added a redirect-based login flow that broke API access
- The MCP Portal already provides OAuth and issues JWTs
- The Portal's JWT is sufficient for Worker authentication

## Cloudflare Components Summary

| Component | Type | Purpose |
|-----------|------|---------|
| **Tunnel** | `cloudflared` | Outbound connection from your network to Cloudflare |
| **VPC Service** | Workers VPC | Private binding between Worker and Tunnel |
| **Worker** | Cloudflare Worker | OAuth 2.1 provider + proxy with JWT verification |
| **MCP Server** | AI Controls | Metadata registration (URL, name, tools) with `auth_type: "oauth"` |
| **MCP Portal** | AI Controls | OAuth gateway, issues JWTs, user-facing URL |
| **Access Application** | Zero Trust | Backs the MCP Portal, contains AUD |

**Note on Access Application creation:**
- When using the **Cloudflare Dashboard** to create MCP Portals, an Access Application is automatically created
- When using the **API** (as the setup wizard does), you must create a `self_hosted` Access Application separately to get the AUD for JWT verification
- The setup wizard handles this automatically by creating the Access Application during portal creation

## Current Deployment Reference

For auditing purposes, here are the current Cloudflare resource IDs:

### Worker Configuration

`worker/wrangler.toml` is generated by `./scripts/deploy-worker.sh` — it fetches the VPC service ID from the backend database so it's always in sync with the wizard configuration.

### Worker Secrets (set via `wrangler secret put`)
- `MCPBOX_SERVICE_TOKEN` - 64-character hex string
- `CF_ACCESS_TEAM_DOMAIN` - e.g., `yourteam.cloudflareaccess.com`
- `CF_ACCESS_AUD` - 64-character hex string (from MCP Portal)

### MCPbox Configuration

All remote access tokens are stored in the database (managed by the setup wizard):
- **Service token**: Generated by wizard step 4, loaded at startup by `ServiceTokenCache`
- **Tunnel token**: Generated by wizard step 1, fetched by cloudflared at startup

### Docker Compose Profile
```bash
# Start with remote access enabled
docker compose --profile remote up -d

# This starts the cloudflared container which:
# - Connects to Cloudflare via QUIC (UDP 7844)
# - Routes traffic to mcp-gateway:8002
# - Uses the tunnel token for authentication
```

## Service Token Rotation

The service token should be rotated periodically for security best practices.

### Rotation Procedure

**Recommended frequency:** Every 30-90 days

The easiest way to rotate the service token is to re-run the Worker deployment step
of the setup wizard, which generates a new token:

1. **Re-run the wizard's Worker deployment step** (re-deploys Worker with a new token)
2. **Run the deploy script** to push the new token to the Worker:
   ```bash
   ./scripts/deploy-worker.sh --set-secrets
   ```
3. **Restart MCPbox** to reload the new token from the database:
   ```bash
   docker compose --profile remote restart backend mcp-gateway
   ```
4. **Verify connectivity:**
   ```bash
   # Direct access should still return 401/403 (expected - no OAuth token)
   curl -s https://your-worker.workers.dev/mcp
   # Should return: {"error":"Unauthorized",...}

   # Test via Claude Web to verify end-to-end
   ```

## Security Checklist for Production

Before deploying to production, verify:

- [ ] Setup wizard completed (service token generated and stored in database)
- [ ] Tunnel configuration is active in the MCPbox UI (token stored in database)
- [ ] `./scripts/deploy-worker.sh --set-secrets` run (syncs token to Worker)
- [ ] Worker secret `CF_ACCESS_TEAM_DOMAIN` is set
- [ ] Worker secret `CF_ACCESS_AUD` matches MCP Portal's AUD
- [ ] MCP Portal has appropriate Access Policy (restrict by email/domain)
- [ ] Identity provider is configured in Zero Trust dashboard
- [ ] Tunnel has NO public hostname configured
- [ ] Direct Worker access returns 401/403: `curl https://your-worker.workers.dev/health`
- [ ] MCP Server created with `auth_type: oauth` (not `unauthenticated`)
- [ ] MCP Server authenticated in Cloudflare dashboard (triggers initial tool sync)
- [ ] Frontend/Backend are bound to 127.0.0.1 (not 0.0.0.0)

## Failure Mode Analysis

What happens if each security layer is compromised:

| Layer Compromised | Impact | Mitigated By |
|-------------------|--------|--------------|
| OAuth provider (Google/GitHub) | Attacker can authenticate | Access Policy (email allowlist) |
| MCP Portal JWT signing key | Attacker can forge JWTs | Cloudflare manages keys, 6-week rotation |
| Worker code | Attacker can bypass OAuth/JWT check | Code review, Wrangler deployment auth |
| VPC Service misconfiguration | Wrong tunnel routed | Service token validation in MCPbox |
| Service token leaked | Attacker with token can bypass defense-in-depth layer | Still needs valid OAuth token, VPC access |
| Tunnel token leaked | Attacker can create tunnel | Service token still required |
| MCPbox gateway compromised | Full MCP access | Docker network isolation, sandbox |
| Sandbox escape | Code execution on host | Container security, resource limits |

### Security Trade-offs

**JTI Replay Protection (Not Implemented)**

JWT tokens could theoretically be replayed within their validity window by an attacker who intercepts them. We chose not to implement `jti` (JWT ID) tracking because:

1. JWTs have short validity (typically 5-15 minutes from Cloudflare Access)
2. Implementing JTI requires distributed state (Redis, Cloudflare KV, etc.)
3. The attack window is minimal and requires token theft (TLS prevents network-level interception)
4. The service token provides an additional authentication layer
5. The tunnel is private (no public hostname) limiting attack vectors

For high-security deployments requiring replay protection, consider implementing JTI tracking with Cloudflare KV.

**DPoP Token Binding (Not Implemented)**

[DPoP (RFC 9449)](https://datatracker.ietf.org/doc/html/rfc9449) provides cryptographic proof-of-possession but adds significant complexity. Reserved for future enhancement if token theft becomes a specific concern.

### Critical Security Dependencies

1. **Cloudflare's JWT signing infrastructure** - If compromised, attackers could forge tokens. Cloudflare rotates keys every 6 weeks and uses HSMs.

2. **VPC binding isolation** - Workers VPC ensures only your Worker can reach your tunnel. This is enforced at Cloudflare's infrastructure level.

3. **No public tunnel hostname** - The tunnel literally has no DNS entry. There's no URL to discover or attack.

## Related Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Overall MCPbox system architecture
- [PRODUCTION-DEPLOYMENT.md](./PRODUCTION-DEPLOYMENT.md) - Production deployment checklist
- [CLOUDFLARE-SETUP-WIZARD.md](./CLOUDFLARE-SETUP-WIZARD.md) - Automated setup wizard
- [Cloudflare MCP Server Portals](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/) - Official Cloudflare documentation
- [Cloudflare Workers VPC](https://developers.cloudflare.com/workers-vpc/) - VPC binding documentation
- [Cloudflare Access JWT Validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/) - JWT verification reference
