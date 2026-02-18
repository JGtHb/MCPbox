# Consider Removing — Pre-Release Cleanup Candidates

This document catalogs code, files, and patterns identified during a comprehensive codebase inventory that are candidates for removal, consolidation, or refactoring before initial release. Nothing has been released yet, so there are no backwards-compatibility obligations.

Items are organized by category and prioritized by impact. Each item includes the rationale, affected files, and recommended action.

---

## 1. Dead / Duplicate Files

### ~~1a. Duplicate Architecture Doc~~ — **REMOVED**
- **Files**: `docs/architecture.md` (190 lines) vs `docs/ARCHITECTURE.md` (644 lines)
- **Issue**: `architecture.md` is an older, shorter outline superseded by the comprehensive `ARCHITECTURE.md`
- **Action**: Delete `docs/architecture.md`

### ~~1b. Root-Level Planning Artifacts~~ — **REMOVED**
- **Files**: `PLAN.md` (137 lines), `plan.md` (317 lines), `SECURITY-REVIEW.md` (329 lines)
- **Issue**: Development planning documents that served their purpose during initial development. Not part of the product documentation structure defined in `CLAUDE.md`
- **Action**: Delete all three files. Relevant content has been captured in `docs/SECURITY.md`, `docs/DECISIONS.md`, and `docs/FEATURES.md`

### ~~1c. Missing LICENSE File~~ — **FIXED**
- **Issue**: README references "AGPL-3.0 / Commercial dual license" but no `LICENSE` file exists at the repo root
- **Resolution**: Created `LICENSE` with PolyForm Noncommercial 1.0.0. Updated README to reference the new license. Personal/non-commercial use is free; commercial use requires a paid license

---

## 2. Vestigial Database Enum Values

### ~~2a. ServerStatus.building~~ — **REMOVED**
- **File**: `backend/app/models/server.py:21`
- **Issue**: Defined in enum but never set anywhere in the codebase. Comment says "vestigial from per-server container architecture"
- **Resolution**: Removed from model, created Alembic migration 0034, updated frontend types/constants/tests

### ~~2b. NetworkMode.monitored and NetworkMode.learning~~ — **REMOVED**
- **File**: `backend/app/models/server.py:35-36`
- **Issue**: Defined in enum but never referenced in any code path. Comment says "unused, kept for database enum compatibility"
- **Resolution**: Removed from model, included in Alembic migration 0034, updated frontend types/tests

---

## 3. Deprecated / Backwards-Compatibility Code

### ~~3a. Sandbox `credentials` Parameter~~ — **REMOVED**
- **Files**: `sandbox/app/routes.py`, `sandbox/app/registry.py`, `backend/app/services/sandbox_client.py`
- **Resolution**: Removed deprecated `credentials` parameter from schema, function, client, and all callers. Removed test fixture.

### ~~3b. Crypto Legacy Decrypt Fallback (aad=None)~~ — **REMOVED**
- **File**: `backend/app/services/crypto.py`, `backend/app/core/config.py`
- **Resolution**: Made `aad` a required parameter on encrypt/decrypt. Removed aad=None fallback, old-key rotation fallback, and `mcpbox_encryption_key_old` setting. Updated tests and SECURITY.md.

---

## 4. Overlapping / Duplicate Code

### ~~4a. Duplicate Config Endpoints~~ — **FIXED**
- **Resolution**: Added `auth_required` to `/api/config`, removed duplicate `/config` from health.py, updated middleware exclusion path to `/api/config`

### ~~4b. Duplicated `_build_tool_definitions()` Logic~~ — **FIXED**
- **Resolution**: Extracted shared `build_tool_definitions()` into `backend/app/services/tool_utils.py` with optional `filter_enabled_approved` parameter. Both sandbox.py and mcp_management.py now delegate to it

### ~~4c. Enum Redefinition (Models vs Schemas)~~ — **FIXED**
- **Resolution**: StrEnum definitions in `schemas/external_mcp_source.py` are now the single source of truth. Model file derives SQLAlchemy Enums from the StrEnum values

---

## 5. Code Quality Issues

### ~~5a. Singleton Bypass in Approval Service~~ — **FIXED**
- **Resolution**: Changed `SandboxClient()` to `SandboxClient.get_instance()`

### ~~5b. Fragile `__table__.columns` Pattern~~ — **FIXED**
- **Resolution**: Replaced with Pydantic `model_validate()` pattern using `ExternalMCPSourceResponse`

### ~~5c. Dashboard N+1 Query (Time Series)~~ — **FIXED**
- **Resolution**: Replaced per-bucket queries with single `GROUP BY date_trunc()` query using `.filter()` for error counting. Gaps filled in Python

### ~~5d. Incomplete Frontend Barrel Export~~ — **REMOVED**
- **Resolution**: Removed `frontend/src/api/index.ts`. Updated the one consumer (Dashboard.tsx) to import directly from `api/health`

---

## 6. Hardcoded Values

### ~~6a. Sandbox Resource Limits~~ — **FIXED**
- **File**: `sandbox/app/executor.py`
- **Values**:
  - `MAX_OUTPUT_SIZE = 1024 * 1024` (1MB, line 22)
  - `MAX_MEMORY_BYTES = 256 * 1024 * 1024` (256MB, line 25)
  - `REGEX_TIMEOUT = 5.0` (seconds, line 989)
- **Resolution**: Extracted to environment variables (`SANDBOX_MAX_OUTPUT_SIZE`, `SANDBOX_MAX_MEMORY_BYTES`, `SANDBOX_REGEX_TIMEOUT`) with original values as defaults

### ~~6b. Cloudflare Worker Configuration~~ — **FIXED**
- **File**: `backend/app/services/cloudflare.py`
- **Values**:
  - `compatibility_date = "2025-03-01"` (lines 683, 755, 1261)
  - `compatibility_flags = ["nodejs_compat"]` (lines 756, 1262)
  - `http_port: 8002` (line 570)
- **Resolution**: Extracted to config settings (`cf_worker_compatibility_date`, `cf_worker_compatibility_flags`, `mcp_gateway_port`) in `backend/app/core/config.py`. All 5 hardcoded references in `cloudflare.py` now use `settings.*`

---

## 7. Half-Implemented Features

### ~~7a. Settings Model (Under-Utilized)~~ — **EXPANDED**
- **Files**: `backend/app/api/settings.py`, `frontend/src/api/settings.ts`, `frontend/src/pages/Settings.tsx`
- **Resolution**: Expanded into a Security Policy feature with 6 configurable settings:
  1. `remote_tool_editing` (disabled/enabled) — controls remote session tool mutation access
  2. `tool_approval_mode` (require_approval/auto_approve) — tool approval workflow
  3. `network_access_policy` (require_approval/allow_all_public) — network allowlist enforcement
  4. `module_approval_mode` (require_approval/auto_approve) — module request workflow
  5. `redact_secrets_in_output` (enabled/disabled) — secret scrubbing in tool output
  6. `log_retention_days` (1-3650) — log retention period
- Uses existing Setting model key-value store. Backend: GET/PATCH `/api/settings/security-policy`. Frontend: Security Policy card with dropdown controls and warnings for less-secure options

### ~~7b. Helper Code (Shared Server Code)~~ — **REMOVED**
- **Files**: `backend/app/models/server.py` (field), `sandbox/app/executor.py` (loading), `sandbox/app/registry.py`, `sandbox/app/routes.py`, `backend/app/services/sandbox_client.py`, `backend/app/api/sandbox.py`, `backend/app/api/tools.py`, `backend/app/api/servers.py`, `backend/app/api/export_import.py`, `backend/app/services/mcp_management.py`, `backend/app/services/server_recovery.py`, frontend types/UI
- **Resolution**: Feature was never exposed via API or UI after server creation. Removed database column (migration 0035), model field, executor loading, all API/sandbox/frontend references. Updated FEATURES.md, INCONSISTENCIES.md, API-CONTRACTS.md

---

## 8. In-Memory State (Operational Concern)

### 8a. JWT Token Blacklist
- **File**: `backend/app/api/auth.py`
- **Issue**: Logout invalidates tokens via an in-memory JTI blacklist. Lost on process restart. Short access token TTL (15 min) limits the blast radius
- **Action**: Acceptable for single-process deployment. Document the limitation. If horizontal scaling is ever needed, move to Redis or database-backed blacklist

### 8b. MCP Gateway Session Dict
- **File**: `backend/app/api/mcp_gateway.py:71-72`
- **Issue**: `_active_sessions` stores MCP session state in memory. No periodic cleanup of expired sessions. Gateway must run `--workers 1`
- **Action**: Add periodic cleanup task for expired sessions. Already documented in `INCONSISTENCIES.md`. Not blocking for release but should be addressed

---

## 9. Duplicate Middleware Initialization

### 9a. Two Entry Points With Duplicated Setup
- **Files**: `backend/app/main.py`, `backend/app/mcp_only.py`
- **Issue**: Both entry points initialize similar middleware stacks (CORS, SecurityHeaders, RateLimit) and lifespan handlers (activity logger, service token cache, log retention, server recovery). Changes must be applied in both files
- **Action**: Extract shared initialization into a common module (e.g., `backend/app/core/shared_lifespan.py`). Already documented in `INCONSISTENCIES.md`

---

## Review Checklist

When reviewing this document, for each item decide:
- **Remove**: Delete the code/file now
- **Fix**: Make the code change described
- **Defer**: Keep as-is, move to backlog
- **Keep**: The current state is intentional

| # | Item | Category | Effort | Risk |
|---|------|----------|--------|------|
| ~~1a~~ | ~~Duplicate architecture doc~~ | ~~File cleanup~~ | ~~Trivial~~ | **REMOVED** |
| ~~1b~~ | ~~Root planning artifacts~~ | ~~File cleanup~~ | ~~Trivial~~ | **REMOVED** |
| ~~1c~~ | ~~Missing LICENSE~~ | ~~File creation~~ | ~~Trivial~~ | **FIXED** |
| ~~2a~~ | ~~ServerStatus.building~~ | ~~DB migration~~ | ~~Low~~ | **REMOVED** |
| ~~2b~~ | ~~NetworkMode.monitored/learning~~ | ~~DB migration~~ | ~~Low~~ | **REMOVED** |
| ~~3a~~ | ~~Sandbox credentials param~~ | ~~API change~~ | ~~Low~~ | **REMOVED** |
| ~~3b~~ | ~~Crypto aad=None fallback~~ | ~~Code change~~ | ~~Low~~ | **REMOVED** |
| ~~4a~~ | ~~Duplicate config endpoints~~ | ~~API change~~ | ~~Low~~ | **FIXED** |
| ~~4b~~ | ~~Duplicate _build_tool_defs~~ | ~~Refactor~~ | ~~Medium~~ | **FIXED** |
| ~~4c~~ | ~~Duplicate enum definitions~~ | ~~Refactor~~ | ~~Medium~~ | **FIXED** |
| ~~5a~~ | ~~Singleton bypass~~ | ~~Bug fix~~ | ~~Trivial~~ | **FIXED** |
| ~~5b~~ | ~~__table__.columns pattern~~ | ~~Refactor~~ | ~~Low~~ | **FIXED** |
| ~~5c~~ | ~~Dashboard N+1 query~~ | ~~Performance~~ | ~~Medium~~ | **FIXED** |
| ~~5d~~ | ~~Incomplete barrel export~~ | ~~Consistency~~ | ~~Low~~ | **REMOVED** |
| ~~6a~~ | ~~Sandbox hardcoded limits~~ | ~~Config~~ | ~~Low~~ | **FIXED** |
| ~~6b~~ | ~~Cloudflare hardcoded values~~ | ~~Config~~ | ~~Low~~ | **FIXED** |
| ~~7a~~ | ~~Settings model scope~~ | ~~Feature decision~~ | ~~High~~ | **EXPANDED** |
| ~~7b~~ | ~~Helper code feature~~ | ~~Feature decision~~ | ~~Medium~~ | **REMOVED** |
| 8a | In-memory token blacklist | Documentation | Trivial | None |
| 8b | Session dict cleanup | Feature | Low | Low |
| 9a | Duplicate middleware init | Refactor | Medium | Low |
