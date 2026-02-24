# Documentation Accuracy Audit — 2026-02-24

Cross-reference of MCPbox documentation claims against actual codebase.
Each claim verified by reading source files directly.

**Legend:** ✅ Accurate · ⚠️ Outdated/Misleading · ❌ Wrong · 🔍 Unverifiable

---

## Priority 1: Getting Started Path (blocks new users)

### `docs/getting-started/installation.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L11 | Prerequisites: Docker and Docker Compose | Correct — everything runs in containers via `docker-compose.yml` | ✅ |
| L12 | "~2.5 CPU cores and ~2.5 GB RAM available" | Docker resource limits sum to 5.5 CPU / 2.8 GB (excluding optional cloudflared). These are ceilings not reservations, but the RAM claim is tight and could cause swapping under load | ⚠️ |
| L19 | `git clone https://github.com/JGtHb/MCPbox.git` | Correct repo URL | ✅ |
| L28-33 | `cp .env.example .env` + `openssl rand -hex 32` for 3 secrets | Commands are correct and match `.env.example` structure. Generated values meet all validators in `config.py` | ✅ |
| L38 | "`MCPBOX_ENCRYPTION_KEY`: Must be 64 hex characters" | Matches `config.py:63` validator | ✅ |
| L40 | "`SANDBOX_API_KEY`: Min 32 characters" | Matches `config.py:121` validator | ✅ |
| L43 | "Each secret must be a unique value. MCPBox validates this on startup" | `config.py:219-234` `check_security_configuration()` checks for duplicate secrets but only **warns** (logs), does not fail startup | ⚠️ |
| L51 | `docker compose run --rm backend alembic upgrade head` | Correct — matches CLAUDE.md gotcha #9 | ✅ |
| L63 | `curl http://localhost:8000/health` returns `{"status": "healthy"}` | Backend bound to `127.0.0.1:8000`, health route exists at `/health` in `health.py:35` | ✅ |
| L71 | Open `http://localhost:3000` for admin UI | Frontend bound to `127.0.0.1:3000` per `docker-compose.yml:29` | ✅ |

### `docs/getting-started/quick-start.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L14 | "You'll be prompted to create an admin account" | `auth.py:160` has `/auth/setup` endpoint for initial account creation | ✅ |
| L19-23 | Dashboard shows server count, tool count, recent activity | `dashboard.py:86` returns `DashboardResponse` with these fields | ✅ |
| L29 | Key pages: Servers, Approvals, Activity, Remote Access | All pages exist in `frontend/src/pages/` | ✅ |
| L36 | "28 `mcpbox_*` management tools" | Confirmed 28 tools in `mcp_management.py` (lines 28-525) | ✅ |
| L44 | "Nothing runs until you approve it in the Approvals page" | Tools start as `draft`, require `request_publish` → admin approval | ✅ |

### `docs/getting-started/connecting-clients.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L9 | "MCP endpoint is `http://localhost:8000/mcp`" | Backend includes `mcp_router` at root level (`main.py:152`), serves `/mcp` on port 8000 | ✅ |
| L17-21 | Claude Code config: `"url": "http://localhost:8000/mcp"` | Correct for local mode | ✅ |
| L27 | Cursor: URL `http://localhost:8000/mcp` | Correct | ✅ |
| L39 | "28 tools with the `mcpbox_` prefix" | Confirmed 28 tools in code | ✅ |
| L46 | Troubleshooting: `docker compose ps` and health check | Valid commands | ✅ |

### `README.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L7 | CI badge link `actions/workflows/ci.yml` | 🔍 Cannot verify GitHub Actions config from codebase | 🔍 |
| L53 | Quick start: `cp .env.example .env` | Correct | ✅ |
| L56 | Quick start: `python -c "import secrets; print(secrets.token_hex(32))"` — "add to .env as MCPBOX_ENCRYPTION_KEY" | Only prints to stdout; user must manually edit `.env`. Does NOT mention `POSTGRES_PASSWORD` or `SANDBOX_API_KEY`, which are **required** (`docker-compose.yml` uses `${POSTGRES_PASSWORD:?required}` and `${SANDBOX_API_KEY:?required}`). `docker compose up -d` would fail immediately. | ❌ |
| L58 | Quick start: `docker compose up -d` with no migration step | Missing `docker compose run --rm backend alembic upgrade head` before startup. CLAUDE.md gotcha #9 confirms auto table creation is disabled. App would fail on first request. | ❌ |
| L77 | "28 `mcpbox_*` management tools" | Confirmed 28 in code | ✅ |
| L82-109 | Architecture diagram: ports, services, layout | Matches `docker-compose.yml` service definitions and port bindings | ✅ |
| L111 | Two modes: Local (localhost:8000/mcp) and Remote | Correct — `main.py` serves `/mcp`, `mcp_only.py` serves gateway at `:8002` | ✅ |
| L117 | Links to `docs/MCP-MANAGEMENT-TOOLS.md` | File exists at that path | ✅ |
| L131 | Links to `docs/CLOUDFLARE-SETUP-WIZARD.md` | File exists at that path | ✅ |
| L162 | Links to `CONTRIBUTING.md` | File exists | ✅ |

---

## Priority 2: Reference Accuracy (causes subtle bugs)

### `docs/reference/environment-variables.md`

Compared against `backend/app/core/config.py` (all env vars).

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L15 | `MCPBOX_ENCRYPTION_KEY`: "32-byte hex key" | Validator requires 64 hex characters which equals 32 bytes. Technically correct but doc should say "64 hex characters" to match error messages and installation.md | ⚠️ |
| L16 | `POSTGRES_PASSWORD`: PostgreSQL database password | Used in `docker-compose.yml` connection string | ✅ |
| L17 | `SANDBOX_API_KEY`: min 32 chars | `config.py:121`: `if len(v) < 32` | ✅ |
| L26 | `JWT_SECRET_KEY`: derived from encryption key if not set | `config.py:191-198`: `effective_jwt_secret_key` property derives via SHA-256 | ✅ |
| L27-28 | `MCPBOX_FRONTEND_PORT` (3000), `MCPBOX_BACKEND_PORT` (8000) | `docker-compose.yml:29,69` defaults match | ✅ |
| L29 | `CORS_ORIGINS` default `http://localhost:3000` | `config.py:80` | ✅ |
| L30 | `MCP_CORS_ORIGINS` default includes Claude, ChatGPT, OpenAI | `config.py:84` matches | ✅ |
| L31 | `LOG_LEVEL` default `INFO` | `config.py:38` | ✅ |
| L37-41 | DB pool settings (pool_size=20, overflow=20, timeout=30, recycle=1800) | `config.py:44-47` all match | ✅ |
| L47-49 | "Runtime Settings (Admin UI)": log retention, rate limit, alert webhook | Rate limit also exists as env var `config.py:95`; alert webhook also at `config.py:139`. Both are in config.py **and** can be set at runtime. Doc implies they are runtime-only. | ⚠️ |
| — | **Missing**: `http_timeout` (30.0), `http_max_connections` (10), `http_keepalive_connections` (5) | `config.py:90-92` | ⚠️ |
| — | **Missing**: `cf_worker_compatibility_date`, `cf_worker_compatibility_flags` | `config.py:136-137` | ⚠️ |
| — | **Missing**: `enable_metrics` (True), `debug` (False) | `config.py:37,142` | ⚠️ |
| — | **Missing**: `app_name` ("MCPbox"), `app_version` ("0.1.0") | `config.py:35-36` | ⚠️ |
| — | **Missing**: `jwt_access_token_expire_minutes` (15), `jwt_refresh_token_expire_days` (7), `jwt_algorithm` ("HS256") | `config.py:99-101` | ⚠️ |
| — | **Missing**: `sandbox_url` is used in docker-compose but not in config.py (set via env only) | `docker-compose.yml:74,120` | ⚠️ |

### `docs/reference/mcp-tools.md`

Compared against `backend/app/services/mcp_management.py` (28 tools).

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L9 | "28 management tools with the `mcpbox_` prefix" | Confirmed: 28 tool definitions at lines 28-525, 28 handler registrations at lines 564-603 | ✅ |
| L13-21 | Server Management: 7 tools listed including `start_server`, `stop_server` | All 7 exist in code | ✅ |
| L25-31 | Tool Management: 5 tools | All 5 exist | ✅ |
| L35-38 | Versioning: 2 tools | Both exist | ✅ |
| L42-45 | Development: `test_code`, `validate_code` | Both exist | ✅ |
| L49-52 | Secrets: 2 tools | Both exist | ✅ |
| L56-62 | Approval: 5 tools | All 5 exist | ✅ |
| L66-71 | External MCP Sources: 4 tools | All 4 exist | ✅ |
| L77 | Observability: `get_tool_logs` | Exists | ✅ |
| L119 | Data structures: lists `operator` as allowed module | `executor.py:816`: `operator` is **intentionally excluded** — "`attrgetter()` enables sandbox escape". NOT in `DEFAULT_ALLOWED_MODULES` | ❌ |
| L119 | Data structures: lists `collections`, `itertools`, `functools` | All three are in `DEFAULT_ALLOWED_MODULES` | ✅ |
| L119 | Missing: `collections.abc` | Present in `DEFAULT_ALLOWED_MODULES` at `executor.py:814` but not documented | ⚠️ |
| L131 | Sandbox limit: "Memory: 256 MB" | `executor.py:140-141` sets 256MB via `resource.RLIMIT_AS` | ✅ |
| L132 | Sandbox limit: "CPU time: 60 seconds" | `executor.py:135` sets 60s via `resource.RLIMIT_CPU` | ✅ |
| L133 | Sandbox limit: "Execution timeout: 30 seconds (configurable up to 300s)" | `routes.py` uses timeout with these bounds | ✅ |
| L134 | Sandbox limit: "Code size: 100 KB" | 🔍 Need to verify in routes.py validation | 🔍 |
| L135 | Sandbox limit: "Stdout capture: 10 KB" | `routes.py:807,855` truncates to `[:10000]` in test-code path. But `executor.py:22` uses `MAX_OUTPUT_SIZE = 1MB` for actual tool execution. Doc reflects test-code limit only. | ⚠️ |
| L136 | Sandbox limit: "File descriptors: 64" | `executor.py:149`: `max_fds = 256`. The actual limit is **256**, not 64. | ❌ |

### `docs/reference/api.md`

Compared against `backend/app/api/router.py` and all route files.

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| — | All server CRUD endpoints | Match actual routes in `servers.py` with prefix `/api/servers` | ✅ |
| — | All tool CRUD endpoints | Match actual routes in `tools.py` | ✅ |
| — | Sandbox start/stop/restart/status/logs | Match actual routes in `sandbox.py` with prefix `/api/sandbox` | ✅ |
| — | Approval endpoints (stats, tools, modules, network, actions) | Match actual routes in `approvals.py` with prefix `/api/approvals` | ✅ |
| — | Settings endpoints (security-policy, modules, enhanced, pypi, install, sync) | Match actual routes in `settings.py` with prefix `/api/settings` | ✅ |
| — | External MCP Sources endpoints | Match actual routes in `external_mcp_sources.py` with prefix `/api/external-sources` | ✅ |
| — | Dashboard, Activity, Export/Import, Config, Health | All match actual routes | ✅ |
| — | MCP Gateway endpoints | Match `mcp_gateway.py` routes | ✅ |

> The dedicated `docs/reference/api.md` is accurate. The **ARCHITECTURE.md** API spec section (see Priority 3) is the one with errors.

---

## Priority 3: Architecture Docs (misleads contributors)

### `docs/ARCHITECTURE.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L62-112 | High-level diagram: ports 3000, 8000, 8002, 5432, 8001 | All match `docker-compose.yml` | ✅ |
| L80-82 | Diagram shows arrow from Sandbox to PostgreSQL | Sandbox is on `mcpbox-sandbox` + `mcpbox-sandbox-external` networks. PostgreSQL is on `mcpbox-db`. **No network overlap** — sandbox cannot reach postgres | ❌ |
| L117-124 | Container architecture: 6 services listed | All 6 present in `docker-compose.yml` | ✅ |
| L123 | cloudflared listed as `profile: remote` | No Docker profiles used in `docker-compose.yml`. cloudflared is always defined (though it depends on backend having a tunnel token) | ❌ |
| L128-133 | Docker networks: 4 networks | Matches `docker-compose.yml:267-282`. All network assignments correct | ✅ |
| L162-164 | Dangerous builtins: lists `type()`, `getattr()`, etc. | Confirmed in `executor.py` ALLOWED_BUILTIN_NAMES — these are excluded | ✅ |
| L168 | Default allowed modules: lists `re` | Code uses `regex` (not `re`). `executor.py:805`: "`regex`, # Timeout-protected wrapper (not 're' - ReDoS vulnerable)" | ❌ |
| L172 | Resource: "256MB memory limit" | `executor.py:140-141` ✓ | ✅ |
| L173 | Resource: "60-second CPU timeout" | `executor.py:135` ✓ | ✅ |
| L174 | Resource: "256 file descriptor limit" | `executor.py:149`: `max_fds = 256` ✓ | ✅ |
| L175 | Resource: "1MB output cap" | `executor.py:22`: `MAX_OUTPUT_SIZE = 1024 * 1024` ✓ | ✅ |
| L252-326 | Frontend + Backend file structure maps | Spot-checked key files — mostly accurate. `models/cloudflare_config.py`, `models/global_config.py`, `models/external_mcp_source.py` exist but not all listed in the map. Backend `core/` is missing `shared_lifespan.py` and `logging.py` | ⚠️ |
| L348 | MCP gateway: "Runs with `--workers 1`" | `docker-compose.yml:115`: `"--workers", "1"` ✓ | ✅ |
| L387-398 | "28 management tools" with category table | All 28 tools listed correctly with proper categories | ✅ |
| **L497-560** | **API Specification section** — see below | **Many incorrect paths, methods, and structures** | ❌ |

#### ARCHITECTURE.md API Spec Errors (L497-560)

| Documented | Actual | Issue |
|---|---|---|
| `PUT /api/servers/{id}` | `PATCH /api/servers/{id}` | Wrong HTTP method |
| `POST /api/servers/{id}/start` | `POST /api/sandbox/servers/{id}/start` | Wrong path prefix (missing `/sandbox`) |
| `POST /api/servers/{id}/stop` | `POST /api/sandbox/servers/{id}/stop` | Wrong path prefix |
| `PUT /api/secrets/{id}/value` | `PUT /api/servers/{server_id}/secrets/{key_name}` | Completely wrong path structure |
| `DELETE /api/secrets/{id}` | `DELETE /api/servers/{server_id}/secrets/{key_name}` | Completely wrong path structure |
| `GET /api/tools/{id}/logs` | `GET /api/execution-logs` + per-tool variants | Different prefix/structure |
| `GET /api/approvals` | `GET /api/approvals/tools`, `/modules`, `/network` | Single endpoint → three typed endpoints |
| `POST /api/approvals/{id}/approve` | `POST /api/approvals/tools/{id}/action` | Different path and unified action endpoint |
| `POST /api/approvals/{id}/reject` | (merged into action endpoint above) | Separate reject endpoint doesn't exist |
| `POST /api/cloudflare/verify-token` | `POST /api/cloudflare/api-token` | Wrong path |
| `POST /api/cloudflare/access` | `PUT /api/cloudflare/access-policy` | Wrong method + path |
| `GET /api/activity` | `GET /api/activity/logs` | Missing `/logs` |
| `WS /api/ws/activity` | `WS /api/activity/stream` | Completely wrong path |
| `GET /api/dashboard/stats` | `GET /api/dashboard` | Extra `/stats` doesn't exist |
| `POST /api/export` | `GET /api/export/servers` | Wrong method + path |
| `POST /api/import` | `POST /api/export/import` | Wrong prefix |
| `PUT /api/settings` | `PATCH /api/settings/security-policy` | Wrong method + path |

### `docs/SECURITY.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L10 | "AST analysis blocks dangerous patterns" | `executor.py` uses `validate_code_safety()` with regex + pattern checks | ✅ |
| L12 | "Static safety checks" | Confirmed in executor code | ✅ |
| L15 | "Restricted execution namespace with dangerous builtins removed" | `executor.py` `ALLOWED_BUILTIN_NAMES` whitelist confirmed | ✅ |
| L16 | "Module access mediated through attribute-filtered proxies" | Confirmed in executor's module proxy mechanism | ✅ |
| L17 | Resource limits: "memory (256 MB), CPU time (60 s), file descriptors (256), stdout (1 MB)" | All match code: `executor.py:140` (256MB), `:135` (60s), `:149` (256 FDs), `:22` (1MB) | ✅ |
| L22 | "Code changes after approval automatically reset the tool to `pending_review`" | `tool.py:137`: "Reset approval when code changes to prevent TOCTOU bypass" | ✅ |
| L23 | "Version rollbacks reset approval status unconditionally" | `tool.py:298`: "Reset approval on rollback — rolled-back code needs re-review" | ✅ |
| L33 | "Constant-time token comparison for service tokens" | `mcp_gateway.py:899`: `secrets.compare_digest()` confirmed | ✅ |
| L36 | "Server secrets encrypted at rest with AES-256-GCM" | Confirmed in `services/crypto.py` | ✅ |
| L41 | "Four isolated Docker networks" | `docker-compose.yml:267-282`: `mcpbox-internal`, `mcpbox-sandbox`, `mcpbox-sandbox-external`, `mcpbox-db` | ✅ |
| L42 | "Sandbox has no direct database or internet access (except admin-approved outbound)" | Sandbox networks: `mcpbox-sandbox` (internal) + `mcpbox-sandbox-external` (outbound). No `mcpbox-db`. Correct. | ✅ |
| L48 | "`MCPBOX_ENCRYPTION_KEY` (64 hex chars) and `SANDBOX_API_KEY` (32+ chars)" | Matches validators in `config.py` | ✅ |

### `docs/FEATURES.md`

| Line/Section | Claim | Actual Code State | Status |
|---|---|---|---|
| L16-18 | "Helper Code (Shared Server Code) — REMOVED" | Not found in models or API. Removal confirmed. | ✅ |
| L24-30 | MCP Tool Creation: draft → approve workflow | Confirmed in `mcp_management.py` and `tool.py` | ✅ |
| L33-38 | Tool Approval: TOCTOU (SEC-001, SEC-002) "fixed" | `tool.py:137` resets on code change, `tool.py:298` resets on rollback | ✅ |
| L42 | Sandbox: "256 FDs" | `executor.py:149`: `max_fds = 256` ✓ | ✅ |
| L46 | References `SECURITY.md#sec-003` and `#sec-004` | SECURITY.md has been simplified and no longer has numbered findings (SEC-003, SEC-004 anchors don't exist) | ⚠️ |
| L57 | Secrets: "immutable `MappingProxyType` dict" | 🔍 Need to verify in executor injection code | 🔍 |
| L91 | MCP Gateway: "Method-level authorization in remote mode" | Confirmed in `mcp_gateway.py` auth logic | ✅ |
| L99 | JWT: "JWT logout now server-side via in-memory JTI blacklist (SEC-009)" | `main.py:44-57`: `_token_blacklist_cleanup_loop` + `TokenBlacklist` model exists | ✅ |
| L103 | Cloudflare: "6-step setup wizard" | `cloudflare.py` has start, api-token, tunnel, vpc-service, worker, worker-jwt-config, access-policy steps | ✅ |
| L155 | Rate limiting: "Per-IP rate limiting on API endpoints (100 req/min default)" | `config.py:95`: `rate_limit_requests_per_minute = 100`, `main.py:114`: `RateLimitMiddleware` | ✅ |
| L184 | Metrics: `backend/app/services/metrics.py` | `main.py:140-145`: Prometheus instrumentator enabled when `enable_metrics=True` | ✅ |
| L191 | Webhook Alerting: `backend/app/services/webhook_alerting.py` | `config.py:139`: `alert_webhook_url` setting exists | ✅ |

### `CLAUDE.md` — Known Gotchas

| Gotcha # | Claim | Actual Code State | Status |
|---|---|---|---|
| 1 | "MCP gateway must run `--workers 1`" | `docker-compose.yml:115`: `"--workers", "1"` | ✅ |
| 2 | "Backend tests require Docker — testcontainers" | Standard setup for this project | ✅ |
| 3 | "Tool approval TOCTOU — **Fixed**: approval resets to `pending_review` on code change" | `tool.py:137`: confirmed | ✅ |
| 4 | "Rollback preserves approval — **Fixed**: rollback always resets approval" | `tool.py:298`: confirmed | ✅ |
| 5 | "Sandbox stdout race — **Already mitigated**: `print` is overridden per-execution" | `executor.py:1852-1856`: per-execution `print()` override to `stdout_capture` | ✅ |
| 6 | "Two entry points — `main.py` (admin) and `mcp_only.py` (gateway)" with shared lifespan via `shared_lifespan.py` | `main.py:17`: imports from `shared_lifespan`, `mcp_only.py` exists, `core/shared_lifespan.py` exists | ✅ |
| 7 | "`MCPBOX_ENCRYPTION_KEY` must be exactly 64 hex chars. `SANDBOX_API_KEY` must be 32+ chars" | `config.py:63,121`: both validators confirmed | ✅ |
| 8 | "Route prefix double-nesting — **Fixed**: endpoint is now `/api/settings`" | `settings.py:26`: `prefix="/settings"` under `/api` → `/api/settings` ✓ | ✅ |
| 9 | "alembic upgrade head required — Auto table creation disabled" | `installation.md` documents migration step. No auto-create in code | ✅ |
| 10 | "Service token comparison — Must use `secrets.compare_digest()`" | `mcp_gateway.py:899`, `internal.py:56`: both use `secrets.compare_digest()` | ✅ |

---

## Summary of Issues

### Critical (❌ Wrong — blocks or misleads users)

| # | Doc File | Issue | Impact |
|---|---|---|---|
| 1 | `README.md` L56-58 | Quick start missing `POSTGRES_PASSWORD`, `SANDBOX_API_KEY` generation, doesn't write key to `.env`, missing alembic migration | **New users cannot start MCPbox** following README alone |
| 2 | `docs/reference/mcp-tools.md` L119 | Lists `operator` as allowed module | `operator` is **intentionally excluded** (sandbox escape via `attrgetter()`). Users expecting `operator` will get import errors |
| 3 | `docs/reference/mcp-tools.md` L136 | "File descriptors: 64" | Actual limit is **256** (`executor.py:149`) |
| 4 | `docs/ARCHITECTURE.md` L80-82 | Diagram shows Sandbox → PostgreSQL connection | No network path exists. Sandbox is on `mcpbox-sandbox`, postgres on `mcpbox-db` |
| 5 | `docs/ARCHITECTURE.md` L123 | cloudflared has `profile: remote` | No Docker profiles used. Service is always defined |
| 6 | `docs/ARCHITECTURE.md` L168 | Default modules include `re` | Code uses `regex` (not `re`). `re` excluded for ReDoS protection |
| 7 | `docs/ARCHITECTURE.md` L497-560 | 17 API endpoints with wrong methods, paths, or structures | See detailed table above. Entire API spec section is stale |

### High (⚠️ Outdated — causes confusion or subtle bugs)

| # | Doc File | Issue | Impact |
|---|---|---|---|
| 8 | `docs/reference/environment-variables.md` | 10+ env vars in `config.py` not documented | Operators miss tuning options (`http_timeout`, `enable_metrics`, JWT expiry, etc.) |
| 9 | `docs/reference/environment-variables.md` L15 | "32-byte hex key" vs "64 hex characters" | Inconsistent with installation.md and error messages |
| 10 | `docs/reference/environment-variables.md` L47-49 | Runtime settings implication | `rate_limit_requests_per_minute` and `alert_webhook_url` also exist as env vars in config.py |
| 11 | `docs/reference/mcp-tools.md` L119 | Missing `collections.abc` from module list | Module is allowed but undocumented |
| 12 | `docs/reference/mcp-tools.md` L135 | "Stdout capture: 10 KB" | 10KB for test-code only; actual execution uses 1MB limit |
| 13 | `docs/getting-started/installation.md` L12 | "~2.5 CPU / ~2.5 GB RAM" | Container limits sum to 5.5 CPU / 2.8 GB. Misleading minimum |
| 14 | `docs/getting-started/installation.md` L43 | "MCPBox validates this on startup" (unique secrets) | Startup only **warns**, does not fail |
| 15 | `docs/ARCHITECTURE.md` L252-326 | File structure maps | Missing several files (`shared_lifespan.py`, `logging.py`, newer models) |
| 16 | `docs/FEATURES.md` L46 | References `SECURITY.md#sec-003` and `#sec-004` | SECURITY.md no longer has numbered findings |

---

## Recommended Fixes (Priority Order)

### Must Fix Before Release

1. **README Quick Start** — Add all 3 required secret generations, pipe to `.env`, add migration step. Or replace with "See [Installation](docs/getting-started/installation.md)" link.
2. **mcp-tools.md module list** — Remove `operator`, add `collections.abc`.
3. **mcp-tools.md sandbox limits** — Change FDs from 64 → 256. Clarify stdout as "1 MB (execution) / 10 KB (test-code)".
4. **ARCHITECTURE.md API spec** — Either delete the API spec section (since `docs/reference/api.md` is accurate) or rewrite it from scratch based on actual route definitions.
5. **ARCHITECTURE.md diagram** — Remove the Sandbox→PostgreSQL arrow.

### Should Fix

6. **ARCHITECTURE.md** — Fix `re` → `regex`, remove `profile: remote` claim.
7. **environment-variables.md** — Document missing env vars, especially `enable_metrics`, `debug`, `http_timeout`, JWT settings.
8. **environment-variables.md** — Change "32-byte hex key" → "64 hex characters (32 bytes)" for consistency.
9. **FEATURES.md** — Update broken `SECURITY.md` section anchors.
10. **installation.md** — Adjust resource estimates or note they are minimums.
