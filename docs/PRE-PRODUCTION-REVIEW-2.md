# Pre-Production Review #2: MCPbox

**Date:** 2026-02-06
**Reviewer:** Claude Opus 4.6 (automated review)
**Branch:** `claude/pre-production-review-Ckbuo`
**Prior Review:** `docs/PRE-PRODUCTION-REVIEW.md` (2025-02-05, all findings fixed in commit `33729ec`)

---

## Executive Summary

This is a **follow-up review** after the first pre-production review (PR #69). All prior findings (operator.attrgetter sandbox escape, race condition in tool.py, circuit breaker thread safety, unverified JWT email, unpinned Docker images) have been fixed.

This review found **new issues** not covered by the first review:

| Severity | Count | Summary |
|----------|-------|---------|
| **CRITICAL** | 1 | Sandbox bypass via `/execute` endpoint missing `validate_code_safety()` |
| **HIGH** | 3 | Divergent sandbox implementations, SSRF redirect bypass, `hasattr` escape vector |
| **MEDIUM** | 5 | Unencrypted OAuth code_verifier, code injection via string interpolation, etc. |
| **LOW** | 3 | Double commits, deprecated APIs, redundant config |

---

## 1. SECURITY ISSUES

### CRITICAL

#### S1. Sandbox `/execute` endpoint missing `validate_code_safety()` check
- **File:** `sandbox/app/routes.py:649-799`
- **Severity:** Critical
- **Description:** The `/execute` endpoint runs `exec(body.code, namespace)` at line 733 **without** calling `validate_code_safety()` first. The `PythonExecutor.execute()` method in `executor.py:1094-1128` properly validates code for forbidden dunder patterns (`__class__`, `__mro__`, `__subclasses__`, `__globals__`, etc.) before execution, but the direct `/execute` route bypasses this entirely.
- **Impact:** An attacker with access to the sandbox API can use patterns like `[].__class__.__mro__[-1].__subclasses__()` to escape the sandbox, access `subprocess.Popen`, file I/O classes, etc. While the sandbox is behind API key auth, this is the **test code** endpoint that `mcpbox_test_code` uses.
- **Fix:** Add `validate_code_safety()` call before `exec()` in the `/execute` endpoint, identical to how `PythonExecutor.execute()` does it.

### HIGH

#### S2. Sandbox `/execute` endpoint has weaker builtins than PythonExecutor
- **File:** `sandbox/app/routes.py:518-548`
- **Severity:** High
- **Description:** The `SAFE_BUILTINS` dict in `routes.py` is a **different, less restrictive** sandbox than the one in `PythonExecutor._create_safe_builtins()` at `executor.py:903-1025`. The `/execute` endpoint's builtins also lack the restricted `__import__` that wraps the `regex` module with timeout protection (TimeoutProtectedRegex). This means code submitted to `/execute` can use the raw `regex` module without ReDoS protection.
- **Fix:** Consolidate both code paths to use the same sandbox implementation (`PythonExecutor`), or at minimum, share the `_create_safe_builtins()` method.

#### S3. No redirect-following protection in SSRF clients
- **File:** `sandbox/app/ssrf.py:295-339`
- **Severity:** High
- **Description:** The SSRF protection validates the initial URL, but the underlying `httpx.AsyncClient` follows redirects by default. An attacker controlling an external server could serve a 302 redirect to `http://169.254.169.254/` (AWS metadata) or `http://localhost:8001/` (sandbox internal API) after the initial URL passes validation.
- **Fix:** Either disable redirects on the SSRF-protected clients (`follow_redirects=False`) or validate each redirect URL before following it. The simplest fix: create the httpx client with `follow_redirects=False`.

#### S4. `hasattr` allowed in sandbox enables indirect `getattr` calls
- **File:** `sandbox/app/executor.py:955`
- **Severity:** Medium-High
- **Description:** `hasattr` is in the allowed builtins list, but `hasattr(obj, name)` internally calls `getattr(obj, name)` and catches `AttributeError`. While `getattr` itself is blocked, `hasattr` can be used to probe for dunder attributes. Combined with the fact that `validate_code_safety` uses regex pattern matching (which can potentially be circumvented with string concatenation or encoding), this provides a secondary attack vector.
- **Fix:** Remove `hasattr` from allowed builtins, or at minimum add `hasattr\s*\(.*__\w+__` to `FORBIDDEN_PATTERNS`.

### MEDIUM

#### S5. OAuth `code_verifier` stored unencrypted in database
- **File:** `backend/app/services/oauth.py:214`
- **Severity:** Medium
- **Description:** The PKCE `code_verifier` is stored as plain text in `credential.oauth_code_verifier`. This value is sensitive - if an attacker can read the database, they can complete an OAuth flow by intercepting the authorization code and using the stored verifier.
- **Fix:** Encrypt the code_verifier before storing: `credential.oauth_code_verifier = encrypt(code_verifier)` and decrypt when using it.

#### S6. `re` module used instead of timeout-protected `regex` in management service
- **File:** `backend/app/services/mcp_management.py:465,575`
- **Severity:** Medium
- **Description:** The `_create_server` and `_create_tool` methods use `import re` for name validation. While these are simple patterns, using `re` instead of the timeout-protected `regex` module is inconsistent with the project's ReDoS prevention strategy.
- **Fix:** Use `regex` with timeout, or pre-compile the pattern since these are simple fixed patterns that aren't ReDoS-vulnerable.

#### S7. Swagger docs enabled unconditionally in production
- **File:** `backend/app/main.py:129-131`
- **Severity:** Low-Medium
- **Description:** `/docs` and `/redoc` are always enabled. The comment says "admin panel is local-only," but these provide a complete attack surface map if the backend is ever accidentally exposed. They're also excluded from auth middleware.
- **Fix:** Gate docs behind `settings.debug` or a separate `ENABLE_DOCS` setting. For a homelab that's explicitly local-only, this is acceptable but worth noting.

#### S8. Rate limiter uses `asyncio.Lock` which won't protect across multiple workers
- **File:** `backend/app/middleware/rate_limit.py:59`
- **Severity:** Low (by design - single instance deployment)
- **Description:** The in-memory rate limiter uses `asyncio.Lock` and is designed for single-instance deployments. This is fine per the architecture docs, but worth documenting prominently if someone tries to run with multiple workers/processes.
- **Fix:** Add a startup warning if multiple workers are detected.

---

## 2. BUGS

### B1. Double `db.commit()` in OAuth callback endpoints
- **File:** `backend/app/api/oauth.py:165-166` and `backend/app/api/oauth.py:223-224`
- **Severity:** Low (no-op, but indicates confusion)
- **Description:** `oauth_service.handle_callback()` already calls `await self.db.commit()` internally (at `oauth.py:365`). The route handler then calls `await db.commit()` again. The second commit is a no-op but suggests the transaction boundaries are unclear.
- **Fix:** Remove the redundant `await db.commit()` from the route handlers, or remove the commit from inside `handle_callback()` and let the route manage it.

### B2. Deprecated `@router.on_event("startup")` in sandbox
- **File:** `sandbox/app/routes.py:190`
- **Severity:** Low
- **Description:** `@router.on_event("startup")` is deprecated in newer FastAPI versions. Should use lifespan events.
- **Fix:** Move the startup logic to the lifespan context manager in `sandbox/app/main.py`.

### B3. `MCPResponse.model_config` is redundant
- **File:** `backend/app/api/mcp_gateway.py:65`
- **Severity:** Trivial
- **Description:** `model_config = {"exclude_none": True}` is set on the model, but `model_dump(exclude_none=True)` is also called explicitly at line 206. The model config is never used via implicit serialization since the return at line 206 is explicit.
- **Fix:** Remove the model_config or the explicit `exclude_none=True` parameter.

### B4. `_test_code` constructs Python code via string interpolation
- **File:** `backend/app/services/mcp_management.py:839-846`
- **Severity:** Medium
- **Description:** The `_test_code` method builds Python code using `repr(arguments)` interpolated into a string: `f"_test_args = {args_repr}"`. While `arguments` comes from JSON (limiting types), if a value contains specially crafted strings, `repr()` output could alter the code semantics. More importantly, this uses `asyncio.get_event_loop().run_until_complete()` inside what may already be an async context in the sandbox.
- **Fix:** Pass arguments via the sandbox's normal argument injection mechanism rather than string interpolation.

### B5. `settings` module-level instantiation can fail with unclear errors
- **File:** `backend/app/core/config.py:283`
- **Severity:** Medium
- **Description:** `settings = get_settings()` at module level means any import of `app.core` will fail if environment variables are missing. The error messages from Pydantic validation are good, but the stacktrace can be confusing. This is a common pattern but worth noting for production deployment troubleshooting.
- **Fix:** Document clearly in deployment guide. Consider lazy initialization.

---

## 3. DEAD CODE & REMOVABLE FOR FIRST RELEASE

### Remove: Legacy/Unused Code

#### D1. `SSRFProtectedHttpx` synchronous class (partially unused)
- **File:** `sandbox/app/ssrf.py:240-292`
- **Description:** The synchronous `SSRFProtectedHttpx` class is only used in the `/execute` endpoint via `sandbox/app/routes.py:554-575`. The main tool execution path uses the async `SSRFProtectedAsyncHttpClient`. If the `/execute` endpoint is refactored to use `PythonExecutor` (as recommended in S1/S2), this class may become unused.

#### D2. `DebugHttpClient.options()` and `DebugHttpClient.head()` methods
- **File:** `sandbox/app/executor.py:840-870`
- **Description:** These HTTP methods are unlikely to be used by MCP tools. Not harmful but adds code surface.

#### D3. Redundant `model_config` on `MCPResponse`
- **File:** `backend/app/api/mcp_gateway.py:65`
- **Description:** As noted in B3, this is redundant.

### Consider Removing for V1 (Feature Scope)

#### D4. OAuth infrastructure (if not needed for V1)
- **Files:**
  - `backend/app/api/oauth.py` - OAuth API endpoints
  - `backend/app/services/oauth.py` - OAuth service with 8 provider presets
  - `backend/app/services/token_refresh.py` - Background token refresh
- **Description:** The OAuth infrastructure (authorization code flow, PKCE, provider presets for Google/GitHub/Slack/etc., background token refresh) is significant complexity. If V1 tools primarily use API keys, this could be deferred. However, it IS used by the credential system, so only remove if you're simplifying credentials to API-key-only.

#### D5. Cloudflare setup wizard (if manual setup is acceptable for V1)
- **Files:**
  - `backend/app/api/cloudflare.py` - 10 wizard endpoints
  - `backend/app/services/cloudflare.py` - Cloudflare API integration
  - `backend/app/schemas/cloudflare.py` - Wizard schemas
  - `backend/app/models/cloudflare_config.py` - Config model
- **Description:** The wizard automates 7 steps of Cloudflare setup. For a first release, if users follow the manual setup guide (`docs/REMOTE-ACCESS-SETUP.md`), this entire wizard could be deferred. It's a lot of code touching external APIs.

#### D6. Named tunnel configuration management
- **Files:**
  - `backend/app/services/tunnel_configuration.py`
  - `backend/app/models/tunnel_configuration.py`
  - `backend/app/api/tunnel.py` (partially)
  - `backend/app/schemas/tunnel_configuration.py`
- **Description:** The ability to save and manage multiple named tunnel configurations. For V1 with a single tunnel, this may be unnecessary.

---

## 4. TEST COVERAGE GAPS

### High Priority (Security-Critical)

#### T1. No tests for sandbox escape prevention (`validate_code_safety`)
- **File:** `sandbox/app/executor.py:369-402`
- **Description:** The `validate_code_safety()` function is critical for preventing sandbox escapes, but there are no dedicated tests verifying it blocks all `FORBIDDEN_PATTERNS`. Tests should cover every forbidden pattern and common bypass techniques.

#### T2. No tests for SSRF protection bypass via redirects
- **File:** `sandbox/app/ssrf.py`
- **Description:** No tests verify that SSRF protection can't be bypassed via HTTP redirects to internal IPs.

#### T3. No tests for `/execute` endpoint sandbox safety
- **File:** `sandbox/app/routes.py:649-799`
- **Description:** The direct `/execute` endpoint has different sandboxing than `PythonExecutor` but lacks tests verifying forbidden operations are blocked.

### Medium Priority

#### T4. Missing tests for cloudflare service
- **File:** `backend/app/services/cloudflare.py`
- **Description:** No test file for `test_cloudflare_service.py`. The `test_cloudflare.py` tests exist but they may not cover the full service layer.

#### T5. Missing tests for approval service edge cases
- **Description:** Test that double-publish requests are rejected, that rejected tools can be re-submitted, that approved tools can't be re-approved, etc.

#### T6. No frontend tests at all
- **Description:** The `frontend/` directory has no test files. For production, at minimum add tests for critical API client functions and any complex business logic in components.

#### T7. Missing integration tests
- **File:** `backend/tests/integration/` (empty `__init__.py`)
- **Description:** The integration test directory exists but appears empty. Integration tests for the full MCP flow (create server -> create tool -> approve -> start -> call via /mcp) would catch issues the unit tests miss.

---

## 5. CODE QUALITY & CONSISTENCY ISSUES

### Q1. Two separate sandbox implementations
- **Files:** `sandbox/app/routes.py` (execute_python_code) vs `sandbox/app/executor.py` (PythonExecutor)
- **Description:** There are two distinct sandbox implementations with different security properties. The `/execute` endpoint has its own builtins, its own import restrictions, and its own execution model (ThreadPoolExecutor + exec). The `PythonExecutor` used by tool calls has a more thorough sandbox with `validate_code_safety()`. These should be consolidated.

### Q2. Inconsistent use of `re` vs `regex` module
- **Description:** The codebase uses timeout-protected `regex` in the sandbox but `re` (standard library) in backend services like `mcp_management.py`. For consistency and ReDoS protection, use `regex` everywhere or at minimum use compiled patterns.

### Q3. Global mutable state in singleton patterns
- **Files:** Multiple services use singleton patterns with `_instance` class variables
- **Description:** `SandboxClient`, `TokenRefreshService`, `LogRetentionService`, `RateLimiter`, `TunnelService` all use singleton patterns with threading locks. While this is fine for single-instance deployment, it makes testing harder and could cause issues if the app is ever run with multiple processes.

---

## 6. RECOMMENDATIONS (Priority Order)

1. **[CRITICAL]** Fix S1: Add `validate_code_safety()` to `/execute` endpoint
2. **[HIGH]** Fix S2: Consolidate sandbox implementations (routes.py and executor.py)
3. **[HIGH]** Fix S3: Disable redirect following in SSRF-protected clients
4. **[HIGH]** Add T1: Write tests for sandbox escape prevention
5. **[MEDIUM]** Fix S4: Remove or restrict `hasattr` in sandbox builtins
6. **[MEDIUM]** Fix S5: Encrypt OAuth code_verifier before storing
7. **[MEDIUM]** Fix B1: Remove double commits in OAuth callbacks
8. **[MEDIUM]** Fix B4: Don't build code via string interpolation in `_test_code`
9. **[LOW]** Fix B2: Replace deprecated `on_event("startup")`
10. **[LOW]** Add T6: Basic frontend tests
11. **[OPTIONAL]** Consider D4/D5/D6: Trim OAuth/Cloudflare wizard/tunnel configs for leaner V1
