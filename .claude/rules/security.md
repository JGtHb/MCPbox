---
paths:
  - "backend/app/api/**"
  - "backend/app/services/**"
  - "backend/app/middleware/**"
  - "sandbox/app/**"
  - "worker/src/**"
---
# Security Rules

## API Endpoints
- All `/api/*` endpoints require JWT auth via AdminAuthMiddleware. No exceptions.
- `/internal/*` endpoints require `Authorization: Bearer <SANDBOX_API_KEY>` validation
- `/auth/setup` and `/auth/login` are the only unauthenticated endpoints
- MCP gateway `/mcp` auth depends on mode: none (local), service token (remote)
- Never return secret values in API responses. Return `has_value: bool` instead.
- Validate all user input with Pydantic schemas. Never trust raw request data.
- Use `status.HTTP_*` enums for error responses, with specific detail messages.

## Secrets & Encryption
- Server secrets use AES-256-GCM via `crypto.py`. Never roll your own crypto.
- Encryption key comes from `MCPBOX_ENCRYPTION_KEY` env var (64 hex chars = 32 bytes)
- Secrets are injected as read-only `MappingProxyType` at execution time
- Never log secret values. Use redaction in all debug/error output.
- Service tokens compared with `secrets.compare_digest()` (constant-time)

## Sandbox Security
- All code must pass `validate_code_safety()` before execution
- Dunder attribute access (`__class__`, `__mro__`, `__globals__`, etc.) is blocked via regex
- Dangerous builtins removed: `type`, `getattr`, `setattr`, `eval`, `exec`, `compile`, `open`, `vars`, `dir`
- Import whitelisting enforced — only admin-approved modules available
- SSRF prevention: IP pinning, private IP blocking, `follow_redirects=False` on all HTTP clients
- Resource limits: 256MB memory, 60s CPU, 256 FDs, 1MB stdout

## Approval Workflow
- Tools start as `draft`. Only `approved` tools are registered with the sandbox.
- IMPORTANT: If changing tool code after approval, reset `approval_status` to `draft`
- LLMs cannot self-approve. Approval requires admin JWT auth with identity from JWT `sub` claim.
- Multi-layer tool filtering: registration gate, listing gate, recovery gate

## Auth Architecture
- Local mode: no auth (localhost trust)
- Remote mode: OAuth 2.1 (Worker) + OIDC (Access for SaaS) + service token (defense-in-depth)
- User email from OIDC id_token, stored in encrypted OAuth token props
- Gateway trusts `X-MCPbox-User-Email` header only when valid service token present
