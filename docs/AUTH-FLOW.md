# Auth Flow Reference

Complete reference for the MCPbox authentication and authorization flow across the Worker (TypeScript) and Gateway (Python).

## 1. Architecture Overview

Three actors access the MCP endpoint through different paths. With Access for SaaS, the Worker acts as both an OAuth 2.1 server (downstream to MCP clients) and an OIDC client (upstream to Cloudflare Access):

```
                         ┌─────────────────────┐
 Cloudflare Sync ──────►│                     │
 (OAuth only,            │  Cloudflare Worker  │──VPC──► MCP Gateway (/mcp)
  no user email)         │  (OAuth 2.1 proxy)  │
                         │                     │
 MCP Portal User ──────►│  OIDC upstream to   │
 (OAuth + OIDC)          │  Cloudflare Access  │
                         └─────────────────────┘

 Local User ────────────────────────────────────► MCP Gateway (/mcp)
 (no auth)                                        (port 8000, localhost only)
```

| Actor | Path | OAuth Token | OIDC (Access for SaaS) | Service Token |
|-------|------|-------------|----------------------|---------------|
| **Cloudflare Sync** | Worker → VPC → Gateway | Yes (auto) | No | Yes (Worker adds) |
| **MCP Portal User** | Worker → VPC → Gateway | Yes (user-approved) | Yes (at authorization) | Yes (Worker adds) |
| **Local User** | Direct to Gateway | No | No | No |

### OIDC Flow (Access for SaaS)

When a user authorizes an MCP client, the Worker redirects to Cloudflare Access as an OIDC identity provider:

```
MCP Client → Worker /authorize → Cloudflare Access OIDC → Worker /callback → Client
```

1. MCP client starts OAuth 2.1 authorization
2. Worker redirects to Cloudflare Access OIDC authorize endpoint
3. User authenticates via Access (email OTP, SSO, etc.)
4. Access redirects back to Worker's `/callback` with authorization code
5. Worker exchanges code for id_token + access_token at Access token endpoint
6. Worker verifies id_token signature using Access JWKS
7. Worker stores verified email in encrypted OAuth token props
8. Worker forwards requests with `X-MCPbox-User-Email` header

## 2. Worker Request Routing

### URL Rewriting

The Worker uses `OAuthProvider` with `apiRoute: '/oauth-protected-api'` (an internal-only path). Real MCP requests arrive at `/` or `/mcp` and are rewritten before reaching OAuthProvider:

```
Client request         → Rewritten to            → Handler
─────────────────────────────────────────────────────────────
POST /                 → /oauth-protected-api     → apiHandler (OAuth validated)
POST /mcp              → /oauth-protected-api     → apiHandler (OAuth validated)
GET /authorize         → (not rewritten)          → access-handler (OIDC flow)
POST /authorize        → (not rewritten)          → access-handler (OIDC flow)
GET /callback          → (not rewritten)          → access-handler (OIDC callback)
GET /.well-known/*     → (not rewritten)          → OAuthProvider built-in
POST /token            → (not rewritten)          → OAuthProvider built-in
POST /register         → (not rewritten)          → OAuthProvider built-in
OPTIONS (any)          → (handled pre-OAuth)      → CORS preflight response
GET /health            → (handled pre-OAuth)      → Health check response
GET /.well-known/oauth-protected-resource[/mcp]
                       → (handled pre-OAuth)      → PRM response
```

**Why rewrite?** OAuthProvider's `matchApiRoute` uses `startsWith()`. If `apiRoute` were `/`, it would catch every path including `/authorize`, `/token`, etc. The dummy `/oauth-protected-api` path avoids this conflict.

### Pre-OAuth Endpoints

These are handled before OAuthProvider processes the request (no OAuth token required):

- `OPTIONS` — CORS preflight (any path)
- `GET /health` — Health check
- `GET /.well-known/oauth-protected-resource` — PRM, returns `resource: origin`
- `GET /.well-known/oauth-protected-resource/mcp` — PRM, returns `resource: origin/mcp`

### Access Handler Endpoints

OIDC upstream authentication flow (in `access-handler.ts`):

- `GET /authorize` — Shows client approval dialog (encrypted cookie for state)
- `POST /authorize` — User approves → redirects to Cloudflare Access OIDC
- `GET /callback` — Receives OIDC callback, exchanges code for tokens, verifies id_token

### Protected Resource Metadata (PRM)

RFC 9728 PRM tells MCP clients where to find the OAuth authorization server:

```json
{
  "resource": "https://worker.workers.dev/mcp",
  "authorization_servers": ["https://worker.workers.dev"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": []
}
```

Served at two paths because Cloudflare sync probes the root path while claude.ai users add the URL as `https://worker.workers.dev/mcp`.

### Redirect URI Validation

OAuth client registration validates redirect URIs against:

**Static patterns:**
- `https://mcp.claude.ai/*`
- `https://claude.ai/*`
- `https://one.dash.cloudflare.com/*`
- `http://localhost[:port]/*`
- `http://127.0.0.1[:port]/*`

Unrecognized redirect URIs are rejected with 400.

## 3. Gateway Authentication

### `verify_mcp_auth()` Decision Tree

With Access for SaaS (OIDC), the gateway no longer performs server-side JWT verification. User identity comes from the Worker-supplied `X-MCPbox-User-Email` header, set from OIDC-verified OAuth token props.

```
                    ┌──────────────────────┐
                    │ ServiceTokenCache     │
                    │ is_auth_enabled()?    │
                    └──────┬───────────────┘
                           │
                    ┌──────┴──────┐
                    │             │
                  True          False
                    │             │
                    ▼             ▼
           ┌────────────┐  ┌──────────────┐
           │ Has valid   │  │ Local mode:  │
           │ X-MCPbox-   │  │ source=local │
           │ Service-    │  │ auth=None    │
           │ Token?      │  │ (all allowed)│
           └──────┬──────┘  └──────────────┘
                  │
           ┌──────┴──────┐
           │             │
          Yes           No/Invalid
           │             │
           ▼             ▼
    ┌──────────────┐  ┌──────────┐
    │ Has Worker-  │  │ 403      │
    │ supplied     │  │ (fail    │
    │ email?       │  │ closed)  │
    │ (X-MCPbox-   │  └──────────┘
    │  User-Email) │
    └──────┬───────┘
    ┌──────┴──────┐
    │             │
   Yes           No
    │             │
    ▼             ▼
 source=worker  source=worker
 auth=oidc      auth=oidc
 email=<oidc>   email=None
```

**Key points:**
- Service token comparison uses `secrets.compare_digest` (constant-time)
- Database/decryption errors → fail-closed (auth enabled, no valid token → all requests rejected)
- No server-side JWT verification — the Worker handles OIDC at authorization time
- User email is set by the Worker from OIDC-verified id_token claims (stored in encrypted OAuth token props)
- Email freshness is bounded by OAuth token TTL
- `auth_method` is always `oidc` for remote requests

### Rate Limiting

Failed auth attempts are tracked per IP. After 10 failures in 60 seconds, the IP gets 429 responses.

## 4. Method Authorization

The gateway uses `_is_anonymous_remote` flag to control per-method access:

```python
_is_anonymous_remote = _user.source == "worker" and not _user.email
```

A remote request is "anonymous" when it has no verified user email. With OIDC, all human users who authenticate via the MCP Portal have a verified email from the OIDC id_token. Only Cloudflare's internal sync (tool discovery) lacks an email — it's allowed for read-only methods but blocked from tool execution.

### Per-Method Authorization Table

| Method | Local User | OIDC User (email) | Anonymous Remote (no email) |
|--------|-----------|---------------------|----------------------------|
| `initialize` | Allowed | Allowed | **Allowed** |
| `tools/list` | Allowed | Allowed | **Blocked** (-32600) |
| `notifications/*` | Allowed (202) | Allowed (202) | **Allowed** (202) |
| `tools/call` | Allowed | Allowed | **Blocked** (-32600) |
| Unknown methods | Allowed (forwarded) | Allowed (forwarded) | **Blocked** (-32600) |

User email for authorization and audit logging comes from:
1. **OIDC id_token** (verified at authorization time by Worker, stored in OAuth token props)
2. **None** (Cloudflare sync — blocked from tool execution)

### Destructive Tool Restrictions

Even with OIDC auth, some management tools are local-only:

| Tool | Local | Remote (any auth) |
|------|-------|-------------------|
| `mcpbox_delete_server` | Allowed | **Blocked** (local-only) |
| `mcpbox_delete_tool` | Allowed | **Blocked** (local-only) |
| All other `mcpbox_*` | Allowed | Allowed |
| Sandbox tools | Allowed | Allowed |

## 5. Worker Secrets

Secrets are pushed to the Worker at different wizard steps:

| Secret | First set at | Source |
|--------|-------------|--------|
| `MCPBOX_SERVICE_TOKEN` | Step 4 (deploy Worker), re-synced at step 5 | Generated in `deploy_worker()` |
| `ACCESS_CLIENT_ID` | Step 5 (configure access) | From SaaS OIDC app (created in step 5) |
| `ACCESS_CLIENT_SECRET` | Step 5 (configure access) | From SaaS OIDC app (created in step 5) |
| `ACCESS_TOKEN_URL` | Step 5 (configure access) | Derived from team_domain + client_id |
| `ACCESS_AUTHORIZATION_URL` | Step 5 (configure access) | Derived from team_domain + client_id |
| `ACCESS_JWKS_URL` | Step 5 (configure access) | Derived from team_domain |
| `COOKIE_ENCRYPTION_KEY` | Step 5 (configure access) | Generated (32-byte hex) |

Step 5 creates the SaaS OIDC Access Application, stores the credentials, and syncs all secrets to the Worker in a single operation. The deploy script (`scripts/deploy-worker.sh --set-secrets`) can also push them for re-deployment after code changes.

MCP clients (Claude Web, OpenAI, etc.) connect directly to the Worker URL — no MCP Server or Portal objects are needed.

**Important:** After the wizard regenerates a service token (e.g., re-running setup), you must either re-run step 5 or run `deploy-worker.sh --set-secrets` to sync the new token to the Worker.

### OIDC Endpoint URLs

OIDC endpoints are derived from the Cloudflare Access team domain and client ID:

```
Token URL:    https://{team_domain}/cdn-cgi/access/sso/oidc/{client_id}/token
Auth URL:     https://{team_domain}/cdn-cgi/access/sso/oidc/{client_id}/authorize
JWKS URL:     https://{team_domain}/cdn-cgi/access/certs
```

## 6. Common Pitfalls

### apiRoute Prefix Matching (Bug #1)
`OAuthProvider.matchApiRoute` uses `startsWith()`. Setting `apiRoute: '/'` catches `/authorize`, `/token`, etc. **Fix:** Use a dummy internal path (`/oauth-protected-api`) and rewrite `/` and `/mcp` to it.

### /mcp Path Must Be Rewritten (Bug #4)
Cloudflare sync sends requests to `/mcp`, not `/`. The URL rewriting must handle both paths: `if (url.pathname === '/' || url.pathname === '/mcp')`.

### Redirect URI Allowlist (Bug #3, #6)
The Cloudflare dashboard (`one.dash.cloudflare.com`) must be in the redirect URI allowlist.

### Sync Methods Work Without Email, Tool Access Requires Email (Bug #5)
Cloudflare's MCP server sync authenticates via OAuth only (no user email). Only protocol-level methods (`initialize`, `notifications/*`) are allowed without a verified email. Tool listing (`tools/list`), tool execution (`tools/call`), and unknown methods require a verified user email from OIDC authentication. This prevents both anonymous tool enumeration and execution.

### Service Token Must Return 403, Not 401
Returning 401 for service token failures triggers Cloudflare's OAuth re-auth logic. Always return 403 for service token mismatches.

### MCP Server Hostname Must Include /mcp Path
Creating an MCP server with a hostname without a path (origin-only) causes `"Cannot read properties of null"`. Always use `https://worker.workers.dev/mcp`.

### MCP Server Hostname Is Immutable
PUT to update the hostname is silently ignored. You must delete and recreate (but see below).

### Don't Delete+Recreate MCP Servers
Cloudflare's internal OAuth state breaks. Use portal auth to trigger sync instead.

### MCP Notifications Must Return 202
MCP Streamable HTTP transport spec requires 202 Accepted for notifications, not 204 No Content.

### Deploy Script After Token Regeneration
`deploy-worker.sh --set-secrets` must be run after the wizard regenerates service tokens, or the Worker will have stale tokens.

### OIDC id_token Verification
The Worker verifies OIDC id_tokens using Cloudflare Access JWKS. The JWKS is cached for 1 hour. If verification fails (e.g., key rotation), clear the cache and retry.

### Cookie Encryption for Client Approval
The `/authorize` page uses AES-GCM encrypted cookies to pass OAuth state through the OIDC flow. The `COOKIE_ENCRYPTION_KEY` must be 32 bytes (64 hex chars).

### MCP Gateway Must Run Single Worker
The MCP gateway uses `--workers 1` because MCP Streamable HTTP is stateful. The `Mcp-Session-Id` header correlates all requests in a session to in-memory state (`_active_sessions`, `_sse_subscribers`). Multiple workers cause ~50% of requests to hit the wrong worker, resulting in "Session terminated" errors.

### Server Recovery After Sandbox Restart
After a sandbox container restart, all in-memory tool registrations are lost. The `server_recovery.py` background task automatically re-registers all "running" servers on backend/gateway startup. It waits for sandbox health (up to 30 seconds) before attempting recovery.
