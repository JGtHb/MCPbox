# Architecture Decision Records

## ADR-001: MCP-First Architecture (No Visual Builders)
- **Date**: Inferred (Epic 2/3 removal visible in CHANGELOG)
- **Status**: Active
- **Context**: The project needed a way for LLMs to create tools. Options included visual workflow builders (like n8n/Node-RED), API configuration (HTTP method + URL + headers), or code-first (Python with `async def main()`). An earlier "API Config" mode existed but was removed.
- **Decision**: All tools use Python code only. Tool creation happens via `mcpbox_*` MCP management tools invoked by external LLMs. No embedded LLM, no visual builders, no API spec import.
- **Rationale**: Python can do everything visual builders and API config can, plus more. Code diffs cleanly (vs. JSON workflow blobs). LLMs excel at writing Python. One execution model to secure and maintain. No API key management needed — users leverage existing Claude access.
- **Consequences**: Higher barrier for non-developer users. Full power of Python available to tool authors. Simpler codebase (one execution path). Requires robust sandbox security.
- **Affected modules**: `backend/app/services/mcp_management.py`, `sandbox/app/executor.py`, `sandbox/app/routes.py`

## ADR-002: Separate MCP Gateway Service
- **Date**: Inferred (visible in docker-compose.yml architecture)
- **Status**: Active
- **Context**: The MCP endpoint needs to be tunnel-accessible for remote Claude Web access. But admin API endpoints (`/api/*`) must remain local-only.
- **Decision**: Run a separate Docker service (`mcp-gateway`) using `app.mcp_only:app` that only exposes `/mcp` and `/health`. Shares backend codebase but with different entry point.
- **Rationale**: Physical separation — the tunnel-exposed service cannot serve admin endpoints even if tunnel or Worker is compromised. Defense in depth.
- **Consequences**: Two FastAPI processes sharing the same codebase. Duplicate middleware setup in `main.py` and `mcp_only.py`. Must keep both entry points synchronized. Resource overhead of second process (mitigated: 512MB limit).
- **Affected modules**: `backend/app/main.py`, `backend/app/mcp_only.py`, `docker-compose.yml`

## ADR-003: Shared Sandbox (Not Per-Server Containers)
- **Date**: Inferred (foundational architecture decision)
- **Status**: Active
- **Context**: Tool code from different servers needs isolated execution. Options: per-server Docker containers (stronger isolation, higher resource usage, requires docker.sock) or shared sandbox with application-level restrictions.
- **Decision**: Single shared sandbox container with restricted builtins, import whitelisting, and resource limits. No per-server containers.
- **Rationale**: Lower resource usage for homelab target (no need to run N containers). No docker.sock exposure (significant security risk). Simpler architecture. Application-level isolation is sufficient given the approval workflow and module whitelisting.
- **Consequences**: Tools share process space — output leakage possible (see [SECURITY.md](SECURITY.md#sec-006)). Module whitelisting must be robust. No kernel-level isolation between tools. All sandbox security is application-level.
- **Affected modules**: `sandbox/app/executor.py`, `sandbox/app/routes.py`, `sandbox/app/registry.py`

## ADR-004: Hybrid Architecture (Local-First + Optional Remote)
- **Date**: Inferred (Epic 4: Cloudflare Tunnel)
- **Status**: Active
- **Context**: Users need both local access (Claude Desktop) and remote access (Claude Web). Public tunnel exposure creates security risk.
- **Decision**: Admin panel bound to `127.0.0.1` (local-only). MCP gateway optionally exposed via Cloudflare Workers VPC (no public hostname). Worker provides OAuth 2.1 + OIDC authentication layer.
- **Rationale**: Workers VPC eliminates public attack surface — tunnel has no URL, only Worker can access it. Local mode requires zero configuration. Remote mode adds 10 security layers.
- **Consequences**: Complex authentication stack (OAuth 2.1 + OIDC + service token). Cloudflare dependency for remote access. Setup wizard needed (6 steps). Two auth modes to maintain and test.
- **Affected modules**: `worker/src/index.ts`, `worker/src/access-handler.ts`, `backend/app/api/cloudflare.py`, `cloudflared/`

## ADR-005: Human-in-the-Loop Approval Workflow
- **Date**: Inferred (Epic 7: Tool Approval Workflow)
- **Status**: Active
- **Context**: LLMs creating tools is powerful but dangerous. Unrestricted tool creation could lead to malicious or buggy tools being immediately callable.
- **Decision**: All tools start as `draft`. LLM must explicitly request publish (`mcpbox_request_publish`). Admin reviews and approves/rejects in UI. Same pattern for module whitelisting and network access requests.
- **Rationale**: LLMs should not self-approve — clear privilege separation. Admin can review code, module requests, and network access before any tool becomes active. Aligns with "human-in-the-loop" design principle.
- **Consequences**: Slower tool iteration (requires admin action). Multi-layer filtering needed (registration gate, listing gate, recovery gate). TOCTOU risk if code changes after approval (see [SECURITY.md](SECURITY.md#sec-001)).
- **Affected modules**: `backend/app/api/approvals.py`, `backend/app/services/approval.py`, `backend/app/services/tool.py`, `frontend/src/pages/Approvals.tsx`

## ADR-006: AES-256-GCM for Secret Encryption
- **Date**: Inferred (migration 0029: server secrets)
- **Status**: Active
- **Context**: Server secrets (API keys, tokens) need encryption at rest. Options: database-level encryption, application-level encryption, or external secret manager.
- **Decision**: Application-level AES-256-GCM encryption via Python `cryptography` library. Per-value random 12-byte IV. 64-character hex encryption key from environment variable. Dual-key support for rotation.
- **Rationale**: State-of-the-art authenticated encryption. No external dependencies (no Vault/KMS). Per-value IV prevents ciphertext analysis. Key rotation support for operational needs.
- **Consequences**: Encryption key is single point of failure. Key must be backed up securely. Missing AAD means ciphertext swapping between columns is theoretically possible (see [SECURITY.md](SECURITY.md#sec-005)). All encryption/decryption happens in application layer.
- **Affected modules**: `backend/app/services/crypto.py`, `backend/app/models/server_secret.py`

## ADR-007: Python Backend (Not Rust/Go Gateway)
- **Date**: Inferred (foundational decision)
- **Status**: Active
- **Context**: The backend needs to serve REST API, proxy MCP protocol, manage database, and coordinate sandbox execution.
- **Decision**: Python 3.11+ with FastAPI, SQLAlchemy async ORM, and httpx for HTTP client.
- **Rationale**: Faster iteration than compiled languages. Native async support via asyncio. Rich ecosystem for web frameworks, ORM, crypto libraries. Sandbox also Python — shared language reduces complexity. FastAPI provides automatic OpenAPI documentation.
- **Consequences**: Higher memory usage than Rust/Go. GIL limits CPU-bound parallelism (mitigated: all operations are I/O-bound). Type safety relies on mypy enforcement rather than compiler.
- **Affected modules**: Entire backend and sandbox

## ADR-008: PostgreSQL with SQLAlchemy Async ORM
- **Date**: Inferred (foundational decision)
- **Status**: Active
- **Context**: The system needs persistent storage for servers, tools, secrets, activity logs, and configuration.
- **Decision**: PostgreSQL 16 with SQLAlchemy async ORM via `asyncpg` driver. Alembic for migrations. Connection pooling (20 base, 20 overflow).
- **Rationale**: PostgreSQL supports ARRAY types (used for `allowed_modules`, `allowed_hosts`), full-text search, and JSON. Alembic provides reliable schema migrations. Async ORM matches the async FastAPI architecture.
- **Consequences**: Requires Docker for tests (testcontainers). ARRAY types make SQLite testing impossible. 33+ migrations to manage. Connection pool sizing matters for homelab resource constraints.
- **Affected modules**: `backend/app/core/database.py`, `backend/app/models/`, `alembic/`

## ADR-009: Argon2id for Password Hashing
- **Date**: Inferred (migration 0019: admin users)
- **Status**: Active
- **Context**: Admin panel needs password authentication. Choice of hashing algorithm affects security and performance.
- **Decision**: Argon2id via `argon2-cffi` library. Password versioning stored in JWT to force re-login on password change. Dummy hash verification on unknown users to prevent timing attacks.
- **Rationale**: Argon2id is the current recommended password hashing algorithm (won Password Hashing Competition). Memory-hard, resistant to GPU attacks. Timing attack prevention built in.
- **Consequences**: Higher CPU/memory cost per login attempt (by design). Depends on `argon2-cffi` library quality.
- **Affected modules**: `backend/app/core/security.py`, `backend/app/api/auth.py`

## ADR-010: Cloudflare Workers + Access for SaaS (OIDC)
- **Date**: Inferred (Epic 4 + OIDC implementation)
- **Status**: Active
- **Context**: Remote MCP access needs authentication. Options: API keys, custom OAuth server, or delegating to identity provider.
- **Decision**: Cloudflare Worker wrapped with `@cloudflare/workers-oauth-provider`. User identity via OIDC upstream to Cloudflare Access for SaaS. Worker stores verified email in encrypted OAuth token props. Service token header for defense-in-depth.
- **Rationale**: No server-side JWT verification needed — user identity verified at authorization time. Leverages Cloudflare's infrastructure (KV for tokens, Access for identity). Supports Claude Web's OAuth 2.1 flow natively.
- **Consequences**: Cloudflare vendor dependency for remote access. Complex auth stack (3 layers). Cookie size limits from OIDC state. JWKS caching needed for performance.
- **Affected modules**: `worker/src/index.ts`, `worker/src/access-handler.ts`, `backend/app/services/mcp_oauth_client.py`

## ADR-011: JWT Secret Derivation from Encryption Key
- **Date**: Inferred (config.py implementation)
- **Status**: Active (with caveat)
- **Context**: Admin JWT signing requires a secret key. Requiring yet another secret increases operational burden for homelab users.
- **Decision**: If `JWT_SECRET_KEY` is not explicitly set, derive it via `SHA256(encryption_key + "_jwt_secret")`. Separate key can be configured for higher security.
- **Rationale**: Reduces required secrets from 3 to 2 for homelab deployments. SHA256 derivation is one-way. Separate key is available for production use.
- **Consequences**: Single encryption key compromise breaks both encryption and JWT auth. Not suitable for high-security deployments without separate key. See [SECURITY.md](SECURITY.md#sec-011).
- **Affected modules**: `backend/app/core/config.py:191-198`

## ADR-012: Single-Worker MCP Gateway
- **Date**: Inferred (docker-compose.yml: `--workers 1`)
- **Status**: Active
- **Context**: MCP Streamable HTTP uses stateful sessions (`Mcp-Session-Id`). The gateway maintains an in-memory `_active_sessions` dict.
- **Decision**: Run MCP gateway with `--workers 1`. No horizontal scaling.
- **Rationale**: Multiple workers would cause ~50% of requests to hit the wrong worker, losing session state. In-memory sessions avoid external state store (Redis).
- **Consequences**: Single point of failure. Cannot horizontally scale MCP connections. Acceptable for homelab (designed for single-instance deployment).
- **Affected modules**: `backend/app/api/mcp_gateway.py`, `docker-compose.yml`

## ADR-013: Tool Version History with Database Storage
- **Date**: Inferred (migration 0002: tool versions)
- **Status**: Active
- **Context**: Tool code changes need tracking for audit trail and recovery. Options: git-based versioning, database-stored versions, or external VCS.
- **Decision**: Store versions in `tool_versions` table with full code snapshots. Rollback via `mcpbox_rollback_tool` restores code from version record.
- **Rationale**: Self-contained — no external git dependency. Simple implementation. Full code available for each version without git operations.
- **Consequences**: Database storage grows with version count (no automatic pruning). Full code duplication per version (not diffs). Rollback preserves approval status — security concern (see [SECURITY.md](SECURITY.md#sec-002)).
- **Affected modules**: `backend/app/models/tool_version.py`, `backend/app/services/tool.py`

## ADR-014: Application-Level Sandbox Security (Not Kernel-Level)
- **Date**: Inferred (foundational sandbox design)
- **Status**: Active
- **Context**: User-submitted Python code needs isolation. Options: gVisor/Firecracker (kernel-level), Docker seccomp/AppArmor profiles, or application-level restrictions.
- **Decision**: Application-level sandbox with multiple layers: restricted builtins, AST validation (dunder blocking), module proxy with attribute allowlists, import whitelisting, SSRF prevention, and resource limits via rlimit + Docker cgroups.
- **Rationale**: Kernel-level sandboxing adds significant complexity and resource overhead for homelab. Multiple application-level layers provide defense-in-depth. Combined with approval workflow, the attack window is limited to admin-reviewed code.
- **Consequences**: Potential for sandbox escape via Python internals (mitigated by multiple layers). No filesystem isolation between tools. stdout race condition with concurrent execution. Requires ongoing security review as Python evolves.
- **Affected modules**: `sandbox/app/executor.py`, `sandbox/app/ssrf.py`
