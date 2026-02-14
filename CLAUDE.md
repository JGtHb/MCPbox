# CLAUDE.md - MCPbox Project Context

This file provides context for AI assistants (like Claude) working on this codebase. It serves as a single source of truth for project status, architecture decisions, and development guidelines.

## Project Summary

**MCPbox** is a self-hosted MCP (Model Context Protocol) server management platform for homelabs. It enables users to:

- Create MCP tools programmatically via LLMs (Claude Code, etc.)
- Securely expose tools to Claude Web via Cloudflare Worker + Tunnel
- Manage servers and tools through a web UI
- **MCP-first approach** - External LLMs create/manage servers and tools via `mcpbox_*` MCP tools

## Current Status

**The project is stable and production-ready.**

| Epic | Title | Status |
|------|-------|--------|
| Epic 1 | Project Foundation | ✅ Complete |
| Epic 4 | Cloudflare Tunnel | ✅ Complete |
| Epic 5 | Observability | ✅ Complete |
| Epic 6 | Python Code Tools | ✅ Complete |
| Epic 7 | Tool Approval Workflow | ✅ Complete |

*Note: Legacy API Builder (Epic 2) and OpenAPI Import (Epic 3) have been removed in favor of the MCP-first approach.*

### Recent Changes

- **Tunnel Security Review** - Worker simplified (apiRoute: '/', eliminated Bug #108 workaround), server-side JWT verification, /internal/* auth, fail-closed ServiceTokenCache, isolated DB network, OAuth redirect_uri validation, HMAC-based timingSafeEqual
- **Pre-Production Security Review** - Two review cycles completed, all findings fixed
- **Sandbox Hardening** - `validate_code_safety()` on all execution paths, consolidated builtins, SSRF redirect prevention
- **Cloudflare Setup Wizard** - Automated 7-step wizard at `/tunnel/setup` for configuring remote access (tunnel, VPC, Worker, MCP Portal)
- **Hybrid Architecture** - Local-first with optional Cloudflare Worker for remote access
- **OAuth 2.1 Worker Protection** - Worker wrapped with `@cloudflare/workers-oauth-provider`, all /mcp requests require valid OAuth token
- **Service Token Defense-in-Depth** - Service token between Worker and MCPbox gateway (in addition to OAuth)
- **Tool Approval Workflow** - LLMs create tools in draft status, request publish, admin approves/rejects
- **Module Whitelist Requests** - LLMs can request Python modules to be whitelisted via MCP tools
- **Network Access Requests** - LLMs can request network access to external hosts via MCP tools
- **Admin Approval Queue** - New UI for reviewing and approving/rejecting pending requests
- **Admin API Authentication** - API key protection for admin endpoints (defense-in-depth)
- **Separate MCP Gateway** - Tunnel-exposed service that physically cannot serve admin endpoints
- **Activity Log Retention** - Automatic cleanup of old logs (configurable retention period)
- **Production Security Checks** - Startup warnings for missing security configuration
- **Named Tunnel Management** - Save and manage multiple tunnel configurations
- **MCP Management Tools** - MCPbox management exposed as MCP tools (`mcpbox_*`)
- **MCP-First Architecture** - Tools are created via `mcpbox_create_tool` with Python code only (legacy API Builder removed)
- Comprehensive test coverage for MCP gateway and tool management

### Production Configuration

Essential environment variables for production deployment:

```bash
# Required
DATABASE_URL=postgresql+asyncpg://user:pass@host/mcpbox
MCPBOX_ENCRYPTION_KEY=<64-char-hex-key>  # 32-byte key for credential encryption
SANDBOX_API_KEY=<secret>  # Required, min 32 chars. Generate: openssl rand -hex 32

# For Remote Access (optional)
# All tokens (service token, tunnel token) are stored in the database.
# Use the setup wizard at /tunnel/setup, then run ./scripts/deploy-worker.sh --set-secrets

# Optional
LOG_RETENTION_DAYS=30  # Days to keep activity logs (default: 30)
CORS_ORIGINS=https://your-domain.com  # Allowed CORS origins
RATE_LIMIT_REQUESTS_PER_MINUTE=100  # API rate limit (default: 100)
```

**Important:** Run `alembic upgrade head` before starting in production. Auto table creation is disabled by default. See `docs/PRODUCTION-DEPLOYMENT.md` for complete deployment instructions.

## MCP Management Tools

MCPbox exposes its management functions as MCP tools, allowing external LLMs (like Claude Code) to programmatically create and manage servers and tools. This approach:

- **No API key management** - Users leverage their existing Claude access
- **Better UX** - LLM does the heavy lifting externally
- **18 management tools** - Full CRUD for servers, tools, and approval workflow

See `docs/MCP-MANAGEMENT-TOOLS.md` for complete documentation.

### Available Tools (prefix: `mcpbox_`)

| Category | Tools |
|----------|-------|
| Servers | `list_servers`, `get_server`, `create_server`, `delete_server`, `start_server`, `stop_server`, `get_server_modules` |
| Tools | `list_tools`, `get_tool`, `create_tool`, `update_tool`, `delete_tool` |
| Development | `test_code`, `validate_code` |
| Approval | `request_publish`, `request_module`, `request_network_access`, `get_tool_status` |

### Tool Approval Workflow

Tools are created in **draft** status and must be approved by an admin before they become available:

1. LLM creates tool with `mcpbox_create_tool` → tool is in **draft** status
2. LLM tests with `mcpbox_test_code` and `mcpbox_validate_code`
3. LLM requests publish with `mcpbox_request_publish` → tool moves to **pending_review**
4. Admin reviews in UI at `/approvals` → approves or rejects
5. If **approved**, tool becomes available in `tools/list`
6. If **rejected**, LLM can revise and re-submit

Similarly for module and network access requests:
- `mcpbox_request_module` - Request Python module whitelisting
- `mcpbox_request_network_access` - Request access to external hosts

## Architecture Overview

MCPbox uses a **hybrid architecture** - local-first with optional remote access via Cloudflare Workers VPC.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCPbox (Docker Compose)                            │
│                                                                              │
│  LOCAL ONLY (127.0.0.1)                    PRIVATE TUNNEL                    │
│  ┌──────────┐  ┌──────────────┐           ┌──────────────┐                  │
│  │ Frontend │  │   Backend    │           │ MCP Gateway  │                  │
│  │ (React)  │◄─┤  (FastAPI)   │           │ (FastAPI)    │◄── cloudflared   │
│  │ :3000    │  │  :8000       │           │ :8002        │   (no public URL)│
│  └──────────┘  │  /api/*      │           │ /mcp ONLY    │                  │
│                └──────┬───────┘           └──────┬───────┘                  │
│                       │                          │                          │
│                       └──────────┬───────────────┘                          │
│                                  │                                          │
│                                  ▼                                          │
│  ┌────────────┐     ┌──────────────────────────┐                           │
│  │ PostgreSQL │◄────┤     Shared Sandbox       │                           │
│  │   :5432    │     │        :8001             │                           │
│  └────────────┘     └──────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ Workers VPC (private)
                                    │
┌───────────────────────────────────┴─────────────────────────────────────────┐
│                         Cloudflare (Optional)                                │
│                                                                              │
│  ┌──────────────────┐     ┌─────────────────────────────────┐              │
│  │ MCP Server Portal│────►│ Cloudflare Worker (mcpbox-proxy)│              │
│  │ (handles OAuth)  │     │ - VPC binding to tunnel         │              │
│  └──────────────────┘     │ - Adds X-MCPbox-Service-Token   │              │
│                           └─────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Two Deployment Modes

| Mode | Configuration | Use Case |
|------|---------------|----------|
| **Local Only** | No wizard config | Claude Desktop → `http://localhost:8000/mcp` |
| **Remote** | Wizard completed + Worker deployed | Claude Web → Worker → VPC → Tunnel → MCPbox |

### Key Architecture Decisions

1. **Hybrid Architecture** - Local-first with optional Cloudflare Worker for remote access. Uses Workers VPC for truly private tunnel access (no public hostname).
2. **Separate MCP Gateway** - The tunnel only reaches a service that serves `/mcp` endpoints. Admin API (`/api/*`) is physically unreachable through the tunnel.
3. **Workers VPC** - The tunnel has no public URL. Only the Worker can access it via VPC binding, eliminating any public attack surface.
4. **Single-Instance Deployment** - Designed for homelab use, not horizontal scaling. No Redis, no distributed state, no multi-instance coordination.
5. **Shared Sandbox** (not per-server containers) - Lower resource usage, simpler architecture, no docker.sock exposure
6. **Code-First Approach** (not visual builders) - More maintainable, LLM-friendly
7. **Python Backend** (not Rust gateway) - Faster iteration, async support, simpler deployment
8. **MCP Tools for Management** (not embedded LLM) - No API key management, leverages existing Claude access

## Key Directories

```
MCPbox/
├── frontend/          # React 18 + TypeScript + Vite
│   └── src/
│       ├── pages/     # Route components
│       ├── components/# Reusable UI
│       ├── api/       # API client functions
│       ├── hooks/     # Custom React hooks
│       └── lib/       # Utilities, constants
│
├── backend/           # Python FastAPI
│   └── app/
│       ├── api/       # Route handlers
│       ├── services/  # Business logic (incl. mcp_management.py)
│       ├── models/    # SQLAlchemy models
│       ├── schemas/   # Pydantic schemas
│       └── core/      # Config, database
│
├── sandbox/           # Isolated tool execution
│   └── app/
│       ├── routes.py  # Tool execution API
│       ├── registry.py# Dynamic tool registration
│       └── executor.py# Python code execution
│
├── worker/            # Cloudflare Worker (MCP proxy)
│   ├── src/index.ts   # Worker code
│   ├── wrangler.toml  # Worker configuration
│   └── package.json   # Dependencies
│
└── docs/              # Documentation
```

## Development Guidelines

### Code Style

- **Backend**: Python 3.11+, use async/await, type hints required
- **Frontend**: TypeScript strict mode, functional components, hooks
- **Tests**: pytest for backend, requires PostgreSQL (due to ARRAY types)

### Pre-PR Checklist

**Option 1: Use pre-commit hooks (recommended)**

```bash
# One-time setup
pip install pre-commit
pre-commit install

# Now formatting/linting runs automatically on every commit
```

**Option 2: Run the pre-PR check script**

```bash
# Run all checks (format, lint, tests)
./scripts/pre-pr-check.sh
```

**Option 3: Run checks manually**

```bash
# Format Python code (required)
ruff format backend/app sandbox/app

# Check for linting issues
ruff check backend/app sandbox/app

# Run all pre-commit hooks
pre-commit run --all-files
```

Formatting is enforced in CI - PRs with formatting issues will fail.

### Key Patterns

1. **Services pattern** - Business logic in `backend/app/services/`, not in route handlers
2. **Pagination** - All list endpoints return `{ items, total, page, page_size, pages }`
3. **Shared constants** - Frontend uses `lib/constants.ts` for METHOD_COLORS, STATUS_COLORS, etc.
4. **Hooks** - Use `useCopyToClipboard` and other custom hooks from `hooks/`

### Testing Requirements

**Always run tests before committing changes.** This project maintains comprehensive test coverage.

#### When to Write Tests

- **New API endpoints** - Add tests in `backend/tests/test_<module>.py`
- **New services** - Add unit tests for business logic
- **Bug fixes** - Add a regression test that would have caught the bug
- **Sandbox changes** - Add tests in `sandbox/tests/`

#### Pre-PR Checks

**Always run the pre-PR check script before creating a pull request:**

```bash
./scripts/pre-pr-check.sh
```

This script runs:
1. Python formatting check (ruff format --check)
2. Python linting check (ruff check)
3. Backend tests (requires Docker for testcontainers)
4. Sandbox tests

You can also run individual checks manually or use pre-commit hooks (see Pre-PR Checklist above).

#### Test Commands

```bash
# Backend tests (requires PostgreSQL)
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/mcpbox_test pytest tests -v

# Sandbox tests
cd sandbox && pytest tests -v --cov=app

# Run specific test file
pytest tests/test_mcp_gateway.py -v

# Run with coverage report
pytest tests -v --cov=app --cov-report=term-missing
```

#### Test Conventions

- **Fixtures**: Use `conftest.py` for shared fixtures (db_session, async_client, factories)
- **Async tests**: Use `@pytest.mark.asyncio` decorator
- **Mocking**: Mock external services (httpx requests, etc.)
- **Isolation**: Each test should be independent; use `autouse` fixtures for cleanup
- **Naming**: Test files as `test_<module>.py`, test functions as `test_<behavior>`

#### Common Testing Patterns

```python
# Mock service token auth for MCP gateway tests
# In local mode (no service token in database), auth passes automatically

# Mock external HTTP calls
with patch("httpx.AsyncClient") as mock_client:
    mock_client.return_value.__aenter__.return_value.get.return_value = Mock(status_code=200, json=lambda: {...})

# Use factories for test data
tool = await tool_factory(server_id=server.id, name="test_tool", python_code="async def main(): return 'test'")
```

### Security Considerations

- **OAuth 2.1 Worker Protection** - Worker wrapped with `@cloudflare/workers-oauth-provider`, all requests to `/` (MCP endpoint) require a valid OAuth token. Cloudflare sync and MCP Portal users both authenticate via OAuth.
- **OAuth-only is blocked** - OAuth-only requests (no valid Cf-Access-Jwt-Assertion) are rejected for ALL MCP methods including `initialize`, `tools/list`, `tools/call`, and `notifications/*`. Only Cloudflare sync (service token bypass) can operate without a JWT.
- **MCP Server uses OAuth auth** - Created with `auth_type: "oauth"` at the Worker's origin (no `/mcp` subpath), so Cloudflare performs full OAuth 2.1 discovery+flow against the Worker's OAuthProvider
- **Server-side JWT verification** - Gateway verifies Cf-Access-Jwt-Assertion using JWKS from Cloudflare Access (RS256 signature, audience, issuer). Does NOT trust Worker-supplied X-MCPbox-Auth-Method or X-MCPbox-User-Email headers.
- **Service Token Authentication** - Shared secret between Worker and MCPbox gateway (defense-in-depth via `X-MCPbox-Service-Token`, returns 403 on mismatch). Fail-closed on database errors.
- **Internal Endpoint Auth** - `/internal/*` endpoints require `Authorization: Bearer <SANDBOX_API_KEY>` for defense-in-depth
- **OAuth Client Registration** - Redirect URIs validated against allowlist (claude.ai, localhost)
- **Isolated Database** - PostgreSQL on dedicated internal-only network (no outbound internet)
- **SSRF Prevention** via URL validation (blocks private IPs, localhost)
- **AES-256-GCM Encryption** for stored credentials
- **Rate Limiting** on API endpoints (100 req/min default)
- **Production Warnings** - Security issues logged on startup
- **X-Forwarded-For Support** - Proper client IP handling behind proxies

## Documentation Map

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **CLAUDE.md** (this file) | Project context | Start here |
| **CHANGELOG.md** | Version history | Tracking changes |
| **docs/PRODUCTION-DEPLOYMENT.md** | Production deployment guide | Deploying to production |
| **docs/REMOTE-ACCESS-SETUP.md** | Remote access via Cloudflare | Setting up Claude Web access |
| **docs/MCP-MANAGEMENT-TOOLS.md** | MCP tools for management | Building with Claude |
| **docs/CLOUDFLARE-SETUP-WIZARD.md** | Automated remote access setup | Cloudflare wizard |
| **docs/ARCHITECTURE.md** | Technical deep-dive | Understanding design |
| **docs/INCIDENT-RESPONSE.md** | Operational runbooks | Diagnosing failures |
| **docs/FUTURE-EPICS.md** | Feature roadmap | Planning new features |
| **docs/COMPETITIVE-ANALYSIS.md** | Strategic rationale | Understanding "why" decisions |

## Common Tasks

### Adding a New API Endpoint

1. Add route in `backend/app/api/`
2. Add to router in `backend/app/api/router.py`
3. Create service in `backend/app/services/` if needed
4. Add Pydantic schemas in `backend/app/schemas/`
5. **Add tests in `backend/tests/`** - Required before merging
6. **Run full test suite** to ensure no regressions

### Adding a Frontend Page

1. Create page in `frontend/src/pages/`
2. Add route in `frontend/src/routes.tsx`
3. Add API functions in `frontend/src/api/`
4. Use shared constants from `frontend/src/lib/constants.ts`

### Fixing Bugs

1. **Write a failing test first** that reproduces the bug
2. Fix the bug in the code
3. Verify the test now passes
4. Run full test suite to check for regressions

## What NOT to Do

- Don't add visual workflow builders (code-first approach)
- Don't create per-server Docker containers (use shared sandbox)
- Don't duplicate constants (use lib/constants.ts)
- Don't skip pagination on list endpoints
- Don't expose credentials in API responses
- Don't add embedded LLM features (use MCP management tools instead)
- **Don't skip tests** - All new endpoints and bug fixes require tests
- **Don't commit with failing tests** - Run the test suite before pushing
- **Don't use hardcoded test values** that violate validation (e.g., API keys must be 32+ chars)

## Questions?

- Remote access setup → `docs/REMOTE-ACCESS-SETUP.md`
- Architecture questions → `docs/ARCHITECTURE.md`
- MCP management tools → `docs/MCP-MANAGEMENT-TOOLS.md`
- Feature planning → `docs/FUTURE-EPICS.md`
- Strategic decisions → `docs/COMPETITIVE-ANALYSIS.md`
