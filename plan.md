# Implementation Plan: Actionable Findings

Excludes SEC-004 (hardcoded forbidden modules) per design decision — admin retains full control.

---

## Phase 1: Critical Security Fixes (SEC-001, SEC-002)

### 1.1 SEC-001 — Reset approval on code update
**File:** `backend/app/services/tool.py` (lines 119-127)

After the `python_code` schema regeneration block (line 123) and before the "Apply updates" loop (line 126), add:

```python
# SECURITY: Reset approval when code changes (prevents TOCTOU bypass)
if "python_code" in update_data and update_data["python_code"]:
    if tool.python_code != update_data["python_code"]:
        update_data["approval_status"] = "pending_review"
```

This only resets if code *actually* changed (not just re-submitted identical code).

### 1.2 SEC-002 — Reset approval on rollback
**File:** `backend/app/services/tool.py` (lines 264-270)

After restoring fields from `target_version` (line 270), add:

```python
# SECURITY: Always reset approval on rollback — rolled-back code needs re-review
tool.approval_status = "pending_review"
```

### 1.3 Tests for SEC-001 and SEC-002
**File:** `backend/tests/test_tool_service.py` (add new tests)

- `test_update_python_code_resets_approval` — create approved tool, update code, verify approval_status = "pending_review"
- `test_update_non_code_field_preserves_approval` — update name/description on approved tool, verify approval stays "approved"
- `test_rollback_resets_approval` — create approved tool with versions, rollback, verify approval_status = "pending_review"

---

## Phase 2: High-Priority Security (SEC-007, SEC-013, SEC-015)

### 2.1 SEC-007 — Disable redirects in MCP passthrough client
**File:** `sandbox/app/mcp_client.py` (lines 104-107, 156-160)

In `_send_request()` POST call (line 156), add `allow_redirects=False`:

```python
response = await self._session.post(
    self.url,
    json=request,
    headers=self._request_headers(),
    allow_redirects=False,
)
```

Also add to the DELETE call in `__aexit__` (line 127):

```python
await self._session.delete(
    self.url,
    headers=self._request_headers(),
    allow_redirects=False,
)
```

### 2.2 SEC-013 — Remove service token from CORS allowed headers
**File:** `backend/app/mcp_only.py` (line 148)

Change:
```python
allow_headers=["Authorization", "Content-Type", "Accept", "X-MCPbox-Service-Token"],
```
To:
```python
allow_headers=["Authorization", "Content-Type", "Accept"],
```

The `X-MCPbox-Service-Token` is a server-to-server header (Worker → Gateway). It never comes from browser CORS requests. The gateway's service token middleware reads it from any request regardless of CORS.

### 2.3 SEC-015 — Remove allowed_modules override from /execute
**File:** `sandbox/app/routes.py` (lines 625-634, 717-720)

Remove `allowed_modules` field from `ExecuteCodeRequest` (line 632-634).

Change the execution logic (lines 717-720) from:
```python
allowed_modules_set = (
    set(body.allowed_modules) if body.allowed_modules else DEFAULT_ALLOWED_MODULES
)
```
To:
```python
allowed_modules_set = DEFAULT_ALLOWED_MODULES
```

### 2.4 Tests for Phase 2
- `sandbox/tests/test_mcp_client.py` — add test that redirect responses are NOT followed (mock a 302 response, verify no redirect)
- `sandbox/tests/test_execute.py` — add test that `/execute` ignores any `allowed_modules` in request body (if still accepted, it should be ignored)

---

## Phase 3: Medium Security (SEC-005, SEC-009, SEC-010, SEC-011, SEC-012)

### 3.1 SEC-005 — Enforce AAD on new encryptions, add migration
**File:** `backend/app/services/crypto.py`

The encrypt/decrypt already support AAD and have backwards compatibility. The fix is to ensure all callers pass AAD:

1. **Audit callers** — grep for `encrypt(` and `encrypt_to_base64(` to find all call sites
2. **Add AAD to each call site** — e.g., `encrypt_to_base64(value, aad=f"server_secret:{server_id}:{key_name}")` for server secrets, `encrypt_to_base64(value, aad="service_token")` for service tokens
3. **Add deprecation warning** in `encrypt()` when `aad is None`:
   ```python
   if aad is None:
       logger.warning("encrypt() called without AAD — context binding disabled")
   ```
4. **Keep backwards-compat decrypt fallback** (already exists at lines 125-134) — this allows reading legacy data. Log when it triggers so operators know to re-encrypt.

### 3.2 SEC-009 — Add JWT token blacklist for active logout
**File:** `backend/app/api/auth.py` (lines 208-218)

1. Create an in-memory token blacklist with TTL matching JWT expiry (15 min):
   - Add `_token_blacklist: dict[str, float] = {}` module-level
   - On logout, extract the token's `jti` (JWT ID) and add to blacklist with expiry timestamp
   - In `get_current_user` dependency, check blacklist before accepting token
   - Cleanup expired entries opportunistically (same pattern as `_active_sessions` in mcp_gateway.py)

2. **Prerequisite:** Ensure JWTs include a `jti` claim. Check `backend/app/services/auth.py` token creation — add `jti=str(uuid.uuid4())` if missing.

### 3.3 SEC-010 — Use timing-safe comparison in Worker CSRF
**File:** `worker/src/index.ts`

Research found this is **already correctly implemented** using `crypto.subtle.timingSafeEqual()` in `worker/src/access-handler.ts:113-122`. **No change needed.** Remove from tracking.

### 3.4 SEC-011 — Warn when JWT secret derived from encryption key
**File:** `backend/app/core/config.py` (lines 190-198)

In `check_security_configuration()` (line 208+), add a warning when `jwt_secret_key` is not explicitly set:

```python
if not self.jwt_secret_key:
    warnings.append(
        "JWT_SECRET_KEY not set — derived from MCPBOX_ENCRYPTION_KEY. "
        "Set a separate JWT_SECRET_KEY for production deployments."
    )
```

### 3.5 SEC-012 — Add format validator for old encryption key
**File:** `backend/app/core/config.py` (after line 76)

Add a field validator for `mcpbox_encryption_key_old`:

```python
@field_validator("mcpbox_encryption_key_old")
@classmethod
def validate_old_encryption_key(cls, v: str | None) -> str | None:
    if v is None:
        return v
    import re
    if len(v) != 64 or not re.fullmatch(r"[0-9a-fA-F]+", v):
        raise ValueError(
            "MCPBOX_ENCRYPTION_KEY_OLD must be exactly 64 hex characters (32 bytes)"
        )
    return v
```

### 3.6 Tests for Phase 3
- `backend/tests/test_crypto.py` — add tests for AAD enforcement: encrypt with AAD, attempt decrypt without AAD (should fall through to compat), verify warning logged
- `backend/tests/test_auth.py` — add test for JWT blacklist: login, get token, logout, attempt API call with same token (should fail 401)
- `backend/tests/test_config.py` — add test for old encryption key validator: valid hex passes, non-hex fails, wrong length fails, None passes

---

## Phase 4: Test Coverage Gaps

### 4.1 Server Secrets API tests
**New file:** `backend/tests/test_server_secrets.py`

Test all 4 endpoints:
- `test_create_secret` — POST, verify 201, verify value not returned in response
- `test_list_secrets` — GET list, verify pagination, verify values masked
- `test_update_secret` — PUT, verify 200
- `test_delete_secret` — DELETE, verify 204
- `test_create_secret_nonexistent_server` — 404
- `test_create_duplicate_key` — conflict error
- `test_delete_nonexistent_secret` — 404

### 4.2 Execution Logs API tests
**New file:** `backend/tests/test_execution_logs.py`

Test all 3 endpoints:
- `test_list_tool_logs` — GET /tools/{id}/logs with pagination
- `test_list_server_logs` — GET /servers/{id}/execution-logs
- `test_get_single_log` — GET /logs/{id}
- `test_get_nonexistent_log` — 404
- `test_list_logs_nonexistent_tool` — empty list or 404

### 4.3 External MCP Sources API tests
**New file:** `backend/tests/test_external_mcp_sources.py`

Test core CRUD + discovery endpoints (11 endpoints):
- CRUD: create, list, get, update, delete
- Discovery: discover tools from source (mock external MCP server)
- Import: import discovered tools
- Health: check source health
- Error cases: nonexistent source, invalid URL, connection failures

### 4.4 Execution Log Service tests
**New file:** `backend/tests/test_execution_log_service.py`

- `test_create_log` — verify log created with correct fields
- `test_list_by_tool` — verify filtering and pagination
- `test_list_by_server` — verify filtering
- `test_redact_args` — verify sensitive arguments are redacted
- `test_truncate_result` — verify long results are truncated
- `test_cleanup` — verify old logs are cleaned up

### 4.5 Tool Change Notifier tests
**New file:** `backend/tests/test_tool_change_notifier.py`

- `test_notify_tools_changed_via_gateway` — mock httpx call, verify correct URL and method
- `test_fire_and_forget_notify` — verify non-blocking behavior
- `test_notify_failure_doesnt_raise` — verify graceful error handling

### 4.6 MCP Management Service coverage expansion
**File:** `backend/tests/test_mcp_management.py` (extend existing)

Add tests for uncovered tool handlers. Focus on the most critical:
- `mcpbox_create_tool` — verify tool creation flow
- `mcpbox_update_tool` — verify code update triggers approval reset (ties to SEC-001)
- `mcpbox_delete_tool` — verify cleanup
- `mcpbox_list_servers` / `mcpbox_list_tools` — verify pagination
- Error cases: invalid tool ID, missing required fields

---

## Phase 5: Code Consistency

### 5.1 Fix route prefix double-nesting
**File:** `backend/app/api/settings.py` (line 51)

Change:
```python
@router.get("/settings", response_model=SettingListResponse)
```
To:
```python
@router.get("", response_model=SettingListResponse)
```

Also audit other endpoints in settings.py for the same pattern — any endpoint that starts with `/settings` should have that prefix removed since the router already has `prefix="/settings"`.

**Frontend impact:** Search frontend for `/api/settings/settings` and update to `/api/settings`.

### 5.2 Standardize HTTPException status codes
**Files:** `backend/app/api/server_secrets.py`, `backend/app/api/mcp_gateway.py`

Replace bare integer status codes with `status.HTTP_*` enums:
- `status_code=404` → `status_code=status.HTTP_404_NOT_FOUND`
- `status_code=400` → `status_code=status.HTTP_400_BAD_REQUEST`
- `status_code=409` → `status_code=status.HTTP_409_CONFLICT`
- etc.

Add `from fastapi import status` import where missing.

### 5.3 Standardize type annotations
**Files:** Files using `Optional[X]` in `backend/app/services/`

Replace `Optional[X]` → `X | None` across:
- `backend/app/services/tunnel.py`
- `backend/app/services/sandbox_client.py`
- `backend/app/services/activity_logger.py`
- `backend/app/services/log_retention.py`

Remove `from typing import Optional` imports where no longer needed.

---

## Phase 6: Technical Debt

### 6.1 Add periodic session cleanup task for MCP gateway
**File:** `backend/app/api/mcp_gateway.py`

The session cleanup already happens opportunistically in `_create_session()` (lines 102-107). This is adequate for now. Document this in a code comment noting the `--workers 1` constraint. **No code change needed** — the existing implementation is correct.

### 6.2 Document vestigial enum values
**File:** `backend/app/models/server.py` (lines 16-39)

The comments already explain vestigial values (lines 17-18, 31). **No code change needed** — these are kept for DB enum compatibility and already documented.

---

## Phase 7: Documentation Updates

After all implementation:
1. **`docs/SECURITY.md`** — Update SEC-001, SEC-002 status to "Fixed". Add SEC-007, SEC-013, SEC-015 resolutions. Update SEC-005, SEC-009, SEC-011, SEC-012 status.
2. **`docs/TESTING.md`** — Update test coverage map with new test files.
3. **`docs/FEATURES.md`** — Update JWT blacklist as new feature.
4. **`docs/INCONSISTENCIES.md`** — Mark route prefix double-nesting, HTTPException style, and type annotation issues as resolved.

---

## Execution Order

| Step | Phase | Items | Est. Lines Changed |
|------|-------|-------|--------------------|
| 1 | 1.1-1.3 | SEC-001, SEC-002 + tests | ~50 |
| 2 | 2.1-2.4 | SEC-007, SEC-013, SEC-015 + tests | ~30 |
| 3 | 3.1-3.6 | SEC-005, SEC-009, SEC-011, SEC-012 + tests | ~150 |
| 4 | 4.1-4.6 | Test coverage for 6 modules | ~600 |
| 5 | 5.1-5.3 | Route prefix, HTTPException, type annotations | ~80 |
| 6 | 7 | Documentation updates | ~100 |

**Total estimated: ~1,010 lines across ~25 files**

SEC-010 is removed (already correctly implemented). SEC-006 is removed (already fixed — print override per-execution exists at executor.py:1824-1829). SEC-008 is removed (enforcement logic exists and is correct; `allowed_hosts=None` means no per-server restriction, which is by design).
