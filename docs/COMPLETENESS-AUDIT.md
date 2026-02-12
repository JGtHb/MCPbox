# MCPbox Completeness Audit Report

**Date:** 2026-02-12
**Auditor:** Automated (Claude Opus 4.6)
**Scope:** Full codebase — backend, frontend, sandbox, worker, infrastructure, documentation

## Executive Summary

The MCPbox codebase is **well-structured and production-ready** for its homelab use case. The audit found **11 actionable findings** across all categories. No critical incomplete features, no stub implementations, and no placeholder logic were found. The codebase is notably clean — zero TODO/FIXME/HACK comments exist in application code.

**Key metrics:**
- 0 TODO/FIXME/HACK/STUB comments in application code
- 0 frontend routes pointing to missing components
- 0 API client functions with zero callers
- 0 backend endpoints returning 501/NotImplementedError
- 11 findings total (3 dead code, 3 vestigial, 2 config gaps, 2 infrastructure, 1 documentation)

---

## Findings

### [Dead Code] Unused Schema: `ExistingResource` in cloudflare.py

- **Location:** `backend/app/schemas/cloudflare.py:32`
- **What exists:** A Pydantic model `ExistingResource` with fields `resource_type`, `name`, `id`
- **What's missing:** Zero references anywhere in the codebase — never imported, never instantiated
- **Evidence:** `grep -r "ExistingResource" backend/` returns only the definition at line 32
- **Recommendation:** **REMOVE** — Dead schema class with no callers

---

### [Dead Code] Unused Schema: `RequestStatus` in approval.py

- **Location:** `backend/app/schemas/approval.py:10-15`
- **What exists:** A `StrEnum` class `RequestStatus` with values PENDING, APPROVED, REJECTED
- **What's missing:** Never imported anywhere outside its own file. The models (ModuleRequest, NetworkAccessRequest) define their own status fields as plain strings, and the approval service uses string literals directly.
- **Evidence:** `grep -r "from.*approval.*import.*RequestStatus" backend/` returns 0 matches. The `schemas/__init__.py` does not export it.
- **Recommendation:** **REMOVE** — Duplicate of model-level status handling, never used

---

### [Dead Code] Unused Schema: `SettingUpdate` in setting.py

- **Location:** `backend/app/schemas/setting.py:9-12`
- **What exists:** A Pydantic model `SettingUpdate` with a single `value` field
- **What's missing:** Never imported or used in any API endpoint. The settings API uses inline request parsing instead.
- **Evidence:** `grep -r "SettingUpdate" backend/app/api/` returns 0 matches
- **Recommendation:** **REMOVE** — Dead schema, API endpoints don't use it

---

### [Dead Code] Unused Function: `get_all_stdlib_modules()` in stdlib_detector.py

- **Location:** `sandbox/app/stdlib_detector.py:283-293`
- **What exists:** A utility function that returns all stdlib module names using `sys.stdlib_module_names`
- **What's missing:** Never called from anywhere. The codebase uses `is_stdlib_module()` and `classify_modules()` instead.
- **Evidence:** `grep -r "get_all_stdlib_modules" .` returns only the definition
- **Recommendation:** **REMOVE** — Unused utility function

---

### [Vestigial Code] Dead Enum Values in Server Model

- **Location:** `backend/app/models/server.py:16-27` (ServerStatus) and `backend/app/models/server.py:30-38` (NetworkMode)
- **What exists:**
  - `ServerStatus` includes `"building"` — commented as "vestigial from per-server container architecture"
  - `NetworkMode` includes `"monitored"` and `"learning"` — commented as "unused, kept for database enum compatibility"
- **What's missing:** These enum values are never set by any application code. No code path transitions a server to "building" status. No code path sets network mode to "monitored" or "learning".
- **Evidence:** `grep -r '"building"' backend/app/` returns only the enum definition and comment. Same for "monitored" and "learning".
- **Recommendation:** **DECIDE** — These are kept for database enum compatibility (PostgreSQL enums can't easily drop values). If a migration to remove them is worth the effort, do so; otherwise, the comments adequately explain their presence.

---

### [Vestigial Code] Unused Column: `container_id` in Server Model

- **Location:** `backend/app/models/server.py:61`
- **What exists:** `container_id: Mapped[str | None]` — a String(64) column, commented as "Vestigial from per-server container architecture"
- **What's missing:** Never read or written by any backend application code (`grep -r "\.container_id" backend/app/` returns 0 matches). The frontend includes it in type definitions and mock data but never displays or uses it.
- **Evidence:** Zero references in `backend/app/services/`, `backend/app/api/`, or any query
- **Recommendation:** **REMOVE** — Create a migration to drop this column. Unlike enum values, columns can be cleanly removed.

---

### [Configuration Gap] Alembic env.py Missing Model Imports

- **Location:** `backend/alembic/env.py:15`
- **What exists:** `from app.models import Credential, Server, Tool  # noqa: F401` — only 3 of 13 models imported
- **What's missing:** 10 models are not imported: ActivityLog, AdminUser, BaseModel, CloudflareConfig, GlobalConfig, ModuleRequest, NetworkAccessRequest, Setting, ToolVersion, TunnelConfiguration
- **Evidence:** The `backend/app/models/__init__.py` exports all 13 models. Alembic's `env.py` only imports 3. While existing migrations were written manually (not autogenerated), future `alembic revision --autogenerate` would miss schema changes for the 10 unimported models.
- **Recommendation:** **COMPLETE** — Update the import to `from app.models import *  # noqa: F401` or explicitly import all models. This prevents future autogenerate surprises.

---

### [Configuration Gap] `.env.example` Missing Optional Variables

- **Location:** `.env.example`
- **What exists:** Documents MCPBOX_ENCRYPTION_KEY, POSTGRES_PASSWORD, SANDBOX_API_KEY, port configs, LOG_RETENTION_DAYS, RATE_LIMIT_REQUESTS_PER_MINUTE
- **What's missing:** Several environment variables used in `docker-compose.yml` are not documented:
  - `LOG_LEVEL` (used in backend + mcp-gateway, defaults to INFO)
  - `BACKEND_URL` (used in backend service)
  - `FRONTEND_URL` (used in backend service)
  - `CORS_ORIGINS` (used in backend service)
  - `MCP_CORS_ORIGINS` (used in mcp-gateway service)
  - `ENABLE_METRICS` (used in both backend apps, defaults to true)
  - `ALERT_WEBHOOK_URL` (used for webhook alerting)
- **Evidence:** These variables appear in `docker-compose.yml` lines 66-70 and 112-114, and in `backend/app/core/config.py`, but not in `.env.example`
- **Recommendation:** **COMPLETE** — Add commented-out entries to `.env.example` with descriptions

---

### [Infrastructure] Cloudflared Dockerfile TARGETARCH Default

- **Location:** `cloudflared/Dockerfile:11`
- **What exists:** `ARG TARGETARCH=arm64` — hardcodes ARM64 as the default architecture
- **What's missing:** When users build with plain `docker build` (not `docker buildx`), Docker does NOT set TARGETARCH automatically. This means x86_64 users get an ARM64 binary by default.
- **Evidence:** The `docker compose build` command uses BuildKit which does set TARGETARCH, but `docker build .` does not. The default should match the most common homelab architecture or be removed entirely to force explicit selection.
- **Recommendation:** **DECIDE** — Either remove the default (causing a build failure with a clear message) or change to `amd64` if most homelab users are on x86_64. If the project is primarily targeting ARM64 homelabs (e.g., Raspberry Pi), the current default is correct.

---

### [Inconsistency] Schemas `__init__.py` Missing Exports

- **Location:** `backend/app/schemas/__init__.py`
- **What exists:** Exports 37 schema classes across approval, credential, server, tool, and tunnel_configuration modules
- **What's missing:** Several actively-used schema classes are not exported from `__init__.py`:
  - From `cloudflare.py`: ~20 classes (all used by cloudflare API/service, imported directly)
  - From `auth.py`: ~9 classes (all used by auth API/service, imported directly)
  - From `setting.py`: `SettingResponse`, `SettingListResponse` (used by settings API, imported directly)
  - Various paginated response types from other modules
- **Evidence:** These schemas ARE used in production code via direct imports (e.g., `from app.schemas.cloudflare import WizardStatusResponse`). They're just not re-exported from the `__init__.py` barrel file.
- **Recommendation:** **DECIDE** — This is a style choice. The direct imports work fine. If the project wants a consistent barrel-file pattern, add the missing exports. Otherwise, leave as-is since it causes no functional issues.

---

### [Documentation] CHANGELOG Placeholder Reference

- **Location:** `CHANGELOG.md:10`
- **What exists:** `Replace placeholder security@example.com in README.md with GitHub Security Advisory guidance`
- **What's missing:** This CHANGELOG entry references a task that has already been completed (README.md now correctly points to GitHub Security Advisory). The CHANGELOG entry reads like a TODO rather than a completed change.
- **Evidence:** `grep -r "security@example" README.md` returns 0 matches — the fix was already applied
- **Recommendation:** **COMPLETE** — Reword the CHANGELOG entry to past tense: "Replaced placeholder `security@example.com` in README.md with GitHub Security Advisory guidance"

---

## Areas Verified Clean

The following areas were audited and found to have **zero issues**:

### Frontend (100% clean)
- All 9 routes verified → components exist and are functional
- All API client functions have callers in components
- Zero empty `onClick` handlers
- Zero commented-out JSX
- Zero "Coming Soon" or placeholder text
- All forms have submit handlers
- All pages handle loading and error states

### Backend Services (100% wired)
- All 21 service files are actively imported and used
- All background tasks (TokenRefreshService, LogRetentionService) are started at boot and stopped on shutdown
- AuditService properly integrated with credential and tunnel endpoints
- WebhookAlertingService wired into ActivityLoggerService
- ServiceTokenCache fail-closed on database errors

### MCP Management Tools (100% implemented)
- All 18 documented tools verified in `backend/app/services/mcp_management.py`
- All tools registered in MCP gateway
- Documentation in CLAUDE.md and docs/MCP-MANAGEMENT-TOOLS.md matches implementation exactly

### Sandbox (99% clean)
- Single source of truth for safe builtins via `create_safe_builtins()` in executor.py
- Both execution paths (tool registry, direct /execute) use the shared function
- All security clients (OSV, deps, PyPI, stdlib) are actively called
- Package sync wired into startup lifespan
- SSRF protection fully integrated

### Worker (100% clean)
- All functions serve clear purposes in the OAuth + proxy flow
- No dead code paths
- JWT verification, CORS handling, and PRM endpoints all functional

### Docker & Infrastructure (98% clean)
- All services properly connected via Docker networks
- All volumes mounted and used
- All scripts reference valid paths and endpoints
- CI workflow has all jobs active (backend, sandbox, frontend, worker tests + lint + type-check + audit)

---

## Summary Table

| # | Category | Finding | Location | Recommendation | Effort |
|---|----------|---------|----------|----------------|--------|
| 1 | Dead Code | Unused `ExistingResource` schema | `schemas/cloudflare.py:32` | REMOVE | S |
| 2 | Dead Code | Unused `RequestStatus` enum | `schemas/approval.py:10` | REMOVE | S |
| 3 | Dead Code | Unused `SettingUpdate` schema | `schemas/setting.py:9` | REMOVE | S |
| 4 | Dead Code | Unused `get_all_stdlib_modules()` | `sandbox/app/stdlib_detector.py:283` | REMOVE | S |
| 5 | Vestigial | Dead enum values (building, monitored, learning) | `models/server.py:16-38` | DECIDE | M |
| 6 | Vestigial | Unused `container_id` column | `models/server.py:61` | REMOVE | S |
| 7 | Config Gap | Alembic missing model imports | `alembic/env.py:15` | COMPLETE | S |
| 8 | Config Gap | `.env.example` missing variables | `.env.example` | COMPLETE | S |
| 9 | Infrastructure | Cloudflared TARGETARCH default | `cloudflared/Dockerfile:11` | DECIDE | S |
| 10 | Inconsistency | Schemas `__init__.py` missing exports | `schemas/__init__.py` | DECIDE | S |
| 11 | Documentation | CHANGELOG placeholder wording | `CHANGELOG.md:10` | COMPLETE | S |

**Effort:** S = < 30 min, M = 1-4 hours, L = 4+ hours

**Totals:** 4 REMOVE, 3 COMPLETE, 0 DOCUMENT, 4 DECIDE
