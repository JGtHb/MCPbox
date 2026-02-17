# Architecture

## System Overview

MCPbox is a self-extending MCP (Model Context Protocol) platform where LLMs create their own tools. An LLM writes Python code via `mcpbox_create_tool`, that code becomes a permanent MCP tool in a sandboxed executor, and the tool is available for future conversations. The platform runs as a Docker Compose stack designed for homelab self-hosting, with optional Cloudflare Worker integration for remote access from Claude Web.

The system follows a hybrid architecture: the admin panel (React frontend + FastAPI backend) is local-only, while the MCP gateway can optionally be tunnel-exposed via Cloudflare Workers VPC. All user-submitted tool code executes in a shared sandbox with restricted builtins, import whitelisting, and SSRF prevention. Tools must pass an admin approval workflow before becoming available to MCP clients.

## Module Map

### frontend/
- **Purpose**: React 18 admin panel for managing servers, tools, approvals, secrets, tunnel configuration, and activity monitoring
- **Key files**:
  - `src/routes.tsx` — Route definitions (8 pages + OAuth callback)
  - `src/pages/Dashboard.tsx` — System overview with server/tool counts
  - `src/pages/Servers.tsx`, `src/pages/ServerDetail.tsx` — Server CRUD and tool management
  - `src/pages/Approvals.tsx` — Admin approval queue for tools, modules, network access
  - `src/pages/Activity.tsx` — Activity log viewer with WebSocket live stream
  - `src/pages/Settings.tsx` — Global settings and module configuration
  - `src/pages/Tunnel.tsx`, `src/pages/CloudflareWizard.tsx` — Remote access setup
  - `src/api/` — API client functions (one file per domain: servers, tools, activity, etc.)
  - `src/components/` — Reusable UI (ServerList, CodePreview, Layout, shared/ui)
  - `src/hooks/` — Custom hooks (useCopyToClipboard, etc.)
  - `src/lib/constants.ts` — Shared constants (METHOD_COLORS, STATUS_COLORS)
- **Dependencies**: Backend API via HTTP (`VITE_API_URL`), WebSocket for activity stream
- **Dependents**: None (leaf node — user-facing only)
- **External services**: None (all communication through backend API)

### backend/
- **Purpose**: Python FastAPI application providing the admin API (`/api/*`), auth endpoints (`/auth/*`), internal sandbox API (`/internal/*`), and MCP gateway (`/mcp`)
- **Key files**:
  - `app/main.py` — Admin API entry point (port 8000, local-only). Registers all middleware: AdminAuthMiddleware, SecurityHeadersMiddleware, RateLimitMiddleware, CORSMiddleware
  - `app/mcp_only.py` — MCP gateway entry point (port 8002, tunnel-exposed). Only exposes `/mcp` and `/health`. Runs with `--workers 1` for stateful MCP sessions
  - `app/api/router.py` — Aggregates 15 sub-routers under `/api` prefix
  - `app/api/mcp_gateway.py` — MCP Streamable HTTP endpoint, session management, tool aggregation
  - `app/api/approvals.py` — Approval workflow for tools, modules, network access
  - `app/api/servers.py` — Server CRUD + start/stop
  - `app/api/tools.py` — Tool CRUD + versioning
  - `app/api/server_secrets.py` — Encrypted secret management
  - `app/api/execution_logs.py` — Tool execution log viewer
  - `app/api/cloudflare.py` — Cloudflare setup wizard API (tunnel, VPC, Worker, OIDC)
  - `app/api/activity.py` — Activity log + WebSocket stream
  - `app/api/auth.py` — Admin auth (setup, login, refresh, logout)
  - `app/api/internal.py` — Internal endpoints for sandbox (requires SANDBOX_API_KEY)
  - `app/services/mcp_management.py` — 24 MCP management tools (`mcpbox_*` prefix, 1927 lines)
  - `app/services/sandbox_client.py` — HTTP client for sandbox communication (998 lines)
  - `app/services/crypto.py` — AES-256-GCM encryption/decryption with key rotation
  - `app/services/cloudflare.py` — Cloudflare API integration
  - `app/services/tool.py` — Tool business logic (CRUD, versioning, rollback)
  - `app/services/approval.py` — Approval service (approve/reject with audit trail)
  - `app/services/server_recovery.py` — Re-register running servers after sandbox restart
  - `app/services/tool_change_notifier.py` — MCP `tools/list_changed` notification broadcasting
  - `app/services/activity_logger.py` — Activity log recording
  - `app/services/execution_log.py` — Tool execution log recording
  - `app/services/service_token_cache.py` — Service token validation with 30s TTL cache
  - `app/services/url_validator.py` — URL validation and SSRF prevention
  - `app/models/` — 15 SQLAlchemy models (Server, Tool, ToolVersion, ServerSecret, AdminUser, etc.)
  - `app/schemas/` — Pydantic validation schemas
  - `app/core/config.py` — Settings singleton (23 core settings with validators)
  - `app/core/security.py` — JWT + Argon2id auth utilities
  - `app/core/database.py` — Async SQLAlchemy engine and session factory
  - `app/middleware/` — AdminAuth, RateLimit, SecurityHeaders middleware
- **Dependencies**: PostgreSQL (via SQLAlchemy asyncpg), Sandbox (via HTTP), Cloudflare API (optional)
- **Dependents**: Frontend (admin API consumer), Worker (MCP gateway consumer via tunnel), Sandbox (internal API)
- **External services**: PostgreSQL, Cloudflare API (tunnel/VPC/Worker/Access management), Sandbox HTTP API

### sandbox/
- **Purpose**: Isolated Python code execution environment. Receives tool code from backend, executes it with restricted builtins and resource limits, returns results
- **Key files**:
  - `app/main.py` — FastAPI entry point (port 8001, internal network only)
  - `app/routes.py` — Tool execution API: server registration, tool calls, MCP protocol, package management, code execution (1102 lines)
  - `app/executor.py` — Python code executor with safety validation, restricted builtins, module proxy, resource limits (largest file in project)
  - `app/registry.py` — Dynamic tool registration (in-memory registry per server)
  - `app/ssrf.py` — SSRF prevention: IP pinning, private IP blocking, DNS rebinding protection, metadata endpoint blocking
  - `app/mcp_client.py` — MCP protocol client for external MCP source passthrough
  - `app/mcp_session_pool.py` — Connection pooling for external MCP sources
  - `app/package_installer.py` — pip package installation for whitelisted modules
  - `app/osv_client.py` — OSV vulnerability checking for requested packages
  - `app/pypi_client.py` — PyPI package metadata client
- **Dependencies**: None (receives all data via HTTP from backend/gateway)
- **Dependents**: Backend (tool execution), MCP Gateway (tool execution)
- **External services**: PyPI (package installation), OSV API (vulnerability checks), external MCP servers (passthrough)

### worker/
- **Purpose**: Cloudflare Worker acting as OAuth 2.1 proxy between MCP clients (Claude Web) and the MCPbox MCP gateway. Handles authentication, OIDC identity verification, and request proxying via Workers VPC
- **Key files**:
  - `src/index.ts` — Worker entry point with OAuth 2.1 provider, URL rewriting, CORS, rate limiting, client auto-registration (471 lines)
  - `src/access-handler.ts` — OIDC upstream handler: Cloudflare Access for SaaS authentication, id_token verification (RS256, JWKS)
  - `wrangler.toml` — Worker configuration (generated by deploy-worker.sh, gitignored)
- **Dependencies**: MCP Gateway (via Workers VPC binding), Cloudflare Access (OIDC provider)
- **Dependents**: MCP clients (Claude Web, etc.)
- **External services**: Cloudflare Access (OIDC), Cloudflare KV (OAuth token storage)

### alembic/
- **Purpose**: Database migration management. 33+ migrations tracking schema evolution from project foundation through current features
- **Key files**:
  - `alembic.ini` — Migration configuration
  - `versions/` — Migration files (0001 through 0033+)
- **Dependencies**: PostgreSQL, Backend models
- **Dependents**: Backend (requires migrations applied before startup)

### scripts/
- **Purpose**: Development and deployment automation
- **Key files**:
  - `pre-pr-check.sh` — Pre-PR validation (format, lint, tests for all components)
  - `deploy-worker.sh` — Cloudflare Worker deployment with secret injection
  - `validate_imports.py` — Import validation checker
  - `rotate_encryption_key.py` — Encryption key rotation utility
- **Dependencies**: ruff, pytest, npm, wrangler
- **Dependents**: CI/CD pipeline, developer workflow

### cloudflared/
- **Purpose**: Cloudflare tunnel daemon container configuration
- **Key files**:
  - `Dockerfile` — cloudflared binary with entrypoint script
  - `entrypoint.sh` — Fetches tunnel token from backend, starts tunnel
- **Dependencies**: Backend (fetches tunnel token via internal API)
- **Dependents**: Worker (tunnel is VPC binding target)

## Data Flow

### MCP Request Lifecycle (Local Mode)

1. Claude Desktop sends MCP JSON-RPC request to `http://localhost:8000/mcp`
2. Backend MCP gateway (`mcp_gateway.py`) receives request
3. No auth required in local mode (no service token in database)
4. Gateway parses MCP method:
   - `initialize` → Returns server capabilities
   - `tools/list` → Queries all running servers, aggregates approved tools from sandbox registry
   - `tools/call` → Routes to sandbox for execution
5. For `tools/call`: Gateway sends HTTP POST to `sandbox:8001/tools/{name}/call`
6. Sandbox executor validates code safety, sets up restricted builtins, executes Python code
7. Result flows back: Sandbox → Gateway → Claude Desktop

### MCP Request Lifecycle (Remote Mode)

1. Claude Web sends MCP request to Worker URL (`mcpbox-proxy.you.workers.dev`)
2. Worker validates OAuth 2.1 token
3. Worker extracts user email from OIDC token props
4. Worker proxies to MCP Gateway via Workers VPC binding with `X-MCPbox-Service-Token` and `X-MCPbox-User-Email` headers
5. MCP Gateway validates service token (constant-time comparison, fail-closed)
6. Gateway processes request same as local mode (steps 4-7 above)
7. Response flows back: Sandbox → Gateway → Worker → Claude Web

### Tool Creation Flow

1. LLM calls `mcpbox_create_server` → Backend creates server record (status: stopped)
2. LLM calls `mcpbox_create_tool` → Backend creates tool record (status: draft)
3. LLM calls `mcpbox_test_code` → Backend sends code to sandbox for test execution
4. LLM calls `mcpbox_request_publish` → Tool moves to `pending_review`
5. Admin reviews at `/approvals` UI → Approves or rejects
6. If approved: Backend calls `mcpbox_start_server` → Registers tools with sandbox → `tools/list_changed` notification sent to all connected MCP clients

## Key Design Decisions

1. **MCP-First Architecture**: Tools are created programmatically by external LLMs via `mcpbox_*` MCP tools, not via visual builders or embedded LLM. This avoids API key management and leverages existing Claude access.

2. **Separate MCP Gateway**: Runs as independent Docker service (`app.mcp_only:app` on port 8002). The tunnel-exposed service physically cannot serve admin endpoints — defense in depth.

3. **Shared Sandbox**: Single sandbox container for all tool execution. Tradeoff: lower resource usage and no docker.sock exposure, but tools share the same process space (isolated via application-level restrictions).

4. **Hybrid Auth Model**: Local mode has no auth (localhost trust). Remote mode uses OAuth 2.1 + OIDC + service token (three layers). Method-level authorization: `initialize` and `notifications/*` allowed without verified email; `tools/list` and `tools/call` require verified email.

5. **Human-in-the-Loop**: All tools start as drafts. Admin approval required before tools become callable. Module whitelisting and network access also require approval.

6. **AES-256-GCM Secret Encryption**: Server secrets encrypted at rest with per-value random IV. Secrets injected as read-only `MappingProxyType` dict at execution time. Values never flow through LLMs.

7. **Workers VPC (No Public Hostname)**: The tunnel has no public URL. Only the Cloudflare Worker can access it via VPC binding, eliminating public attack surface.

8. **Single Worker Process**: MCP gateway runs `--workers 1` because MCP sessions are stateful (in-memory `_active_sessions` dict). Multiple workers would cause ~50% session mismatches.

## Identified Issues

### Orphaned / Vestigial Code
- **Server model enum values**: `ServerStatus.building`, `NetworkMode.monitored`, `NetworkMode.learning` are defined but never set in code. Kept for database enum compatibility but should be marked deprecated.
- **Setting model**: `backend/app/models/setting.py` exists with encrypted value support but is minimally used. Appears designed for future feature toggles.
- **`frontend/src/api/types.ts`**: Contains only `HealthResponse` — all other types are defined inline in page/component files rather than in this shared types file.

### Architectural Concerns
- **Stdout race condition**: `sandbox/app/executor.py` globally replaces `sys.stdout` during execution. Concurrent tool executions in the same process can have output leakage. Should override `print` builtin instead.
- **MCP client SSRF gap**: `sandbox/app/mcp_client.py` uses `curl_cffi.AsyncSession` without SSRF URL validation and with `follow_redirects=True`. External MCP sources could redirect to internal IPs.
- **Tool approval TOCTOU**: Updating `python_code` on an approved tool does not reset `approval_status`. An approved tool's code can be changed without re-review (see [SECURITY.md](SECURITY.md#sec-001)).
- **Rollback preserves approval**: Rolling back to a different code version maintains the approved status (see [SECURITY.md](SECURITY.md#sec-002)).

### Inconsistencies
- **HTTPException style**: Some API endpoints use `status.HTTP_404_NOT_FOUND` (enum), others use `404` (integer literal). Not functionally different but inconsistent.
- **Type annotation style**: Mix of `Optional[Type]` (old) and `Type | None` (Python 3.10+) across service files.
- **Route prefix double-nesting**: `/api/settings/settings` endpoint has a doubled prefix due to router configuration in `settings.py`.

See [INCONSISTENCIES.md](INCONSISTENCIES.md) for the complete technical debt inventory.
