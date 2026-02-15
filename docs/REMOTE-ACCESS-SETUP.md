# Remote Access Setup (Claude Web via Cloudflare)

This guide explains how to expose your MCPbox instance to Claude Web using Cloudflare Workers VPC. The tunnel has **no public hostname** - it's only accessible via your Worker.

> **Recommended:** Use the [Setup Wizard](/tunnel/setup) for automated configuration. This manual guide is provided for reference and troubleshooting. See [CLOUDFLARE-SETUP-WIZARD.md](./CLOUDFLARE-SETUP-WIZARD.md) for wizard documentation.

## Architecture Overview

```
+---------------------------------------------------------------------------+
|                              Your Network                                  |
|                                                                            |
|  +--------------------------------------------------------------------+   |
|  |                        MCPbox (Docker)                              |   |
|  |                                                                     |   |
|  |   +--------------+     +------------------+                         |   |
|  |   | MCP Gateway  |<----| cloudflared      |<--- Private tunnel      |   |
|  |   | :8002        |     | (tunnel agent)   |     (no public hostname)|   |
|  |   +--------------+     +------------------+                         |   |
|  |                                                                     |   |
|  +--------------------------------------------------------------------+   |
+---------------------------------------------------------------------------+
                                        |
                                        | Workers VPC (private)
                                        |
+---------------------------------------+-----------------------------------+
|                            Cloudflare                                      |
|                                                                            |
|  +--------------------------------------------------------------------+   |
|  |                    Cloudflare Worker                                |   |
|  |              (mcpbox-proxy.you.workers.dev)                        |   |
|  |                                                                     |   |
|  |  - @cloudflare/workers-oauth-provider wrapper                      |   |
|  |  - OAuth 2.1 (downstream to MCP clients)                          |   |
|  |  - OIDC upstream to Cloudflare Access for SaaS (user identity)    |   |
|  |  - Accesses tunnel via Workers VPC binding (private)               |   |
|  |  - Adds X-MCPbox-Service-Token header (defense-in-depth)          |   |
|  |  - Sets X-MCPbox-User-Email from OIDC-verified id_token           |   |
|  +--------------------------------------------------------------------+   |
|                                        ^                                   |
|                                        | MCP Protocol (HTTPS)              |
|                                        |                                   |
+----------------------------------------+----------------------------------+
                                         |
                     MCP Clients (Claude Web, etc.)
```

MCP clients connect directly to the Worker URL (e.g., `https://mcpbox-proxy.you.workers.dev/mcp`). There are no MCP Server or Portal objects required -- the Worker handles OAuth 2.1 and OIDC authentication directly.

## Security Model

MCPbox uses a **defense-in-depth** architecture with multiple security layers.

### Security Layers (10 Total)

| Layer | Component | Security Mechanism | What It Protects Against |
|-------|-----------|-------------------|--------------------------|
| **1** | MCP Client -> Worker | OAuth 2.1 token verification (all requests) | Unauthenticated access |
| **2** | Worker -> Cloudflare Access | OIDC upstream (Access for SaaS) | Unverified user identity |
| **3** | Worker | OIDC id_token verification (RS256, JWKS, iss/aud/nonce/exp/nbf) | Token forgery, replay attacks |
| **4** | Worker | Path validation (`/mcp`, `/health` only) | Admin API access via tunnel |
| **5** | Worker | CORS whitelist (`claude.ai` domains) | Cross-origin request abuse |
| **6** | Worker -> Tunnel | Workers VPC (private binding) | Public tunnel exposure |
| **7** | Tunnel -> MCP Gateway | Service Token header | Defense in depth |
| **8** | MCP Gateway | Token validation + email-based method authorization | Requests bypassing Worker, anonymous tool execution |
| **9** | Docker network | Internal bridge networks | Container-to-container isolation |
| **10** | Frontend/Backend | 127.0.0.1 binding | WAN access to admin API |

### Worker Auth Model

| Request source | Auth | Worker validates | Allowed operations |
|---|---|---|---|
| User via OIDC | OAuth 2.1 token + OIDC-verified email (in token props) | OAuth token + email from OIDC id_token | All (list + execute) |
| Cloudflare sync | OAuth 2.1 token (no OIDC, no user email) | OAuth token valid | Sync only (list, initialize) |
| Random internet | No valid OAuth token | Rejected 401 | None |

### Attack Surface Analysis

**Publicly Accessible:**
- Worker URL (`mcpbox-proxy.*.workers.dev`) -- Protected by OAuth 2.1 (all requests). Unauthenticated requests rejected with 401.

**NOT Publicly Accessible:**
- Tunnel endpoint -- No public hostname, only reachable via Workers VPC binding
- MCPbox admin API (`:8000`) -- Bound to 127.0.0.1
- MCPbox frontend (`:3000`) -- Bound to 127.0.0.1
- MCP Gateway (`:8002`) -- Only reachable via tunnel
- Sandbox (`:8001`) -- Internal Docker network only
- PostgreSQL (`:5432`) -- Internal Docker network only

### OIDC Token Verification Details

The Worker verifies OIDC id_tokens from Cloudflare Access at authorization time:

1. **Algorithm Validation** -- Explicitly requires RS256; rejects all other algorithms (prevents algorithm confusion attacks)
2. **Signature Verification** -- Fetches public keys from Access JWKS endpoint (`ACCESS_JWKS_URL`) with 5-minute caching
3. **Audience Claim** -- Must match the OIDC client ID (`ACCESS_CLIENT_ID`)
4. **Issuer Claim** -- Must match the Cloudflare Access team domain (derived from `ACCESS_AUTHORIZATION_URL`)
5. **Nonce Validation** -- The nonce sent in the OIDC authorize request must match the nonce in the id_token (prevents replay)
6. **Expiration** -- Token must not be expired (`exp` claim), with 60-second clock skew tolerance
7. **Not Before** -- Token must be valid (`nbf` claim), with 60-second clock skew tolerance

**JWKS Caching:** Public keys are cached for 5 minutes to reduce latency. If a key ID (`kid`) is not found in cache, a fresh fetch is attempted to handle key rotation.

**When verification succeeds**, the verified email is stored in encrypted OAuth token props and set as `X-MCPbox-User-Email` on every subsequent proxied request.

### Known Limitations & Considerations

1. **Worker URL is technically public** -- Anyone can send requests to the Worker URL, but without a valid OAuth 2.1 token, requests are rejected with 401. OAuth-only requests (no OIDC email) are restricted to sync operations (tool discovery), never tool execution.

2. **Service Token is defense-in-depth** -- The `X-MCPbox-Service-Token` header is validated by MCPbox even though the tunnel is already private. This protects against potential VPC binding misconfigurations. Service token failures return 403 Forbidden.

3. **CORS provides zero protection against non-browser attackers** -- CORS headers are set to `claude.ai` domains. However:
   - CORS is purely a browser-enforced policy, not a server-side security control
   - Any non-browser client (`curl`, Python scripts, custom tools) can freely ignore CORS headers
   - When an attacker runs `curl -X POST https://your-worker.workers.dev/mcp`, CORS has no effect
   - The actual security boundary is OAuth 2.1 verification -- without a valid OAuth token, all requests are rejected
   - CORS should be considered defense-in-depth against browser-based XSS exploitation only

4. **OIDC key rotation** -- Cloudflare rotates signing keys periodically. The Worker caches JWKS for 5 minutes and automatically refreshes when an unknown key ID is encountered.

5. **Email freshness** -- User email is verified at OAuth authorization time and stored in encrypted token props. Email freshness is bounded by OAuth token TTL.

### Threat Model

| Threat | Mitigation | Residual Risk |
|--------|------------|---------------|
| Unauthenticated access | OAuth 2.1 required (all requests), returns 401 | None |
| OIDC id_token forgery | RS256 signature verification via Cloudflare JWKS | None (cryptographically secure) |
| OIDC id_token replay | Nonce validation + OAuth state management | None |
| Direct Worker access (no OIDC) | OAuth-only requests restricted to sync (no tool execution) | None |
| Direct tunnel access | No public hostname, VPC binding | None |
| Admin API access via tunnel | Path validation in Worker | None |
| SSRF via tunnel | Path validation, VPC isolation | None |
| Service token brute force | 256-bit entropy (64 hex chars) | Computationally infeasible |
| OAuth token theft | Token bound to client session, TLS in transit | Short window before expiry |

### Security Guarantees

This architecture provides:
- **Authentication** -- Users must authenticate via OAuth 2.1 + OIDC
- **Authorization** -- Cloudflare Access policies control who can authenticate
- **Confidentiality** -- All traffic is TLS-encrypted
- **Integrity** -- OIDC id_token signatures prevent tampering
- **Audit logging** -- User email extracted from OIDC id_token for logs
- **Network isolation** -- Tunnel has no public attack surface

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

## Step 3: Configure and Deploy the Worker (with OIDC)

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
   - Set all Worker secrets: `MCPBOX_SERVICE_TOKEN`, `ACCESS_CLIENT_ID`, `ACCESS_CLIENT_SECRET`, `ACCESS_TOKEN_URL`, `ACCESS_AUTHORIZATION_URL`, `ACCESS_JWKS_URL`, `COOKIE_ENCRYPTION_KEY`

   The service token is fetched from the database (generated by the wizard) and
   pushed to the Worker automatically -- no manual token management needed.

   Note your Worker URL (e.g., `https://mcpbox-proxy.yourname.workers.dev`)

The OIDC configuration (Access for SaaS) is set up during the wizard's "Configure Access" step. The Worker redirects users to Cloudflare Access for authentication and verifies the returned id_token.

## Step 4: Connect MCP Clients

1. In Claude Web, go to **Settings** -> **Integrations** -> **MCP Servers**
2. Click **Add Server** and enter your Worker URL **with `/mcp` path** (e.g., `https://mcpbox-proxy.yourname.workers.dev/mcp`)
3. Complete OAuth authentication (the Worker redirects to Cloudflare Access for OIDC login)
4. Your MCPbox tools should now appear in Claude's tool list

**Note:** The URL must include `/mcp` -- entering just the domain without the path will return a 404.

## Verification

```bash
# Direct Worker access should return 401 (expected - no OAuth token)
curl -s https://mcpbox-proxy.yourname.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
# Expected: 401 Unauthorized

# Health check is public (returns 200)
curl -s https://mcpbox-proxy.yourname.workers.dev/health
# Expected: {"status":"ok"}

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
- The token is generated by the wizard and stored in the database -- the deploy script pushes it to the Worker
- Service token failures return 403 Forbidden

### "401 Unauthorized" when accessing Worker directly

This is **expected behavior**. The Worker requires a valid OAuth 2.1 token for all MCP requests. Users authenticate via OIDC (Cloudflare Access) during the OAuth authorization flow. Unauthenticated requests are always rejected.

To verify auth is working:
```bash
# This should return 401 (expected - no OAuth token)
curl -s https://mcpbox-proxy.yourname.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
# Expected: 401 Unauthorized
```

### "McpAuthorizationError: Your account was authorized but the integration rejected the credentials"

This is usually caused by **Cloudflare AI Crawl Control** blocking claude.ai's requests. If you have AI Crawl Control enabled on your zone, disable it: Cloudflare Dashboard -> your zone -> **Security** -> **Bots** -> **AI Crawlers** -> Disable. Most accounts won't have this enabled by default.

### "invalid_id_token" or OIDC verification failure

- Check that OIDC secrets are correctly set: `ACCESS_CLIENT_ID`, `ACCESS_CLIENT_SECRET`, `ACCESS_TOKEN_URL`, `ACCESS_AUTHORIZATION_URL`, `ACCESS_JWKS_URL`
- Verify the Access for SaaS OIDC application exists in Cloudflare Access
- JWKS keys may have rotated -- the Worker auto-refreshes, but verify `ACCESS_JWKS_URL` is correct
- Check Worker logs for specific verification error details

### "token_exchange_failed"

- Verify `ACCESS_TOKEN_URL` is correct (format: `https://{team}.cloudflareaccess.com/cdn-cgi/access/sso/oidc/{client_id}/token`)
- Verify `ACCESS_CLIENT_ID` and `ACCESS_CLIENT_SECRET` match the SaaS OIDC application
- Check that the Access Application has an active policy allowing your users

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
| `MCPBOX_SERVICE_TOKEN` | Worker secret | Shared secret with MCPbox backend (defense-in-depth) |
| `ACCESS_CLIENT_ID` | Worker secret | OIDC client ID from Cloudflare Access SaaS application |
| `ACCESS_CLIENT_SECRET` | Worker secret | OIDC client secret from Cloudflare Access SaaS application |
| `ACCESS_TOKEN_URL` | Worker secret | OIDC token endpoint (e.g., `https://{team}.cloudflareaccess.com/cdn-cgi/access/sso/oidc/{client_id}/token`) |
| `ACCESS_AUTHORIZATION_URL` | Worker secret | OIDC authorization endpoint (e.g., `https://{team}.cloudflareaccess.com/cdn-cgi/access/sso/oidc/{client_id}/authorize`) |
| `ACCESS_JWKS_URL` | Worker secret | JWKS endpoint for id_token verification (e.g., `https://{team}.cloudflareaccess.com/cdn-cgi/access/certs`) |
| `COOKIE_ENCRYPTION_KEY` | Worker secret | 32-byte hex key for encrypting client approval cookies |

### OIDC Endpoint URLs

OIDC endpoints are derived from the Cloudflare Access team domain and client ID:

```
Token URL:    https://{team_domain}/cdn-cgi/access/sso/oidc/{client_id}/token
Auth URL:     https://{team_domain}/cdn-cgi/access/sso/oidc/{client_id}/authorize
JWKS URL:     https://{team_domain}/cdn-cgi/access/certs
```

## Local vs Remote Mode

| Mode | Service Token | Tunnel | Use Case |
|------|---------------|--------|----------|
| **Local** | Not in database | Not needed | Claude Desktop only |
| **Remote** | Generated by wizard, stored in DB | Required (private) | Claude Web + Desktop |

When a service token exists in the database (created by the wizard), MCPbox requires the `X-MCPbox-Service-Token` header on all MCP requests. The Worker adds this header automatically. For Claude Desktop in remote mode, you'd need to configure it to include this header.

## Authentication Flow

Understanding how authentication works helps with troubleshooting:

```
+--------------+    +--------------------+    +----------------+    +-----------+
| MCP Client   |--->| Worker             |--->| Cloudflare     |--->| MCPbox    |
| (Claude Web) |    | (OAuth 2.1 + OIDC) |    | Access (OIDC)  |    | (gateway) |
+--------------+    +--------------------+    +----------------+    +-----------+
      |                      |                       |                    |
      | 1. Connect to Worker URL                     |                    |
      |----->|               |                       |                    |
      |      |               |                       |                    |
      | 2. OAuth 2.1 discovery (/.well-known/*)      |                    |
      |<---->|               |                       |                    |
      |      |               |                       |                    |
      | 3. OAuth authorize redirect                  |                    |
      |----->|               |                       |                    |
      |      |               |                       |                    |
      |      | 4. Redirect to Cloudflare Access OIDC |                    |
      |      |-------------->|                       |                    |
      |      |               |                       |                    |
      |      |               | 5. User authenticates |                    |
      |      |               |   (email OTP, SSO)    |                    |
      |      |               |                       |                    |
      |      | 6. OIDC callback with auth code        |                    |
      |      |<--------------|                       |                    |
      |      |               |                       |                    |
      |      | 7. Exchange code for id_token + access_token               |
      |      |-------------->|                       |                    |
      |      |<--------------|                       |                    |
      |      |               |                       |                    |
      |      | 8. Verify id_token (RS256, iss, aud, nonce, exp, nbf)     |
      |      |   Store email in encrypted OAuth token props               |
      |      |               |                       |                    |
      | 9. OAuth token issued to MCP client           |                    |
      |<-----|               |                       |                    |
      |      |               |                       |                    |
      | 10. MCP request with OAuth token              |                    |
      |----->|               |                       |                    |
      |      |               |                       |                    |
      |      | 11. Add service token + user email     |                    |
      |      |    headers, proxy via VPC              |------>|           |
      |      |               |                       |       |           |
      |      |               |                       | 12. Validate token |
      |      |               |                       |      Execute tool  |
      |      |               |                       |<------|           |
      |      |               |                       |                    |
      | 13. Response                                  |                    |
      |<-----|               |                       |                    |
```

**Security layers:**
1. **Worker OAuth 2.1** -- All MCP requests require a valid OAuth 2.1 token
2. **OIDC Upstream** -- User identity verified via Cloudflare Access for SaaS (OIDC id_token)
3. **Email-Based Authorization** -- Requests without verified email (e.g., Cloudflare sync) can only list tools, not execute them
4. **Service Token** -- MCPbox validates the shared secret (defense in depth)
5. **Private Tunnel** -- VPC binding ensures only the Worker can reach MCPbox

## Why Workers VPC?

Unlike a traditional public tunnel setup where you'd need Cloudflare Access to protect a public hostname, Workers VPC creates a **truly private** connection:

- No public DNS entry for your tunnel
- No attack surface for hostname discovery
- No need for Access policies on the tunnel itself
- The tunnel literally cannot be reached except through your Worker

## Worker Security Implementation

The Worker (`worker/src/index.ts`) implements the following security controls:

### OAuth 2.1 Provider
The Worker is wrapped with `@cloudflare/workers-oauth-provider`, which manages:
- OAuth 2.1 discovery endpoints (`.well-known/oauth-authorization-server`)
- Protected Resource Metadata (RFC 9728)
- Client registration and token issuance
- Token validation on all API requests

### OIDC Upstream (Access for SaaS)
The Worker redirects users to Cloudflare Access for authentication during the OAuth authorization flow:

1. MCP client starts OAuth 2.1 authorization
2. Worker redirects to Cloudflare Access OIDC authorize endpoint
3. User authenticates via Access (email OTP, SSO, etc.)
4. Access redirects back to Worker's `/callback` with authorization code
5. Worker exchanges code for id_token + access_token at Access token endpoint
6. Worker verifies id_token signature using Access JWKS
7. Worker stores verified email in encrypted OAuth token props
8. On subsequent requests, Worker sets `X-MCPbox-User-Email` from token props

### Path Validation
```typescript
// Only the rewritten MCP endpoint is allowed through the API handler
if (path !== INTERNAL_API_ROUTE) {
  return new Response(JSON.stringify({ error: 'Not found' }), { status: 404 });
}
```
Only MCP requests (rewritten from `/` and `/mcp`) are proxied. All other paths return 404.

### CORS Configuration
```typescript
const allowedOrigins = [
  'https://mcp.claude.ai',
  'https://claude.ai',
  'https://one.dash.cloudflare.com',
];
```
CORS headers restrict browser-based access to Claude and Cloudflare domains only.

### Headers Added to Backend Requests
```typescript
headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
headers.set('X-Forwarded-Host', url.host);
headers.set('X-Forwarded-Proto', 'https');
headers.set('X-MCPbox-User-Email', userEmail);    // From OIDC-verified token props
headers.set('X-MCPbox-Auth-Method', 'oidc');       // Always 'oidc' with Access for SaaS
```

The `X-MCPbox-User-Email` and `X-MCPbox-Auth-Method` headers are stripped from client requests (defense-in-depth) and set by the Worker based on OIDC-verified OAuth token props.

### Configuration (Worker Secrets)

| Secret | Required | Purpose |
|--------|----------|---------|
| `MCPBOX_SERVICE_TOKEN` | Yes | Shared secret with MCPbox backend (defense-in-depth) |
| `ACCESS_CLIENT_ID` | Yes | OIDC client ID from Cloudflare Access SaaS application |
| `ACCESS_CLIENT_SECRET` | Yes | OIDC client secret from Cloudflare Access SaaS application |
| `ACCESS_TOKEN_URL` | Yes | OIDC token endpoint URL |
| `ACCESS_AUTHORIZATION_URL` | Yes | OIDC authorization endpoint URL |
| `ACCESS_JWKS_URL` | Yes | JWKS endpoint for id_token signature verification |
| `COOKIE_ENCRYPTION_KEY` | Yes | 32-byte hex key for encrypting client approval cookies |

If the OIDC secrets are not set, the Worker cannot redirect users to Cloudflare Access for authentication. OAuth-only requests (Cloudflare sync) still work but are limited to sync operations.

## Cloudflare Components Summary

| Component | Type | Purpose |
|-----------|------|---------|
| **Tunnel** | `cloudflared` | Outbound connection from your network to Cloudflare |
| **VPC Service** | Workers VPC | Private binding between Worker and Tunnel |
| **Worker** | Cloudflare Worker | OAuth 2.1 provider + OIDC upstream + proxy |
| **Access for SaaS Application** | Zero Trust | OIDC identity provider for user authentication |

The Worker handles all authentication directly. MCP clients connect to the Worker URL -- no MCP Server or Portal objects are needed in Cloudflare.

## Current Deployment Reference

For auditing purposes, here are the current Cloudflare resource IDs:

### Worker Configuration

`worker/wrangler.toml` is generated by `./scripts/deploy-worker.sh` -- it fetches the VPC service ID from the backend database so it's always in sync with the wizard configuration.

### Worker Secrets (set via `./scripts/deploy-worker.sh --set-secrets`)
- `MCPBOX_SERVICE_TOKEN` -- 64-character hex string
- `ACCESS_CLIENT_ID` -- OIDC client ID from Access SaaS application
- `ACCESS_CLIENT_SECRET` -- OIDC client secret from Access SaaS application
- `ACCESS_TOKEN_URL` -- OIDC token endpoint URL
- `ACCESS_AUTHORIZATION_URL` -- OIDC authorization endpoint URL
- `ACCESS_JWKS_URL` -- JWKS endpoint URL
- `COOKIE_ENCRYPTION_KEY` -- 64-character hex string (32 bytes)

### MCPbox Configuration

All remote access tokens are stored in the database (managed by the setup wizard):
- **Service token**: Generated by wizard step 4, loaded at startup by `ServiceTokenCache`
- **Tunnel token**: Generated by wizard step 2, fetched by cloudflared at startup
- **OIDC credentials**: Created by wizard step 5 (Configure Access), synced to Worker

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
   # Direct access should still return 401 (expected - no OAuth token)
   curl -s https://your-worker.workers.dev/mcp
   # Should return: 401 Unauthorized

   # Test via Claude Web to verify end-to-end
   ```

## Security Checklist for Production

Before deploying to production, verify:

- [ ] Setup wizard completed (service token generated and stored in database)
- [ ] Tunnel configuration is active in the MCPbox UI (token stored in database)
- [ ] `./scripts/deploy-worker.sh --set-secrets` run (syncs all secrets to Worker)
- [ ] Worker secret `ACCESS_CLIENT_ID` is set (OIDC client ID)
- [ ] Worker secret `ACCESS_CLIENT_SECRET` is set (OIDC client secret)
- [ ] Worker secret `ACCESS_TOKEN_URL` is set (OIDC token endpoint)
- [ ] Worker secret `ACCESS_AUTHORIZATION_URL` is set (OIDC authorization endpoint)
- [ ] Worker secret `ACCESS_JWKS_URL` is set (JWKS endpoint)
- [ ] Worker secret `COOKIE_ENCRYPTION_KEY` is set (32-byte hex key)
- [ ] Access for SaaS application has appropriate Access Policy (restrict by email/domain)
- [ ] Identity provider is configured in Zero Trust dashboard
- [ ] Tunnel has NO public hostname configured
- [ ] Direct Worker access returns 401: `curl https://your-worker.workers.dev/mcp`
- [ ] Frontend/Backend are bound to 127.0.0.1 (not 0.0.0.0)

## Failure Mode Analysis

What happens if each security layer is compromised:

| Layer Compromised | Impact | Mitigated By |
|-------------------|--------|--------------|
| Identity provider (Google/GitHub) | Attacker can authenticate via OIDC | Access Policy (email allowlist) |
| OIDC signing key | Attacker can forge id_tokens | Cloudflare manages keys, automatic rotation |
| Worker code | Attacker can bypass OAuth/OIDC checks | Code review, Wrangler deployment auth |
| VPC Service misconfiguration | Wrong tunnel routed | Service token validation in MCPbox |
| Service token leaked | Attacker with token can bypass defense-in-depth layer | Still needs valid OAuth token, VPC access |
| Tunnel token leaked | Attacker can create tunnel | Service token still required |
| MCPbox gateway compromised | Full MCP access | Docker network isolation, sandbox |
| Sandbox escape | Code execution on host | Container security, resource limits |

### Security Trade-offs

**DPoP Token Binding (Not Implemented)**

[DPoP (RFC 9449)](https://datatracker.ietf.org/doc/html/rfc9449) provides cryptographic proof-of-possession but adds significant complexity. Reserved for future enhancement if token theft becomes a specific concern.

### Critical Security Dependencies

1. **Cloudflare Access OIDC infrastructure** -- If compromised, attackers could forge id_tokens. Cloudflare uses HSMs for key management.

2. **VPC binding isolation** -- Workers VPC ensures only your Worker can reach your tunnel. This is enforced at Cloudflare's infrastructure level.

3. **No public tunnel hostname** -- The tunnel literally has no DNS entry. There's no URL to discover or attack.

## Related Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) -- Overall MCPbox system architecture
- [AUTH-FLOW.md](./AUTH-FLOW.md) -- Complete Worker + Gateway auth flow reference
- [PRODUCTION-DEPLOYMENT.md](./PRODUCTION-DEPLOYMENT.md) -- Production deployment checklist
- [CLOUDFLARE-SETUP-WIZARD.md](./CLOUDFLARE-SETUP-WIZARD.md) -- Automated setup wizard
- [Cloudflare Workers VPC](https://developers.cloudflare.com/workers-vpc/) -- VPC binding documentation
- [Cloudflare Access for SaaS](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/saas-apps/) -- OIDC integration documentation
