# Feature Registry

Features are sorted by status, with broken/partial items at the top for visibility.

---

## Partial / Needs Attention

### Settings Model + Security Policy
- **Status**: Active — expanded during pre-release cleanup
- **Description**: Key-value settings storage with optional encryption. Now includes a Security Policy feature with 6 configurable settings: `remote_tool_editing`, `tool_approval_mode`, `network_access_policy`, `module_approval_mode`, `redact_secrets_in_output`, `log_retention_days`. Backend API: GET/PATCH `/api/settings/security-policy`. Frontend: Security Policy card on Settings page with dropdown controls and warnings for less-secure options.
- **Owner modules**: `backend/app/models/setting.py`, `backend/app/services/setting.py`, `backend/app/api/settings.py`, `frontend/src/pages/Settings.tsx`, `frontend/src/api/settings.ts`
- **Dependencies**: Crypto service (for encrypted values)
- **Security notes**: Supports encrypted values via AES-256-GCM. Defaults are the most restrictive options for all security policy settings

### ~~Helper Code (Shared Server Code)~~ — **REMOVED**
- **Status**: Removed during pre-release cleanup
- **Reason**: Never exposed via API or UI after server creation. Database field, executor loading, and all references removed. Migration 0035 drops the column.

---

## Complete

### MCP Tool Creation (LLM as Toolmaker)
- **Status**: Complete
- **Description**: External LLMs create Python tools via `mcpbox_create_tool` MCP management tool. Tools are Python code with `async def main()` entry points. LLMs can also test (`mcpbox_test_code`), validate (`mcpbox_validate_code`), update (`mcpbox_update_tool`), and delete (`mcpbox_delete_tool`) tools.
- **Owner modules**: `backend/app/services/mcp_management.py`, `backend/app/services/tool.py`, `backend/app/api/tools.py`
- **Dependencies**: Sandbox (code execution), Approval Workflow (publishing)
- **Test coverage**: `backend/tests/test_tools.py` (27 tests), `backend/tests/test_mcp_management.py` (16 tests)
- **Security notes**: Tools start as drafts; require admin approval. Code validated for safety before execution.

### Tool Approval Workflow
- **Status**: Complete
- **Description**: Human-in-the-loop approval for tool publishing, module whitelisting, and network access. Tools start as `draft`, move to `pending_review` on publish request, then admin approves/rejects in the `/approvals` UI. Module and network access requests follow same pattern.
- **Owner modules**: `backend/app/api/approvals.py`, `backend/app/services/approval.py`, `frontend/src/pages/Approvals.tsx`
- **Dependencies**: Admin auth (JWT), Tool service
- **Test coverage**: `backend/tests/test_approvals.py` (40+ tests) — well covered
- **Security notes**: LLMs cannot self-approve. Admin identity extracted from JWT for audit trail. TOCTOU issue (SEC-001, SEC-002) is now **fixed** — approval resets on code update and rollback.

### Sandboxed Code Execution
- **Status**: Complete
- **Description**: All tool code executes in a hardened shared sandbox. Restricted builtins (no `eval`, `exec`, `open`, `type`, `getattr`), dunder attribute blocking via regex, import whitelisting, resource limits (256MB memory, 60s CPU, 256 FDs), SSRF prevention with IP pinning.
- **Owner modules**: `sandbox/app/executor.py`, `sandbox/app/ssrf.py`, `sandbox/app/routes.py`
- **Dependencies**: None (standalone execution environment)
- **Test coverage**: `sandbox/tests/test_code_safety.py` (40+ tests), `sandbox/tests/test_sandbox_escape.py` (30+ tests), `sandbox/tests/test_security_hardening.py` (30+ tests), `sandbox/tests/test_safety_clients.py` (25+ tests) — excellent coverage
- **Security notes**: See [SECURITY.md](SECURITY.md#sec-003) for full module object injection concern, [SECURITY.md](SECURITY.md#sec-004) for missing FORBIDDEN_MODULES hardcoded list

### Server Management
- **Status**: Complete
- **Description**: CRUD operations for MCP servers. Each server groups related tools, has its own allowed modules/hosts, and can be started/stopped independently. Available via admin API and MCP management tools.
- **Owner modules**: `backend/app/api/servers.py`, `backend/app/services/server.py`, `backend/app/models/server.py`, `frontend/src/pages/Servers.tsx`, `frontend/src/pages/ServerDetail.tsx`
- **Dependencies**: Sandbox (server registration), Tool service
- **Test coverage**: `backend/tests/test_servers.py` (25+ tests)

### Server Secrets
- **Status**: Complete
- **Description**: Per-server encrypted key-value secret storage. LLMs create placeholders via `mcpbox_create_server_secret`, admins set values in UI. Secrets injected as immutable `MappingProxyType` dict (`secrets["KEY_NAME"]`) at tool execution time. Values never flow through LLMs.
- **Owner modules**: `backend/app/api/server_secrets.py`, `backend/app/services/server_secret.py`, `backend/app/models/server_secret.py`, `backend/app/services/crypto.py`
- **Dependencies**: Crypto service (AES-256-GCM), Sandbox (secret injection)
- **Test coverage**: `backend/tests/test_server_secrets.py` (8 tests) — CRUD, duplicate key, value leak prevention. Crypto tested in `backend/tests/test_crypto.py` (17+ tests).
- **Security notes**: AES-256-GCM with per-value random IV and AAD context binding (`server_secret:{server_id}:{key_name}`). Secrets redacted in execution logs and debug output.

### Tool Version History & Rollback
- **Status**: Complete
- **Description**: Every tool code change creates a version record. View previous versions via `mcpbox_list_tool_versions`, restore via `mcpbox_rollback_tool`. Viewable in admin UI.
- **Owner modules**: `backend/app/services/tool.py` (rollback logic), `backend/app/models/tool_version.py`
- **Dependencies**: Tool service
- **Test coverage**: Covered in `backend/tests/test_tools.py`
- **Security notes**: Rollback now resets `approval_status` to `pending_review` (SEC-002 fixed)

### Tool Execution Logging
- **Status**: Complete
- **Description**: Every tool invocation is logged with arguments (secrets redacted), results (truncated to 10KB), errors, stdout, duration, and success status. Viewable per-tool in UI and via `mcpbox_get_tool_logs`.
- **Owner modules**: `backend/app/services/execution_log.py`, `backend/app/api/execution_logs.py`, `backend/app/models/tool_execution_log.py`
- **Dependencies**: Activity logger
- **Test coverage**: `backend/tests/test_execution_logs.py` (7 tests), `backend/tests/test_execution_log_service.py` (14 tests) — API integration + service unit tests.

### Activity Logging & Live Stream
- **Status**: Complete
- **Description**: System-wide activity log tracking tool calls, server changes, approval actions, auth events. WebSocket live stream for real-time monitoring. Configurable retention (default 30 days).
- **Owner modules**: `backend/app/api/activity.py`, `backend/app/services/activity_logger.py`, `backend/app/models/activity_log.py`, `frontend/src/pages/Activity.tsx`
- **Dependencies**: PostgreSQL
- **Test coverage**: `backend/tests/test_activity_api.py` (10 tests), `backend/tests/test_activity_logger.py` (18 tests)

### MCP Gateway (Streamable HTTP)
- **Status**: Complete
- **Description**: MCP Streamable HTTP endpoint supporting stateful sessions via `Mcp-Session-Id`. Handles `initialize`, `tools/list`, `tools/call`, and `notifications/*`. Aggregates tools from all running servers. Broadcasts `tools/list_changed` when tools change.
- **Owner modules**: `backend/app/api/mcp_gateway.py`, `backend/app/mcp_only.py`, `backend/app/services/tool_change_notifier.py`
- **Dependencies**: Sandbox (tool execution), Service token cache (auth)
- **Test coverage**: `backend/tests/test_mcp_gateway.py` (39 tests) — good coverage
- **Security notes**: Method-level authorization in remote mode. Only `initialize` and `notifications/*` allowed without verified email. Gateway-level email allowlist enforcement (SEC-039): `verify_mcp_auth` checks forwarded email against stored access policy as defense-in-depth against Cloudflare Access misconfiguration.

### Admin Authentication (JWT)
- **Status**: Complete
- **Description**: Admin panel JWT authentication with Argon2id password hashing. Access tokens (15 min) and refresh tokens (7 days) with rotation. Password versioning for forced re-login on password change.
- **Owner modules**: `backend/app/api/auth.py`, `backend/app/core/security.py`, `backend/app/middleware/admin_auth.py`
- **Dependencies**: PostgreSQL (admin_users table)
- **Test coverage**: `backend/tests/test_auth.py` (15+ tests), `backend/tests/test_admin_auth.py`
- **Security notes**: JWT secret derived from encryption key if not set separately — startup warning emitted (SEC-011). JWT logout now server-side via in-memory JTI blacklist (SEC-009). See [DECISIONS.md](DECISIONS.md#adr-011).

### Cloudflare Remote Access
- **Status**: Complete
- **Description**: Optional remote access via Cloudflare Workers VPC. 6-step setup wizard configures tunnel, VPC service, Worker deployment, and OIDC (Access for SaaS). Worker handles OAuth 2.1 downstream and OIDC upstream. Admin-configurable CORS origins and OAuth redirect URIs stored in DB and synced to Worker KV for zero-downtime updates (SEC-038).
- **Owner modules**: `backend/app/api/cloudflare.py`, `backend/app/services/cloudflare.py`, `worker/src/index.ts`, `worker/src/access-handler.ts`, `cloudflared/`, `frontend/src/pages/CloudflareWizard.tsx`, `frontend/src/pages/Tunnel.tsx`
- **Dependencies**: Cloudflare API, PostgreSQL (config storage), Cloudflare KV (worker config)
- **Test coverage**: `backend/tests/test_cloudflare.py` (30+ tests), `worker/src/index.test.ts` (68 tests) — excellent coverage
- **Security notes**: 10 security layers documented in [AUTH-FLOW.md](AUTH-FLOW.md). Service token + OIDC + OAuth 2.1. CORS/redirect URI validation enforces HTTPS for non-localhost origins.

### Server Recovery
- **Status**: Complete
- **Description**: Servers marked as "running" are automatically re-registered with the sandbox on backend/gateway startup. Handles sandbox container restarts that lose in-memory tool registrations.
- **Owner modules**: `backend/app/services/server_recovery.py`
- **Dependencies**: Sandbox client
- **Test coverage**: Covered in backend tests

### Tool Change Notifications
- **Status**: Complete
- **Description**: MCP `tools/list_changed` notifications broadcast to all connected clients when tools are added, removed, approved, or servers start/stop.
- **Owner modules**: `backend/app/services/tool_change_notifier.py`, `backend/app/api/mcp_gateway.py`
- **Dependencies**: MCP gateway sessions
- **Test coverage**: `backend/tests/test_tool_change_notifier.py` (6 tests) — notify, fire-and-forget, error handling

### External MCP Source Passthrough
- **Status**: Complete
- **Description**: Connect to external MCP servers and proxy their tools through MCPbox. Supports MCP session pooling, health checks, and OAuth 2.1 authentication to external sources.
- **Owner modules**: `backend/app/api/external_mcp_sources.py`, `backend/app/models/external_mcp_source.py`, `sandbox/app/mcp_client.py`, `sandbox/app/mcp_session_pool.py`
- **Dependencies**: Sandbox (MCP client), External MCP servers
- **Test coverage**: `sandbox/tests/test_mcp_client.py` (20+ tests), `sandbox/tests/test_mcp_session_pool.py` (15+ tests)
- **Security notes**: MCP client now uses `allow_redirects=False` to prevent redirect-based SSRF (SEC-007 fixed)

### Export / Import
- **Status**: Complete
- **Description**: Export servers and tools as JSON for backup or migration. Import from JSON to restore.
- **Owner modules**: `backend/app/api/export_import.py`
- **Dependencies**: Server and Tool services
- **Test coverage**: `backend/tests/test_export_import.py` (30+ tests) — well covered

### Dashboard
- **Status**: Complete
- **Description**: Overview page showing server count, tool count, recent activity, and system status.
- **Owner modules**: `backend/app/api/dashboard.py`, `frontend/src/pages/Dashboard.tsx`
- **Dependencies**: All core services (aggregates statistics)
- **Test coverage**: `backend/tests/test_dashboard_api.py`, `frontend/src/**/__tests__/Dashboard.test.tsx` (10 tests)

### Frontend UI Standards & Accessibility
- **Status**: Complete
- **Description**: Comprehensive frontend UI/UX polish pass. Established documented standards in `docs/FRONTEND-STANDARDS.md` covering: Rosé Pine color system (no generic Tailwind colors), three-tier button sizing (xs/sm/md), visible focus indicators on all interactive elements (WCAG 2.1 AA), `ConfirmModal` for all destructive confirmations (replacing native `confirm()`), ARIA attributes (`aria-label` on icon-only buttons, `aria-expanded` on collapsibles, `role="dialog"` on modals), consistent border-radius (`rounded-lg`/`rounded-md`/`rounded-full`), standardized empty states with icons, and mobile-responsive toolbars.
- **Owner modules**: All `frontend/src/` components and pages, `docs/FRONTEND-STANDARDS.md`
- **Dependencies**: `components/ui/ConfirmModal.tsx` (focus trap, escape handling, ARIA)
- **Test coverage**: Existing frontend tests; standards enforced via documentation
- **Security notes**: None (UI-only changes)

### Rate Limiting
- **Status**: Complete
- **Description**: Per-IP rate limiting on API endpoints (100 req/min default). Login rate limiting (5/min). Service token failure rate limiting (10/min). Sandbox tool rate limiting (60/min).
- **Owner modules**: `backend/app/middleware/rate_limit.py`, `sandbox/app/routes.py`
- **Dependencies**: None (in-memory)
- **Test coverage**: `backend/tests/test_rate_limit.py`

### Module Whitelist Management
- **Status**: Complete
- **Description**: Admins manage which Python modules are available to tool code. LLMs can request modules via `mcpbox_request_module`. Includes PyPI info and OSV vulnerability checking.
- **Owner modules**: `backend/app/api/settings.py` (module settings), `sandbox/app/package_installer.py`, `sandbox/app/osv_client.py`, `sandbox/app/pypi_client.py`
- **Dependencies**: PyPI API, OSV API
- **Test coverage**: `backend/tests/test_module_settings_api.py`, `sandbox/tests/test_package_installer.py` (20+ tests)

### Log Retention
- **Status**: Complete
- **Description**: Automatic cleanup of activity logs older than configured retention period (default 30 days). Runs as background task.
- **Owner modules**: `backend/app/services/log_retention.py`
- **Dependencies**: PostgreSQL
- **Test coverage**: `backend/tests/test_log_retention.py`

### Health Checks
- **Status**: Complete
- **Description**: Health endpoints on all services. Backend `/health`, MCP Gateway `/health` (localhost-only to prevent service discovery through tunnel), Sandbox `/health`.
- **Owner modules**: `backend/app/api/health.py`, `backend/app/mcp_only.py`, `sandbox/app/main.py`
- **Dependencies**: None
- **Test coverage**: No dedicated tests for health endpoints — **gap** (low risk)

### Metrics (Prometheus)
- **Status**: Complete
- **Description**: Prometheus-compatible metrics collection for monitoring. Configurable via `enable_metrics` setting.
- **Owner modules**: `backend/app/services/metrics.py`
- **Dependencies**: None
- **Test coverage**: `backend/tests/test_metrics.py` (40+ tests) — excellent coverage

### Webhook Alerting
- **Status**: Complete
- **Description**: Optional Discord/Slack webhook alerts for system events. Configurable via `alert_webhook_url`.
- **Owner modules**: `backend/app/services/webhook_alerting.py`
- **Dependencies**: External webhook URL
- **Test coverage**: `backend/tests/test_webhook_alerting.py`

### Circuit Breaker
- **Status**: Complete
- **Description**: Circuit breaker pattern for sandbox communication. 5 failures triggers open state, 60s recovery timeout. Prevents cascade failures.
- **Owner modules**: `backend/app/services/sandbox_client.py`
- **Dependencies**: None
- **Test coverage**: `backend/tests/test_circuit_breaker_api.py`
