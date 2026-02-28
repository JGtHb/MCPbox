# Data Model

> Conceptual overview and detailed schema reference for all backend database models.

## Table of Contents

- [Overview](#overview)
- [Entity Relationship Diagram](#entity-relationship-diagram)
- [Design Patterns](#design-patterns)
- [Base Classes](#base-classes)
- [Schema Reference](#schema-reference)
  - [Core Platform](#core-platform)
  - [External MCP Integration](#external-mcp-integration)
  - [Approval Workflow](#approval-workflow)
  - [Authentication & Security](#authentication--security)
  - [Cloudflare Remote Access](#cloudflare-remote-access)
  - [Observability](#observability)
  - [Configuration](#configuration)
- [Enums](#enums)
- [Migrations](#migrations)

---

## Overview

MCPBox uses PostgreSQL 16 with SQLAlchemy (async) and Alembic for migrations. The backend defines **15 models** inheriting from `BaseModel` (UUID primary key + timestamps) plus **1 special model** (`TokenBlacklist`) with a string primary key.

Models are organized into 7 functional domains:

| Domain | Models | Purpose |
|--------|--------|---------|
| Core Platform | Server, Tool, ToolVersion, ServerSecret | MCP servers, tools, versioning, secrets |
| External MCP | ExternalMCPSource | Connections to external MCP servers |
| Approval Workflow | NetworkAccessRequest, ModuleRequest, GlobalConfig | Network/module whitelisting with audit trail |
| Auth & Security | AdminUser, TokenBlacklist | JWT auth, token revocation |
| Cloudflare | CloudflareConfig, TunnelConfiguration | Remote access wizard state |
| Observability | ActivityLog, ToolExecutionLog | MCP activity and tool execution logs |
| Configuration | Setting | Key-value application settings |

All model source files are in `backend/app/models/`.

---

## Entity Relationship Diagram

```
                          ┌──────────────────┐
                          │    AdminUser      │
                          └──────────────────┘

                          ┌──────────────────┐
                          │  TokenBlacklist   │  (no FK, string PK)
                          └──────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  CloudflareConfig│      │     Setting      │      │TunnelConfiguration│
└──────────────────┘      └──────────────────┘      └──────────────────┘

                          ┌──────────────────┐
                          │   GlobalConfig    │  ← derived cache: allowed_modules
                          └──────────────────┘
                                   ▲
                                   │ sync_allowed_modules() recomputes from:
                                   │
                          ┌──────────────────┐
                     ┌────│  ModuleRequest    │  ← single source of truth
                     │    └──────────────────┘
                     │             │
                     │ tool_id     │ server_id
                     │ (nullable)  │ (nullable)
                     ▼             ▼
               ┌───────────┐ ┌──────────────────┐
               │   Tool     │ │     Server        │ ← derived cache: allowed_hosts
               │           │ │                    │
               │ server_id─┼─►                    │
               └───────────┘ └──────────────────┘
                     ▲  │           │  ▲         │
                     │  │           │  │         │
        ┌────────────┘  │           │  │         └──────────────┐
        │               ▼           │  │                        │
        │    ┌──────────────────┐   │  │         ┌──────────────────┐
        │    │   ToolVersion    │   │  │         │  ServerSecret    │
        │    └──────────────────┘   │  │         └──────────────────┘
        │                           │  │
        │    ┌──────────────────┐   │  │         ┌──────────────────┐
        │    │ToolExecutionLog  │   │  │         │ExternalMCPSource │
        │    └──────────────────┘   │  │         └──────────────────┘
        │                           │  │              │        ▲
        │                           │  │    tools ────┘        │
        │                           │  │ (external_source_id)  │
        │                           │  │                       │
        │                           │  └── server_id ──────────┘
        │                           │
        │  ┌────────────────────┐   │
        └──│NetworkAccessRequest│───┘
           └────────────────────┘
             tool_id (nullable)
             server_id (nullable)
             ↑ single source of truth → sync_allowed_hosts() recomputes Server.allowed_hosts
```

```
┌──────────────────┐      ┌──────────────────┐
│   ActivityLog    │─────►│     Server       │  (server_id, nullable)
└──────────────────┘      └──────────────────┘
```

**Key:** Arrows indicate foreign key direction (child → parent). Nullable FKs allow standalone records (e.g., admin-initiated requests without a tool).

---

## Design Patterns

### 1. Single Source of Truth

Request tables are authoritative; array columns are derived caches:

```
NetworkAccessRequest (approved records)  ──sync_allowed_hosts()──►  Server.allowed_hosts
ModuleRequest (approved records)         ──sync_allowed_modules()──► GlobalConfig.allowed_modules
```

Every mutation creates/deletes records first, then calls the sync helper. No code path writes to the cache columns directly. The sandbox reads the cache columns for performance; the UI reads from request tables for full audit history.

### 2. Approval Workflow

Tools follow a state machine: `draft → pending_review → approved → rejected`

- **Code changes reset status** to `pending_review` (prevents TOCTOU — see ADR in [DECISIONS.md](DECISIONS.md))
- **Rollback resets status** (rolling back to different code requires re-approval)
- Only `approved` + `enabled` tools are registered in the sandbox

### 3. Nullable tool_id

`NetworkAccessRequest` and `ModuleRequest` support two origins:

| Origin | `tool_id` | `server_id` | Meaning |
|--------|-----------|-------------|---------|
| LLM request | Set (FK to tool) | Denormalized from tool | Tool requested this resource |
| Admin addition | NULL | Set directly (or NULL for global modules) | Admin manually added |

### 4. Partial Unique Indexes

Prevent duplicate **pending** requests while allowing multiple approved/rejected records for the same resource:

```sql
-- Only one pending request per tool+host combination
CREATE UNIQUE INDEX ix_nar_pending_tool_unique
  ON network_access_requests (tool_id, host, COALESCE(port, 0))
  WHERE status = 'pending' AND tool_id IS NOT NULL;

-- Only one pending admin request per server+host combination
CREATE UNIQUE INDEX ix_nar_pending_admin_unique
  ON network_access_requests (server_id, host, COALESCE(port, 0))
  WHERE status = 'pending' AND tool_id IS NULL;
```

### 5. Application-Level Encryption

Sensitive fields use AES-256-GCM encryption via `MCPBOX_ENCRYPTION_KEY` (64 hex chars). Encryption happens in the service layer, not at the database level. Affected models:
- `ServerSecret.encrypted_value` (BYTEA)
- `CloudflareConfig.encrypted_*` fields (Text, base64-encoded)
- `ExternalMCPSource.oauth_tokens_encrypted` (Text)
- `Setting.value` (when `encrypted=True`)

### 6. Denormalization

`server_id` is denormalized onto child tables for query performance:
- `NetworkAccessRequest.server_id` — avoids JOIN through Tool to find server
- `ModuleRequest.server_id` — same pattern
- `ToolExecutionLog.server_id` + `tool_name` — avoids JOINs in log queries

### 7. Cascade Deletion

Most relationships use `cascade="all, delete-orphan"`. Deleting a Server cascades to its tools, secrets, sources, requests, and logs. Deleting a Tool cascades to its versions, requests, and execution logs.

Exception: `Tool.external_source_id` uses `ondelete="SET NULL"` — deleting an external source doesn't delete imported tools, just unlinks them.

### 8. Soft Foreign Key

`ExternalMCPSource.auth_secret_name` is a string reference to `ServerSecret.key_name`, not a database FK. This allows flexible auth configuration without circular dependencies.

---

## Base Classes

All models except `TokenBlacklist` inherit from `BaseModel`, which provides:

**Source:** `backend/app/models/base.py`

| Mixin | Column | Type | Notes |
|-------|--------|------|-------|
| UUIDMixin | `id` | UUID | Primary key, auto-generated (`uuid4`) |
| TimestampMixin | `created_at` | DateTime(tz) | Server default `now()`, not nullable |
| TimestampMixin | `updated_at` | DateTime(tz) | Server default `now()`, auto-updates, not nullable |

> These three columns are **inherited by all models below** and omitted from individual model tables for brevity.

---

## Schema Reference

### Core Platform

#### Server

**Table:** `servers` &nbsp;|&nbsp; **Source:** `backend/app/models/server.py`

MCP server configuration. Central hub that owns tools, secrets, external sources, and approval requests.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `name` | String(255) | No | | Display name |
| `description` | Text | Yes | | |
| `status` | Enum(`server_status`) | No | `imported` | See [Enums](#enums) |
| `allowed_hosts` | ARRAY(String) | No | `{}` | **Derived cache** — recomputed by `sync_allowed_hosts()` |
| `default_timeout_ms` | Integer | No | `30000` | Per-server timeout for tool execution |

**Relationships:**

| Relationship | Target | FK | Cascade |
|-------------|--------|-----|---------|
| `tools` | Tool[] | `Tool.server_id` | all, delete-orphan |
| `secrets` | ServerSecret[] | `ServerSecret.server_id` | all, delete-orphan |
| `external_mcp_sources` | ExternalMCPSource[] | `ExternalMCPSource.server_id` | all, delete-orphan |
| `network_access_requests` | NetworkAccessRequest[] | `NetworkAccessRequest.server_id` | all, delete-orphan |
| `module_requests` | ModuleRequest[] | `ModuleRequest.server_id` | all, delete-orphan |

---

#### Tool

**Table:** `tools` &nbsp;|&nbsp; **Source:** `backend/app/models/tool.py`

MCP tool exposed by a server. Can be Python code executed in the sandbox or a passthrough to an external MCP server.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `server_id` | UUID (FK → servers) | No | | Parent server, `ondelete=CASCADE` |
| `name` | String(255) | No | | Unique per server |
| `description` | Text | Yes | | MCP tool description |
| `input_schema` | JSONB | Yes | | JSON Schema for parameters |
| `enabled` | Boolean | No | `True` | Disabled tools excluded from sandbox |
| `timeout_ms` | Integer | Yes | | Per-tool override (NULL = inherit from server) |
| `tool_type` | Enum(`tool_type`) | No | `python_code` | `python_code` or `mcp_passthrough` |
| `python_code` | Text | Yes | | Source code with `async def main()` |
| `external_source_id` | UUID (FK → external_mcp_sources) | Yes | | For passthrough tools, `ondelete=SET NULL` |
| `external_tool_name` | String(255) | Yes | | Original name on external server |
| `code_dependencies` | ARRAY(String) | Yes | | pip packages required |
| `current_version` | Integer | No | `1` | Incremented on each update |
| `approval_status` | Enum(`approval_status`) | No | `draft` | See [Approval Workflow](#2-approval-workflow) |
| `approval_requested_at` | DateTime(tz) | Yes | | When admin review was requested |
| `approved_at` | DateTime(tz) | Yes | | When approved |
| `approved_by` | String(255) | Yes | | Admin who approved |
| `rejection_reason` | Text | Yes | | Admin feedback on rejection |
| `created_by` | String(255) | Yes | | Creator email |
| `publish_notes` | Text | Yes | | LLM notes for admin review |

**Constraints:** `UNIQUE(server_id, name)`

**Relationships:**

| Relationship | Target | FK | Cascade |
|-------------|--------|-----|---------|
| `server` | Server | `server_id` | — |
| `external_source` | ExternalMCPSource | `external_source_id` | — |
| `versions` | ToolVersion[] | `ToolVersion.tool_id` | all, delete-orphan |
| `module_requests` | ModuleRequest[] | `ModuleRequest.tool_id` | all, delete-orphan |
| `network_access_requests` | NetworkAccessRequest[] | `NetworkAccessRequest.tool_id` | all, delete-orphan |

---

#### ToolVersion

**Table:** `tool_versions` &nbsp;|&nbsp; **Source:** `backend/app/models/tool_version.py`

Immutable snapshot of tool state at a point in time. Enables version comparison and rollback.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `tool_id` | UUID (FK → tools) | No | | Parent tool, `ondelete=CASCADE` |
| `version_number` | Integer | No | | Sequential within tool |
| `name` | String(255) | No | | Snapshot of tool name |
| `description` | Text | Yes | | Snapshot |
| `enabled` | Boolean | No | `True` | Snapshot |
| `timeout_ms` | Integer | Yes | | Snapshot |
| `python_code` | Text | Yes | | Snapshot of source code |
| `input_schema` | JSONB | Yes | | Snapshot |
| `change_summary` | String(500) | Yes | | Brief description of changes |
| `change_source` | String(50) | No | `manual` | Values: `manual`, `llm`, `import`, `rollback` |

---

#### ServerSecret

**Table:** `server_secrets` &nbsp;|&nbsp; **Source:** `backend/app/models/server_secret.py`

Encrypted key-value secrets shared by all tools in a server. LLMs create placeholders; admins set values via the UI. Secret values never pass through the LLM or appear in API responses (only `has_value: bool`).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `server_id` | UUID (FK → servers) | No | | Parent server, `ondelete=CASCADE` |
| `key_name` | String(255) | No | | e.g., `GITHUB_TOKEN` |
| `encrypted_value` | BYTEA | Yes | | AES-256-GCM encrypted; NULL = placeholder |
| `description` | Text | Yes | | Human-readable purpose |

**Constraints:** `UNIQUE(server_id, key_name)`

**Properties:** `has_value: bool` — True if `encrypted_value` is not None.

Tool code accesses secrets via `secrets["KEY_NAME"]`.

---

### External MCP Integration

#### ExternalMCPSource

**Table:** `external_mcp_sources` &nbsp;|&nbsp; **Source:** `backend/app/models/external_mcp_source.py`

Connection to an external MCP server. Multiple sources can be attached to one MCPBox server. Tools from external servers can be selectively imported as `mcp_passthrough` tools.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `server_id` | UUID (FK → servers) | No | | Parent MCPBox server, `ondelete=CASCADE` |
| `name` | String(255) | No | | Display name (e.g., "GitHub MCP") |
| `url` | Text | No | | External MCP server endpoint |
| `auth_type` | Enum(`external_mcp_auth_type`) | No | `none` | See [Enums](#enums) |
| `auth_secret_name` | String(255) | Yes | | Soft FK to `ServerSecret.key_name` |
| `auth_header_name` | String(255) | Yes | | Custom header name (default: Authorization) |
| `transport_type` | Enum(`external_mcp_transport_type`) | No | `streamable_http` | See [Enums](#enums) |
| `status` | Enum(`external_mcp_source_status`) | No | `active` | See [Enums](#enums) |
| `oauth_tokens_encrypted` | Text | Yes | | Encrypted JSON: tokens, endpoint, expiry |
| `oauth_issuer` | String(2000) | Yes | | Authorization server URL |
| `oauth_client_id` | String(255) | Yes | | From DCR or manual config |
| `last_discovered_at` | DateTime(tz) | Yes | | Last tool discovery timestamp |
| `tool_count` | Integer | No | `0` | Discovered tool count |
| `discovered_tools_cache` | JSONB | Yes | | Cached `[{name, description, input_schema}]` |

**Relationships:**

| Relationship | Target | FK | Notes |
|-------------|--------|-----|-------|
| `server` | Server | `server_id` | |
| `tools` | Tool[] | `Tool.external_source_id` | Imported passthrough tools |

---

### Approval Workflow

#### NetworkAccessRequest

**Table:** `network_access_requests` &nbsp;|&nbsp; **Source:** `backend/app/models/network_access_request.py`

Single source of truth for network host whitelist. `Server.allowed_hosts` is recomputed from approved records via `sync_allowed_hosts()`.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `tool_id` | UUID (FK → tools) | **Yes** | | NULL for admin-initiated, `ondelete=CASCADE` |
| `server_id` | UUID (FK → servers) | **Yes** | | Denormalized or set directly, `ondelete=CASCADE` |
| `host` | String(255) | No | | Hostname or IP address |
| `port` | Integer | Yes | | NULL = any port |
| `justification` | Text | No | | Why access is needed |
| `requested_by` | String(255) | Yes | | Email from JWT |
| `status` | Enum(`request_status`) | No | `pending` | See [Enums](#enums) |
| `reviewed_at` | DateTime(tz) | Yes | | |
| `reviewed_by` | String(255) | Yes | | Admin email |
| `rejection_reason` | Text | Yes | | |

**Indexes:** Two partial unique indexes prevent duplicate pending requests (see [Design Patterns](#4-partial-unique-indexes)).

---

#### ModuleRequest

**Table:** `module_requests` &nbsp;|&nbsp; **Source:** `backend/app/models/module_request.py`

Single source of truth for Python module whitelist. `GlobalConfig.allowed_modules` is recomputed from approved records via `sync_allowed_modules()`.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `tool_id` | UUID (FK → tools) | **Yes** | | NULL for admin-initiated, `ondelete=CASCADE` |
| `server_id` | UUID (FK → servers) | **Yes** | | NULL for admin global additions, `ondelete=CASCADE` |
| `module_name` | String(255) | No | | e.g., `xml.etree.ElementTree` |
| `justification` | Text | No | | Why the module is needed |
| `requested_by` | String(255) | Yes | | Email from JWT |
| `status` | Enum(`request_status`) | No | `pending` | See [Enums](#enums) |
| `reviewed_at` | DateTime(tz) | Yes | | |
| `reviewed_by` | String(255) | Yes | | Admin email |
| `rejection_reason` | Text | Yes | | |

**Indexes:** Two partial unique indexes — same pattern as NetworkAccessRequest.

---

#### GlobalConfig

**Table:** `global_config` &nbsp;|&nbsp; **Source:** `backend/app/models/global_config.py`

Singleton for application-wide settings. Only one row exists (enforced by unique `config_key`).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `config_key` | String(50) | No | `main` | Unique, enforces singleton |
| `allowed_modules` | ARRAY(String) | Yes | | **Derived cache** — recomputed by `sync_allowed_modules()` |

---

### Authentication & Security

#### AdminUser

**Table:** `admin_users` &nbsp;|&nbsp; **Source:** `backend/app/models/admin_user.py`

JWT-based authentication for the web UI. Passwords are Argon2-hashed.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `username` | String(255) | No | | Unique, indexed |
| `password_hash` | String(255) | No | | Argon2 hash |
| `is_active` | Boolean | No | `True` | |
| `password_version` | Integer | No | `1` | Incremented on password change to invalidate all tokens |
| `last_login_at` | DateTime(tz) | Yes | | Audit tracking |

---

#### TokenBlacklist

**Table:** `token_blacklist` &nbsp;|&nbsp; **Source:** `backend/app/models/token_blacklist.py`

Revoked JWT tokens. Survives process restarts (SEC-009). **Does not inherit from BaseModel** — uses a string primary key with no UUID or timestamps.

| Column | Type | Nullable | PK | Notes |
|--------|------|----------|-----|-------|
| `jti` | String(64) | No | Yes | JWT ID claim |
| `expires_at` | DateTime(tz) | No | | Indexed; rows cleaned up after expiry |

---

### Cloudflare Remote Access

#### CloudflareConfig

**Table:** `cloudflare_configs` &nbsp;|&nbsp; **Source:** `backend/app/models/cloudflare_config.py`

Wizard state for Cloudflare remote access setup. Stores encrypted API tokens, tunnel configuration, Worker deployment details, and OIDC credentials. Only one active configuration is supported.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `encrypted_api_token` | Text | No | | Cloudflare API token (encrypted) |
| `account_id` | String(64) | No | | From token verification |
| `account_name` | String(255) | Yes | | |
| `team_domain` | String(255) | Yes | | Zero Trust team domain |
| `tunnel_id` | String(64) | Yes | | Named tunnel ID |
| `tunnel_name` | String(255) | Yes | | |
| `encrypted_tunnel_token` | Text | Yes | | Tunnel connector token (encrypted) |
| `vpc_service_id` | String(64) | Yes | | Cloudflare VPC service ID |
| `vpc_service_name` | String(255) | Yes | | |
| `worker_name` | String(255) | Yes | | |
| `worker_url` | String(1024) | Yes | | |
| `encrypted_service_token` | Text | Yes | | MCP auth token (encrypted) |
| `kv_namespace_id` | String(64) | Yes | | OAuth token storage KV namespace |
| `access_app_id` | String(64) | Yes | | SaaS OIDC app ID |
| `encrypted_access_client_id` | Text | Yes | | OIDC credentials (encrypted) |
| `encrypted_access_client_secret` | Text | Yes | | OIDC credentials (encrypted) |
| `encrypted_cookie_encryption_key` | Text | Yes | | Worker approval cookie key (encrypted) |
| `access_policy_type` | String(16) | Yes | | Policy enforcement type |
| `access_policy_emails` | Text | Yes | | CSV of allowed emails |
| `access_policy_email_domain` | String(255) | Yes | | Email domain restriction |
| `allowed_cors_origins` | Text | Yes | | JSON array of additional CORS origins |
| `allowed_redirect_uris` | Text | Yes | | JSON array of OAuth redirect URIs |
| `completed_step` | Integer | No | `0` | Wizard progress (0-5) |
| `status` | String(32) | No | `pending` | Values: pending, active, error |
| `error_message` | Text | Yes | | Wizard error details |

---

#### TunnelConfiguration

**Table:** `tunnel_configurations` &nbsp;|&nbsp; **Source:** `backend/app/models/tunnel_configuration.py`

Saved tunnel configuration profiles. Users can have multiple profiles (e.g., "Production", "Development") and switch between them.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `name` | String(255) | No | | Profile name |
| `description` | Text | Yes | | |
| `tunnel_token` | Text | Yes | | Encrypted Cloudflare tunnel token |
| `public_url` | String(1024) | Yes | | e.g., `mcpbox.example.com` |
| `is_active` | Boolean | No | `False` | Only one active at a time |

---

### Observability

#### ActivityLog

**Table:** `activity_logs` &nbsp;|&nbsp; **Source:** `backend/app/models/activity_log.py`

MCP request/response logging with correlation support. No relationships (read-only for observability).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `server_id` | UUID (FK → servers) | Yes | | NULL for system-wide events, `ondelete=CASCADE` |
| `log_type` | Enum(`log_type`) | No | | See [Enums](#enums) |
| `level` | Enum(`log_level`) | No | `info` | See [Enums](#enums) |
| `message` | Text | No | | Log message |
| `details` | JSONB | Yes | | Additional structured context |
| `request_id` | String(64) | Yes | | For request/response correlation |
| `duration_ms` | Integer | Yes | | Response time tracking |

**Indexes:**

| Name | Columns |
|------|---------|
| `ix_activity_logs_server_created` | server_id, created_at |
| `ix_activity_logs_type_created` | log_type, created_at |
| `ix_activity_logs_level_created` | level, created_at |

---

#### ToolExecutionLog

**Table:** `tool_execution_logs` &nbsp;|&nbsp; **Source:** `backend/app/models/tool_execution_log.py`

Per-tool execution history. Input arguments have secrets redacted. Results are truncated if large. No relationships (read-only).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `tool_id` | UUID (FK → tools) | No | | `ondelete=CASCADE` |
| `server_id` | UUID (FK → servers) | No | | Denormalized, `ondelete=CASCADE` |
| `tool_name` | String(255) | No | | Denormalized for display |
| `input_args` | JSONB | Yes | | Secrets redacted |
| `result` | JSONB | Yes | | Truncated if large |
| `error` | Text | Yes | | Exception message |
| `stdout` | Text | Yes | | Captured print output |
| `duration_ms` | Integer | Yes | | Execution time |
| `success` | Boolean | No | `False` | |
| `is_test` | Boolean | No | `False` | Flags runs from `mcpbox_test_code` |
| `executed_by` | String(255) | Yes | | User email if available |

**Indexes:**

| Name | Columns |
|------|---------|
| `ix_tool_execution_logs_tool_created` | tool_id, created_at |
| `ix_tool_execution_logs_server_created` | server_id, created_at |

---

### Configuration

#### Setting

**Table:** `settings` &nbsp;|&nbsp; **Source:** `backend/app/models/setting.py`

Generic key-value configuration store. Supports application-level encryption for sensitive values (API keys, feature toggles, etc.).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `key` | String(255) | No | | Unique, indexed |
| `value` | Text | Yes | | May be encrypted |
| `encrypted` | Boolean | No | `False` | Whether value is encrypted |
| `description` | String(500) | Yes | | Human-readable description |

---

## Enums

All enums are PostgreSQL-level constraints created in migrations.

| Enum Name | Values | Used By |
|-----------|--------|---------|
| `server_status` | imported, ready, running, stopped, error | Server.status |
| `tool_type` | python_code, mcp_passthrough | Tool.tool_type |
| `approval_status` | draft, pending_review, approved, rejected | Tool.approval_status |
| `request_status` | pending, approved, rejected | NetworkAccessRequest.status, ModuleRequest.status |
| `log_type` | mcp_request, mcp_response, network, alert, error, system, audit | ActivityLog.log_type |
| `log_level` | debug, info, warning, error | ActivityLog.level |
| `external_mcp_auth_type` | none, bearer, header, oauth | ExternalMCPSource.auth_type |
| `external_mcp_transport_type` | streamable_http, sse | ExternalMCPSource.transport_type |
| `external_mcp_source_status` | active, error, disabled | ExternalMCPSource.status |

---

## Migrations

Migration files are in `backend/alembic/versions/`. Migrations run automatically on container startup via `backend/entrypoint.sh`.

### 0001: Initial Schema

**File:** `0001_initial_schema.py`

Creates all 15 tables, enum types, unique constraints, and partial unique indexes. Establishes the full database schema from scratch.

### 0002: Consolidate Approval Sources

**File:** `0002_consolidate_approval_sources.py`

Makes request tables the single source of truth:

1. Adds `server_id` column to `network_access_requests` and `module_requests`
2. Makes `tool_id` nullable on both tables (was NOT NULL)
3. Backfills `server_id` from `tools.server_id` for existing tool-initiated records
4. Replaces single partial unique indexes with two each (tool-initiated vs admin-initiated)
5. Creates `NetworkAccessRequest` records for existing manual hosts in `Server.allowed_hosts`
6. Creates `ModuleRequest` records for existing manual modules in `GlobalConfig.allowed_modules`

**Downgrade:** Removes admin-originated records, restores original indexes, reverts `tool_id` to NOT NULL, drops `server_id` columns.
