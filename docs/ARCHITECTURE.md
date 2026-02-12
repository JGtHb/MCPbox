# MCPbox Architecture

> A self-hosted MCP server management platform for homelabs, designed for secure Claude Web integration via Cloudflare tunnels.

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

MCPbox provides homelab users with a single Docker deployment that:

1. **Manages MCP Servers** - Create, deploy, and control MCP servers in a shared sandbox
2. **Tunnels to Claude Web** - Secure Cloudflare tunnel integration for remote MCP access
3. **Creates Custom Tools** - External LLMs (Claude Code, etc.) create Python tools programmatically via `mcpbox_*` MCP tools
4. **Tool Approval Workflow** - LLMs create tools in draft status, admins approve before publishing

### Design Principles

- **MCP-First**: External LLMs create tools via `mcpbox_*` MCP tools — no embedded LLM or visual builders.
- **Code-First**: All tools are Python code with `async def main()` entry points.
- **Sandbox by Default**: All MCP tools run in a hardened shared sandbox with resource limits.
- **Homelab-First**: Single Docker Compose deployment, minimal external dependencies.
- **Hybrid Architecture**: Local-first with optional remote access via Cloudflare Workers VPC.

### Hybrid Architecture

MCPbox uses a **hybrid architecture** - local-first with optional remote access via Cloudflare Workers VPC:

- **Admin Panel**: Accessible locally only (ports bound to 127.0.0.1). JWT authentication required (defense-in-depth).
- **MCP Gateway (/mcp)**:
  - **Local mode**: No authentication required (for Claude Desktop via localhost)
  - **Remote mode**: Exposed via Cloudflare Workers VPC tunnel with service token authentication

**Key security properties:**
- The tunnel has **no public hostname** - it's only accessible via Cloudflare Worker through Workers VPC
- The Worker enforces **OAuth 2.1 authentication** via `@cloudflare/workers-oauth-provider` — all /mcp requests require a valid OAuth token
- OAuth-only requests (no Cf-Access-Jwt-Assertion) are **sync-only** (can list tools, but cannot execute them)
- MCPbox validates the service token as defense-in-depth
- Unauthenticated requests to the Worker are rejected with 401

---

## System Architecture

### High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HOMELAB NETWORK                                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         MCPbox (Docker Compose)                      │    │
│  │                                                                      │    │
│  │   LOCAL ONLY (127.0.0.1)                    PRIVATE TUNNEL           │    │
│  │   ┌──────────┐  ┌──────────────┐           ┌──────────────┐         │    │
│  │   │ Frontend │  │   Backend    │           │ MCP Gateway  │         │    │
│  │   │ (React)  │◄─┤  (FastAPI)   │           │ (FastAPI)    │◄── cloudflared
│  │   │ :3000    │  │  :8000       │           │ :8002        │   (no public URL)
│  │   └──────────┘  │  /api/*      │           │ /mcp ONLY    │         │    │
│  │                 └──────┬───────┘           └──────┬───────┘         │    │
│  │                        │                          │                 │    │
│  │                        └──────────┬───────────────┘                 │    │
│  │                                   │                                 │    │
│  │   ┌────────────┐     ┌──────────────────────────┐                  │    │
│  │   │ PostgreSQL │◄────┤     Shared Sandbox       │                  │    │
│  │   │   :5432    │     │        :8001             │                  │    │
│  │   └────────────┘     └──────────────────────────┘                  │    │
│  │                                                                      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  LOCAL ACCESS ONLY: Admin panel (frontend + /api/*) bound to 127.0.0.1      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        │ Workers VPC (private)
                                        │
┌───────────────────────────────────────┴─────────────────────────────────────┐
│                            Cloudflare (Optional)                             │
│                                                                              │
│  ┌──────────────────┐     ┌─────────────────────────────────┐              │
│  │ MCP Server Portal│────►│ Cloudflare Worker (mcpbox-proxy)│              │
│  │ (handles OAuth)  │     │ - VPC binding to tunnel         │              │
│  └──────────────────┘     │ - OAuth 2.1 (all /mcp requests) │              │
│         ▲                 │ - Adds X-MCPbox-Service-Token   │              │
│  Cloudflare Sync ────────►│ - OAuth-only: sync (no exec)   │              │
│  (OAuth token)            └─────────────────────────────────┘              │
│                                        ▲                                     │
│                                        │ MCP Protocol                        │
│                                        │                                     │
└────────────────────────────────────────┼────────────────────────────────────┘
                                         │
                                    Claude Web
```

### Container Architecture

```yaml
services:
  frontend        # React web UI (127.0.0.1:3000)
  backend         # Python FastAPI admin API (127.0.0.1:8000)
  mcp-gateway     # Separate FastAPI service for /mcp (internal :8002, tunnel-exposed)
  sandbox         # Shared sandbox for tool execution (internal :8001)
  postgres        # Configuration and state storage (internal :5432)
  cloudflared     # Cloudflare tunnel daemon (optional, profile: remote)
```

### Docker Networks

| Network | Services | Purpose |
|---------|----------|---------|
| `mcpbox-internal` | backend, mcp-gateway, cloudflared | Internal service communication |
| `mcpbox-sandbox` | backend, mcp-gateway, sandbox | Sandbox access |
| `mcpbox-db` | backend, mcp-gateway, sandbox, postgres | Database access |

---

## Security Model

### Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│ TRUSTED: Your Infrastructure                                    │
│  - MCPbox containers (frontend, backend, gateway, postgres)    │
│  - Cloudflare tunnel                                            │
│  - Your network                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ UNTRUSTED: User-Created Tool Code                               │
│  - Python code submitted via mcpbox_create_tool                │
│  - Runs in shared sandbox with restricted builtins             │
└─────────────────────────────────────────────────────────────────┘
```

### Sandbox Security

Tool code runs in a shared sandbox container with application-level protections:

**Builtin Restrictions:**
- Dangerous builtins removed: `type()`, `getattr()`, `setattr()`, `eval()`, `exec()`, `compile()`, `open()`
- Discovery functions blocked: `vars()`, `dir()`
- Dunder attribute access blocked via regex: `__class__`, `__mro__`, `__bases__`, `__subclasses__`, `__globals__`, `__code__`, `__builtins__`, `__import__`, `__loader__`, `__spec__`

**Import Restrictions:**
- Whitelist-based module restriction (configurable via admin UI)
- Default allowed: `json`, `math`, `datetime`, `re`, `hashlib`, `base64`, `urllib.parse`, etc.
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
┌─────────────────────────────────────────────────────────────────┐
│                  TOOL CREATION WORKFLOW                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. LLM creates server with mcpbox_create_server                │
│                                                                  │
│  2. LLM creates tool with mcpbox_create_tool (draft status)     │
│     └─► Python code with async def main() entry point           │
│                                                                  │
│  3. LLM tests code with mcpbox_test_code                        │
│     └─► Validates execution in sandbox without saving           │
│                                                                  │
│  4. LLM validates code with mcpbox_validate_code                │
│     └─► Checks syntax, module usage, security constraints       │
│                                                                  │
│  5. LLM requests publish with mcpbox_request_publish            │
│     └─► Tool moves to pending_review status                     │
│                                                                  │
│  6. Admin reviews in UI at /approvals                           │
│     └─► Approves or rejects with reason                         │
│                                                                  │
│  7. If approved, tool becomes available in tools/list            │
│     If rejected, LLM can revise and re-submit                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Credential Management

```
┌─────────────────────────────────────────────────────────────────┐
│                   CREDENTIAL STORAGE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PostgreSQL (encrypted at rest)                                  │
│  ├─► API keys (AES-256-GCM encrypted)                           │
│  ├─► OAuth tokens (AES-256-GCM encrypted)                       │
│  └─► Refresh tokens (AES-256-GCM encrypted)                     │
│                                                                  │
│  Encryption key: MCPBOX_ENCRYPTION_KEY env variable              │
│  ├─► User provides: openssl rand -hex 32                        │
│  └─► Per-value random IV, authenticated encryption              │
│                                                                  │
│  Credentials passed to sandbox via:                              │
│  └─► Environment variables at execution time                    │
│                                                                  │
│  Credential scoping:                                             │
│  ├─► Each MCP server has its own credential namespace           │
│  └─► Server A cannot access Server B's credentials              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Frontend (React + TypeScript)

```
frontend/
├── src/
│   ├── components/
│   │   ├── ServerList/          # List of MCP servers
│   │   ├── CodePreview/         # Code viewer for tools
│   │   ├── Server/              # Server management components
│   │   ├── Tunnel/              # Cloudflare tunnel health
│   │   ├── Layout/              # App layout components
│   │   ├── shared/              # Shared components
│   │   └── ui/                  # Base UI components
│   ├── pages/                   # Route components
│   └── api/                     # Backend API client
├── package.json
└── Dockerfile
```

**Key Libraries:**
- React 18 + TypeScript
- TanStack Query (data fetching)
- React Router (navigation)
- Tailwind CSS (styling)

### 2. Backend (Python + FastAPI)

```
backend/
├── app/
│   ├── main.py                  # FastAPI application (admin API)
│   ├── mcp_only.py              # MCP gateway application (separate service)
│   ├── api/
│   │   ├── router.py            # Aggregates all /api routes
│   │   ├── servers.py           # MCP server CRUD
│   │   ├── tools.py             # Tool management
│   │   ├── sandbox.py           # Sandbox management
│   │   ├── tunnel.py            # Tunnel configuration
│   │   ├── cloudflare.py        # Cloudflare setup wizard API
│   │   ├── mcp_gateway.py       # MCP gateway routes (/mcp)
│   │   ├── approvals.py         # Tool/module approval endpoints
│   │   ├── credentials.py       # Credential management
│   │   ├── activity.py          # Activity logging + WebSocket
│   │   ├── dashboard.py         # Dashboard stats
│   │   ├── export_import.py     # Server/tool export/import
│   │   ├── settings.py          # App settings
│   │   ├── oauth.py             # OAuth token management
│   │   └── config.py            # Server config endpoints
│   ├── services/
│   │   ├── mcp_management.py    # MCP management tools (mcpbox_*)
│   │   ├── cloudflare.py        # Cloudflare API integration
│   │   ├── crypto.py            # AES-256-GCM credential encryption
│   │   ├── sandbox_client.py    # HTTP client for sandbox communication
│   │   └── ...
│   ├── models/
│   │   ├── server.py            # Server model
│   │   ├── tool.py              # Tool model
│   │   ├── credential.py        # Encrypted credential model
│   │   ├── activity_log.py      # Activity log model
│   │   ├── admin_user.py        # Admin user model
│   │   ├── cloudflare_config.py # Cloudflare wizard state
│   │   ├── tunnel_configuration.py # Named tunnel configs
│   │   └── ...
│   └── core/
│       ├── config.py            # Settings
│       ├── security.py          # Auth utilities (JWT, Argon2id)
│       └── database.py          # DB connection
├── alembic/                     # Database migrations
├── requirements.txt
└── Dockerfile
```

**Key Libraries:**
- FastAPI (web framework)
- SQLAlchemy (async ORM)
- cryptography (AES-256-GCM credential encryption)
- httpx (async HTTP client)
- argon2-cffi (password hashing)

### 3. MCP Gateway (Separate Service)

The MCP gateway runs as a **separate Docker service** (`mcp-gateway:8002`) using `app.mcp_only:app`. It shares the backend codebase but only exposes `/mcp` and `/health` endpoints. This ensures the tunnel can **never** reach admin API endpoints.

**Responsibilities:**
- Terminate MCP Streamable HTTP connections from Claude
- Validate service token header (remote mode) or allow all (local mode)
- Verify JWT from Cf-Access-Jwt-Assertion (remote mode)
- Proxy tool execution requests to the sandbox
- Aggregate tool listings from all enabled servers
- Log all requests for observability

### 4. Sandbox (Python Tool Execution)

```
sandbox/
├── app/
│   ├── routes.py              # Tool execution API, /execute endpoint
│   ├── registry.py            # Dynamic tool registration
│   ├── executor.py            # Python code execution with safety checks
│   ├── ssrf.py                # SSRF prevention for HTTP clients
│   ├── osv_client.py          # OSV vulnerability checking for modules
│   └── pypi_client.py         # PyPI package info client
├── requirements.txt
└── Dockerfile
```

### 5. Cloudflare Worker (MCP Proxy)

```
worker/
├── src/index.ts               # Worker code with OAuth 2.1 provider
├── wrangler.toml              # Generated by deploy-worker.sh (gitignored)
└── package.json
```

**Security features:**
- Wrapped with `@cloudflare/workers-oauth-provider`
- Path whitelist: only `/mcp` and `/health` allowed
- JWT verification (RS256) with JWKS caching
- CORS restricted to `claude.ai` domains
- Service token injection (`X-MCPbox-Service-Token`)
- User email extraction from JWT for audit logging

### 6. MCP Management Tools

MCPbox exposes 18 management tools with the `mcpbox_` prefix:

| Category | Tools |
|----------|-------|
| Servers | `list_servers`, `get_server`, `create_server`, `delete_server`, `start_server`, `stop_server`, `get_server_modules` |
| Tools | `list_tools`, `get_tool`, `create_tool`, `update_tool`, `delete_tool` |
| Development | `test_code`, `validate_code` |
| Approval | `request_publish`, `request_module`, `request_network_access`, `get_tool_status` |

See `docs/MCP-MANAGEMENT-TOOLS.md` for complete documentation.

---

## Data Flow

### MCP Request Flow

```
                        LOCAL MODE                         REMOTE MODE
                        ──────────                         ───────────
Claude Desktop                                Claude Web
    │                                             │
    │ HTTP (localhost)                            │ MCP Protocol (HTTPS)
    │                                             ▼
    │                                     MCP Server Portal (OAuth)
    │                                             │
    │                                             │ Cf-Access-Jwt-Assertion
    │                                             ▼
    │                                     Cloudflare Worker
    │                                             │
    │                                             │ + X-MCPbox-Service-Token
    │                                             │ + X-MCPbox-User-Email
    │                                             ▼
    │                                     Workers VPC Binding (private)
    │                                             │
    └─────────────────┬───────────────────────────┘
                      │
                      ▼
          MCP Gateway (mcp-gateway:8002)
                      │
                      ├─► Validate service token (remote mode)
                      ├─► Allow all (local mode)
                      ├─► Parse MCP request
                      │
                      ▼
          ┌─────────────────────────────────────┐
          │         Request Router              │
          ├─────────────────────────────────────┤
          │ initialize  → Return capabilities   │
          │ tools/list  → Aggregate all servers │
          │ tools/call  → Route to sandbox      │
          └─────────────────────────────────────┘
                      │
                      │ HTTP (internal sandbox network)
                      ▼
          Shared Sandbox (:8001)
                      │
                      │ Execute Python code
                      │
                      ▼
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
| `credentials` | Encrypted API credentials per server |
| `admin_users` | Admin panel users (JWT auth) |
| `settings` | Application settings (key-value) |
| `global_configs` | Global configuration (allowed modules, etc.) |

### Activity & Observability

| Table | Purpose |
|-------|---------|
| `activity_logs` | All system activity (tool calls, server changes, etc.) |

### Approval Workflow

| Table | Purpose |
|-------|---------|
| `module_requests` | Pending module whitelist requests |
| `network_access_requests` | Pending network access requests |

### Tunnel & Cloudflare

| Table | Purpose |
|-------|---------|
| `tunnel_configurations` | Named tunnel configurations |
| `cloudflare_configs` | Cloudflare wizard state (tunnel, VPC, Worker, MCP server/portal) |

---

## API Specification

### Admin API (`/api/*` - local only)

**Server Management:**
```
GET    /api/servers                 # List all servers (paginated)
POST   /api/servers                 # Create server
GET    /api/servers/{id}            # Get server details
PUT    /api/servers/{id}            # Update server
DELETE /api/servers/{id}            # Delete server
POST   /api/servers/{id}/start      # Start server
POST   /api/servers/{id}/stop       # Stop server
```

**Tool Management:**
```
GET    /api/servers/{id}/tools      # List tools for server
POST   /api/servers/{id}/tools      # Create tool
GET    /api/tools/{id}              # Get tool details
PUT    /api/tools/{id}              # Update tool
DELETE /api/tools/{id}              # Delete tool
```

**Credentials:**
```
POST   /api/servers/{id}/credentials      # Add credential
GET    /api/servers/{id}/credentials      # List credentials (names only)
DELETE /api/credentials/{id}              # Remove credential
```

**Approval Workflow:**
```
GET    /api/approvals                     # List pending approvals
POST   /api/approvals/{id}/approve        # Approve request
POST   /api/approvals/{id}/reject         # Reject request
```

**Tunnel & Cloudflare:**
```
GET    /api/tunnel/status                 # Get tunnel status
POST   /api/tunnel/configurations         # Save tunnel configuration
GET    /api/cloudflare/status             # Get Cloudflare wizard status
POST   /api/cloudflare/verify-token       # Verify Cloudflare API token
POST   /api/cloudflare/tunnel             # Create tunnel
POST   /api/cloudflare/vpc-service        # Create VPC service
POST   /api/cloudflare/worker             # Deploy Worker
POST   /api/cloudflare/mcp-server         # Create MCP server
POST   /api/cloudflare/mcp-portal         # Create MCP portal
```

**Other:**
```
GET    /api/activity                      # Activity log (paginated)
WS     /api/ws/activity                   # WebSocket live activity stream
GET    /api/dashboard/stats               # Dashboard statistics
POST   /api/export                        # Export servers/tools
POST   /api/import                        # Import servers/tools
GET    /api/settings                      # Get app settings
PUT    /api/settings                      # Update settings
```

### MCP Gateway (`/mcp` - local + tunnel)

```
POST   /mcp                              # MCP Streamable HTTP endpoint
GET    /health                           # Health check
```

---

## Design Decisions

### MCP-First Architecture

MCPbox uses an **MCP-first approach** where external LLMs create tools via the `mcpbox_*` MCP tools rather than a visual builder.

**Rationale:**
- No API key management - users leverage existing Claude access
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

**Admin Panel (Local Only):**
- Ports bound to `127.0.0.1` (localhost only)
- JWT authentication with Argon2id password hashing (defense-in-depth)

**MCP Gateway:**

| Mode | Auth | Use Case |
|------|------|----------|
| Local (no service token in DB) | None | Claude Desktop via localhost |
| Remote (service token from wizard) | OAuth 2.1 + JWT + service token | Claude Web via Cloudflare |

**Remote mode auth paths:**

| Request Source | Auth | Allowed Operations |
|---|---|---|
| User via MCP Portal | OAuth + Cf-Access-Jwt-Assertion | All (list + execute) |
| Cloudflare sync | OAuth only | Sync only (list, initialize) |
| Unauthenticated | Rejected 401 | None |

---

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [FastMCP Documentation](https://gofastmcp.com/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Cloudflare Tunnel Documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
