# Security Model

## Overview

MCPbox executes LLM-generated Python code in a sandboxed environment. Security is enforced through multiple independent layers so that no single bypass compromises the system.

## Security Layers

### 1. Code Validation
- **AST analysis** blocks dangerous patterns before execution (dunder access, attribute chains, metaclass manipulation)
- **Import whitelisting** restricts available modules to an admin-approved set
- **Static safety checks** reject code that attempts to escape the sandbox

### 2. Sandbox Isolation
- Code runs in a restricted execution namespace with dangerous builtins removed
- Module access mediated through attribute-filtered proxies
- Resource limits enforced: memory (256 MB), CPU time (60 s), file descriptors (256), stdout (1 MB)
- Network access gated by admin approval with SSRF prevention (private IP blocking, IP pinning, redirect restrictions)

### 3. Approval Workflow
- Tools created by LLMs start in `draft` status and cannot execute until an admin approves them
- Code changes after approval automatically reset the tool to `pending_review`
- Version rollbacks reset approval status unconditionally
- LLMs cannot self-approve tools

### 4. Authentication & Authorization
- **Local mode**: Localhost-only access, no authentication required
- **Remote mode**: Three-layer defense-in-depth:
  - OAuth 2.1 via Cloudflare Worker
  - OIDC identity via Cloudflare Access for SaaS
  - Service token validation between Worker and Gateway
- Admin JWT tokens with server-side blacklist for logout
- Constant-time token comparison for service tokens

### 5. Encryption
- Server secrets encrypted at rest with AES-256-GCM
- Secrets injected as read-only mappings at execution time, never persisted in tool code
- Encryption key derived from operator-provided environment variable
- All-zeros encryption key rejected at startup outside CI environments

### 6. Container & Network Architecture
- Five isolated Docker networks segment traffic between services
- Sandbox has no direct internet access — all outbound traffic is forced through the squid proxy via Docker network isolation (`mcpbox-sandbox-proxy` is internal-only; sandbox is not on the external network)
- Squid proxy blocks private/internal IPs (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16, etc.) and only allows HTTPS CONNECT on port 443
- **Allowed private ranges**: Operators can set `MCPBOX_ALLOWED_PRIVATE_RANGES` (comma-separated IP/CIDR, optionally with `:PORT`) to let sandbox tools reach specific LAN hosts (e.g., NAS, Home Assistant). Both the SSRF client and squid proxy honour this setting. Loopback, link-local, and metadata ranges are always rejected for safety.
- Per-server domain enforcement handled at the application layer (SSRF client) — squid provides network-level isolation that survives Python sandbox escapes
- Sandbox has no direct database access
- MCP Gateway runs as a separate process with its own middleware stack
- Cloudflare Tunnel provides remote access without exposing ports
- Dedicated `CLOUDFLARED_API_KEY` separates tunnel auth from sandbox auth
- All containers run with `cap_drop: ALL` (zero Linux capabilities; postgres has minimal exceptions)
- Read-only root filesystems on 5/6 containers (all except postgres)
- `no-new-privileges:true` on all containers
- Memory, CPU, and PID limits on all containers
- Health checks on all 7 containers (including squid-proxy)
- Nginx rate limiting on authentication endpoints (5r/s per IP)
- HSTS conditionally enabled via `MCPBOX_ENABLE_HSTS` (off by default for localhost)

## Dependency Vulnerability Audit (2026-02-25)

### Fixes Applied

| Package | Issue | CVE(s) | Action Taken |
|---------|-------|--------|--------------|
| `vite` (frontend) | Dev server file disclosure, one actively exploited (CISA KEV) | CVE-2025-30208, CVE-2025-31125, CVE-2025-32395 | Updated `^6.0.0` → `^6.2.6` |
| `@testing-library/dom` (frontend) | Listed as production dependency | N/A | Moved to `devDependencies` |

### Resolved (No Action Required)

| Package | CVE(s) | Status |
|---------|--------|--------|
| `react ^19.2.4` | CVE-2025-55182 (React2Shell, CVSS 10.0), CVE-2025-55183, CVE-2025-55184 | Pinned version is patched; RSC-only CVEs, not applicable to this SPA |
| `@cloudflare/workers-oauth-provider 0.2.3` | CVE-2025-4143 (Open Redirect), CVE-2025-4144 (PKCE Bypass, CVSS 9.8) | Pinned version includes fixes (patched in ≥0.0.5) |
| `wrangler ^4.64.0` | CVE-2026-0933 (Command Injection, CVSS 9.9) | Pinned version is well above fix version (≥4.59.1) |

### Technical Debt (No CVE, Future Migration)

| Package | Current | Latest Major | Notes |
|---------|---------|-------------|-------|
| `react-router-dom` | `^6.21.0` | v7 | v7 consolidates under `react-router`; non-breaking upgrade path via future flags |
| `tailwindcss` | `^3.4.1` | v4 | CSS-first config paradigm change; plan as dedicated migration |
| `eslint` | `^9.39.2` | v10 | v9 still receiving maintenance patches; optional upgrade |

### Python Dependencies

All pinned Python packages (backend and sandbox) are at current versions with no known unpatched CVEs affecting MCPbox's usage:

- `fastapi==0.128.8` — ecosystem CVEs (fastapi-sso, fastapi-guard, fastapi-api-key) are in separate packages not used by MCPbox
- `jinja2==3.1.6` — 4 CVEs in 2024-2025 (sandbox escapes, XSS, RCE), all fixed at exactly 3.1.6 including CVE-2025-27516 (CVSS 9.9 sandbox breakout via `|attr` filter)
- `cryptography==46.0.5` — 3 CVEs in 2024 (OpenSSL issues), all fixed well before 46.0.5
- `PyJWT==2.11.0` — CVE-2024-53861 (issuer validation, fixed 2.10.1); CVE-2025-45768 (weak encryption, DISPUTED by supplier — application-level key length responsibility)
- `sqlalchemy==2.0.46`, `httpx==0.28.1`, `pydantic==2.12.5`, `uvicorn==0.40.0` — no unpatched CVEs at pinned versions
- `asyncpg==0.31.0`, `alembic==1.18.4`, `slowapi==0.1.9`, `regex==2026.1.15`, `argon2-cffi==25.1.0` — no known CVEs
- Starlette (transitive via FastAPI) — CVE-2024-47874 (DoS, CVSS 8.7) fixed in 0.40.0; FastAPI 0.128.8 requires `>=0.40.0`

## Security Hardening (2026-02 Audit)

The following issues were identified and fixed in the February 2026 API security audit:

- **F-01**: Module-level `exec()` now runs with the same timeout as `main()`, preventing DoS via infinite loops outside `main()`
- **F-02**: Admin auth middleware checks an in-memory JTI blacklist, so revoked tokens are rejected immediately (not just after access token expiry)
- **F-03**: `MCPBOX_ENCRYPTION_KEY` removed from sandbox container environment to reduce blast radius on sandbox escape
- **F-04**: `TimeoutProtectedRegex` uses `__slots__` and name-mangled attributes (consistent with `SSRFProtectedAsyncHttpClient`) to prevent sandbox code from accessing the underlying module
- **F-05**: `0.0.0.0/8` ("this network") added to SSRF blocked IP ranges; hostname `"0"` added to blocked hostnames
- **F-06**: MCP gateway enforces a 1 MB request body size limit to prevent OOM from oversized payloads
- **F-07**: Import endpoint rejects unsigned or tampered export files (previously only warned)
- **F-08**: Rate limiter logs a warning at startup that state is in-memory and non-persistent
- **F-09**: `_handle_tools_list` requires a database session (no longer optional) to ensure approval filtering always runs

## Operator Responsibilities

- Set strong values for `MCPBOX_ENCRYPTION_KEY` (64 hex chars) and `SANDBOX_API_KEY` (32+ chars)
- Review and approve tool code before allowing execution
- Review module whitelist requests — some modules can enable sandbox escape
- Review network access requests — outbound HTTP can be used for data exfiltration
- Keep Docker images and dependencies updated
- See [PRODUCTION-DEPLOYMENT.md](PRODUCTION-DEPLOYMENT.md) for hardening guidance

## Security Reviews

Security review documents are kept out of the public repository. Findings are tracked privately and fixes are applied directly.

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly by opening a GitHub Security Advisory on this repository. Do not file a public issue for security bugs.
