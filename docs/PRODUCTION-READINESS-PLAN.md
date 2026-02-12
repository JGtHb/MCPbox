# Production Readiness: Implementation Plan

**Source:** `docs/PRODUCTION-READINESS-REVIEW.md`
**Created:** 2026-02-11
**Branch:** `claude/mcpbox-production-review-1h0w1`

---

## PR Tracker

| # | Title | Severity | Size | Deps | Status |
|---|-------|----------|------|------|--------|
| 1 | Consolidate sandbox builtins, remove `super()` | CRITICAL | M | None | DONE |
| 2 | Secure pip install with `--only-binary :all:` | CRITICAL | S | None | DONE |
| 3 | Replace `python-jose` with `PyJWT` | HIGH | M | None | DONE |
| 4 | Pin all dependencies to exact versions | HIGH | S | After #3 | DONE |
| 5 | Add frontend + worker tests to CI | HIGH | S | None | DONE |
| 6 | Enable mypy, add `pip-audit`/`npm audit` to CI | HIGH | M-L | After #3, #4 | DONE |
| 7 | Add Dependabot configuration | MEDIUM | S | After #4 | DONE |
| 8 | Docker: `no-new-privileges`, read-only sandbox root | MEDIUM+LOW | S | None | DONE |
| 9 | Harden admin auth prefix matching, `Permissions-Policy`, error sanitization | MEDIUM | S | None | DONE |
| 10 | Restrict destructive mgmt tools to local-only, SSE connection limit | MEDIUM | M | None | DONE |
| 11 | AST-based code validation (defense-in-depth) | CRITICAL (d-i-d) | M | After #1 | DONE |
| 12 | Fix structured logging JSON escaping | MEDIUM | S | None | DONE |
| 13 | Encryption key rotation utility | HIGH | M | None | DONE |
| 14 | Incident response + rollback documentation | HIGH | S-M | None | DONE |
| 15 | Prometheus metrics + webhook alerting | HIGH | L | After #4 | DONE |
| 16 | Fix admin auth prefix matching + error sanitization | MEDIUM | S | None | DONE |

---

## Phase 1: Critical Security Fixes

### PR 1 — Consolidate sandbox builtins, remove `super()`

**Findings addressed:**
- [CRITICAL] `super()` exposed in `/execute` builtins but not in `PythonExecutor` (`sandbox/app/routes.py:565`)
- [HIGH] Duplicate sandbox implementations with divergent builtins (`routes.py:521-595` vs `executor.py:902-1024`)
- [MEDIUM] `/execute` stdout not size-limited (`routes.py:787`)

**Files to change:**
- `sandbox/app/executor.py` — Extract `_create_safe_builtins()` to a module-level function so both execution paths can share it
- `sandbox/app/routes.py` — Remove the `SAFE_BUILTINS` dict (lines 521-595) and duplicate `safe_import` (lines 753-769); delegate to the shared function from `executor.py`; replace `io.StringIO()` with `SizeLimitedStringIO`
- `sandbox/tests/` — Add tests verifying `super` is blocked in both paths and builtins are identical

### PR 2 — Secure pip install with `--only-binary :all:`

**Findings addressed:**
- [HIGH] `pip install` can execute arbitrary code via `setup.py` (`sandbox/app/package_installer.py:123-133`)

**Files to change:**
- `sandbox/app/package_installer.py` — Add `"--only-binary", ":all:"` to the pip command
- `sandbox/tests/` — Test that the flag is present

---

## Phase 2: Dependency & Supply Chain

### PR 3 — Replace `python-jose` with `PyJWT`

**Findings addressed:**
- [HIGH] `python-jose` unmaintained (last release 2022), known CVEs (`backend/requirements.txt:15`)

**Files to change:**
- `backend/requirements.txt` — Replace `python-jose[cryptography]` with `PyJWT[crypto]`
- `backend/requirements-dev.txt` — Replace `types-python-jose`
- `backend/app/services/auth.py` — Migrate `jose.jwt` → `jwt` (PyJWT API)
- `backend/app/api/auth_simple.py` — Migrate JWKS verification to PyJWT
- `backend/tests/test_mcp_gateway.py` — Update `jose` imports to PyJWT equivalents
- Any other test files importing `jose`

### PR 4 — Pin all dependencies to exact versions

**Findings addressed:**
- [HIGH] All Python deps use `>=` instead of `==` (`backend/requirements.txt`, `sandbox/requirements.txt`)
- [MEDIUM] No lock files for deterministic builds

**Files to change:**
- `backend/requirements.txt` — `>=` → `==` at currently-installed versions
- `backend/requirements-dev.txt` — Same
- `sandbox/requirements.txt` — Same
- `sandbox/requirements-dev.txt` — Same

---

## Phase 3: CI Hardening

### PR 5 — Add frontend + worker tests to CI

**Findings addressed:**
- [HIGH] 4 frontend test files and 36 worker test cases exist but never run in CI

**Files to change:**
- `.github/workflows/ci.yml` — Add `test-frontend` and `test-worker` jobs

### PR 6 — Enable mypy, add dependency scanning to CI

**Findings addressed:**
- [HIGH] mypy disabled with `|| true` (`.github/workflows/ci.yml:142`)
- [HIGH] No dependency vulnerability scanning

**Files to change:**
- `.github/workflows/ci.yml` — Remove `|| true` from mypy; add `pip-audit` + `npm audit` steps
- `backend/requirements-dev.txt` — Add `pip-audit`
- Various backend source files — Fix any existing mypy errors

### PR 7 — Add Dependabot configuration

**Findings addressed:**
- [MEDIUM] No automated dependency updates

**Files to change:**
- `.github/dependabot.yml` — New file covering pip, npm, Docker base images

---

## Phase 4: Infrastructure & API Hardening

### PR 8 — Docker security hardening

**Findings addressed:**
- [HIGH] Sandbox has outbound internet via `mcpbox-sandbox-external` (`docker-compose.yml:148-149`)
- [LOW] No `no-new-privileges` on containers
- [LOW] No read-only root filesystem on sandbox

**Files to change:**
- `docker-compose.yml` — Add `security_opt: ["no-new-privileges:true"]` to all services; add `read_only: true` and `tmpfs: ["/tmp"]` to sandbox

### PR 9 — Harden admin auth, security headers, error sanitization

**Findings addressed:**
- [MEDIUM] Admin auth prefix matching could be bypassed (`backend/app/middleware/admin_auth.py:64-66`)
- [MEDIUM] `Permissions-Policy` header missing (`backend/app/middleware/security_headers.py`)
- [MEDIUM] Error responses may leak implementation details (`sandbox/app/routes.py:845-848`)

**Files to change:**
- `backend/app/middleware/admin_auth.py` — Tighten prefix matching to `path == excluded or path.startswith(excluded + "/")`
- `backend/app/middleware/security_headers.py` — Add `Permissions-Policy` header
- `sandbox/app/routes.py` — Sanitize error messages in `/execute` response
- Tests for each change

### PR 10 — MCP gateway authorization + SSE limits

**Findings addressed:**
- [MEDIUM] Destructive `mcpbox_*` tools accessible through tunnel (`backend/app/api/mcp_gateway.py:201-208`)
- [MEDIUM] SSE stream has no connection limit (`backend/app/api/mcp_gateway.py:85-101`)

**Files to change:**
- `backend/app/api/mcp_gateway.py` — Restrict destructive mgmt tools to `_user.source == "local"`; add `asyncio.Semaphore` for SSE connection limit
- Tests for both changes

---

## Phase 5: Defense-in-Depth & Operations

### PR 11 — AST-based code validation

**Findings addressed:**
- [CRITICAL] String concatenation can bypass regex dunder checks (`sandbox/app/executor.py:349-368`)

**Files to change:**
- `sandbox/app/executor.py` — Add `ast.parse()` + tree walk in `validate_code_safety()` to detect `ast.Attribute` nodes with forbidden names; keep regex as secondary layer
- `sandbox/tests/test_sandbox_escape.py` — Add obfuscation test cases

### PR 12 — Fix structured logging JSON escaping

**Findings addressed:**
- [MEDIUM] Structured logging produces invalid JSON (`backend/app/core/logging.py:8-10`)

**Files to change:**
- `backend/app/core/logging.py` — Use `python-json-logger` or custom formatter with `json.dumps()`
- `backend/requirements.txt` — Add `python-json-logger` if needed

### PR 13 — Encryption key rotation utility

**Findings addressed:**
- [HIGH] No encryption key rotation path (`backend/app/services/crypto.py:38-58`)

**Files to change:**
- `backend/app/services/crypto.py` — Support `MCPBOX_ENCRYPTION_KEY_OLD` env var
- `scripts/rotate-encryption-key.py` — New script to re-encrypt all DB records
- `backend/app/core/config.py` — Add optional `MCPBOX_ENCRYPTION_KEY_OLD` setting
- `docs/PRODUCTION-DEPLOYMENT.md` — Document key rotation procedure
- Tests for dual-key decryption

### PR 14 — Incident response + rollback documentation

**Findings addressed:**
- [HIGH] No incident response runbooks
- [MEDIUM] No rollback procedures documented
- [LOW] Configurable timeouts/limits not centrally documented

**Files to change:**
- `docs/INCIDENT-RESPONSE.md` — New file with runbooks for top failure scenarios
- `docs/PRODUCTION-DEPLOYMENT.md` — Add rollback section and configuration reference table

### PR 15 — Prometheus metrics + webhook alerting

**Findings addressed:**
- [HIGH] No application metrics (deployment docs describe metrics that don't exist)
- [HIGH] No alerting mechanism
- [LOW] Unauthenticated circuit breaker reset endpoint

**Files to change:**
- `backend/requirements.txt` — Add `prometheus-fastapi-instrumentator`
- `backend/app/main.py` — Add metrics middleware, expose `/metrics`
- `backend/app/mcp_only.py` — Same for MCP gateway
- `backend/app/api/health.py` — Require admin auth for `POST /health/circuits/reset`
- `backend/app/services/activity_logger.py` — Add webhook alerting (configurable URL)
- `docs/PRODUCTION-DEPLOYMENT.md` — Update monitoring section

---

## Accepted Risks (not addressed)

These findings were evaluated and accepted as reasonable for a homelab deployment:

| Finding | Rationale |
|---------|-----------|
| In-memory rate limit state lost on restart | Single-instance homelab; window is brief |
| Per-worker circuit breaker state | Effective threshold = threshold × workers; acceptable |
| No DB TLS | Internal Docker network (`mcpbox-db`, `internal: true`) |
| DNS rebinding timing window | Mitigated by `follow_redirects=False` |
| Auth rate limiting per-worker | Effective limit = limit × workers; acceptable |
| Race condition in tool approval | Low probability; follow-up if needed |
| `mcpbox-internal` network not internal | Backend needs outbound for Cloudflare API |
| Setup wizard can overwrite config | Admin panel is local-only |
| No integration/e2e tests | Significant effort; separate epic |
