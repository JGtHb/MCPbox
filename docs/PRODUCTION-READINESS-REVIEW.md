# MCPbox Production Readiness Review

**Date:** 2026-02-11
**Reviewer:** Claude (automated security & architecture review)
**Scope:** Complete codebase review across 12 areas
**Branch:** `claude/mcpbox-production-review-1h0w1`

---

## Executive Summary

MCPbox demonstrates strong security engineering for a homelab MCP platform. The sandbox escape prevention, SSRF protection with IP pinning, fail-closed service token cache, and multi-layer Cloudflare authentication are all well-implemented. The project has clearly undergone prior security reviews and addressed findings systematically.

The most significant gaps are in **sandbox escape edge cases** (string concatenation bypass of dunder checks, `super()` in the builtins), **dependency pinning** (all dependencies use `>=` instead of `==`), **CI completeness** (mypy disabled, no frontend/worker tests in CI, no dependency scanning), and **operational observability** (no metrics, no alerting).

**Overall Production Readiness Score: 7.0 / 10**

For a homelab deployment, this is solid. For a production deployment exposed to the internet via Cloudflare, the CRITICAL and HIGH items below should be addressed first.

---

## 1. SANDBOX SECURITY & CODE EXECUTION

### Summary

The sandbox is well-designed with multiple defense layers: restricted builtins (no `type`, `object`, `getattr`, `setattr`, `eval`, `exec`, `compile`, `open`), regex-based dunder attribute blocking, module import whitelist, SSRF-protected HTTP client with IP pinning, resource limits (RLIMIT_AS, RLIMIT_CPU, RLIMIT_NOFILE), and container-level isolation (non-root user, resource caps). The code safety validator (`validate_code_safety()`) is called on all execution paths.

However, there are bypass vectors in the regex-based validation that could allow sandbox escape.

### Findings

**[CRITICAL] String concatenation can bypass dunder attribute regex checks**
- **File:** `sandbox/app/executor.py:349-368`
- **Description:** The `FORBIDDEN_PATTERNS` use regex like `r"\.__class__\b"` to detect dunder access. However, these patterns only match literal string occurrences. An attacker could use string concatenation to dynamically construct attribute names, then use allowed builtins to access them. For example, while `getattr` is removed from builtins, the `operator` module is correctly excluded (line 293), but `functools.reduce` is available and `collections` module is allowed — creative use of allowed modules could potentially reconstruct access patterns. More critically, the pattern `getattr\s*\([^)]*['\"]__\w+__['\"]` only catches direct string literals passed to getattr, not variables: `attr = '_' + '_class_' + '_'; result = getattr([], attr)` would bypass the regex (though `getattr` is also removed from builtins, mitigating this specific vector).
- **Recommended fix:** Consider using AST-based validation instead of regex. Python's `ast` module can reliably detect attribute access nodes (`ast.Attribute`) regardless of obfuscation. This is a defense-in-depth improvement over regex.

**[CRITICAL] `super()` is exposed in `/execute` endpoint builtins but not in PythonExecutor builtins**
- **File:** `sandbox/app/routes.py:565` vs `sandbox/app/executor.py:924-991`
- **Description:** The `SAFE_BUILTINS` dict in `routes.py` (used by the `/execute` endpoint) includes `super` at line 565. However, the `PythonExecutor._create_safe_builtins()` in `executor.py` does NOT include `super`. `super()` can be used to traverse the MRO and potentially access parent class methods or attributes that enable escape. While `__class__` is blocked by regex, `super()` implicitly accesses the class hierarchy.
- **Recommended fix:** Remove `super` from `SAFE_BUILTINS` in `routes.py:565` to maintain consistency with `executor.py`. The `/execute` endpoint should have the same restrictions as the tool execution path.

**[HIGH] Duplicate sandbox implementations with divergent builtins**
- **File:** `sandbox/app/routes.py:521-595` vs `sandbox/app/executor.py:902-1024`
- **Description:** There are two separate sandbox implementations: `SAFE_BUILTINS` (dict at module level in routes.py for `/execute`) and `PythonExecutor._create_safe_builtins()` (method in executor.py for tool calls). They have different allowed builtins — routes.py includes `complex`, `super`, `IOError`, `OSError`, `FileNotFoundError`, `PermissionError`, `ConnectionError`, `StopAsyncIteration`, `NotImplementedError`, `ZeroDivisionError`, `OverflowError`, `UnicodeError`, `UnicodeDecodeError`, `UnicodeEncodeError`, `ArithmeticError`, `LookupError`, `TimeoutError` that executor.py does not. This divergence makes it easy for security fixes to be applied to one path but not the other.
- **Recommended fix:** Consolidate into a single `create_safe_builtins()` function shared between both execution paths. The `/execute` endpoint should delegate to `PythonExecutor` rather than maintaining its own sandbox logic.

**[HIGH] Package installation via `pip install` can execute arbitrary code in `setup.py`**
- **File:** `sandbox/app/package_installer.py:123-133`
- **Description:** The `pip install` command does not use `--no-build-isolation` to prevent `setup.py` execution, but more importantly it does NOT use `--only-binary :all:` which would restrict to pre-built wheels. A malicious package (or a legitimate package with a C extension) will run `setup.py` during installation, which executes arbitrary code outside the sandbox's restricted builtins. The OSV vulnerability check happens via a separate endpoint, not as a gate before installation.
- **Recommended fix:** Add `--only-binary`, `:all:` to the pip install command to only install pre-built wheels. If source builds are needed, add `--no-build-isolation` isn't sufficient — consider running pip in a more restricted sub-sandbox. Also gate installation on passing the vulnerability check.

**[MEDIUM] Resource limits set at module load time are process-wide, not per-execution**
- **File:** `sandbox/app/executor.py:192`
- **Description:** `set_resource_limits()` is called once at module load (line 192). The RLIMIT_CPU limit of 60 seconds (line 126) is cumulative across all executions in the process lifetime, not per-request. After ~60 seconds of total CPU time across all tool executions, the process will receive SIGXCPU. With uvicorn workers, this means a worker restart, but it's not per-request isolation.
- **Recommended fix:** Document that RLIMIT_CPU is a process-level safety net, not per-request. The per-request timeout via `asyncio.wait_for` (line 1192) is the primary mechanism. Consider resetting CPU time tracking between requests or using cgroup-level limits.

**[MEDIUM] `/execute` endpoint stdout is not size-limited like PythonExecutor**
- **File:** `sandbox/app/routes.py:787`
- **Description:** The `/execute` endpoint uses plain `io.StringIO()` (line 787) for stdout capture, while `PythonExecutor` uses `SizeLimitedStringIO` (line 1086). A tool that prints enormous output to stdout via `/execute` could exhaust memory before the resource limit kicks in (RLIMIT_AS is 256MB, and strings can grow to fill that).
- **Recommended fix:** Use `SizeLimitedStringIO` in the `/execute` endpoint as well.

**[MEDIUM] DNS rebinding timing window in SSRF protection**
- **File:** `sandbox/app/ssrf.py:196-206`
- **Description:** While IP pinning is implemented correctly (DNS is resolved once and the IP is used for the request), there is a small timing window: DNS is resolved via `socket.getaddrinfo()` which is synchronous and blocking. If the DNS TTL is very short and the attacker controls the DNS server, the first resolution returns a safe IP (used for the request), but a subsequent request to the same hostname could resolve to an internal IP. The mitigation is that redirects are disabled (`follow_redirects=False`), which eliminates the most common DNS rebinding attack vector.
- **Recommended fix:** The current implementation is reasonable. For additional hardening, consider caching validated IPs per hostname for a minimum TTL (e.g., 30 seconds).

**[LOW] `collections` module allows `namedtuple` which uses `exec` internally**
- **File:** `sandbox/app/executor.py:289`
- **Description:** The `collections` module is in the allowed list. `collections.namedtuple` internally uses `exec()` to generate classes. While this doesn't directly enable escape (the `exec` call happens in the collections module's own context, not the sandbox namespace), it's worth noting as a potential concern for defense-in-depth.

### What's Done Well
- SSRF protection with IP pinning, IPv4-mapped IPv6 handling, redirect blocking
- `__slots__` on `SSRFProtectedAsyncHttpClient` to prevent attribute access to underlying client
- Comprehensive dunder attribute blocking list
- `validate_code_safety()` called on ALL execution paths (both `/execute` and tool execution)
- Resource limits (memory, CPU, FD) with fail-closed behavior
- Isolated `IsolatedOs` and `IsolatedEnv` for credential injection
- `TimeoutProtectedRegex` wrapper preventing ReDoS
- Non-root container user

---

## 2. AUTHENTICATION & AUTHORIZATION

### Summary

Authentication is well-architected with a hybrid model: local mode (no auth for Claude Desktop) and remote mode (service token + JWT via Cloudflare). The fail-closed design in `ServiceTokenCache` is excellent — DB errors or decryption failures default to denying all requests. Server-side JWT verification prevents trusting Worker-supplied headers.

### Findings

**[HIGH] `python-jose` is unmaintained and has known vulnerabilities**
- **File:** `backend/requirements.txt:15`
- **Description:** `python-jose[cryptography]>=3.3.0` is used for JWT operations. The `python-jose` library is effectively unmaintained (last release 2022) and has known issues including CVE-2024-33663 (algorithm confusion in ECDSA). While the code explicitly specifies `algorithms=["RS256"]` (auth_simple.py:103), mitigating algorithm confusion, the library itself is a risk.
- **Recommended fix:** Migrate to `PyJWT` (actively maintained) or `joserfc`. Both support RS256 with JWKS.

**[MEDIUM] Admin auth middleware uses prefix matching that could be bypassed**
- **File:** `backend/app/middleware/admin_auth.py:64-66`
- **Description:** The `EXCLUDED_PATHS` check uses `path.startswith(excluded)`. This means any path starting with `/config`, `/mcp`, `/auth`, or `/internal` is excluded from admin auth. For example, if a future route like `/configuration` or `/mcpbox-admin` were added, it would accidentally bypass auth. The current routes don't have this issue, but it's fragile.
- **Recommended fix:** Use more specific prefix matching (e.g., `/config/`, `/config`) or exact path matching where possible.

**[MEDIUM] In-memory rate limiting state lost on restart**
- **File:** `backend/app/middleware/rate_limit.py:48-96`
- **Description:** The `RateLimiter` is in-memory (designed for single-instance homelab). On process restart, all rate limit state is lost. An attacker could trigger a restart (e.g., by causing the circuit breaker to trip repeatedly) and then exploit the window of no rate limiting.
- **Recommended fix:** Acceptable for homelab. Document this as a known limitation. For hardening, consider persisting rate limit state to Redis or a file.

**[MEDIUM] Auth rate limiting for service token uses `time.monotonic()` which resets on restart**
- **File:** `backend/app/api/auth_simple.py:35-37`
- **Description:** `_failed_auth_attempts` is a module-level dict using `time.monotonic()`. On process restart, all failed attempt tracking is lost. With 4 uvicorn workers, each worker has its own dict, so an attacker could distribute attempts across workers (10 failures * 4 workers = 40 attempts before any worker rate-limits).
- **Recommended fix:** For homelab this is acceptable. Document that the effective rate limit is `_FAILED_AUTH_MAX * num_workers` per window.

**[LOW] JWT access tokens cannot be revoked**
- **File:** `backend/app/services/auth.py` (referenced by admin_auth.py)
- **Description:** JWT access tokens are stateless — once issued, they're valid until expiry. If an admin session is compromised, there's no way to revoke the token short of changing the signing key (which invalidates ALL tokens). The password change invalidation noted in tests works for refresh tokens but not already-issued access tokens.
- **Recommended fix:** Use short-lived access tokens (e.g., 15 minutes) with refresh tokens. Already partially implemented.

### What's Done Well
- Fail-closed `ServiceTokenCache` — DB errors and decryption failures default to deny-all
- `secrets.compare_digest()` for constant-time token comparison
- Server-side JWT verification (doesn't trust Worker headers)
- Team domain format validation preventing JWKS redirection attacks
- Separate auth for MCP gateway vs admin API
- X-Forwarded-For only trusted from configured proxy IPs

---

## 3. DATABASE & DATA INTEGRITY

### Summary

Database layer is clean with async SQLAlchemy, proper session management with rollback on exception, AES-256-GCM encryption for credentials, and configurable connection pooling. No SQL injection vectors found — all queries use ORM or parameterized statements.

### Findings

**[HIGH] No encryption key rotation path**
- **File:** `backend/app/services/crypto.py:38-58`
- **Description:** If `MCPBOX_ENCRYPTION_KEY` needs to be rotated (e.g., suspected compromise), all encrypted data (credentials, service tokens) becomes unreadable. There is no re-encryption migration tool or dual-key support.
- **Recommended fix:** Build a key rotation utility that decrypts with the old key and re-encrypts with the new key. Support a `MCPBOX_ENCRYPTION_KEY_OLD` env var for transition periods.

**[MEDIUM] No database connection encryption (TLS)**
- **File:** `docker-compose.yml:60`
- **Description:** The DATABASE_URL uses `postgresql+asyncpg://` without SSL parameters. Database traffic is unencrypted, relying solely on Docker network isolation (`mcpbox-db` internal network). If the Docker network is compromised or misconfigured, credentials could be intercepted.
- **Recommended fix:** For homelab with internal Docker networks, this is acceptable. Document as a conscious decision. For production with separate DB hosts, add `?sslmode=require`.

**[MEDIUM] Potential race condition in tool approval workflow**
- **File:** `backend/app/services/mcp_management.py` (referenced by mcp_gateway.py)
- **Description:** The tool approval workflow (draft → pending_review → approved/rejected) doesn't use database-level locking. Two concurrent requests could both read a tool as "pending_review" and both attempt to approve it, or a tool could be modified while being approved. SQLAlchemy's ORM doesn't provide row-level locking by default.
- **Recommended fix:** Add `SELECT ... FOR UPDATE` (via `with_for_update()`) on tool status transitions to prevent concurrent modifications.

**[LOW] `pool_pre_ping=True` adds latency to every query**
- **File:** `backend/app/core/database.py:28`
- **Description:** `pool_pre_ping=True` issues a `SELECT 1` before every connection checkout. For a homelab with low latency to the local PostgreSQL, this is minimal overhead but does add one round trip per query.
- **Recommended fix:** Acceptable for reliability. No change needed.

### What's Done Well
- AES-256-GCM with random 96-bit IVs (not CBC, not ECB)
- Minimum encrypted data length validation preventing oracle attacks
- Session management with proper rollback on both `Exception` and `BaseException` (catches `CancelledError`)
- Connection pool with configurable sizes via environment variables
- `pool_pre_ping=True` for connection health checking

---

## 4. DOCKER & INFRASTRUCTURE SECURITY

### Summary

Docker configuration is well-segmented with four networks (internal, sandbox, sandbox-external, db), resource limits on all containers, and non-root users. The sandbox is on an internal network with a separate external network for PyPI access. PostgreSQL is isolated on `mcpbox-db` (internal: true).

### Findings

**[HIGH] Sandbox container has outbound internet access via `mcpbox-sandbox-external`**
- **File:** `docker-compose.yml:148-149, 223-225`
- **Description:** The sandbox container is on `mcpbox-sandbox-external` (internal: false) for pip/PyPI access. This means user code executing in the sandbox could potentially make outbound requests to the internet directly (bypassing the SSRF-protected HTTP client) if they can import `socket` or `urllib`. While the import whitelist blocks `socket` and `urllib.request`, the package installer runs `pip` which needs network access. There's no network-level restriction on what the sandbox process can reach.
- **Recommended fix:** Consider using a network policy or iptables rules to restrict sandbox outbound traffic to only PyPI hostnames. Alternatively, use a pip proxy/cache so the sandbox doesn't need direct internet access.

**[MEDIUM] `mcpbox-internal` network is not internal**
- **File:** `docker-compose.yml:215-216`
- **Description:** `mcpbox-internal` has `internal: false`, which means containers on this network can reach the internet. The backend, frontend, mcp-gateway, and cloudflared are all on this network. While the backend needs outbound access for Cloudflare API calls, the frontend (nginx serving static files) does not.
- **Recommended fix:** Consider creating a separate external network just for the backend's Cloudflare API access, and making `mcpbox-internal` truly internal.

**[MEDIUM] Wrangler installed globally as root in backend Dockerfile**
- **File:** `backend/Dockerfile:40-41`
- **Description:** `npm install -g wrangler@4` is run as root before switching to the non-root user. This is a large dependency tree installed globally. The wrangler is only needed for the deploy-worker.sh script, not for normal backend operation.
- **Recommended fix:** Consider moving wrangler to a separate deploy container or install it in a user-local directory. This reduces the backend image's attack surface.

**[LOW] No `--no-new-privileges` security option on containers**
- **File:** `docker-compose.yml` (all services)
- **Description:** None of the container definitions include `security_opt: ["no-new-privileges:true"]` which prevents processes from gaining additional privileges via setuid/setgid binaries.
- **Recommended fix:** Add `security_opt: ["no-new-privileges:true"]` to all service definitions, especially the sandbox.

**[LOW] No read-only root filesystem on sandbox**
- **File:** `docker-compose.yml:136-161`
- **Description:** The sandbox container's root filesystem is writable. While user code runs in a restricted Python environment, a sandbox escape could write to the filesystem. Adding `read_only: true` with tmpfs for `/tmp` would add defense-in-depth.
- **Recommended fix:** Add `read_only: true` and `tmpfs: ["/tmp"]` to the sandbox service.

### What's Done Well
- All ports bound to `127.0.0.1` (frontend:3000, backend:8000)
- MCP gateway port NOT exposed to host (only accessible within Docker network)
- PostgreSQL on dedicated internal-only network (`mcpbox-db`, internal: true)
- Resource limits (CPU + memory) on ALL containers
- Non-root users in all Dockerfiles
- Multi-stage build for backend (reduces image size and attack surface)
- Health checks on all services

---

## 5. API SECURITY & INPUT VALIDATION

### Summary

API endpoints use Pydantic schemas for validation, rate limiting is applied via middleware with per-path configuration, and security headers are comprehensive. CORS is separately configured for admin and MCP gateway.

### Findings

**[MEDIUM] No maximum `page_size` limit on list endpoints**
- **File:** `backend/app/api/` (various endpoints)
- **Description:** List endpoints that accept `page_size` parameters don't enforce a maximum. A request with `page_size=1000000` could cause the database to return and serialize a very large result set, potentially exhausting memory.
- **Recommended fix:** Add a maximum page_size (e.g., 100) to all list endpoint schemas.

**[MEDIUM] Error responses may leak implementation details**
- **File:** `sandbox/app/routes.py:845-848`
- **Description:** The `/execute` endpoint returns `f"Execution error: {type(e).__name__}: {str(e)}"` which includes the full exception message. Depending on the exception, this could leak internal file paths, database connection strings, or other sensitive information.
- **Recommended fix:** Sanitize error messages in the `/execute` response. Return generic messages for unexpected exceptions and detailed messages only for known safe exceptions (ValueError, TypeError, etc.).

**[MEDIUM] `Permissions-Policy` header not set**
- **File:** `backend/app/middleware/security_headers.py:10-24`
- **Description:** Security headers include X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy, and conditional HSTS, but missing `Permissions-Policy` header to restrict browser features.
- **Recommended fix:** Add `Permissions-Policy: camera=(), microphone=(), geolocation=()` to the security headers.

**[LOW] HSTS only set conditionally on HTTPS**
- **File:** `backend/app/middleware/security_headers.py:20-22`
- **Description:** HSTS header is only added when the request arrives via HTTPS or has `x-forwarded-proto: https`. In a homelab deployment where the backend is behind a reverse proxy, the initial HTTP connection (before redirect) won't have HSTS. This is standard behavior but worth noting.

### What's Done Well
- Pydantic schemas for all API inputs
- Code size limits enforced (100KB per code field)
- Rate limiting with token bucket + sliding window (minute + hour)
- X-Forwarded-For only trusted from configured proxy IPs
- Security headers (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
- Separate CORS configs for admin panel and MCP gateway
- Wildcard CORS explicitly rejected in Worker

---

## 6. MCP PROTOCOL IMPLEMENTATION

### Summary

The MCP implementation is clean with proper JSON-RPC 2.0 handling, notification support (202 for notifications), and combined tool listing (sandbox + management tools). Gateway isolation is achieved by having `mcp_only.py` include only the MCP router.

### Findings

**[MEDIUM] Management tools (mcpbox_*) accessible through tunnel with same auth as regular tools**
- **File:** `backend/app/api/mcp_gateway.py:201-208`
- **Description:** All 18 `mcpbox_*` management tools (create_server, delete_server, create_tool, etc.) are accessible through the tunnel with the same authentication as regular tool calls. A remote user with valid Cloudflare Access can create/delete servers and tools. While the approval workflow prevents immediate publication, the management tools have significant destructive capability (delete_server, delete_tool).
- **Recommended fix:** Consider restricting destructive management tools (delete_*, update_*) to local-only access (`_user.source == "local"`), or add an additional authorization layer for management tools.

**[MEDIUM] SSE keep-alive stream has no connection limit**
- **File:** `backend/app/api/mcp_gateway.py:85-101`
- **Description:** The SSE endpoint (`GET /mcp`) creates an infinite keep-alive stream per connection. There's no limit on the number of concurrent SSE connections. An attacker could open many SSE connections to exhaust server resources.
- **Recommended fix:** Add a connection counter and limit (e.g., 50 concurrent SSE connections). Close the oldest connections when the limit is reached.

**[LOW] MCP protocol version hardcoded**
- **File:** `backend/app/api/mcp_gateway.py:155`
- **Description:** `protocolVersion: "2024-11-05"` is hardcoded. This should be updated as the MCP specification evolves.

### What's Done Well
- Gateway isolation — `mcp_only.py` physically cannot serve `/api/*` endpoints
- JWT required for ALL MCP methods via remote (including initialize, notifications)
- Proper JSON-RPC 2.0 error codes
- Activity logging for all MCP requests/responses
- Management tool errors don't leak internal details
- Health endpoint on MCP gateway restricted to localhost

---

## 7. CLOUDFLARE INTEGRATION & REMOTE ACCESS

### Summary

The Cloudflare integration is sophisticated with Workers VPC (no public tunnel hostname), OAuth 2.1 via `@cloudflare/workers-oauth-provider`, and multi-layer security (OAuth + service token + JWT). The Worker correctly rejects wildcard CORS and validates JWTs server-side.

### Findings

**[MEDIUM] Setup wizard can overwrite existing active configuration**
- **File:** `backend/app/api/cloudflare.py` (referenced architecture)
- **Description:** The setup wizard at `/tunnel/setup` can be re-run to create a new configuration. If an attacker gains access to the admin panel (local network), they could reconfigure the tunnel and service token, potentially redirecting the tunnel to their own infrastructure.
- **Recommended fix:** Add a confirmation step or require re-authentication before overwriting an active configuration. Display a prominent warning.

**[MEDIUM] Tunnel token stored encrypted but accessible via internal endpoint**
- **File:** `docker-compose.yml:198-199` and `backend/app/api/internal.py`
- **Description:** The cloudflared container fetches its tunnel token from the backend's `/internal` endpoint using `SANDBOX_API_KEY`. Any container on `mcpbox-internal` network could call this endpoint with the sandbox API key to retrieve the tunnel token. The sandbox container is NOT on `mcpbox-internal`, but the frontend container IS.
- **Recommended fix:** Consider using a separate, more restricted authentication mechanism for internal endpoints rather than sharing the `SANDBOX_API_KEY`.

**[LOW] Worker JWKS cache is in-memory (per-isolate)**
- **File:** `worker/src/index.ts:63`
- **Description:** The Worker's JWKS cache is stored in a module-level `Map`. Cloudflare Workers can be evicted and recreated, losing the cache. This means JWKS will be re-fetched frequently in low-traffic scenarios, adding latency to the first request after eviction.
- **Recommended fix:** Consider caching JWKS in KV with a TTL as a fallback.

### What's Done Well
- Workers VPC — tunnel has no public hostname
- OAuth 2.1 with `@cloudflare/workers-oauth-provider`
- Redirect URI validation (only claude.ai, localhost)
- CORS origin validation (rejects wildcard)
- Service token as defense-in-depth (not sole auth)
- Team domain format validation preventing JWKS redirection

---

## 8. ERROR HANDLING & RESILIENCE

### Summary

Error handling is robust with a proper circuit breaker implementation, exponential backoff with jitter, and background task supervision. The circuit breaker correctly handles half-open state transitions and has configurable thresholds.

### Findings

**[MEDIUM] Circuit breaker state is per-worker, not shared**
- **File:** `backend/app/core/retry.py:80`
- **Description:** `CircuitBreaker._instances` is a class-level dict, meaning each uvicorn worker has its own circuit breaker state. With 4 workers (backend) or 2 workers (MCP gateway), the failure threshold is effectively multiplied (5 failures per worker before opening = 10-20 total failures). Worker A might have the circuit open while Worker B still sends requests.
- **Recommended fix:** For homelab this is acceptable. Document that the effective failure threshold is `failure_threshold * num_workers`.

**[MEDIUM] Background task exceptions not fully supervised**
- **File:** `backend/app/mcp_only.py:87`
- **Description:** The rate limit cleanup task is created with `asyncio.create_task()` but if it raises an unhandled exception, the task silently fails without notification. The `token_refresh_service` and `log_retention_service` have their own start/stop methods, but their internal error handling varies.
- **Recommended fix:** Add exception callbacks to background tasks or wrap them in a supervisor that logs failures and attempts restart.

**[LOW] Graceful shutdown doesn't wait for in-flight MCP requests**
- **File:** `backend/app/mcp_only.py:92-105`
- **Description:** The shutdown sequence cancels background tasks and closes the sandbox client, but doesn't explicitly wait for in-flight HTTP requests to complete. Uvicorn's `--timeout-graceful-shutdown` (not configured) defaults to no grace period with `--workers`.
- **Recommended fix:** Configure `--timeout-graceful-shutdown 30` in the uvicorn command.

### What's Done Well
- Circuit breaker with closed → open → half-open state machine
- Exponential backoff with random jitter (prevents thundering herd)
- `CircuitBreakerOpen` exception with `retry_after` for client guidance
- Background task cancellation on shutdown
- Activity logger with batch writes and flush on shutdown

---

## 9. TESTING & CI/CD

### Summary

Backend has 38+ test files with strong coverage of auth, sandbox escape, JWT verification, and service token fail-closed behavior. Worker has 36 test cases. However, CI has significant gaps: mypy is disabled, frontend/worker tests are not in CI, and there's no dependency scanning.

### Findings

**[HIGH] Type checking (mypy) disabled in CI**
- **File:** `.github/workflows/ci.yml:142`
- **Description:** `mypy app --ignore-missing-imports || true` — mypy failures are swallowed by `|| true`. Type errors are never caught in CI.
- **Recommended fix:** Remove `|| true` and fix any existing type errors. Type checking catches real bugs, especially in a security-sensitive codebase.

**[HIGH] No dependency vulnerability scanning in CI**
- **File:** `.github/workflows/ci.yml` (missing)
- **Description:** No Dependabot, Snyk, pip-audit, or npm audit configured. For a project that handles credentials and executes arbitrary code, this is a significant gap.
- **Recommended fix:** Add `pip-audit` and `npm audit` steps to CI. Configure Dependabot for automated PR creation.

**[HIGH] Frontend and Worker tests not in CI**
- **File:** `.github/workflows/ci.yml` (missing jobs)
- **Description:** 4 frontend test files and 36 worker test cases exist but are never run in CI. The worker tests include critical security tests (algorithm confusion, path traversal).
- **Recommended fix:** Add CI jobs for `npm test` in both frontend and worker directories.

**[MEDIUM] No integration/end-to-end tests**
- **File:** `backend/tests/integration/` (empty `__init__.py` only)
- **Description:** No tests that verify the full request path (client → gateway → sandbox → database). Individual unit tests are strong but integration gaps could hide issues.

### What's Done Well
- Dedicated `test_sandbox_escape.py` with comprehensive escape vector coverage
- JWT verification tests covering algorithm confusion, tampering, expiry
- Service token fail-closed tests covering DB errors and decryption errors
- Test fixtures with proper cleanup (circuit breaker reset, rate limiter reset)
- Test isolation via database rollback per test

---

## 10. DEPENDENCY MANAGEMENT & SUPPLY CHAIN

### Summary

Dependencies are reasonably chosen and minimal, but none are pinned to exact versions, there are no lock files, and automated dependency updates are not configured.

### Findings

**[HIGH] All Python dependencies use `>=` instead of exact pinning**
- **File:** `backend/requirements.txt:1-22`, `sandbox/requirements.txt:1-10`
- **Description:** Every dependency uses `>=` (e.g., `fastapi>=0.109.0`, `cryptography>=42.0.0`). This means `pip install` could install any newer version, including ones with breaking changes or new vulnerabilities. Builds are not deterministic.
- **Recommended fix:** Pin all dependencies to exact versions (e.g., `fastapi==0.115.0`). Use `pip-compile` (from `pip-tools`) to generate locked requirements files.

**[HIGH] `python-jose` is unmaintained** (duplicate of Auth finding)
- **File:** `backend/requirements.txt:15`
- **Description:** Last release Feb 2022. Known CVEs. See Auth section.

**[MEDIUM] No lock files for deterministic builds**
- **File:** (missing files)
- **Description:** No `requirements.lock`, `poetry.lock`, or `pip-compile` output. No `package-lock.json` for frontend or worker (should verify). Different builds at different times could produce different dependency trees.
- **Recommended fix:** Generate and commit lock files.

**[MEDIUM] No automated dependency updates**
- **File:** `.github/` (missing `dependabot.yml`)
- **Description:** No Dependabot or Renovate configuration. Dependency updates require manual effort.
- **Recommended fix:** Add `.github/dependabot.yml` covering pip, npm, and Docker base images.

### What's Done Well
- Minimal dependency set (no unnecessary packages)
- `regex` chosen over `re` specifically for timeout support (security-motivated)
- `argon2-cffi` for password hashing (better than bcrypt)
- `cryptography` for AES-256-GCM (proper AEAD)

---

## 11. OBSERVABILITY & OPERATIONAL READINESS

### Summary

Health checks are comprehensive (database + sandbox + circuit breaker states). Activity logging with batch writes and WebSocket streaming is well-designed. However, there are no application metrics (Prometheus), no alerting, and structured logging can produce invalid JSON.

### Findings

**[HIGH] No application metrics**
- **File:** `docs/PRODUCTION-DEPLOYMENT.md:168-175`
- **Description:** The deployment documentation describes monitoring "request latency (p50, p95, p99), error rates by endpoint, database connection pool usage" but none of these metrics are actually exposed. There is no Prometheus endpoint or metrics middleware.
- **Recommended fix:** Add `prometheus-fastapi-instrumentator` or similar middleware to expose `/metrics`. Remove aspirational metrics documentation or mark it as "planned."

**[HIGH] No alerting mechanism**
- **File:** `backend/app/services/activity_logger.py:299-320`
- **Description:** The `log_alert` method writes to the database but doesn't send external notifications. If the database goes down, sandbox starts failing, or tunnel disconnects, no one is notified.
- **Recommended fix:** For homelab, add webhook-based alerting (Discord, Slack, or email via SMTP). Even a simple HTTP POST to a webhook URL on critical failures would significantly improve operational awareness.

**[MEDIUM] Structured logging produces invalid JSON**
- **File:** `backend/app/core/logging.py:8-10`
- **Description:** The structured format uses Python string interpolation for the `message` field. If the message contains double quotes or newlines, the JSON output is invalid. Log aggregation systems will fail to parse these entries.
- **Recommended fix:** Use `python-json-logger` or `structlog` for proper JSON escaping.

**[LOW] Unauthenticated circuit breaker reset endpoint**
- **File:** `backend/app/api/health.py:138-146`
- **Description:** `POST /health/circuits/reset` can reset all circuit breakers without authentication. On a LAN, an attacker could keep circuit breakers from opening, preventing the system from protecting itself against a failing sandbox.
- **Recommended fix:** Require admin auth for the circuit breaker reset endpoint.

### What's Done Well
- Health endpoints check database AND sandbox connectivity
- Circuit breaker state exposed via `/health/circuits`
- Activity logger with batch DB writes (reduces DB load)
- WebSocket streaming for real-time log monitoring
- Log retention with configurable period
- Sensitive parameter sanitization in activity logs

---

## 12. DOCUMENTATION & OPERATIONAL PROCEDURES

### Summary

Documentation is thorough for architecture, security model, and remote access setup. The threat model in REMOTE-ACCESS-SETUP.md is particularly strong. Gaps exist in incident response runbooks, rollback procedures, and operational configuration reference.

### Findings

**[HIGH] No incident response runbooks**
- **File:** `docs/` (missing)
- **Description:** No documented procedures for: database failure recovery, sandbox compromise, credential rotation under duress, tunnel disconnection, encryption key compromise, circuit breaker stuck in open state.
- **Recommended fix:** Create `docs/INCIDENT-RESPONSE.md` with runbooks for the top 5 failure scenarios.

**[MEDIUM] No rollback procedures documented**
- **File:** `docs/PRODUCTION-DEPLOYMENT.md` (missing section)
- **Description:** Upgrade procedures exist but rollback procedures do not. No mention of `alembic downgrade`, Docker image rollback, or how to restore from backup.
- **Recommended fix:** Add a rollback section to the deployment guide.

**[LOW] Configurable timeouts and limits not centrally documented**
- **Description:** Various hardcoded values (circuit breaker thresholds, JWKS cache TTL, sandbox execution timeout, rate limit windows) are scattered across the codebase without a central reference.
- **Recommended fix:** Add a configuration reference table to PRODUCTION-DEPLOYMENT.md.

### What's Done Well
- Excellent security model documentation (11-layer model with table)
- Threat model with mitigations and residual risk assessment
- Failure mode analysis
- Architectural decision records (why Python not Rust, why shared sandbox, etc.)
- Clear "What NOT to Do" section in CLAUDE.md

---

## Final Assessment

### Overall Production Readiness Score: 7.0 / 10

| Area | Score | Notes |
|------|-------|-------|
| Sandbox Security | 7/10 | Strong but dual-implementation divergence and pip `setup.py` risk |
| Authentication | 8/10 | Excellent fail-closed design, python-jose is the main concern |
| Database | 8/10 | Clean, well-structured, needs key rotation path |
| Docker Infrastructure | 8/10 | Good segmentation, sandbox internet access needs tightening |
| API Security | 8/10 | Solid validation and headers, minor gaps |
| MCP Protocol | 8/10 | Clean implementation, management tools need authorization |
| Cloudflare Integration | 9/10 | Excellent multi-layer security |
| Error Handling | 8/10 | Proper circuit breaker and retry logic |
| Testing & CI/CD | 5/10 | Good tests but CI has major gaps |
| Dependencies | 4/10 | No pinning, no lock files, unmaintained jose |
| Observability | 5/10 | Health checks good, no metrics or alerting |
| Documentation | 7/10 | Strong security docs, needs operational runbooks |

### Top 5 Must-Fix Items Before Production

1. **[CRITICAL] Consolidate sandbox builtins** — Remove `super()` from routes.py `SAFE_BUILTINS`, unify with `PythonExecutor._create_safe_builtins()`. The dual implementation is the highest-risk divergence. (`sandbox/app/routes.py:565` + full consolidation)

2. **[CRITICAL] Add `--only-binary :all:` to pip install** — Prevent arbitrary code execution via malicious package `setup.py`. (`sandbox/app/package_installer.py:123-133`)

3. **[HIGH] Pin all dependencies to exact versions** — Replace `>=` with `==` in all requirements files. Generate and commit lock files. (`backend/requirements.txt`, `sandbox/requirements.txt`)

4. **[HIGH] Replace `python-jose` with `PyJWT`** — Unmaintained library with known CVEs handling JWT verification. (`backend/requirements.txt:15`)

5. **[HIGH] Enable mypy and add dependency scanning to CI** — Type checking is disabled, no vulnerability scanning for dependencies. (`.github/workflows/ci.yml:142`)

### Top 5 Should-Fix Items for First Month

1. **[HIGH] Add frontend and worker tests to CI** — 36 worker tests and 4 frontend tests exist but never run in CI.

2. **[HIGH] Add application metrics and basic alerting** — No Prometheus metrics, no failure notifications.

3. **[HIGH] Create incident response runbooks** — No documented recovery procedures for common failure scenarios.

4. **[MEDIUM] Restrict sandbox outbound network access** — Sandbox can reach the internet via `mcpbox-sandbox-external`. Add network-level restrictions.

5. **[MEDIUM] Consider AST-based code validation** — Regex patterns for dunder detection can potentially be bypassed with string manipulation. AST analysis is more robust.

### Architecture Strengths Worth Calling Out

1. **Fail-closed service token cache** — DB errors default to deny-all, not allow-all. This is the correct security posture and is rarely done right.

2. **Physical gateway isolation** — `mcp_only.py` creates a separate FastAPI app that physically cannot serve admin routes. Not just middleware-based, but structurally impossible.

3. **IP pinning for SSRF prevention** — DNS is resolved once, the IP is used for the request, and redirects are disabled. This is the gold standard for SSRF prevention.

4. **Workers VPC** — The tunnel has no public hostname. Only the Worker can reach it via VPC binding. This eliminates the entire class of "tunnel URL leaks" vulnerabilities.

5. **Defense-in-depth layering** — OAuth + service token + JWT + gateway isolation + sandbox restrictions. Each layer can fail and the system remains protected by the remaining layers.
