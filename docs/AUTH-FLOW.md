# Auth Flow Reference

Complete reference for the MCPbox authentication and authorization flow across the Worker (TypeScript) and Gateway (Python).

## 1. Architecture Overview

Three actors access the MCP endpoint through different paths:

```
                         ┌─────────────────────┐
 Cloudflare Sync ──────►│                     │
 (OAuth only,            │  Cloudflare Worker  │──VPC──► MCP Gateway (/mcp)
  no JWT)                │  (OAuth 2.1 proxy)  │
                         │                     │
 MCP Portal User ──────►│  Verifies JWT +     │
 (OAuth + JWT)           │  adds headers       │
                         └─────────────────────┘

 Local User ────────────────────────────────────► MCP Gateway (/mcp)
 (no auth)                                        (port 8000, localhost only)
```

| Actor | Path | OAuth Token | JWT | Service Token |
|-------|------|-------------|-----|---------------|
| **Cloudflare Sync** | Worker → VPC → Gateway | Yes (auto) | No | Yes (Worker adds) |
| **MCP Portal User** | Worker → VPC → Gateway | Yes (auto) | Yes (Cf-Access) | Yes (Worker adds) |
| **Local User** | Direct to Gateway | No | No | No |

## 2. Worker Request Routing

### URL Rewriting

The Worker uses `OAuthProvider` with `apiRoute: '/oauth-protected-api'` (an internal-only path). Real MCP requests arrive at `/` or `/mcp` and are rewritten before reaching OAuthProvider:

```
Client request         → Rewritten to            → Handler
─────────────────────────────────────────────────────────────
POST /                 → /oauth-protected-api     → apiHandler (OAuth validated)
POST /mcp              → /oauth-protected-api     → apiHandler (OAuth validated)
GET /authorize         → (not rewritten)          → defaultHandler
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

**Dynamic pattern:**
- `https://${MCP_PORTAL_HOSTNAME}/*` (if env var is set)

Unrecognized redirect URIs are rejected with 400.

## 3. Gateway Authentication

### `verify_mcp_auth()` Decision Tree

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
    ┌────────────┐  ┌──────────┐
    │ Verify JWT │  │ 403      │
    │ server-    │  │ (fail    │
    │ side       │  │ closed)  │
    └──────┬─────┘  └──────────┘
           │
    ┌──────┴──────┐
    │             │
  Valid JWT    No/Invalid JWT
    │             │
    ▼             ▼
 source=worker  ┌──────────────────┐
 auth=jwt       │ Has Worker-      │
 email=<jwt>    │ supplied email?  │
                │ (X-MCPbox-User-  │
                │  Email header)   │
                └──────┬───────────┘
                ┌──────┴──────┐
                │             │
               Yes           No
                │             │
                ▼             ▼
             source=worker  source=worker
             auth=oauth     auth=oauth
             email=<props>  email=None
```

**Key points:**
- Service token comparison uses `secrets.compare_digest` (constant-time)
- Database/decryption errors → fail-closed (auth enabled, no valid token → all requests rejected)
- JWT verification is server-side using JWKS from Cloudflare Access (RS256)
- JWT-verified email takes precedence over Worker-supplied email
- When no JWT is present but service token is valid, the gateway trusts Worker-supplied `X-MCPbox-User-Email` (from encrypted OAuth token props — the Worker verified the JWT at authorization time)
- Email freshness is bounded by OAuth token TTL

### Rate Limiting

Failed auth attempts are tracked per IP. After 10 failures in 60 seconds, the IP gets 429 responses.

## 4. Method Authorization

The gateway uses `_is_anonymous_remote` flag to control per-method access:

```python
_is_anonymous_remote = _user.source == "worker" and not _user.email
```

A remote request is "anonymous" when it has no verified user email — either from server-side JWT verification or from OAuth token props (email embedded at MCP Portal authorization time). This blocks both Cloudflare sync (no user context) and direct Worker access without Portal authentication.

### Per-Method Authorization Table

| Method | Local User | Portal User (email) | Anonymous Remote (no email) |
|--------|-----------|---------------------|----------------------------|
| `initialize` | Allowed | Allowed | **Allowed** |
| `tools/list` | Allowed | Allowed | **Allowed** |
| `notifications/*` | Allowed (202) | Allowed (202) | **Allowed** (202) |
| `tools/call` | Allowed | Allowed | **Blocked** (-32600) |
| Unknown methods | Allowed (forwarded) | Allowed (forwarded) | **Blocked** (-32600) |

User email for authorization and audit logging comes from:
1. **JWT at request time** (strongest — verified on each request)
2. **OAuth token props** (verified at authorization time, bounded by token TTL)
3. **None** (Cloudflare sync or direct Worker access without Portal — blocked from tool execution)

### Destructive Tool Restrictions

Even with JWT auth, some management tools are local-only:

| Tool | Local | Remote (any auth) |
|------|-------|-------------------|
| `mcpbox_delete_server` | Allowed | **Blocked** (local-only) |
| `mcpbox_delete_tool` | Allowed | **Blocked** (local-only) |
| All other `mcpbox_*` | Allowed | Allowed |
| Sandbox tools | Allowed | Allowed |

## 5. Worker Secrets

Secrets are pushed to the Worker at different wizard steps:

| Secret | First set at | Re-synced at | Source |
|--------|-------------|-------------|--------|
| `MCPBOX_SERVICE_TOKEN` | Step 4 (deploy Worker) | Step 7 (sync secrets) | Generated in `deploy_worker()` |
| `CF_ACCESS_TEAM_DOMAIN` | Step 7 (sync secrets) | — | From Cloudflare Access |
| `CF_ACCESS_AUD` | Step 7 (sync secrets) | — | From Access application (portal AUD) |
| `MCP_PORTAL_HOSTNAME` | Step 7 (sync secrets) | — | From `create_mcp_portal()` (step 6) |

Step 7 runs automatically at the end of step 6 (`create_mcp_portal`) if all required values are available. The `_sync_worker_secrets` function pushes all secrets. The deploy script (`scripts/deploy-worker.sh --set-secrets`) can also push them for re-deployment after code changes.

**Important:** After the wizard regenerates a service token (e.g., re-running setup), you must either re-run the wizard to step 7 or run `deploy-worker.sh --set-secrets` to sync the new token to the Worker.

## 6. Common Pitfalls

### apiRoute Prefix Matching (Bug #1)
`OAuthProvider.matchApiRoute` uses `startsWith()`. Setting `apiRoute: '/'` catches `/authorize`, `/token`, etc. **Fix:** Use a dummy internal path (`/oauth-protected-api`) and rewrite `/` and `/mcp` to it.

### /mcp Path Must Be Rewritten (Bug #4)
Cloudflare sync sends requests to `/mcp`, not `/`. The URL rewriting must handle both paths: `if (url.pathname === '/' || url.pathname === '/mcp')`.

### Redirect URI Allowlist (Bug #3, #6)
The Cloudflare dashboard (`one.dash.cloudflare.com`) and the MCP Portal hostname must be in the redirect URI allowlist. The portal hostname is dynamic per deployment, so it's checked via the `MCP_PORTAL_HOSTNAME` env var.

### Sync Methods Work Without Email, Tool Execution Requires Email (Bug #5)
Cloudflare's MCP server sync authenticates via OAuth only (no Cf-Access-Jwt-Assertion, no email). Sync-only methods (`initialize`, `tools/list`, `notifications/*`) are allowed with a valid service token. Tool execution (`tools/call`) and unknown methods require a verified user email — either from server-side JWT verification or from OAuth token props (email embedded at MCP Portal authorization time). This prevents anonymous tool execution by users who bypass the MCP Portal's Access Policy.

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
