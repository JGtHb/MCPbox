# Codebase Inconsistencies & Technical Debt

## Patterns

### ~~HTTPException Status Code Style~~ — **RESOLVED**
~~Different API endpoints use different styles for HTTP status codes.~~

Status codes in `server_secrets.py` and `mcp_gateway.py` have been standardized to use `status.HTTP_*` enums. Remaining files (`servers.py`, etc.) still use integer literals — lower priority.

**Affected files**: `backend/app/api/server_secrets.py`, `backend/app/api/mcp_gateway.py` (fixed); others remain

### ~~Type Annotation Style~~ — **PARTIALLY RESOLVED**
~~Mix of old and new Python type annotation syntax across service files.~~

`Optional[X]` replaced with `X | None` (using `from __future__ import annotations`) in: `log_retention.py`, `tunnel.py`, `activity_logger.py`, `sandbox_client.py`. Remaining service files still use `Optional` in some places — lower priority.

**Affected files**: 4 files fixed; others remain

### Error Detail Message Format
Inconsistent detail message specificity:

```python
# Specific (some endpoints)
detail=f"Server {server_id} not found"

# Generic (other endpoints)
detail="Not found"
```

**Affected files**: Various API endpoints
**Recommendation**: Use specific messages for debuggability

---

## Dead Code

### Vestigial Server Model Enum Values
- **File**: `backend/app/models/server.py:17-38`
- **Issue**: `ServerStatus.building`, `NetworkMode.monitored`, `NetworkMode.learning` are defined but never set in any code path
- **Reason**: Kept for PostgreSQL enum compatibility (removing requires migration to drop and recreate enum)
- **Recommendation**: Add `# Deprecated` comments. Consider migration to remove if unused for extended period

### ~~Default Server Status "imported"~~ — **VERIFIED CORRECT**
- **File**: `backend/app/models/server.py:58`
- **Issue**: ~~New servers default to `status="imported"` which is a vestigial status from an earlier architecture.~~
- **Resolution**: Inventory confirmed `"imported"` is actively used as the initial state for newly created servers in `backend/app/services/server.py` and expected by multiple test files. This is intentional, not vestigial.

### Minimal Frontend Types File
- **File**: `frontend/src/api/types.ts`
- **Issue**: Contains only `HealthResponse` interface. All other types are defined inline in component files or not typed at all
- **Recommendation**: Consolidate shared API types into this file or remove it if not used

---

## Half-Implemented Features

### Settings Model
- **File**: `backend/app/models/setting.py`, `backend/app/services/setting.py`, `backend/app/api/settings.py`
- **Issue**: Full model with encrypted value support exists. Only basic listing endpoint implemented. No dedicated UI for creating/managing settings. Appears designed for feature toggles, preferences, and configuration but not fully wired up.
- **Status**: Skeleton exists, minimal usage
- **Recommendation**: Either expand to support planned use cases (feature toggles, LLM preferences) or document scope clearly

### Helper Code (Shared Server Code)
- **File**: `backend/app/models/server.py:79-83` (field), `sandbox/app/executor.py` (loading)
- **Issue**: `helper_code` field on Server model allows sharing Python utility functions across all tools in a server. The database field exists and executor loads it, but:
  - No dedicated API endpoint for updating helper code
  - No mention in the admin UI
  - No dedicated tests
- **Status**: Partially implemented — works at the database and executor level but not exposed through API/UI
- **Recommendation**: Add API endpoint and UI support, or document as advanced/internal feature

---

## Dependency Issues

### Consistent Version Pinning (Positive Finding)
All dependencies are pinned to exact versions across all components:
- `backend/requirements.txt`: e.g., `fastapi==0.128.8`
- `sandbox/requirements.txt`: e.g., `httpx==0.28.1`
- `frontend/package.json`: exact versions
- `worker/package.json`: exact versions

### Shared Dependencies Across Components
`httpx==0.28.1` appears in 4 requirement files (backend, backend-dev, sandbox, sandbox-dev). This is expected (separate Docker containers) but version drift between components could cause issues if not updated together.

**Recommendation**: When updating shared dependencies, update all components simultaneously

### Development Dependencies
- `testcontainers[postgres]==4.14.1` in `backend/requirements-dev.txt` — marked as optional with installation comments. Pragmatic approach for CI vs local testing.

---

## Naming Inconsistencies

### ~~Route Prefix Double-Nesting~~ — **RESOLVED**
- **File**: `backend/app/api/settings.py`
- **Issue**: ~~Router is included at `/api/settings` prefix, but individual routes also use `/settings` prefix, resulting in `/api/settings/settings`~~
- **Fix**: Changed `@router.get("/settings", ...)` to `@router.get("", ...)` — endpoint is now correctly at `/api/settings`

### Response Schema Naming Convention
Mix of naming patterns for response schemas:
- `*Response` — Standard single-item response
- `*ListResponse` — List without pagination
- `*ListPaginatedResponse` — List with pagination metadata

Not all list endpoints use the same response wrapper style.
**Recommendation**: Document the convention: use `*Response` for single items, `PaginatedResponse[T]` for paginated lists

### Enum Case Convention
- **File**: `backend/app/schemas/tool.py`
- **Issue**: `ApprovalStatus` enum uses UPPERCASE names (`DRAFT`, `PENDING_REVIEW`) but database stores lowercase values (`draft`, `pending_review`). Pydantic handles the mapping but it's a potential confusion point.
- **Recommendation**: Add explicit `value` attributes or document the mapping

---

## Additional Technical Debt

### Duplicate Middleware Initialization
- **Files**: `backend/app/main.py`, `backend/app/mcp_only.py`
- **Issue**: Both entry points initialize similar middleware stacks (CORS, SecurityHeaders, RateLimit) and lifespan handlers (activity logger, service token cache, log retention, server recovery). Changes to middleware must be applied in both files.
- **Recommendation**: Extract shared initialization into a common module

### Activity Logger Initialization Pattern
- **Files**: `backend/app/main.py`, `backend/app/mcp_only.py`
- **Issue**: Activity logger startup/shutdown replicated in both entry points
- **Recommendation**: Factor into shared lifespan utility

### Global Mutable State in Sandbox
- **File**: `sandbox/app/executor.py`
- **Issue**: `_resource_limit_status` global dict tracks resource limit availability. Modified during first execution, read thereafter. Not thread-safe for concurrent requests.
- **Recommendation**: Initialize during startup, make immutable after

### MCP Gateway Session Dict Without Cleanup
- **File**: `backend/app/api/mcp_gateway.py:71-72`
- **Issue**: `_active_sessions` global dict stores MCP session state. While sessions have TTL, there's no periodic cleanup of expired sessions. Long-running gateway instances could accumulate stale sessions.
- **Recommendation**: Add periodic cleanup task or use TTL cache library

### Console Logging in Worker
- **Files**: `worker/src/index.ts`, `worker/src/access-handler.ts`
- **Issue**: Multiple `console.log()` and `console.error()` statements. Should use structured logging for production.
- **Recommendation**: Replace with structured logging or remove debug logging

### Silent Error Handling in MCP Client
- **File**: `sandbox/app/mcp_client.py`
- **Issue**: Multiple `pass  # Best-effort cleanup` and `pass  # Notification is best-effort` patterns. Silent failures could mask real issues during debugging.
- **Recommendation**: Add at minimum `logging.debug()` calls for these error paths

### Singleton Bypass in Approval Service
- **File**: `backend/app/services/approval.py:374`
- **Issue**: Uses `SandboxClient()` (direct constructor) instead of `SandboxClient.get_instance()`, bypassing the singleton pattern with its retry/circuit breaker configuration. All other call sites use the singleton correctly.
- **Recommendation**: Change to `SandboxClient.get_instance()`

### Duplicate Config Endpoints
- **Files**: `backend/app/api/config.py` (→ `/api/config`), `backend/app/api/health.py:172` (→ `/config`)
- **Issue**: Two endpoints return overlapping app configuration. `/api/config` returns `{app_name, app_version}` (used by frontend). `/config` returns `{auth_required, version, app_name}` (no known consumer). The admin auth middleware explicitly excludes `/config` from auth.
- **Recommendation**: Consolidate into `/api/config` with all fields, remove `/config` from health.py

### Duplicate _build_tool_definitions() Logic
- **Files**: `backend/app/services/mcp_management.py:1890`, `backend/app/api/sandbox.py:355`
- **Issue**: Both contain a function that converts Tool models to sandbox tool definition dicts. The implementations differ in filtering logic (mcp_management.py filters by `enabled` and `approval_status`; sandbox.py does not).
- **Recommendation**: Extract a shared utility with optional filter parameter

### Duplicate Enum Definitions (Models vs Schemas)
- **Files**: `backend/app/models/external_mcp_source.py`, `backend/app/schemas/external_mcp_source.py`
- **Issue**: `ExternalMCPAuthType`, `ExternalMCPTransportType`, `ExternalMCPSourceStatus` are defined as StrEnum in both files with identical values. Model versions are for SQLAlchemy, schema versions for Pydantic.
- **Recommendation**: Define once in a shared location, import in both

### Dashboard N+1 Query
- **File**: `backend/app/api/dashboard.py:221-241`
- **Issue**: Time-series generation executes 2 DB queries per time bucket (total + error count). For 24h hourly view = 48 queries. For 7d view = 336 queries.
- **Recommendation**: Replace with single `GROUP BY date_trunc()` query

### Hardcoded Sandbox Resource Limits
- **File**: `sandbox/app/executor.py:22,25,989`
- **Issue**: `MAX_OUTPUT_SIZE` (1MB), `MAX_MEMORY_BYTES` (256MB), `REGEX_TIMEOUT` (5s) are compile-time constants. Operators cannot tune without code changes.
- **Recommendation**: Move to environment variables with current values as defaults

### Hardcoded Cloudflare Worker Configuration
- **File**: `backend/app/services/cloudflare.py:683,755-756,1261-1262`
- **Issue**: `compatibility_date = "2025-03-01"` and `compatibility_flags = ["nodejs_compat"]` appear as string literals in generated wrangler.toml content. Port `8002` for VPC service also hardcoded.
- **Recommendation**: Extract to config settings

### Fragile __table__.columns Pattern
- **File**: `backend/app/api/external_mcp_sources.py:116`
- **Issue**: `_source_to_response()` uses `{c.name: getattr(source, c.name) for c in source.__table__.columns}` — adding/removing model columns silently changes the response shape.
- **Recommendation**: Use explicit field mapping or Pydantic `model_validate()`

### Deprecated Sandbox credentials Parameter
- **Files**: `sandbox/app/routes.py:89,91`, `sandbox/app/registry.py:102`
- **Issue**: `register_server()` accepts a `credentials` parameter marked "Deprecated, ignored. Kept for API compatibility" — but nothing has been released yet.
- **Recommendation**: Remove the parameter before initial release
