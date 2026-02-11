# MCPbox Architecture

> A self-hosted MCP server management platform for homelabs, designed for secure Claude Web integration via Cloudflare tunnels.

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Security Model](#security-model)
4. [Observability](#observability)
5. [Component Details](#component-details)
6. [Data Flow](#data-flow)
7. [Database Schema](#database-schema)
8. [API Specification](#api-specification)
9. [Development Phases](#development-phases)

---

## Overview

### What MCPbox Does

MCPbox provides homelab users with a single Docker deployment that:

1. **Manages MCP Servers** - Create, deploy, and control MCP servers in a shared sandbox
2. **Tunnels to Claude Web** - Secure Cloudflare tunnel integration for remote MCP access
3. **Creates Custom Tools** - External LLMs (Claude Code, etc.) create Python tools programmatically via `mcpbox_*` MCP tools
4. **Tool Approval Workflow** - LLMs create tools in draft status, admins approve before publishing

### Design Principles

- **User-Reviewed Code**: Users import and review their own MCP server code. No curated catalog.
- **No Automatic Updates**: Users must review diffs before updating any MCP server.
- **Sandbox by Default**: All MCP tools run in a hardened shared sandbox with resource limits and network isolation.
- **Homelab-First**: Single Docker Compose deployment, minimal external dependencies.
- **Free Personal Use**: Open source core, commercial license for business use.

### Hybrid Architecture

MCPbox uses a **hybrid architecture** - local-first with optional remote access via Cloudflare Workers VPC:

- **Admin Panel**: Accessible locally only (ports bound to 127.0.0.1). No authentication required since it cannot be accessed from the internet.
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
  frontend        # React web UI
  backend         # Python FastAPI (admin API)
  mcp-gateway     # Separate FastAPI service for /mcp (tunnel-exposed)
  sandbox         # Shared sandbox for tool execution (Python/FastMCP)
  postgres        # Configuration and state storage
  cloudflared     # Cloudflare tunnel daemon (optional, for remote access)
```

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
│ UNTRUSTED: User-Imported Code                                   │
│  - MCP server containers                                        │
│  - Third-party dependencies                                     │
│  - Tool implementations                                         │
└─────────────────────────────────────────────────────────────────┘
```

### Sandbox Security Layers

#### Layer 1: Shared Sandbox Isolation

```yaml
# Applied to the shared sandbox container
security_opt:
  - no-new-privileges:true
  - seccomp:./seccomp-mcp.json
cap_drop:
  - ALL
read_only: true
user: "65534:65534"  # nobody:nogroup
pids_limit: 100
mem_limit: 512m
cpus: 0.5
tmpfs:
  - /tmp:size=64m,noexec,nosuid
```

#### Layer 2: Network Isolation

| Mode | Docker Network | Use Case |
|------|----------------|----------|
| `isolated` (default) | `network_mode: none` | MCP servers that don't need external access |
| `allowlist` | Custom bridge + iptables | Servers that need specific API access |
| `outbound` | Bridge with no inbound | Servers that need general internet |

```yaml
# Example: Allowlist mode for GitHub MCP
network:
  mode: allowlist
  allowed_hosts:
    - api.github.com
    - github.com
```

#### Layer 3: Filesystem Isolation

```
/app (read-only)     # MCP server code
/tmp (tmpfs, 64MB)   # Ephemeral scratch space
/data (optional)     # User-configured persistent volume
```

#### Layer 4: gVisor Option (Paranoid Mode)

```yaml
# For maximum isolation at cost of performance
runtime: runsc  # gVisor
```

### MCP-First Tool Creation

Tools are created programmatically by external LLMs via `mcpbox_*` MCP tools, not imported from git repositories.

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
│  Encryption key derived from:                                    │
│  ├─► User-provided master password (PBKDF2)                     │
│  └─► OR auto-generated key stored in Docker secret              │
│                                                                  │
│  Credentials passed to containers via:                           │
│  ├─► Environment variables (at container start)                 │
│  └─► NOT mounted as files (prevents theft via file read tools)  │
│                                                                  │
│  Credential scoping:                                             │
│  ├─► Each MCP server has its own credential namespace           │
│  └─► Server A cannot access Server B's credentials              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Observability

Observability is critical for MCP security. MCPbox provides full visibility into what each MCP server is doing at the network and storage layers.

### Design Philosophy

> **"Trust, but verify"** - Users review and approve MCP server code, but MCPbox continuously monitors actual behavior to detect anomalies.

Key principles:
- **Full visibility**: Every network connection and storage operation is logged
- **Real-time monitoring**: Live dashboards show current activity
- **Allowlist enforcement**: Network access is deny-by-default with explicit allowlists
- **Anomaly detection**: Alerts on unexpected behavior patterns
- **Forensic capability**: Historical logs for security investigations

### Network Observability

#### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCP SANDBOX CONTAINER                              │
│                                                                              │
│  ┌─────────────────┐                                                        │
│  │   MCP Server    │                                                        │
│  │                 │                                                        │
│  │  HTTP request ──┼──► eth0 ──► Docker network                            │
│  │                 │                                                        │
│  └─────────────────┘                                                        │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NETWORK PROXY (per sandbox)                          │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Envoy Sidecar Proxy                           │   │
│  │                                                                      │   │
│  │  1. Intercept all outbound traffic                                  │   │
│  │  2. DNS resolution logging                                           │   │
│  │  3. Check against allowlist (host + port)                           │   │
│  │  4. Log connection metadata (timestamp, host, port, bytes)          │   │
│  │  5. Forward allowed traffic OR reject with logged reason            │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Modes:                                                                      │
│  ├─► ISOLATED:  Block all (no proxy needed, network=none)                  │
│  ├─► ALLOWLIST: Only permit explicit host:port combinations                │
│  ├─► MONITORED: Allow all outbound, but log everything                     │
│  └─► LEARNING:  Allow all, auto-generate allowlist from traffic            │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │ Logs via structured logging
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MCPBOX BACKEND                                  │
│                                                                              │
│  Network Log Aggregator                                                      │
│  ├─► Store in PostgreSQL (network_logs table)                              │
│  ├─► Real-time WebSocket feed to frontend                                  │
│  ├─► Anomaly detection (unexpected hosts, high volume, etc.)               │
│  └─► Alert generation                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Network Modes

| Mode | Network Access | Logging | Use Case |
|------|----------------|---------|----------|
| `isolated` | None | N/A | Servers that don't need network (file processors, calculators) |
| `allowlist` | Explicit hosts only | Full | Production - known API dependencies |
| `monitored` | All outbound | Full | Testing - see what server actually needs |
| `learning` | All outbound | Full + auto-allowlist | Initial setup - discover required hosts |

#### Learning Mode Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                     LEARNING MODE WORKFLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. User enables Learning Mode for a server                      │
│                                                                  │
│  2. Server runs with full network access (monitored)             │
│                                                                  │
│  3. User exercises all server functionality via Claude           │
│                                                                  │
│  4. MCPbox records all outbound connections:                     │
│     ├─► api.github.com:443                                      │
│     ├─► github.com:443                                          │
│     └─► raw.githubusercontent.com:443                           │
│                                                                  │
│  5. User clicks "Generate Allowlist"                             │
│                                                                  │
│  6. MCPbox shows proposed allowlist for review:                  │
│     ┌─────────────────────────────────────────────────┐         │
│     │ Proposed Network Allowlist                       │         │
│     │                                                  │         │
│     │ ☑ api.github.com:443    (42 requests)          │         │
│     │ ☑ github.com:443         (3 requests)           │         │
│     │ ☑ raw.githubusercontent.com:443 (7 requests)   │         │
│     │ ☐ telemetry.example.com:443 (2 requests) ⚠️    │         │
│     │                                                  │         │
│     │ [Apply Allowlist]  [Continue Learning]          │         │
│     └─────────────────────────────────────────────────┘         │
│                                                                  │
│  7. User reviews, unchecks suspicious hosts, applies             │
│                                                                  │
│  8. Server switches to Allowlist Mode                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Network Log Schema

```sql
-- Network connection logs
CREATE TABLE network_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Connection details
    destination_host VARCHAR(255) NOT NULL,
    destination_ip INET,
    destination_port INTEGER NOT NULL,
    protocol VARCHAR(10) NOT NULL,  -- 'tcp', 'udp'

    -- Request details (for HTTP/HTTPS)
    http_method VARCHAR(10),
    http_path VARCHAR(2048),
    http_status INTEGER,

    -- Traffic metrics
    bytes_sent BIGINT DEFAULT 0,
    bytes_received BIGINT DEFAULT 0,
    duration_ms INTEGER,

    -- Policy decision
    action VARCHAR(20) NOT NULL,  -- 'allowed', 'blocked', 'learning'
    matched_rule VARCHAR(255),     -- Which allowlist rule matched (if any)

    -- Indexing
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX idx_network_logs_server_time ON network_logs(server_id, timestamp DESC);
CREATE INDEX idx_network_logs_host ON network_logs(destination_host);
CREATE INDEX idx_network_logs_action ON network_logs(action);

-- Aggregated view for dashboard
CREATE VIEW network_stats AS
SELECT
    server_id,
    destination_host,
    destination_port,
    COUNT(*) as request_count,
    SUM(bytes_sent) as total_bytes_sent,
    SUM(bytes_received) as total_bytes_received,
    MAX(timestamp) as last_seen,
    MIN(timestamp) as first_seen
FROM network_logs
GROUP BY server_id, destination_host, destination_port;
```

#### Network Allowlist Configuration

```sql
-- Per-server network allowlist
CREATE TABLE network_allowlist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,

    -- Rule definition
    host_pattern VARCHAR(255) NOT NULL,  -- Exact match or wildcard (*.github.com)
    port INTEGER,                          -- NULL = any port
    protocol VARCHAR(10) DEFAULT 'tcp',

    -- Metadata
    description VARCHAR(500),
    auto_generated BOOLEAN DEFAULT false,  -- From learning mode
    enabled BOOLEAN DEFAULT true,

    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(server_id, host_pattern, port, protocol)
);
```

### Storage Observability

All storage operations go through the backend-mediated storage API, providing complete visibility.

#### Storage Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Storage Activity - github-mcp                                    [Live 🟢] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Usage: 2.3 MB / 10 MB (23%)  │  Keys: 47 / 1000                           │
│  ████████░░░░░░░░░░░░░░░░░░░  │  ████░░░░░░░░░░░░░░░░░░░░░░░░░             │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Recent Operations                                              [View All]  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Time         Op      Key                    Size      Value Preview        │
│  ─────────────────────────────────────────────────────────────────────────  │
│  12:34:56     GET     cache/repos/list       1.2 KB    ["repo1", "repo2"... │
│  12:34:55     PUT     cache/user/profile     340 B     {"login": "user"...  │
│  12:34:52     GET     settings/preferences   128 B     {"theme": "dark"...  │
│  12:34:50     DEL     cache/stale_data       -         (deleted)            │
│  12:34:48     PUT     cache/repos/list       1.2 KB    ["repo1", "repo2"... │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  [View All Data]  [Export]  [Clear All Storage]                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Storage Data Inspector

Users can view the actual stored data (decrypted) for any MCP server:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Storage Inspector - github-mcp                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Keys (47)                          │  Value                                │
│  ─────────────────────────────────  │  ──────────────────────────────────── │
│  📁 cache/                          │                                       │
│    ├── repos/list           1.2 KB  │  [                                    │
│    ├── repos/details/123    890 B   │    {                                  │
│    ├── repos/details/456    920 B   │      "id": 123456,                    │
│    └── user/profile         340 B   │      "name": "my-repo",               │
│  📁 settings/                       │      "full_name": "user/my-repo",     │
│    └── preferences          128 B   │      "private": false,                │
│  📁 state/                          │      "description": "A cool repo",    │
│    └── last_sync            64 B    │      ...                              │
│                                     │    },                                  │
│  [Select key to view value]    ▶    │    ...                                │
│                                     │  ]                                     │
│                                     │                                       │
│  ─────────────────────────────────  │  ──────────────────────────────────── │
│  [Delete Selected]  [Delete All]    │  [Copy]  [Download]                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Storage Log Schema

```sql
-- Storage operation logs (extends existing server_state table)
CREATE TABLE storage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Operation details
    operation VARCHAR(10) NOT NULL,  -- 'GET', 'PUT', 'DELETE', 'LIST'
    key VARCHAR(255) NOT NULL,

    -- Value metadata (not the actual value - that's in server_state)
    value_size_bytes INTEGER,
    value_hash VARCHAR(64),          -- SHA-256 of value for change detection

    -- Result
    success BOOLEAN NOT NULL,
    error_message VARCHAR(500),

    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for efficient querying
CREATE INDEX idx_storage_logs_server_time ON storage_logs(server_id, timestamp DESC);
CREATE INDEX idx_storage_logs_key ON storage_logs(key);
```

### MCP Request Observability

Every MCP tool call is logged for audit and debugging.

#### MCP Request Log Schema

```sql
-- MCP tool invocation logs
CREATE TABLE mcp_request_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Request details
    method VARCHAR(50) NOT NULL,        -- 'tools/call', 'resources/read', etc.
    tool_name VARCHAR(255),

    -- Input/Output (truncated for large payloads)
    request_params JSONB,
    response_result JSONB,
    response_error JSONB,

    -- Metrics
    duration_ms INTEGER,

    -- Correlation
    upstream_request_id VARCHAR(64),    -- From Claude's request

    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for efficient querying
CREATE INDEX idx_mcp_logs_server_time ON mcp_request_logs(server_id, timestamp DESC);
CREATE INDEX idx_mcp_logs_tool ON mcp_request_logs(tool_name);
```

### Unified Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MCPbox Dashboard                                          [All Servers ▼]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐          │
│  │  Active Servers             │  │  Network Activity (24h)      │          │
│  │  ████████████████ 4 / 6    │  │  ▁▂▃▅▇█▇▅▃▂▁▁▂▃▄▅▆▇█▇▅▄▃▂▁│          │
│  │  github-mcp      🟢 Running │  │  Requests: 1,247              │          │
│  │  docker-mcp      🟢 Running │  │  Blocked: 3 (0.2%)            │          │
│  │  protondb-mcp    🟢 Running │  │  Data: 45.2 MB sent           │          │
│  │  slack-mcp       🟢 Running │  │        123.7 MB received      │          │
│  │  weather-mcp     ⚪ Stopped │  └─────────────────────────────┘          │
│  │  custom-api      ⚪ Stopped │                                            │
│  └─────────────────────────────┘  ┌─────────────────────────────┐          │
│                                   │  Alerts                      │          │
│  ┌─────────────────────────────┐  │  ⚠️ github-mcp attempted     │          │
│  │  Tool Calls (24h)           │  │     blocked host: track.io   │          │
│  │  ────────────────────────── │  │  ⚠️ docker-mcp storage near  │          │
│  │  github.list_repos      234 │  │     limit (8.5/10 MB)        │          │
│  │  github.create_issue     45 │  │                              │          │
│  │  docker.list_containers 189 │  └─────────────────────────────┘          │
│  │  protondb.check_game     67 │                                            │
│  │  slack.send_message      23 │                                            │
│  └─────────────────────────────┘                                            │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Live Activity Stream                                        [Pause] [Clear]│
├─────────────────────────────────────────────────────────────────────────────┤
│  12:34:58  github-mcp    TOOL     list_repos                    ✓  45ms    │
│  12:34:57  github-mcp    NET      api.github.com:443            ✓  123ms   │
│  12:34:56  docker-mcp    STORAGE  PUT cache/containers          ✓  12ms    │
│  12:34:55  github-mcp    NET      track.example.com:443         ✗ BLOCKED  │
│  12:34:54  protondb-mcp  TOOL     check_game appid=123          ✓  89ms    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Alerting

#### Alert Types

| Alert | Trigger | Severity |
|-------|---------|----------|
| **Blocked Connection** | Server attempted to reach non-allowlisted host | Warning |
| **High Request Volume** | >100 requests/minute to same host | Warning |
| **Large Data Transfer** | >10MB transferred in single connection | Warning |
| **Storage Near Limit** | >80% of storage quota used | Info |
| **Storage Limit Hit** | Write rejected due to quota | Warning |
| **New Host Detected** | (Learning mode) First connection to new host | Info |
| **Tool Description Changed** | Tool metadata differs from imported version | Critical |
| **Unusual Activity Pattern** | Significant deviation from baseline | Warning |

#### Alert Configuration

```sql
-- Alert definitions
CREATE TABLE alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Scope
    server_id UUID REFERENCES servers(id),  -- NULL = all servers

    -- Rule definition
    alert_type VARCHAR(50) NOT NULL,
    threshold_value INTEGER,
    threshold_unit VARCHAR(20),  -- 'count', 'bytes', 'percent', 'ms'
    time_window_minutes INTEGER DEFAULT 5,

    -- Actions
    enabled BOOLEAN DEFAULT true,
    notify_ui BOOLEAN DEFAULT true,
    notify_webhook VARCHAR(1024),  -- Optional webhook URL

    created_at TIMESTAMP DEFAULT NOW()
);

-- Alert history
CREATE TABLE alert_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID REFERENCES alert_rules(id),
    server_id UUID REFERENCES servers(id),

    severity VARCHAR(20) NOT NULL,  -- 'info', 'warning', 'critical'
    message TEXT NOT NULL,
    details JSONB,

    acknowledged BOOLEAN DEFAULT false,
    acknowledged_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);
```

### API Endpoints for Observability

```
# Network logs
GET    /api/servers/{id}/network/logs      # List network logs (paginated)
GET    /api/servers/{id}/network/stats     # Aggregated network statistics
GET    /api/servers/{id}/network/allowlist # Get current allowlist
PUT    /api/servers/{id}/network/allowlist # Update allowlist
POST   /api/servers/{id}/network/learn     # Enable learning mode
POST   /api/servers/{id}/network/generate-allowlist  # Generate from learning

# Storage logs
GET    /api/servers/{id}/storage/logs      # List storage operation logs
GET    /api/servers/{id}/storage/data      # List all stored keys
GET    /api/servers/{id}/storage/data/{key}  # Get specific value (decrypted)
DELETE /api/servers/{id}/storage/data/{key}  # Delete specific key
DELETE /api/servers/{id}/storage/data      # Clear all storage

# MCP request logs
GET    /api/servers/{id}/mcp/logs          # List MCP request logs

# Alerts
GET    /api/alerts                         # List all alerts
GET    /api/alerts/rules                   # List alert rules
POST   /api/alerts/rules                   # Create alert rule
PATCH  /api/alerts/{id}/acknowledge        # Acknowledge alert

# Real-time
WS     /api/ws/activity                    # WebSocket for live activity stream
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
│   ├── main.py                  # FastAPI application
│   ├── api/
│   │   ├── servers.py           # MCP server CRUD
│   │   ├── tools.py             # Tool management
│   │   ├── sandbox.py           # Sandbox management
│   │   ├── tunnel.py            # Cloudflare tunnel control
│   │   ├── mcp_gateway.py       # MCP gateway (local mode)
│   │   ├── approvals.py         # Tool/module approval endpoints
│   │   ├── credentials.py       # Credential management
│   │   └── activity.py          # Activity logging
│   ├── services/
│   │   ├── mcp_management.py    # MCP management tools (mcpbox_*)
│   │   ├── crypto.py            # Credential encryption
│   │   └── ...
│   ├── models/
│   │   ├── server.py            # SQLAlchemy models
│   │   ├── tool.py
│   │   └── ...
│   └── core/
│       ├── config.py            # Settings
│       ├── security.py          # Auth utilities
│       └── database.py          # DB connection
├── requirements.txt
└── Dockerfile
```

**Key Libraries:**
- FastAPI (web framework)
- SQLAlchemy (ORM)
- cryptography (credential encryption)
- httpx (async HTTP client)
- argon2-cffi (password hashing)

### 3. MCP Gateway (Part of Backend)

The MCP gateway is implemented as a FastAPI router within the backend, not a separate service.

```python
# backend/app/api/mcp_gateway.py

from fastapi import APIRouter, Request, Depends
from app.api.auth import verify_oauth_token, AuthenticatedUser
from app.services.proxy import proxy_to_sandbox
from app.services.tools import aggregate_tools

router = APIRouter(prefix="/mcp")

@router.post("/")
async def handle_mcp_request(
    request: Request,
    user: AuthenticatedUser = Depends(verify_oauth_token)
):
    """Handle MCP Streamable HTTP requests from Claude via tunnel."""
    mcp_request = await request.json()

    if mcp_request["method"] == "tools/list":
        # Aggregate tools from all enabled servers
        return await aggregate_tools()

    elif mcp_request["method"] == "tools/call":
        # Route to specific sandbox based on tool prefix
        server = find_server_for_tool(mcp_request["params"]["name"])
        return await proxy_to_sandbox(server, mcp_request)

    # ... handle other MCP methods
```

**Responsibilities:**
- Terminate Streamable HTTP connections from Claude
- Validate service token header (remote mode) or allow all (local mode)
- Extract user email from X-MCPbox-User-Email header (for audit logging)
- Proxy requests to sandbox containers
- Aggregate tool listings from enabled servers
- Log all requests for observability

### 4. MCP Management Tools

MCPbox exposes its management functions as MCP tools, allowing external LLMs (Claude Code, etc.) to programmatically create and manage servers and tools. This **MCP-first approach** provides:

- **No API key management** - Users leverage their existing Claude access
- **Better UX** - LLM does the heavy lifting externally
- **18 management tools** - Full CRUD for servers, tools, and approval workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                  MCP-FIRST TOOL CREATION                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. LLM creates server with mcpbox_create_server                │
│  2. LLM creates tool with mcpbox_create_tool (draft status)     │
│  3. LLM tests code with mcpbox_test_code                        │
│  4. LLM requests publish with mcpbox_request_publish            │
│  5. Admin approves in UI at /approvals                          │
│  6. Tool becomes available in tools/list                        │
│                                                                  │
│  Module/Network Requests:                                        │
│  - mcpbox_request_module - Request Python module whitelisting   │
│  - mcpbox_request_network_access - Request external host access │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

See `docs/MCP-MANAGEMENT-TOOLS.md` for complete documentation.

### 5. Tunnel Integration

MCPbox uses **Cloudflare Workers VPC** for secure remote access. The tunnel has **no public hostname** - it's only accessible via the Cloudflare Worker.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TUNNEL ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Two Deployment Modes:                                           │
│                                                                  │
│  LOCAL ONLY (no service token in database):                     │
│  └─► Claude Desktop connects to http://localhost:8000/mcp       │
│  └─► No authentication required                                 │
│  └─► No tunnel needed                                           │
│                                                                  │
│  REMOTE ACCESS (service token in database from wizard):         │
│  └─► Cloudflare tunnel connects to mcp-gateway:8002             │
│  └─► Tunnel has NO public hostname (private via Workers VPC)    │
│  └─► Cloudflare Worker is the only entry point                  │
│  └─► Service token validates requests (defense-in-depth)        │
│                                                                  │
│  Admin Panel Access:                                             │
│  └─► Local only - ports bound to 127.0.0.1                      │
│  └─► JWT authentication required (defense-in-depth)             │
│  └─► Access via http://localhost:3000                           │
│                                                                  │
│  Authentication Flow (Remote Mode):                              │
│                                                                  │
│  User requests (via MCP Portal):                                 │
│  1. Claude Web connects to MCP Server Portal                     │
│  2. MCP Server Portal handles OAuth (Google, GitHub, etc.)       │
│  3. MCP Server Portal forwards request to Cloudflare Worker      │
│  4. Worker verifies JWT (RS256) and extracts user email         │
│  5. Worker adds X-MCPbox-Service-Token + auth method header     │
│  6. Worker forwards to MCPbox via Workers VPC binding           │
│  7. MCPbox validates service token and processes request        │
│                                                                  │
│  Cloudflare sync requests (OAuth):                               │
│  1. Cloudflare discovers OAuth via AS metadata + PRM endpoints  │
│  2. Cloudflare performs OAuth 2.1 flow (register/authorize/token)│
│  3. Worker tags auth method as "oauth" (sync-only)              │
│  4. Gateway allows tools/list + initialize, blocks tools/call   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

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
    │                                             │ Encrypted tunnel
    └─────────────────┬───────────────────────────┘
                      │
                      ▼
          MCP Gateway (mcp-gateway:8002)
                      │
                      ├─► Validate service token (remote mode)
                      ├─► Allow all (local mode)
                      ├─► Parse MCP request
                      ├─► Determine target server(s)
                      │
                      ▼
          ┌─────────────────────────────────────┐
          │         Request Router              │
          ├─────────────────────────────────────┤
          │ tools/list    → Aggregate all       │
          │ tools/call    → Route to specific   │
          │ resources/*   → Route to specific   │
          │ prompts/*     → Route to specific   │
          └─────────────────────────────────────┘
                      │
                      │ HTTP (internal sandbox network)
                      ▼
          MCP Sandbox Container
                      │
                      │ Execute tool
                      │
                      ▼
          Response back through chain
```

### Tool Aggregation

```
Gateway receives: tools/list

Gateway queries all enabled servers:
├─► github-mcp     → [create_issue, list_repos, ...]
├─► protondb-mcp   → [check_game, search_games]
└─► docker-mcp     → [list_containers, container_logs]

Gateway responds with merged list:
{
  "tools": [
    {"name": "github.create_issue", ...},
    {"name": "github.list_repos", ...},
    {"name": "protondb.check_game", ...},
    {"name": "protondb.search_games", ...},
    {"name": "docker.list_containers", ...},
    {"name": "docker.container_logs", ...}
  ]
}

Tool names prefixed with server name to avoid collisions.
```

---

## Database Schema

```sql
-- MCP Servers imported by user
CREATE TABLE servers (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL,  -- 'mcp_tool'
    status VARCHAR(50) NOT NULL,        -- 'imported', 'building', 'ready', 'running', 'stopped', 'error'
    network_mode VARCHAR(50) DEFAULT 'isolated',
    allowed_hosts TEXT[],               -- For allowlist mode
    container_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tools exposed by each server
CREATE TABLE tools (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES servers(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    input_schema JSONB,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Credentials for MCP servers
CREATE TABLE credentials (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES servers(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    credential_type VARCHAR(50) NOT NULL,  -- 'api_key', 'oauth', 'basic'
    encrypted_value BYTEA NOT NULL,
    metadata JSONB,  -- Non-sensitive metadata (e.g., OAuth scopes)
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tunnel configuration (named tunnels only - no quick tunnel support)
-- The tunnel token is stored in environment variables, not the database
-- This table tracks tunnel status and metadata only
CREATE TABLE tunnel_status (
    id UUID PRIMARY KEY,
    status VARCHAR(50) NOT NULL,         -- 'connected', 'disconnected', 'error'
    public_url VARCHAR(1024),            -- The public URL for this tunnel
    started_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit log
CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    server_id UUID REFERENCES servers(id),
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## API Specification

### Server Management

```
POST   /api/servers/import          # Import from git repo
POST   /api/servers/upload          # Upload code directly
GET    /api/servers                 # List all servers
GET    /api/servers/{id}            # Get server details
DELETE /api/servers/{id}            # Remove server
POST   /api/servers/{id}/start      # Start sandbox
POST   /api/servers/{id}/stop       # Stop sandbox
POST   /api/servers/{id}/restart    # Restart sandbox
GET    /api/servers/{id}/logs       # Get container logs
```

### Update Management

```
GET    /api/servers/{id}/updates    # Check for updates
GET    /api/servers/{id}/diff       # Get update diff
POST   /api/servers/{id}/update     # Apply update (after review)
POST   /api/servers/{id}/rollback   # Rollback to previous version
```

### Tool Management

```
GET    /api/servers/{id}/tools      # List tools for server
PATCH  /api/tools/{id}              # Update tool (enable/disable)
```

### Tunnel Management

```
GET    /api/tunnel/status                          # Get tunnel status
POST   /api/tunnel/start                           # Start tunnel (uses token from database)
POST   /api/tunnel/stop                            # Stop tunnel
```

**Note**: Tunnel tokens are stored encrypted in the database and managed via the UI wizard. The cloudflared container fetches the active token from the backend at startup.

### Credentials

```
POST   /api/servers/{id}/credentials      # Add credential
GET    /api/servers/{id}/credentials      # List credentials (names only)
DELETE /api/credentials/{id}              # Remove credential
```

---

## Development Phases

### Phase 1: Foundation (Complete)

**Goal:** Basic server management + tunnel

- [x] Docker Compose setup with all core containers
- [x] Backend: Server CRUD, shared sandbox management
- [x] Frontend: Server list, start/stop controls
- [x] Gateway: MCP proxy with tool aggregation
- [x] Tunnel: Named tunnel setup with Cloudflare Workers VPC
- [x] Security: Hardened sandbox, local-only admin access

**Deliverable:** Create MCP servers, run tools, access via Claude Web

### Phase 2: Python Code Tools (Complete)

**Goal:** Production-ready tool creation

- [x] Backend: Python code tool execution in shared sandbox
- [x] Frontend: Tool management UI with code preview
- [x] Sandbox: Dynamic tool registration and execution
- [x] Security: Module whitelisting, SSRF prevention

**Deliverable:** Full create → test → validate → publish workflow

### Phase 3: MCP Management Tools (Complete)

**Goal:** External LLMs create tools via MCP protocol

- [x] 18 management tools (mcpbox_*) for full CRUD
- [x] Tool approval workflow (draft → pending → approved)
- [x] Module whitelist request system
- [x] Network access request system
- [x] Admin approval UI at /approvals

**Deliverable:** LLMs can create and manage tools programmatically

### Phase 4: LLM-Assisted Features

**Goal:** AI-powered tool creation assistance

- [ ] Backend: Anthropic API integration
- [ ] Frontend: Description improvement suggestions
- [ ] Frontend: Auto-generate descriptions from API docs
- [ ] Settings: API key management

**Deliverable:** LLM helps users write better tool descriptions

### Phase 5: Polish + Commercial Features

**Goal:** Production hardening + monetization

- [ ] Named tunnel support with custom domains
- [ ] Multi-user support (for commercial)
- [ ] Usage analytics
- [ ] Backup/restore
- [ ] gVisor runtime option
- [ ] License enforcement

**Deliverable:** Ready for commercial release

---

## File Tree (Target State)

```
MCPbox/
├── docker-compose.yml           # Docker deployment (local admin + optional Cloudflare tunnel)
├── .env.example
├── LICENSE                      # PolyForm Noncommercial License
├── README.md
│
├── docs/
│   ├── ARCHITECTURE.md          # This document
│   ├── SECURITY.md              # Security details
│   ├── DEPLOYMENT.md            # Deployment guide
│   └── API.md                   # API documentation
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── api/
│       │   ├── mcp_gateway.py   # MCP Gateway (merged into backend)
│       │   └── ...              # Admin API endpoints
│       └── ...
│
├── sandbox/
│   ├── Dockerfile               # Shared sandbox service
│   └── app/
│       ├── routes.py            # Tool execution API
│       ├── registry.py          # Dynamic tool registration
│       └── executor.py          # Python code execution
│
└── scripts/
    ├── setup.sh                 # Initial setup
    ├── test-integration.sh      # Integration tests
    └── tunnel-setup.sh          # Tunnel configuration
```

**Note**: The MCP gateway is part of the backend (not a separate service). This simplifies deployment and allows sharing code between admin API and MCP gateway.

---

## Design Decisions

### MCP-First Architecture

MCPbox uses an **MCP-first approach** where external LLMs create tools via the `mcpbox_*` MCP tools rather than a visual builder.

**Rationale:**
- No API key management - users leverage existing Claude access
- Better UX - LLM handles the complexity
- Code-first - Python code is more maintainable than visual workflows
- Full control - users can write any Python logic they need

### Gateway: Python (Merged into Backend)

The MCP gateway functionality is merged into the FastAPI backend rather than being a separate Rust service.

**Rationale:**
- All tools are Python code running in a shared sandbox with HTTP transport
- No stdio-to-HTTP translation needed
- Gateway is simple: auth validation + HTTP proxy + logging
- One codebase (Python) = faster development, LLM-assisted
- Sandboxing + observability provide defense in depth
- Performance is not a bottleneck for homelab scale

**Gateway responsibilities (now in backend):**
- Terminate Streamable HTTP connections from Claude
- Validate service tokens
- Proxy requests to sandbox containers
- Aggregate tool listings
- Log all requests for observability

### Generated Code: Python/FastMCP Only

All MCP servers are generated Python code using FastMCP. This provides:

- One runtime to secure and maintain
- Consistent code structure (we control the template)
- Easier code review (predictable patterns)
- LLM can assist with generation and maintenance

### Tool/Action Architecture with Helpers

MCPbox uses a two-level hierarchy for organizing code:

```
Tool (e.g., "GitHub")
├── _helpers.py          # Tool-level shared code (optional)
├── create_pr.py         # Action with main() entry point
├── list_issues.py       # Action with main() entry point
└── search_code.py       # Action with main() entry point
```

#### Tool-Level Helpers

Helpers contain shared code for all actions within a tool. They focus on **API patterns** (not auth - that's GUI-managed):

```python
# Tool-level helpers for GitHub (_helpers.py)
BASE_URL = "https://api.github.com"

async def paginate(http, path, params=None):
    """Handle GitHub's Link header pagination."""
    results = []
    url = f"{BASE_URL}{path}"
    while url:
        resp = await http.get(url, params=params)
        results.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
        params = None  # Already in the next URL
    return results

def extract_rate_limit(resp):
    """Parse GitHub rate limit headers."""
    return {
        "remaining": resp.headers.get("X-RateLimit-Remaining"),
        "reset": resp.headers.get("X-RateLimit-Reset"),
    }
```

#### Action Code

Each action has a `main()` function as its entry point. The function signature defines the MCP tool's input schema:

```python
# Action: create_pr.py
from _helpers import paginate, BASE_URL

async def main(owner: str, repo: str, title: str, body: str, head: str) -> dict:
    """Create a pull request on GitHub.

    Args:
        owner: Repository owner
        repo: Repository name
        title: PR title
        body: PR description
        head: Branch containing changes

    Returns:
        Created pull request data
    """
    # `http` is injected by MCPbox with auth already configured
    repo_info = await http.get(f"{BASE_URL}/repos/{owner}/{repo}")
    base = repo_info.json()["default_branch"]

    resp = await http.post(
        f"{BASE_URL}/repos/{owner}/{repo}/pulls",
        json={"title": title, "body": body, "head": head, "base": base}
    )
    return resp.json()
```

#### Execution Model

At execution time, MCPbox:
1. Loads the tool's `_helpers.py` into the namespace (if present)
2. Injects `http` - a pre-authenticated `httpx.AsyncClient`
3. Injects standard library modules (`json`, `datetime`, `os.environ` for non-credential env vars)
4. Executes `main()` with the provided arguments
5. Returns the result (or captures exception)

#### Benefits

| Aspect | Benefit |
|--------|---------|
| DRY code | Common patterns (pagination, parsing) defined once per tool |
| Isolation | Tool A's helpers cannot access Tool B's code |
| Atomic actions | Each action is self-contained and testable |
| Easy updates | Change auth flow in one place (GUI), not every action |
| Git-friendly | Python files diff cleanly, unlike visual workflow JSON |

### Authentication Architecture

MCPbox uses a **hybrid architecture** with two distinct access modes:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ACCESS PATHS                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ADMIN PANEL (Local Only)                                                    │
│  ─────────────────────────                                                   │
│  User ──► localhost:3000 ──► Frontend ──► Backend /api/*                    │
│                                                                              │
│  • Ports bound to 127.0.0.1 (cannot be accessed from internet)              │
│  • JWT authentication required (defense-in-depth)                           │
│  • All management features available                                         │
│                                                                              │
│  MCP GATEWAY (Local or Remote)                                               │
│  ─────────────────────────────                                               │
│                                                                              │
│  LOCAL MODE (no service token in database):                                 │
│  Claude Desktop ──► localhost:8000/mcp                                      │
│  • No authentication required                                                │
│  • Direct access for Claude Desktop                                          │
│                                                                              │
│  REMOTE MODE (service token in database from wizard):                       │
│                                                                              │
│  User requests (JWT auth → full access):                                    │
│  Claude Web ──► MCP Portal ──► Worker ──► VPC ──► mcp-gateway:8002         │
│  • MCP Server Portal handles OAuth (Google, GitHub, etc.)                   │
│  • Worker verifies JWT (RS256) and extracts user email                      │
│  • Worker adds X-MCPbox-Service-Token + X-MCPbox-Auth-Method: jwt          │
│  • MCPbox validates service token (defense-in-depth)                        │
│  • All operations allowed (list + execute)                                   │
│                                                                              │
│  Cloudflare sync (OAuth → sync-only):                                      │
│  CF Sync ──► Worker (OAuth 2.1 flow) ──► VPC ──► mcp-gateway:8002        │
│  • Cloudflare discovers OAuth via AS metadata + PRM endpoints              │
│  • Cloudflare completes OAuth 2.1 flow (register/authorize/token)          │
│  • Worker adds X-MCPbox-Auth-Method: oauth                                 │
│  • Only tools/list and initialize allowed (no tools/call)                   │
│                                                                              │
│  Unauthenticated requests ──► Worker ──► 401 Rejected                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

MCPbox also handles downstream authentication to external APIs:

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│ Claude Web  │────────►│   MCPbox    │────────►│  MCP Server │────────►│  External   │
│             │         │   Gateway   │         │  (sandbox)  │         │  API (e.g.  │
│             │         │             │         │             │         │  GitHub)    │
└─────────────┘         └─────────────┘         └─────────────┘         └─────────────┘
        │                      │                       │                       │
        └──────────────────────┘                       └───────────────────────┘
           UPSTREAM AUTH                                  DOWNSTREAM AUTH
   (Claude → MCPbox via Service Token)              (MCP Server → External API)
```

#### Upstream Auth (Claude → MCPbox)

MCPbox supports two authentication modes:

**Local Mode** (no service token in database):
- No authentication required
- Intended for Claude Desktop connecting via localhost
- Simple setup for personal/homelab use

**Remote Mode** (service token in database, generated by wizard):
- **Mechanism**: OAuth 2.1 at Worker level, service token validation at MCPbox gateway
- **Auth paths**:

  | Request source | Auth mechanism | Worker validates | Allowed operations |
  |---|---|---|---|
  | User via MCP Portal | OAuth token + Cf-Access-Jwt-Assertion | OAuth (OAuthProvider) + JWT | All (list + execute) |
  | Cloudflare sync | OAuth token | OAuth (OAuthProvider) | Sync only (list, initialize) |
  | Unauthenticated | None | Rejected 401 by OAuthProvider | None |

- **Flow (user requests)**:
  1. User sets up MCP Server Portal in Cloudflare Zero Trust
  2. MCP Server Portal handles user OAuth (Google, GitHub, etc.)
  3. Cloudflare Worker receives request with OAuth token + CF JWT
  4. OAuthProvider validates OAuth token, then Worker verifies JWT and extracts user email
  5. Worker adds X-MCPbox-Service-Token + X-MCPbox-Auth-Method: jwt headers
  6. Worker forwards to MCPbox via Workers VPC (private tunnel)
  7. MCPbox validates service token and processes request
- **Flow (Cloudflare sync)**:
  1. MCP Server created with `auth_type: "oauth"` — Cloudflare discovers OAuth endpoints
  2. Cloudflare performs OAuth 2.1 flow (client registration, authorize, token exchange)
  3. Worker validates OAuth token, tags as `auth_method: oauth` (no JWT = sync-only)
  4. MCP Gateway allows `tools/list` and `initialize` but blocks `tools/call`
- **Benefits**:
  - OAuth 2.1 protection on Worker via `@cloudflare/workers-oauth-provider`
  - Truly private tunnel (no public hostname)
  - User identity preserved for audit logging via Cf-Access-Jwt-Assertion
  - Cloudflare sync works automatically via OAuth
  - OAuth-only requests restricted to sync-only (no tool execution)

#### Admin Panel Auth (Local Only)

The admin panel requires JWT authentication for defense-in-depth:

- **Ports**: All services bind to `127.0.0.1` (localhost only)
- **Access**: Users access via `http://localhost:3000`
- **Security**: JWT token required even though admin panel is local-only
- **Configuration**: Ports can be customized via environment variables

#### Downstream Auth (MCP Server → External APIs)

- **v1 Approach**: API Key / Personal Access Token
  - User obtains token from external service (e.g., GitHub PAT)
  - User pastes token into MCPbox UI for that server
  - MCPbox encrypts and stores token
  - Token passed to sandbox container via environment variable at startup

- **Future (v2+)**: OAuth Client Flow
  - MCPbox acts as OAuth client for supported services
  - User authorizes via OAuth popup
  - MCPbox stores and refreshes tokens automatically
  - Requires registering OAuth apps with each service

### Backend-Mediated State Storage

MCP servers that need to persist data use a backend-mediated storage API rather than direct filesystem access. This provides:

- Full audit trail of all storage operations
- Size limits per server
- Namespace isolation (server A cannot access server B's data)
- Easy backup/restore
- No filesystem escape risks

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCP SANDBOX CONTAINER                              │
│                                                                              │
│  ┌─────────────────┐                                                        │
│  │   MCP Server    │                                                        │
│  │                 │                                                        │
│  │  state.get(k)  ─┼──► HTTP GET  localhost:9999/state/{key}               │
│  │  state.set(k,v)─┼──► HTTP PUT  localhost:9999/state/{key}               │
│  │  state.del(k)  ─┼──► HTTP DEL  localhost:9999/state/{key}               │
│  │  state.list()  ─┼──► HTTP GET  localhost:9999/state                     │
│  │                 │                                                        │
│  └─────────────────┘                                                        │
│                                                                              │
│         │                                                                    │
│         │ (localhost only, container-internal)                              │
│         ▼                                                                    │
│  ┌─────────────────┐                                                        │
│  │  Storage Sidecar │◄── Injected by MCPbox into every sandbox             │
│  │  (lightweight)   │                                                       │
│  └────────┬────────┘                                                        │
│           │                                                                  │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │
            │ HTTP (internal network)
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MCPBOX BACKEND                                  │
│                                                                              │
│  POST /internal/state/{server_id}/{key}                                     │
│  GET  /internal/state/{server_id}/{key}                                     │
│  DEL  /internal/state/{server_id}/{key}                                     │
│                                                                              │
│  - Validates server_id matches requesting container                         │
│  - Enforces size limits (default: 10MB per server)                         │
│  - Logs all operations to audit_log                                         │
│  - Encrypts data at rest in PostgreSQL                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Storage Schema

```sql
-- Server state storage (backend-mediated)
CREATE TABLE server_state (
    id UUID PRIMARY KEY,
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    key VARCHAR(255) NOT NULL,
    value BYTEA NOT NULL,           -- Encrypted
    size_bytes INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(server_id, key)
);

-- Index for efficient lookups
CREATE INDEX idx_server_state_server_key ON server_state(server_id, key);

-- Track total storage per server
CREATE VIEW server_storage_usage AS
SELECT
    server_id,
    COUNT(*) as key_count,
    SUM(size_bytes) as total_bytes
FROM server_state
GROUP BY server_id;
```

#### Storage Limits

| Limit | Default | Configurable |
|-------|---------|--------------|
| Max keys per server | 1000 | Yes |
| Max value size | 1MB | Yes |
| Max total storage per server | 10MB | Yes |
| Max key length | 255 chars | No |

### Multi-User Architecture (Future-Ready)

The v1 schema includes `user_id` columns (nullable) to enable future multi-user support without schema migration.

```sql
-- Users table (created but not enforced in v1)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',  -- 'user', 'admin'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Default user for v1 (single-user mode)
INSERT INTO users (id, email, role)
VALUES ('00000000-0000-0000-0000-000000000000', 'default@local', 'admin');
```

#### Schema Updates for Multi-User

```sql
-- Add user_id to all user-owned tables
ALTER TABLE servers ADD COLUMN user_id UUID REFERENCES users(id)
    DEFAULT '00000000-0000-0000-0000-000000000000';
ALTER TABLE credentials ADD COLUMN user_id UUID REFERENCES users(id)
    DEFAULT '00000000-0000-0000-0000-000000000000';
ALTER TABLE tunnel_config ADD COLUMN user_id UUID REFERENCES users(id)
    DEFAULT '00000000-0000-0000-0000-000000000000';
ALTER TABLE audit_log ADD COLUMN user_id UUID REFERENCES users(id);
```

#### v1 vs v2 Behavior

| Aspect | v1 (Single-User) | v2 (Multi-User) |
|--------|------------------|-----------------|
| Authentication | None or optional password | Full auth (OAuth, email/password) |
| user_id columns | Default to single user | Required, enforced |
| Container networks | Shared sandbox network | Per-user sandbox networks |
| Tunnel | Single tunnel | Per-user tunnels or shared with routing |
| API filtering | No filtering | Filter by authenticated user |
| UI | No login screen | Login + user management |

### Error Handling

#### Sandbox Crash Recovery

MCP sandbox containers may crash due to bugs, resource exhaustion, or external factors. MCPbox implements automatic restart with backoff:

| Scenario | Response |
|----------|----------|
| First crash | Immediate restart |
| Second crash within 5 min | Restart after 5s |
| Third crash within 5 min | Restart after 15s |
| Fourth+ crash within 5 min | Mark as error, alert user |

After 5 minutes of stability, the crash counter resets.

```python
# Pseudo-code for crash handling
MAX_RESTARTS = 3
RESET_WINDOW = 300  # 5 minutes

def handle_container_exit(server_id, exit_code):
    recent_crashes = get_crashes_in_window(server_id, RESET_WINDOW)

    if len(recent_crashes) < MAX_RESTARTS:
        delay = [0, 5, 15][len(recent_crashes)]
        schedule_restart(server_id, delay)
        log_warning(f"Server {server_id} crashed, restarting in {delay}s")
    else:
        set_server_status(server_id, "error")
        create_alert(server_id, "Server crashed repeatedly, manual intervention required")
```

#### Tool Execution Timeouts

Tool calls have configurable timeouts to prevent runaway operations:

| Setting | Default | Scope |
|---------|---------|-------|
| Global default | 30 seconds | All tools |
| Per-server | Inherits global | All tools on server |
| Per-tool | Inherits server | Specific tool |

Configuration stored in database:

```sql
-- Add to servers table
ALTER TABLE servers ADD COLUMN default_timeout_ms INTEGER DEFAULT 30000;

-- Add to tools table
ALTER TABLE tools ADD COLUMN timeout_ms INTEGER;  -- NULL = inherit from server
```

Timeout behavior:
- Request cancelled after timeout
- Error response returned to Claude: `{"error": {"code": -32002, "message": "Tool execution timed out"}}`
- Container NOT killed (only the request)
- Logged for observability

#### Tunnel Disconnection

Cloudflare tunnel disconnections are handled automatically by `cloudflared`:

| Scenario | Response |
|----------|----------|
| Network blip | `cloudflared` auto-reconnects |
| Cloudflare outage | `cloudflared` retries with backoff |
| Config error | `cloudflared` exits, MCPbox alerts user |

MCPbox monitors tunnel health:
- Periodic health check via `cloudflared` metrics endpoint
- UI shows tunnel status (Connected/Disconnected/Error)
- Alert generated after 60s of disconnection

#### Database Connection Loss

Backend uses connection pooling with automatic reconnection:

```python
# SQLAlchemy configuration
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,  # Recycle connections every 30 min
    pool_pre_ping=True,  # Verify connection before use
)
```

| Scenario | Response |
|----------|----------|
| Transient failure | Automatic retry (up to 3 attempts) |
| Extended outage | API returns 503, alert user |
| Connection pool exhausted | Queue requests, log warning |

### Credential System

MCPbox uses **GUI-managed authentication** - users configure auth in the UI, and credentials are securely stored with AES-256-GCM encryption.

#### Supported Auth Types

| Type | Description | Use Case |
|------|-------------|----------|
| `api_key_bearer` | `Authorization: Bearer <key>` | GitHub, OpenAI, most modern APIs |
| `api_key_header` | Custom header (e.g., `X-API-Key: <key>`) | Various APIs |
| `basic` | HTTP Basic auth (username:password) | Enterprise APIs |
| `custom_headers` | Multiple static headers | APIs requiring multiple headers |

#### Credential Policies

| Policy | Decision | Rationale |
|--------|----------|-----------|
| Multiple credentials per server | **Yes** | APIs may need multiple auth methods |
| Credential sharing across servers | **No** | Security - 1:1 mapping prevents credential leakage |

### Persistence Strategy

#### v1: PostgreSQL Only

All persistence is handled via PostgreSQL:

| Data Type | Storage |
|-----------|---------|
| Server configuration | `servers` table |
| Tool metadata | `tools` table |
| Credentials | `credentials` table (encrypted) |
| MCP server state | `server_state` table (encrypted, backend-mediated) |
| Observability logs | `network_logs`, `storage_logs`, `mcp_request_logs` tables |
| Alerts | `alert_rules`, `alert_history` tables |
| Tunnel config | `tunnel_config` table |

**Rationale:**
- Single backing store = simpler operations
- PostgreSQL handles JSONB well for flexible schemas
- Built-in encryption at rest support
- Easy backup/restore (pg_dump)

### Secrets Management

#### Encryption Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SECRETS ENCRYPTION                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Master Key: MCPBOX_ENCRYPTION_KEY (env variable)                           │
│  ├── User provides: openssl rand -hex 32                                    │
│  └── Stored: User's responsibility (not in PostgreSQL)                      │
│                                                                              │
│  Encryption: AES-256-GCM                                                     │
│  ├── Per-value random IV                                                     │
│  ├── Authenticated encryption (tamper detection)                            │
│  └── Key derivation: HKDF with per-purpose salts                            │
│                                                                              │
│  Stored format: IV || ciphertext || tag                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Key Management Policies

| Scenario | Behavior |
|----------|----------|
| **Key loss** | Data loss - all encrypted credentials unrecoverable. User is responsible for backing up their encryption key. |
| **Key rotation** | Supported - decrypt all values with old key, re-encrypt with new key, atomic transaction |
| **Key backup** | User responsibility - document in setup guide |
| **Export/import** | Phase 2+ - requires secure transport mechanism |

#### Key Rotation Process

```python
# Key rotation endpoint (admin only)
async def rotate_encryption_key(old_key: str, new_key: str):
    async with db.transaction():
        # Re-encrypt all credentials
        for cred in await Credential.all():
            plaintext = decrypt(cred.encrypted_value, old_key)
            cred.encrypted_value = encrypt(plaintext, new_key)
            await cred.save()

        # Re-encrypt server state
        for state in await ServerState.all():
            plaintext = decrypt(state.value, old_key)
            state.value = encrypt(plaintext, new_key)
            await state.save()

        # Re-encrypt OAuth secrets
        for cred in await Credential.filter(auth_type='oauth2'):
            # Re-encrypt client_secret, tokens, etc.
            ...

    return {"status": "rotated", "records_updated": count}
```

### Licensing

MCPbox uses **PolyForm Noncommercial License 1.0.0** for the core project.

#### License Summary

| Use Case | Permitted |
|----------|-----------|
| Personal/homelab use | ✅ Yes, free |
| Academic/research | ✅ Yes, free |
| Non-profit organizations | ✅ Yes, free |
| Internal business use | ❌ Requires commercial license |
| Reselling/SaaS | ❌ Requires commercial license |

#### License Text Location

```
MCPbox/
├── LICENSE                    # PolyForm Noncommercial 1.0.0
├── LICENSE-COMMERCIAL.md      # Commercial license terms
└── docs/
    └── LICENSING.md           # Detailed licensing FAQ
```

#### Commercial Licensing

For commercial use, contact licensing@example.com (placeholder).

Commercial license includes:
- Unlimited commercial deployment
- Priority support
- Custom features on request
- Multi-tenant/SaaS rights

---

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [FastMCP Documentation](https://gofastmcp.com/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Cloudflare Tunnel Documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Claude Remote MCP Guide](https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers)
- [PolyForm Noncommercial License](https://polyformproject.org/licenses/noncommercial/1.0.0/)
