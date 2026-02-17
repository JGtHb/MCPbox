# Consider Removing — Pre-Release Cleanup Candidates

This document catalogs code, files, and patterns identified during a comprehensive codebase inventory that are candidates for removal, consolidation, or refactoring before initial release. Nothing has been released yet, so there are no backwards-compatibility obligations.

Items are organized by category and prioritized by impact. Each item includes the rationale, affected files, and recommended action.

---

## 1. Dead / Duplicate Files

### 1a. Duplicate Architecture Doc
- **Files**: `docs/architecture.md` (190 lines) vs `docs/ARCHITECTURE.md` (644 lines)
- **Issue**: `architecture.md` is an older, shorter outline superseded by the comprehensive `ARCHITECTURE.md`
- **Action**: Delete `docs/architecture.md`

### 1b. Root-Level Planning Artifacts
- **Files**: `PLAN.md` (137 lines), `plan.md` (317 lines), `SECURITY-REVIEW.md` (329 lines)
- **Issue**: Development planning documents that served their purpose during initial development. Not part of the product documentation structure defined in `CLAUDE.md`
- **Action**: Delete all three files. Relevant content has been captured in `docs/SECURITY.md`, `docs/DECISIONS.md`, and `docs/FEATURES.md`

### 1c. Missing LICENSE File
- **Issue**: README references "AGPL-3.0 / Commercial dual license" but no `LICENSE` file exists at the repo root
- **Action**: Create `LICENSE` file with the appropriate license text before release

---

## 2. Vestigial Database Enum Values

### 2a. ServerStatus.building
- **File**: `backend/app/models/server.py:21`
- **Issue**: Defined in enum but never set anywhere in the codebase. Comment says "vestigial from per-server container architecture"
- **Kept for**: PostgreSQL enum compatibility (removing requires migration to drop and recreate enum)
- **Action**: Create Alembic migration to remove. Pre-release, there are no existing databases to migrate — just remove the value

### 2b. NetworkMode.monitored and NetworkMode.learning
- **File**: `backend/app/models/server.py:35-36`
- **Issue**: Defined in enum but never referenced in any code path. Comment says "unused, kept for database enum compatibility"
- **Kept for**: PostgreSQL enum compatibility
- **Action**: Create Alembic migration to remove. Same rationale as 2a

---

## 3. Deprecated / Backwards-Compatibility Code

### 3a. Sandbox `credentials` Parameter
- **Files**: `sandbox/app/routes.py:89,91`, `sandbox/app/registry.py:102`
- **Issue**: `register_server()` accepts a `credentials` parameter marked as "Deprecated, ignored. Kept for API compatibility"
- **Kept for**: API backward compatibility — but nothing has been released
- **Action**: Remove the parameter from `RegisterServerRequest` schema and `register_server()` function. Update any callers (backend's `sandbox_client.py`)

### 3b. Crypto Legacy Decrypt Fallback (aad=None)
- **File**: `backend/app/services/crypto.py`
- **Issue**: `decrypt()` has a fallback path for `aad=None` to handle data encrypted before AAD was enforced. Emits a deprecation warning
- **Kept for**: Backward compatibility with existing encrypted data
- **Action**: If no production databases exist yet, remove the fallback and require AAD on all decrypt calls. If dev databases exist, run a one-time re-encryption migration first

---

## 4. Overlapping / Duplicate Code

### 4a. Duplicate Config Endpoints
- **Files**: `backend/app/api/config.py` (→ `/api/config`), `backend/app/api/health.py:172` (→ `/config`)
- **Issue**: Two endpoints return similar app configuration:
  - `/api/config` returns `{app_name, app_version}` (used by frontend)
  - `/config` returns `{auth_required, version, app_name}` (no known consumer)
- **Action**: Consolidate into one endpoint. Add `auth_required` to the `/api/config` response and delete the `/config` endpoint from `health.py`. Update the admin auth middleware exclusion list (`/config` → `/api/config`). Update frontend mock handlers if needed

### 4b. Duplicated `_build_tool_definitions()` Logic
- **Files**: `backend/app/services/mcp_management.py:1890`, `backend/app/api/sandbox.py:355`
- **Issue**: Both files contain a `_build_tool_definitions()` function that converts Tool models to sandbox tool definition dicts. The implementations differ (mcp_management.py filters by `enabled` and `approval_status`; sandbox.py does not)
- **Action**: Extract a shared utility function in `backend/app/services/tool.py` with an optional filter parameter. Import from both locations

### 4c. Enum Redefinition (Models vs Schemas)
- **Files**: `backend/app/models/external_mcp_source.py`, `backend/app/schemas/external_mcp_source.py`
- **Issue**: `ExternalMCPAuthType`, `ExternalMCPTransportType`, `ExternalMCPSourceStatus` are defined as StrEnum in both models and schemas. The model versions are SQLAlchemy-compatible and the schema versions are for Pydantic, but they duplicate the same values
- **Action**: Define enums once (in models or a shared `enums.py`) and import in both places

---

## 5. Code Quality Issues

### 5a. Singleton Bypass in Approval Service
- **File**: `backend/app/services/approval.py:374`
- **Issue**: Uses `SandboxClient()` (direct constructor) instead of `SandboxClient.get_instance()`, bypassing the singleton pattern with its retry/circuit breaker configuration
- **Action**: Change to `SandboxClient.get_instance()`

### 5b. Fragile `__table__.columns` Pattern
- **File**: `backend/app/api/external_mcp_sources.py:116`
- **Issue**: `_source_to_response()` uses `{c.name: getattr(source, c.name) for c in source.__table__.columns}` to convert a model to a dict. This is fragile — adding/removing columns silently changes the response shape
- **Action**: Use explicit field mapping or a Pydantic `model_validate()` / `.from_orm()` pattern. Note: `base.py:47` also uses this pattern but is a generic `to_dict()` utility method on the base model, which is acceptable

### 5c. Dashboard N+1 Query (Time Series)
- **File**: `backend/app/api/dashboard.py:221-241`
- **Issue**: Generates time-series data by executing TWO database queries per time bucket (one for total count, one for error count). For a 24-hour hourly view, this is 48 queries. For a 7-day view, it's 336 queries
- **Action**: Replace with a single `GROUP BY date_trunc('hour', created_at)` query that returns all buckets at once, then fill gaps in Python

### 5d. Incomplete Frontend Barrel Export
- **File**: `frontend/src/api/index.ts`
- **Issue**: Only re-exports from `client.ts`, `health.ts`, `servers.ts`, and `tools.ts`. Other API modules (`auth.ts`, `approvals.ts`, `cloudflare.ts`, etc.) require direct imports
- **Action**: Either complete the barrel export to include all API modules, or remove it entirely if direct imports are the preferred pattern. Choose one pattern consistently

---

## 6. Hardcoded Values

### 6a. Sandbox Resource Limits
- **File**: `sandbox/app/executor.py`
- **Values**:
  - `MAX_OUTPUT_SIZE = 1024 * 1024` (1MB, line 22)
  - `MAX_MEMORY_BYTES = 256 * 1024 * 1024` (256MB, line 25)
  - `REGEX_TIMEOUT = 5.0` (seconds, line 989)
- **Action**: Move to environment variables with these as defaults. Allows operators to tune for their deployment without code changes

### 6b. Cloudflare Worker Configuration
- **File**: `backend/app/services/cloudflare.py`
- **Values**:
  - `compatibility_date = "2025-03-01"` (lines 683, 755, 1261)
  - `compatibility_flags = ["nodejs_compat"]` (lines 756, 1262)
  - `http_port: 8002` (line 570)
- **Action**: Extract `compatibility_date` and `compatibility_flags` to config settings. The port should reference the same config as `MCP_GATEWAY_URL`

---

## 7. Half-Implemented Features

### 7a. Settings Model (Under-Utilized)
- **Files**: `backend/app/models/setting.py`, `backend/app/services/setting.py`, `backend/app/api/settings.py`
- **Issue**: Full model with encrypted value support exists. Only basic listing endpoint implemented. No dedicated UI for creating/managing general settings. Designed for feature toggles and preferences but the module settings endpoint has taken over the primary use case
- **Decision needed**: Either expand to support planned use cases (feature toggles, LLM preferences, etc.) or simplify to only what's actually used (module whitelist management). The current state is confusing — a general-purpose settings model that's only used for one thing
- **Action**: Decide scope before release. If keeping, add CRUD endpoints and UI. If narrowing, rename to make purpose clear

### 7b. Helper Code (Shared Server Code)
- **Files**: `backend/app/models/server.py:79-83` (field), `sandbox/app/executor.py` (loading)
- **Issue**: `helper_code` field on Server model allows sharing Python utility functions across all tools in a server. The database field exists and executor loads it, but there's no API endpoint for updating helper code after server creation and no UI support
- **Decision needed**: Is this a planned feature for v1 or future work?
- **Action**: If shipping in v1, add API endpoint and UI support. If deferring, add a code comment noting it's intentionally hidden and remove from any user-facing documentation

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
| 1a | Duplicate architecture doc | File cleanup | Trivial | None |
| 1b | Root planning artifacts | File cleanup | Trivial | None |
| 1c | Missing LICENSE | File creation | Trivial | Release blocker |
| 2a | ServerStatus.building | DB migration | Low | Low |
| 2b | NetworkMode.monitored/learning | DB migration | Low | Low |
| 3a | Sandbox credentials param | API change | Low | Low |
| 3b | Crypto aad=None fallback | Code change | Low | Medium (data) |
| 4a | Duplicate config endpoints | API change | Low | Low |
| 4b | Duplicate _build_tool_defs | Refactor | Medium | Low |
| 4c | Duplicate enum definitions | Refactor | Medium | Low |
| 5a | Singleton bypass | Bug fix | Trivial | Low |
| 5b | __table__.columns pattern | Refactor | Low | Low |
| 5c | Dashboard N+1 query | Performance | Medium | Low |
| 5d | Incomplete barrel export | Consistency | Low | None |
| 6a | Sandbox hardcoded limits | Config | Low | Low |
| 6b | Cloudflare hardcoded values | Config | Low | Low |
| 7a | Settings model scope | Feature decision | High | Medium |
| 7b | Helper code feature | Feature decision | Medium | Low |
| 8a | In-memory token blacklist | Documentation | Trivial | None |
| 8b | Session dict cleanup | Feature | Low | Low |
| 9a | Duplicate middleware init | Refactor | Medium | Low |
