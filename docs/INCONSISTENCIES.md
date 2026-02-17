# Codebase Inconsistencies & Technical Debt

## Patterns

### HTTPException Status Code Style
Different API endpoints use different styles for HTTP status codes:

```python
# Style 1: Enum (used in activity.py, approvals.py)
raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="...")

# Style 2: Integer literal (used in server_secrets.py, servers.py)
raise HTTPException(status_code=404, detail="...")
```

**Affected files**: All files in `backend/app/api/`
**Recommendation**: Standardize on `status.HTTP_*` enums for readability and IDE support

### Type Annotation Style
Mix of old and new Python type annotation syntax across service files:

```python
# Old style (some services)
from typing import Optional
def get_server(self, server_id: int) -> Optional[Server]:

# New style (other services)
def get_server(self, server_id: int) -> Server | None:
```

**Affected files**: `backend/app/services/` — mixed across 17+ service files
**Recommendation**: Standardize on `Type | None` (Python 3.10+) since project requires Python 3.11+

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

### Default Server Status "imported"
- **File**: `backend/app/models/server.py:58`
- **Issue**: New servers default to `status="imported"` which is a vestigial status from an earlier architecture. Servers should arguably default to `"stopped"` or `"ready"`
- **Recommendation**: Verify no code depends on `"imported"` status, then update default

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

### Route Prefix Double-Nesting
- **File**: `backend/app/api/settings.py`
- **Issue**: Router is included at `/api/settings` prefix, but individual routes also use `/settings` prefix, resulting in `/api/settings/settings` for the main endpoint
- **Recommendation**: Remove inner prefix to get `/api/settings`

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
