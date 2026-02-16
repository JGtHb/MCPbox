# Changelog

All notable changes to MCPbox will be documented in this file.

## [Unreleased] - Server Secrets, Execution Logging & OIDC Architecture

### Added
- **Server Secrets** - Per-server encrypted key-value secrets (`server_secrets` table, migration 0029). LLMs create placeholders via `mcpbox_create_server_secret`, admins set values in the UI. Secrets injected into tool execution as `secrets["KEY_NAME"]` dict. Values never flow through LLMs.
- **Tool Execution Logging** - Every tool invocation logged with args (secrets redacted), results (truncated to 10K chars), errors, stdout, duration, and success status (`tool_execution_logs` table, migration 0030). Viewable per-tool and per-server in the UI.
- **Server Recovery** - Background task (`server_recovery.py`) re-registers all "running" servers with sandbox on startup. Handles sandbox container restarts that lose in-memory tool registrations. Waits for sandbox health with retries.
- **Tool Change Notifications** - MCP `tools/list_changed` notifications broadcast to all connected MCP clients when tools are added, removed, approved, or servers start/stop (`tool_change_notifier.py`).
- **Tool Version History** - `mcpbox_list_tool_versions` and `mcpbox_rollback_tool` MCP management tools for viewing and restoring previous tool versions.
- **Pending Requests View** - `mcpbox_list_pending_requests` MCP management tool for LLMs to check their pending approval requests.
- **Tool Execution Logs View** - `mcpbox_get_tool_logs` MCP management tool for LLMs to view recent execution results.
- **Frontend Server Tabs** - Server detail page refactored into tabbed UI: Overview, Tools, Execution Logs, Secrets, Settings.
- **Secrets Manager UI** - Admin UI component for creating secrets (key-only), setting values, and deleting secrets per server.
- **Execution Logs UI** - Admin UI component for viewing tool execution history with collapsible detail view.

### Fixed
- Fix `test_code` always failing for async tools — sandbox now natively handles `async def main()` by awaiting on the current event loop instead of wrapping with `asyncio.run()` in a thread
- Fix `http` client not available in `test_code` — `httpx.AsyncClient` is now created on the same event loop as the tool execution, resolving event loop affinity issues
- Fix SSL handshake failure for SSRF IP-pinned HTTPS requests — SNI hostname now correctly set via `extensions={"sni_hostname": hostname}` when connecting to resolved IP addresses
- Fix intermittent "Session terminated" errors (~50% failure rate) — MCP gateway changed from `--workers 2` to `--workers 1` because MCP Streamable HTTP sessions are stateful (in-memory `_active_sessions` dict is per-process)
- Fix `mcp_only.py` not wiring up activity logger — MCP gateway process now persists activity logs

### Removed
- Remove credentials system — `credential.py` model, `credentials.py` API, `credential.py` service, `credential.py` schema, and all related tests
- Remove OAuth token management — `oauth.py` API and `oauth.py` service
- Remove token refresh service — `token_refresh.py` service and tests
- Remove `test_credentials.py`, `test_oauth.py`, `test_token_refresh.py`, `unit/test_credential_service.py` tests

### Changed
- MCP management tools expanded from 18 to 24 (added versioning, secrets, pending requests, execution logs)
- Sandbox `/execute` endpoint restructured — removed `ThreadPoolExecutor`, async main() detected after exec() and awaited directly
- `mcp_management.py` `test_code` handler no longer wraps async code with `asyncio.run()` — sandbox handles async natively

---

## [Previous] - Production Readiness Review

### Security
- Add `.dev.vars` and `.dev.vars.*` to `.gitignore` to prevent accidental commit of Cloudflare Worker secrets
- Remove internal review tracking files (REVIEW_PROGRESS.md, PRE-PRODUCTION-REVIEW*.md) from repository
- Replaced placeholder `security@example.com` in README.md with GitHub Security Advisory guidance

### Fixed
- Fix unawaited `CircuitBreaker.reset_all()` in health endpoint — the `/health/circuits/reset` endpoint was silently doing nothing
- Fix unawaited `CircuitBreaker.reset_all()` in test fixtures — circuit breaker state wasn't being reset between tests
- Fix unawaited `SandboxClient.reset_circuit()` in test — async function called without await
- Fix race condition in `CircuitBreaker.reset_all()` and `get_all_states()` — use `list()` snapshot to prevent `RuntimeError` during concurrent dict modification
- Fix WebSocket reconnect race condition in activity stream — clear previous timeout before setting new one to prevent duplicate reconnection attempts
- Fix untracked `setTimeout` calls in Settings page — add ref-based cleanup to prevent state updates after component unmount

### Removed
- Remove unused `fetchConfig()`, `useConfig()`, and `configKeys` from frontend API
- Remove unused `HealthDetailResponse`, `AppConfig`, and `ApiError` interfaces from frontend types
- Remove dead re-exports from `api/index.ts`
- Remove no-op `PythonExecutor.close()` method and empty `__init__` constructor
- Apply formatting fixes to 3 files with pre-existing `ruff format` issues
- Remove "legacy format" labeling from `mcpbox_test_code` tool description
- Remove "OpenAPI Server" legacy reference from frontend test mocks

### Tests
- Add 34 sandbox escape integration tests (`test_sandbox_escape.py`)
  - Dunder attribute blocking: `__class__`, `__mro__`, `__bases__`, `__subclasses__`, `__globals__`, `__code__`, `__builtins__`, `__import__`, `__loader__`, `__spec__`
  - Dangerous builtin removal: `type()`, `getattr()`, `setattr()`, `eval()`, `exec()`, `compile()`, `open()`
  - Discovery function blocking: `vars()`, `dir()`
  - Import whitelist enforcement and allowed module verification
- Add 22 code safety unit tests (`test_code_safety.py`)
  - Direct tests for `validate_code_safety()` regex pattern detection
  - Edge cases: safe code, multiline scanning, custom source names

### Documentation
- Update README security section to accurately reflect sandbox protections (application-level, not seccomp/read-only)
- Update README architecture diagram to show separate MCP Gateway (:8002)
- Update documentation links to include all available docs
- Add CHANGELOG
- Rewrite ARCHITECTURE.md — remove aspirational content (Envoy sidecar, network_logs, storage_logs, alerting, gVisor, seccomp, learning mode), fix MCP Gateway as separate service, update DB schema and API spec to match reality
- Rewrite FUTURE-EPICS.md — remove completed/outdated epics, document current state accurately
- Update COMPETITIVE-ANALYSIS.md — replace API Config references with code-first approach, update gap analysis to reflect full Python support
