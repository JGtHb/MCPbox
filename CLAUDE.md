# CLAUDE.md - MCPbox

MCPbox is a self-extending MCP platform where LLMs create their own tools. The LLM writes Python code via `mcpbox_create_tool`, that code becomes a permanent MCP tool in a sandboxed executor, and the tool is available for future conversations. Self-hosted for homelabs with optional Cloudflare remote access.

## Tech Stack

| Component | Stack | Key Dependencies |
|-----------|-------|-----------------|
| Backend | Python 3.11+, FastAPI 0.128.8 | SQLAlchemy (asyncpg), cryptography, argon2-cffi, httpx, PyJWT |
| Frontend | React 18, TypeScript, Vite | TanStack Query, React Router, Tailwind CSS |
| Sandbox | Python 3.11+, FastAPI | httpx, regex |
| Worker | TypeScript, Cloudflare Workers | @cloudflare/workers-oauth-provider |
| Database | PostgreSQL 16 | Alembic (migrations) |
| Infra | Docker Compose | 6 services, 4 networks |

## Essential Commands

```bash
# Pre-PR checks (format, lint, all tests) — run before every PR
./scripts/pre-pr-check.sh

# Format + lint
ruff format backend/app sandbox/app && ruff check backend/app sandbox/app

# Backend tests (requires Docker for testcontainers)
cd backend && pytest tests -v

# Sandbox tests
cd sandbox && pytest tests -v --cov=app

# Frontend tests
cd frontend && npm test

# Worker tests
cd worker && npm test

# Database migrations
cd backend && alembic upgrade head
```

## Architecture Overview

```
                         browser
                           │
               ┌───────────┴───────────┐
               ▼                       ▼ (Traefik / reverse proxy)
frontend:3000 (React + nginx)    or direct access
      │ nginx proxies /api/*, /auth/*, /health
      ▼
backend:8000 (FastAPI)
      │
      ├──► sandbox:8001 (code execution, internal)
      ├──► postgres:5432 (internal)
      │
mcp-gateway:8002 (FastAPI, /mcp only) ◄── cloudflared (tunnel, optional)
                                            │
                                     Workers VPC (private)
                                            │
                                Cloudflare Worker (OAuth 2.1 + OIDC)
                                            │
                                    Remote MCP Clients
```

- **frontend** (`nginx.conf.template`): React SPA + nginx reverse proxy to backend for `/api/*`, `/auth/*`, `/health`
- **backend** (`app/main.py`): Admin API, all `/api/*` routes, JWT auth
- **mcp-gateway** (`app/mcp_only.py`): MCP Streamable HTTP, `/mcp` only, `--workers 1`
- **sandbox**: Hardened Python executor, restricted builtins, SSRF prevention
- **worker**: OAuth 2.1 proxy, OIDC identity, service token injection

Two modes: **Local** (no auth, local MCP client → localhost:8000/mcp) and **Remote** (OAuth + OIDC + service token, remote MCP client → Worker → VPC → tunnel → gateway).

## Documentation References

| Document | When to Consult |
|----------|----------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module map, data flow, dependencies, identified issues |
| [docs/FEATURES.md](docs/FEATURES.md) | Feature inventory with status, test coverage, owner modules |
| [docs/SECURITY.md](docs/SECURITY.md) | Security model, review summary, operator best practices |
| [docs/TESTING.md](docs/TESTING.md) | Test coverage map, critical gaps, infrastructure |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision records (15 ADRs) |
| [docs/API-CONTRACTS.md](docs/API-CONTRACTS.md) | Internal + external API contracts and schemas |
| [docs/AUTH-FLOW.md](docs/AUTH-FLOW.md) | Worker + Gateway auth flow details |
| [docs/PRODUCTION-DEPLOYMENT.md](docs/PRODUCTION-DEPLOYMENT.md) | Production env vars, HTTPS, monitoring |
| [docs/MCP-MANAGEMENT-TOOLS.md](docs/MCP-MANAGEMENT-TOOLS.md) | 28 `mcpbox_*` MCP tool reference |
| [docs/INCIDENT-RESPONSE.md](docs/INCIDENT-RESPONSE.md) | Operational runbooks for failures |
| [docs/FRONTEND-STANDARDS.md](docs/FRONTEND-STANDARDS.md) | Frontend style guide: colors, buttons, focus, ARIA, spacing, typography |

## Workflow Rules

- After implementing a new feature → update `docs/FEATURES.md`
- After security-relevant changes → update `docs/SECURITY.md`
- After adding/modifying tests → update `docs/TESTING.md`
- After architectural decisions → add entry to `docs/DECISIONS.md`
- After frontend UI changes → follow `docs/FRONTEND-STANDARDS.md`
- After user-facing feature changes → update docs site pages (`docs/getting-started/`, `docs/guides/`, `docs/reference/`)
- After adding/changing environment variables → update `docs/reference/environment-variables.md`
- After changing MCP management tools → update `docs/reference/mcp-tools.md`
- Always run `./scripts/pre-pr-check.sh` before PRs

## Known Gotchas

1. **MCP gateway must run `--workers 1`** — Sessions are stateful (in-memory dict). Multiple workers cause ~50% session mismatches.
2. **Backend tests require Docker** — testcontainers spins up PostgreSQL. No SQLite fallback (ARRAY types).
3. **Tool approval TOCTOU** — ~~Updating code on an approved tool doesn't reset approval status.~~ **Fixed**: approval resets to `pending_review` on code change.
4. **Rollback preserves approval** — ~~Rolling back to different code keeps "approved" status.~~ **Fixed**: rollback always resets approval.
5. **Sandbox stdout race** — ~~`sys.stdout` globally replaced during execution. Concurrent tools can leak output.~~ **Already mitigated**: `print` is overridden per-execution via a custom function injected into the execution namespace. No global `sys.stdout` replacement occurs.
6. **Two entry points** — `backend/app/main.py` (admin) and `backend/app/mcp_only.py` (gateway) have separate middleware stacks but share lifespan logic via `backend/app/core/shared_lifespan.py`. Middleware changes still need to be applied to both; lifespan changes go in the shared module.
7. **Encryption key required** — `MCPBOX_ENCRYPTION_KEY` must be exactly 64 hex chars. `SANDBOX_API_KEY` must be 32+ chars.
8. **Route prefix double-nesting** — ~~`/api/settings/settings` endpoint has doubled prefix.~~ **Fixed**: endpoint is now `/api/settings`.
9. **Migrations run automatically** — `backend/entrypoint.sh` runs `alembic upgrade head` on container startup (port 8000 only). For manual migration: `docker compose run --rm backend alembic upgrade head`.
10. **Service token comparison** — Must use `secrets.compare_digest()` (constant-time). Never use `==`.

## What NOT to Do

- Don't add visual workflow builders (code-first approach)
- Don't create per-server Docker containers (shared sandbox)
- Don't expose secret values in API responses (return `has_value: bool`)
- Don't skip pagination on list endpoints (`{ items, total, page, page_size, pages }`)
- Don't skip tests — all new endpoints and bug fixes require tests
- Don't commit with failing tests
- Don't add embedded LLM features (use MCP management tools)
- Don't hardcode config values (use `backend/app/core/config.py` settings)

## Common Tasks

### Adding a New API Endpoint
1. Route handler in `backend/app/api/`
2. Register in `backend/app/api/router.py`
3. Service in `backend/app/services/` (business logic)
4. Pydantic schemas in `backend/app/schemas/`
5. Tests in `backend/tests/test_<module>.py`

### Adding a Frontend Page
1. Page component in `frontend/src/pages/`
2. Route in `frontend/src/routes.tsx`
3. API functions in `frontend/src/api/`

### Fixing Bugs
1. Write a failing regression test first
2. Fix the bug
3. Verify test passes + full suite passes
