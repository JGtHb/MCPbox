# MCPbox Architecture

> A self-extending MCP platform where LLMs create their own tools — self-hosted for homelabs, with optional secure remote access via Cloudflare.

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Security Model](#security-model)
4. [Component Details](#component-details)
5. [Data Flow](#data-flow)
6. [Database Schema](#database-schema)
7. [API Specification](#api-specification)
8. [Design Decisions](#design-decisions)

---

## Overview

### What MCPbox Does

MCPbox is a self-hosted platform where LLMs extend their own capabilities by writing tools. The LLM writes Python code, that code becomes a permanent MCP tool, and the tool is available for future conversations. A single Docker deployment provides:

1. **Self-Extending Tool Creation** - LLMs write Python code via `mcpbox_create_tool` that becomes permanent, callable MCP tools
2. **Human-in-the-Loop Approval** - All tools start as drafts; admins review and approve before publishing
3. **Sandboxed Execution** - Tool code runs in a hardened sandbox with restricted builtins, import whitelisting, and SSRF prevention
4. **Remote Access** - Optional Cloudflare Worker + tunnel integration for remote MCP client access

### Design Principles

- **LLM as Toolmaker**: The LLM authors tools via `mcpbox_*` MCP tools — no embedded LLM, no visual builders, no API spec import.
- **Code-First**: All tools are Python code with `async def main()` entry points.
- **Human-in-the-Loop**: Admin approval required before any tool goes live. Module and network access whitelisted individually.
- **Sandbox by Default**: All tool code runs in a hardened shared sandbox with resource limits.
- **Homelab-First**: Single `docker compose up`, no Kubernetes required.
- **Hybrid Architecture**: Local-first with optional remote access via Cloudflare Workers VPC.

### Hybrid Architecture

MCPbox uses a **hybrid architecture** - local-first with optional remote access via Cloudflare Workers VPC:

- **Admin Panel**: Accessible locally only (ports bound to 127.0.0.1). JWT authentication required (defense-in-depth).
- **MCP Gateway (/mcp)**:
  - **Local mode**: No authentication required (for local MCP clients via localhost)
  - **Remote mode**: Exposed via Cloudflare Workers VPC tunnel with service token authentication

**Key security properties:**
- The tunnel has **no public hostname** - it's only accessible via Cloudflare Worker through Workers VPC
- The Worker enforces **OAuth 2.1 authentication** via `@cloudflare/workers-oauth-provider` -- all /mcp requests require a valid OAuth token
- User identity is verified via **OIDC upstream** (Cloudflare Access for SaaS) -- email comes from a verified id_token at authorization time
- Requests without a verified email (e.g., Cloudflare sync) are **sync-only** (can list tools, but cannot execute them)
- MCPbox validates the service token as defense-in-depth
- Unauthenticated requests to the Worker are rejected with 401

---

## System Architecture

### High-Level Diagram

```
+---------------------------------------------------------------------------+
|                              HOMELAB NETWORK                               |
|                                                                            |
|  +---------------------------------------------------------------------+  |
|  |                         MCPbox (Docker Compose)                      |  |
|  |                                                                      |  |
|  |   LOCAL / REVERSE PROXY                    PRIVATE TUNNEL           |  |
|  |   +----------+  +--------------+           +--------------+         |  |
|  |   | Frontend |->|   Backend    |           | MCP Gateway  |         |  |
|  |   | (nginx)  |  |  (FastAPI)   |           | (FastAPI)    |<-- cloudflared
|  |   | :3000    |  |  :8000       |           | :8002        |   (no public URL)
|  |   +----------+  |  /api/*      |           | /mcp ONLY    |         |  |
|  |   nginx proxies  +------+------+           +------+-------+         |  |
|  |   /api,/auth,/health    |                         |                 |  |
|  |                         |                         |                 |  |
|  |                         +---------+---------------+                 |  |
|  |                                   |                                 |  |
|  |   +------------+     +--------------------------+                   |  |
|  |   | PostgreSQL |     |     Shared Sandbox       |                   |  |
|  |   |   :5432    |     |        :8001             |                   |  |
|  |   +------------+     +--------------------------+                   |  |
|  |                                                                      |  |
|  +----------------------------------------------------------------------+  |
|                                                                            |
|  Admin panel: frontend proxies /api/* to backend (works behind reverse proxy) |
|                                                                            |
+---------------------------------------------------------------------------+
                                        |
                                        | Workers VPC (private)
                                        |
+---------------------------------------+-----------------------------------+
|                            Cloudflare (Optional)                           |
|                                                                            |
|  +--------------------------------------------------------------------+   |
|  |                    Cloudflare Worker                                |   |
|  |              (mcpbox-proxy.you.workers.dev)                        |   |
|  |                                                                     |   |
|  |  - @cloudflare/workers-oauth-provider wrapper                      |   |
|  |  - OAuth 2.1 (downstream to MCP clients)                          |   |
|  |  - OIDC upstream to Cloudflare Access for SaaS (user identity)    |   |
|  |  - Accesses tunnel via Workers VPC binding (private)               |   |
|  |  - Adds X-MCPbox-Service-Token header                              |   |
|  |  - Sets X-MCPbox-User-Email from OIDC-verified id_token           |   |
|  +--------------------------------------------------------------------+   |
|                                        ^                                   |
|                                        | MCP Protocol (HTTPS)              |
|                                        |                                   |
+----------------------------------------+----------------------------------+
                                         |
                     MCP Clients (Claude, ChatGPT, etc.)
```

### Container Architecture

```yaml
services:
  frontend        # React web UI (127.0.0.1:3000)
  backend         # Python FastAPI admin API (127.0.0.1:8000)
  mcp-gateway     # Separate FastAPI service for /mcp (internal :8002, tunnel-exposed)
  sandbox         # Shared sandbox for tool execution (internal :8001)
  postgres        # Configuration and state storage (internal :5432)
  cloudflared     # Cloudflare tunnel daemon (optional, requires tunnel token)
```

### Docker Networks

| Network | Services | Internal | Purpose |
|---------|----------|----------|---------|
| `mcpbox-internal` | frontend, backend, mcp-gateway, cloudflared | No | Service communication (nginx proxy, tunnel) |
| `mcpbox-sandbox` | backend, mcp-gateway, sandbox | Yes | Sandbox access (no external egress) |
| `mcpbox-sandbox-proxy` | sandbox, squid-proxy | Yes | Sandbox → squid proxy (all outbound traffic) |
| `mcpbox-sandbox-external` | squid-proxy | No | Squid outbound to internet (sandbox NOT on this network) |
| `mcpbox-db` | backend, mcp-gateway, postgres | Yes | Database access (no external egress) |

---

## Security Model

### Trust Boundaries

```
+-----------------------------------------------------------------+
| TRUSTED: Your Infrastructure                                     |
|  - MCPbox containers (frontend, backend, gateway, postgres)     |
|  - Cloudflare tunnel                                             |
|  - Your network                                                  |
+-----------------------------------------------------------------+
                              |
                              v
+-----------------------------------------------------------------+
| UNTRUSTED: User-Created Tool Code                                |
|  - Python code submitted via mcpbox_create_tool                 |
|  - Runs in shared sandbox with restricted builtins              |
+-----------------------------------------------------------------+
```

### Sandbox Security

Tool code runs in a shared sandbox container with application-level protections:

**Builtin Restrictions:**
- Dangerous builtins removed: `type()`, `getattr()`, `setattr()`, `eval()`, `exec()`, `compile()`, `open()`
- Discovery functions blocked: `vars()`, `dir()`
- Dunder attribute access blocked via regex: `__class__`, `__mro__`, `__bases__`, `__subclasses__`, `__globals__`, `__code__`, `__builtins__`, `__import__`, `__loader__`, `__spec__`

**Import Restrictions:**
- Whitelist-based module restriction (configurable via admin UI)
- Default allowed: `json`, `math`, `datetime`, `regex`, `hashlib`, `base64`, `urllib.parse`, etc. (note: `re` is excluded — `regex` is a timeout-protected wrapper that prevents ReDoS)
- Blocked: `os`, `subprocess`, `sys`, `importlib`, `ctypes`, etc.

**Resource Limits:**
- 256MB memory limit
- 60-second CPU timeout
- 256 file descriptor limit
- 1MB output cap

**Network Security:**
- SSRF prevention with IP pinning, private IP blocking, DNS rebinding protection
- Per-server allowed hosts configuration
- `httpx.AsyncClient` provided with `follow_redirects=False` to prevent redirect-based SSRF

**Code Safety Validation:**
- `validate_code_safety()` called on all execution paths
- Regex-based detection of forbidden patterns before `exec()`

### MCP-First Tool Creation

Tools are created programmatically by external LLMs via `mcpbox_*` MCP tools:

```
+-----------------------------------------------------------------+
|                  TOOL CREATION WORKFLOW                           |
+-----------------------------------------------------------------+
|                                                                  |
|  1. LLM creates server with mcpbox_create_server               |
|                                                                  |
|  2. LLM creates tool with mcpbox_create_tool (draft status)    |
|     +-> Python code with async def main() entry point           |
|                                                                  |
|  3. LLM tests code with mcpbox_test_code                       |
|     +-> Validates execution in sandbox without saving           |
|                                                                  |
|  4. LLM validates code with mcpbox_validate_code               |
|     +-> Checks syntax, module usage, security constraints       |
|                                                                  |
|  5. LLM requests publish with mcpbox_request_publish            |
|     +-> Tool moves to pending_review status                     |
|                                                                  |
|  6. Admin reviews in UI at /approvals                           |
|     +-> Approves or rejects with reason                         |
|                                                                  |
|  7. If approved, tool becomes available in tools/list           |
|     If rejected, LLM can revise and re-submit                   |
|                                                                  |
+-----------------------------------------------------------------+
```

### Server Secrets

```
+-----------------------------------------------------------------+
|                   SECRET STORAGE                                  |
+-----------------------------------------------------------------+
|                                                                  |
|  PostgreSQL (encrypted at rest)                                  |
|  +-> Per-server key-value secrets (AES-256-GCM encrypted)       |
|                                                                  |
|  Encryption key: MCPBOX_ENCRYPTION_KEY env variable              |
|  +-> User provides: openssl rand -hex 32                        |
|  +-> Per-value random IV, authenticated encryption              |
|                                                                  |
|  Workflow:                                                       |
|  +-> LLM creates placeholder: mcpbox_create_server_secret       |
|  +-> Admin sets actual value in web UI                          |
|  +-> Values NEVER flow through LLMs                             |
|                                                                  |
|  Secrets passed to sandbox via:                                  |
|  +-> secrets["KEY_NAME"] dict at execution time                 |
|                                                                  |
|  Secret scoping:                                                 |
|  +-> Each MCP server has its own secret namespace               |
|  +-> Server A cannot access Server B's secrets                  |
|                                                                  |
+-----------------------------------------------------------------+
```

---

## Component Details

### 1. Frontend (React + TypeScript)

```
frontend/
+-- src/
|   +-- components/
|   |   +-- ServerList/          # List of MCP servers
|   |   +-- CodePreview/         # Code viewer for tools
|   |   +-- Server/              # Server management components
|   |   +-- Tunnel/              # Cloudflare tunnel health
|   |   +-- Layout/              # App layout components
|   |   +-- shared/              # Shared components
|   |   +-- ui/                  # Base UI components
|   +-- pages/                   # Route components
|   +-- api/                     # Backend API client
+-- package.json
+-- Dockerfile
```

**Key Libraries:**
- React 18 + TypeScript
- TanStack Query (data fetching)
- React Router (navigation)
- Tailwind CSS (styling)

### 2. Backend (Python + FastAPI)

```
backend/
+-- app/
|   +-- main.py                  # FastAPI application (admin API)
|   +-- mcp_only.py              # MCP gateway application (separate service)
|   +-- api/
|   |   +-- router.py            # Aggregates all /api routes
|   |   +-- servers.py           # MCP server CRUD
|   |   +-- tools.py             # Tool management
|   |   +-- sandbox.py           # Sandbox management
|   |   +-- tunnel.py            # Tunnel configuration
|   |   +-- cloudflare.py        # Cloudflare setup wizard API
|   |   +-- mcp_gateway.py       # MCP gateway routes (/mcp)
|   |   +-- approvals.py         # Tool/module approval endpoints
|   |   +-- server_secrets.py    # Server secret management
|   |   +-- execution_logs.py    # Tool execution log viewer
|   |   +-- activity.py          # Activity logging + WebSocket
|   |   +-- dashboard.py         # Dashboard stats
|   |   +-- export_import.py     # Server/tool export/import
|   |   +-- settings.py          # App settings
|   |   +-- config.py            # Server config endpoints
|   +-- services/
|   |   +-- mcp_management.py    # MCP management tools (mcpbox_*)
|   |   +-- cloudflare.py        # Cloudflare API integration
|   |   +-- crypto.py            # AES-256-GCM secret encryption
|   |   +-- sandbox_client.py    # HTTP client for sandbox communication
|   |   +-- server_secret.py     # Server secret service
|   |   +-- execution_log.py     # Tool execution logging
|   |   +-- server_recovery.py   # Re-register running servers on startup
|   |   +-- tool_change_notifier.py # MCP tools/list_changed notifications
|   |   +-- ...
|   +-- models/
|   |   +-- server.py            # Server model
|   |   +-- tool.py              # Tool model
|   |   +-- server_secret.py     # Encrypted server secrets
|   |   +-- tool_execution_log.py # Tool execution log
|   |   +-- activity_log.py      # Activity log model
|   |   +-- admin_user.py        # Admin user model
|   |   +-- cloudflare_config.py # Cloudflare wizard state
|   |   +-- tunnel_configuration.py # Named tunnel configs
|   |   +-- ...
|   +-- core/
|       +-- config.py            # Settings
|       +-- security.py          # Auth utilities (JWT, Argon2id)
|       +-- database.py          # DB connection
|       +-- shared_lifespan.py   # Shared lifespan for backend + gateway
|       +-- logging.py           # Logging configuration
+-- alembic/                     # Database migrations
+-- requirements.txt
+-- Dockerfile
```

**Key Libraries:**
- FastAPI (web framework)
- SQLAlchemy (async ORM)
- cryptography (AES-256-GCM secret encryption)
- httpx (async HTTP client)
- argon2-cffi (password hashing)

### 3. MCP Gateway (Separate Service)

The MCP gateway runs as a **separate Docker service** (`mcp-gateway:8002`) using `app.mcp_only:app`. It shares the backend codebase but only exposes `/mcp` and `/health` endpoints. This ensures the tunnel can **never** reach admin API endpoints.

**Responsibilities:**
- Terminate MCP Streamable HTTP connections from MCP clients (stateful sessions via `Mcp-Session-Id`)
- Validate service token header (remote mode) or allow all (local mode)
- Trust Worker-supplied `X-MCPbox-User-Email` header (when valid service token is present)
- Proxy tool execution requests to the sandbox
- Aggregate tool listings from all enabled servers
- Broadcast `tools/list_changed` notifications when tools change
- Log all requests for observability

**Important:** Runs with `--workers 1` because MCP sessions are stateful (in-memory `_active_sessions` dict). Multiple workers would cause ~50% of requests to hit the wrong worker.

### 4. Sandbox (Python Tool Execution)

```
sandbox/
+-- app/
|   +-- routes.py              # Tool execution API, /execute endpoint
|   +-- registry.py            # Dynamic tool registration
|   +-- executor.py            # Python code execution with safety checks
|   +-- ssrf.py                # SSRF prevention for HTTP clients
|   +-- osv_client.py          # OSV vulnerability checking for modules
|   +-- pypi_client.py         # PyPI package info client
+-- requirements.txt
+-- Dockerfile
```

### 5. Cloudflare Worker (MCP Proxy)

```
worker/
+-- src/
|   +-- index.ts               # Worker code with OAuth 2.1 provider
|   +-- access-handler.ts      # OIDC upstream auth handler (Cloudflare Access for SaaS)
+-- wrangler.toml              # Generated by deploy-worker.sh (gitignored)
+-- package.json
```

**Security features:**
- Wrapped with `@cloudflare/workers-oauth-provider`
- Path whitelist: only `/mcp` and `/health` allowed
- OIDC upstream: verifies id_token from Cloudflare Access (RS256, JWKS, iss/aud/nonce/exp/nbf)
- CORS restricted to known MCP client domains (Claude, ChatGPT, OpenAI, Cloudflare)
- Service token injection (`X-MCPbox-Service-Token`)
- User email from OIDC id_token stored in encrypted OAuth token props, set as `X-MCPbox-User-Email`
- Auth method is always `oidc`

### 6. MCP Management Tools

MCPbox exposes 28 management tools with the `mcpbox_` prefix:

| Category | Tools |
|----------|-------|
| Servers | `list_servers`, `get_server`, `create_server`, `delete_server`, `start_server`, `stop_server`, `get_server_modules` |
| Tools | `list_tools`, `get_tool`, `create_tool`, `update_tool`, `delete_tool` |
| Versioning | `list_tool_versions`, `rollback_tool` |
| Development | `test_code`, `validate_code` |
| Secrets | `create_server_secret`, `list_server_secrets` |
| Approval | `request_publish`, `request_module`, `request_network_access`, `get_tool_status`, `list_pending_requests` |
| Observability | `get_tool_logs` |

See `docs/MCP-MANAGEMENT-TOOLS.md` for complete documentation.

---

## Data Flow

### MCP Request Flow

```
                        LOCAL MODE                         REMOTE MODE
                        ----------                         -----------
Local MCP Client                          Remote MCP Client
    |                                             |
    | HTTP (localhost)                            | MCP Protocol (HTTPS)
    |                                             v
    |                                     Cloudflare Worker
    |                                     (OAuth 2.1 + OIDC upstream)
    |                                             |
    |                                             | + X-MCPbox-Service-Token
    |                                             | + X-MCPbox-User-Email (from OIDC)
    |                                             v
    |                                     Workers VPC Binding (private)
    |                                             |
    +-----------------+---------------------------+
                      |
                      v
          MCP Gateway (mcp-gateway:8002)
                      |
                      +-> Validate service token (remote mode)
                      +-> Allow all (local mode)
                      +-> Parse MCP request
                      |
                      v
          +-------------------------------------+
          |         Request Router              |
          +-------------------------------------+
          | initialize  -> Return capabilities  |
          | tools/list  -> Aggregate all servers|
          | tools/call  -> Route to sandbox     |
          +-------------------------------------+
                      |
                      | HTTP (internal sandbox network)
                      v
          Shared Sandbox (:8001)
                      |
                      | Execute Python code
                      |
                      v
          Response back through chain
```

### Tool Aggregation

The gateway queries all enabled servers and merges their tool lists. Tool names are prefixed with the server name to avoid collisions (e.g., `github.create_issue`, `docker.list_containers`).

---

## Database Schema

MCPbox uses PostgreSQL with SQLAlchemy async ORM. Key tables:

### Core Tables

| Table | Purpose |
|-------|---------|
| `servers` | MCP server definitions (name, status, allowed_hosts, allowed_modules) |
| `tools` | Tool definitions (name, description, python_code, input_schema, status) |
| `tool_versions` | Version history for tools |
| `server_secrets` | Encrypted per-server key-value secrets (AES-256-GCM) |
| `admin_users` | Admin panel users (JWT auth) |
| `settings` | Application settings (key-value) |
| `global_configs` | Global configuration (allowed modules, etc.) |

### Activity & Observability

| Table | Purpose |
|-------|---------|
| `activity_logs` | All system activity (tool calls, server changes, etc.) |
| `tool_execution_logs` | Per-tool execution logs (args, results, errors, duration) |

### Approval Workflow

| Table | Purpose |
|-------|---------|
| `module_requests` | Pending module whitelist requests |
| `network_access_requests` | Pending network access requests |

### Tunnel & Cloudflare

| Table | Purpose |
|-------|---------|
| `tunnel_configurations` | Named tunnel configurations |
| `cloudflare_configs` | Cloudflare wizard state (tunnel, VPC, Worker, Access for SaaS OIDC) |

---

## API Specification

### Admin API (`/api/*` - local only)

**Server Management:**
```
GET    /api/servers                              # List all servers (paginated)
POST   /api/servers                              # Create server
GET    /api/servers/{id}                         # Get server details
PATCH  /api/servers/{id}                         # Update server
DELETE /api/servers/{id}                         # Delete server
```

**Sandbox Control:**
```
POST   /api/sandbox/servers/{id}/start           # Start server (register with sandbox)
POST   /api/sandbox/servers/{id}/stop            # Stop server (unregister)
POST   /api/sandbox/servers/{id}/restart         # Restart server
GET    /api/sandbox/servers/{id}/status           # Get sandbox status
GET    /api/sandbox/servers/{id}/logs             # Get sandbox logs
```

**Tool Management:**
```
GET    /api/servers/{id}/tools                   # List tools for server
POST   /api/servers/{id}/tools                   # Create tool
GET    /api/tools/{id}                           # Get tool details
PATCH  /api/tools/{id}                           # Update tool
DELETE /api/tools/{id}                           # Delete tool
GET    /api/tools/{id}/versions                  # List tool versions
POST   /api/tools/{id}/versions/{ver}/rollback   # Rollback to version
```

**Server Secrets:**
```
GET    /api/servers/{id}/secrets                  # List secrets (keys + has_value, no values)
POST   /api/servers/{id}/secrets                  # Create secret placeholder
PUT    /api/servers/{id}/secrets/{key_name}       # Set secret value (admin only)
DELETE /api/servers/{id}/secrets/{key_name}       # Remove secret
```

**Execution Logs:**
```
GET    /api/execution-logs                       # List all execution logs (paginated)
GET    /api/execution-logs/stats                 # Execution log statistics
GET    /api/tools/{id}/logs                      # Get logs for a tool
GET    /api/servers/{id}/execution-logs           # Get logs for a server
```

**Approval Workflow:**
```
GET    /api/approvals/stats                      # Approval statistics
GET    /api/approvals/tools                      # List pending tool approvals
POST   /api/approvals/tools/{id}/action          # Approve or reject tool
GET    /api/approvals/modules                    # List pending module requests
POST   /api/approvals/modules/{id}/action        # Approve or reject module
GET    /api/approvals/network                    # List pending network requests
POST   /api/approvals/network/{id}/action        # Approve or reject network access
```

**Tunnel & Cloudflare:**
```
GET    /api/tunnel/status                        # Get tunnel status
POST   /api/tunnel/configurations                # Save tunnel configuration
GET    /api/cloudflare/status                    # Get Cloudflare wizard status
POST   /api/cloudflare/api-token                 # Verify Cloudflare API token
POST   /api/cloudflare/tunnel                    # Create tunnel
POST   /api/cloudflare/vpc-service               # Create VPC service
POST   /api/cloudflare/worker                    # Deploy Worker
PUT    /api/cloudflare/access-policy             # Configure Access for SaaS (OIDC)
```

**Other:**
```
GET    /api/activity/logs                        # Activity log (paginated)
WS     /api/activity/stream                      # WebSocket live activity stream
GET    /api/dashboard                            # Dashboard statistics
GET    /api/export/servers                       # Export all servers/tools
POST   /api/export/import                        # Import servers/tools
GET    /api/settings                             # Get app settings
PATCH  /api/settings/security-policy             # Update security policy settings
```

### MCP Gateway (`/mcp` - local + tunnel)

```
POST   /mcp                              # MCP Streamable HTTP endpoint
GET    /mcp                              # SSE stream for server-to-client notifications
GET    /health                           # Health check
```

---

## Design Decisions

### MCP-First Architecture

MCPbox uses an **MCP-first approach** where external LLMs create tools via the `mcpbox_*` MCP tools rather than a visual builder.

**Rationale:**
- No API key management - users leverage existing LLM access
- Better UX - LLM handles the complexity
- Code-first - Python code is more maintainable than visual workflows
- Full control - users can write any Python logic they need

### Separate MCP Gateway Service

The MCP gateway runs as a separate Docker service rather than being merged into the backend.

**Rationale:**
- The tunnel-exposed service physically **cannot** serve admin endpoints
- Defense in depth - even if the Worker or tunnel is compromised, admin API is unreachable
- Independent scaling and restart

### Shared Sandbox (Not Per-Server Containers)

All tools execute in a single shared sandbox container rather than per-server containers.

**Rationale:**
- Lower resource usage for homelab deployments
- No docker.sock exposure needed
- Simpler architecture
- Application-level isolation via restricted builtins and import whitelisting

### Python Code Only (Not API Config)

All tools use Python code with `async def main()` entry points. A previous "API Config" mode for simple HTTP tools was removed in favor of the unified code-first approach.

**Rationale:**
- One execution model to secure and maintain
- Python can do everything API Config could, plus more
- LLMs excel at writing Python code
- Simpler codebase

### Authentication Architecture

MCPbox uses a **hybrid authentication model**:

**Admin Panel:**
- Ports bound to `127.0.0.1` by default (localhost access)
- Works behind external reverse proxies (Traefik, Caddy, nginx) — frontend nginx proxies `/api/*`, `/auth/*`, `/health` to the backend internally
- JWT authentication with Argon2id password hashing (defense-in-depth)

**MCP Gateway:**

| Mode | Auth | Use Case |
|------|------|----------|
| Local (no service token in DB) | None | Local MCP clients via localhost |
| Remote (service token from wizard) | OAuth 2.1 + OIDC + service token | Remote MCP clients via Cloudflare |

**Remote mode auth paths:**

| Request Source | Auth | Allowed Operations |
|---|---|---|
| User via OIDC | OAuth + OIDC-verified email (in token props) | All (list + execute) |
| Cloudflare sync | OAuth only (no user email) | Sync only (list, initialize) |
| Unauthenticated | Rejected 401 | None |

User identity comes from OIDC id_token verified at authorization time by the Worker. The verified email is stored in encrypted OAuth token props and set as `X-MCPbox-User-Email` on proxied requests. The gateway trusts this header when a valid service token is present. The `auth_method` is always `oidc` for remote requests.

---

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [FastMCP Documentation](https://gofastmcp.com/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Cloudflare Tunnel Documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Cloudflare Access for SaaS](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/saas-apps/)
