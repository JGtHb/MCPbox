# MCPbox

**A self-extending MCP platform where LLMs create their own tools.**

MCPbox lets AI create, test, and manage its own MCP tools — write Python code, register it as a permanent tool, and use it in future conversations. Think of it as a tool forge: the LLM is both the toolmaker and the tool user.

[![CI](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml/badge.svg)](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml)

---

## What is MCPbox?

MCPbox is a self-hosted platform where LLMs extend their own capabilities by writing tools. Unlike MCP gateways (which proxy existing servers) or MCP hosts (which deploy pre-built servers), MCPbox lets the LLM itself author new tools as Python code that persist across sessions.

- **LLM as Toolmaker** - Claude writes Python code via `mcpbox_create_tool`, the code becomes a permanent MCP tool, available for future use
- **Human-in-the-Loop** - Tools are created in draft status; admins review and approve before publishing
- **Sandboxed Execution** - All tool code runs in a hardened sandbox with restricted builtins, import whitelisting, and SSRF prevention
- **Self-Hosted for Homelabs** - Single `docker compose up`, no Kubernetes required
- **Remote Access** - Optional Cloudflare Worker + tunnel integration to use your tools from Claude Web

## How It Works

```
Claude writes Python code
        |
        v
  mcpbox_create_tool  →  Tool saved in draft status
        |
        v
  mcpbox_test_code    →  Code tested in sandbox
        |
        v
  mcpbox_request_publish  →  Admin reviews and approves
        |
        v
  Tool is live  →  Available as MCP tool for all future conversations
```

MCPbox exposes 24 management tools (`mcpbox_*`) that LLMs use to create and manage servers, tools, secrets, and the approval workflow. See [MCP Management Tools](docs/MCP-MANAGEMENT-TOOLS.md) for the full reference.

## Key Features

### Self-Extending via MCP

The LLM doesn't just use tools — it builds them:
- `mcpbox_create_server` / `mcpbox_create_tool` — author new tools as Python code
- `mcpbox_test_code` / `mcpbox_validate_code` — test and validate before publishing
- `mcpbox_request_publish` — submit for admin approval
- `mcpbox_create_server_secret` — create secret placeholders (admins set values)
- `mcpbox_request_module` / `mcpbox_request_network_access` — request new capabilities
- `mcpbox_list_tool_versions` / `mcpbox_rollback_tool` — version history and rollback
- `mcpbox_get_tool_logs` — inspect execution history

### Security-First Design

- **Sandboxed Execution**: All MCP tools run in a shared sandbox with:
  - Restricted builtins (no `eval`, `exec`, `type`, `getattr`, `open`)
  - Dunder attribute blocking prevents sandbox escape (`__class__`, `__mro__`, `__subclasses__`, etc.)
  - Whitelist-based import restrictions (only safe modules allowed)
  - Resource limits (256MB memory, 60s CPU, 256 file descriptors)
  - Code safety validation via regex pattern scanning before execution
- **SSRF Prevention**: URL validation blocks requests to private IPs, metadata endpoints, with DNS rebinding protection
- **Server Secrets**: AES-256-GCM encrypted per-server secrets (LLMs create placeholders, admins set values)
- **Separate MCP Gateway**: Tunnel-exposed service physically cannot serve admin endpoints
- **Rate Limiting**: API rate limiting prevents abuse (100 req/min default)
- **Timing-Safe Auth**: Constant-time token comparison prevents timing attacks

### Cloudflare Tunnel Integration

- Named tunnels for production (stable URLs)
- Workers VPC for truly private tunnel access
- OAuth 2.1 + OIDC authentication (Cloudflare Access for SaaS)
- Service token defense-in-depth
- Works with Claude Web's remote MCP feature

## Quick Start

```bash
# Clone the repo
git clone https://github.com/JGtHb/MCPbox.git
cd mcpbox

# Configure environment
cp .env.example .env

# Generate a secure encryption key
python -c "import secrets; print(secrets.token_hex(32))"
# Add to .env as MCPBOX_ENCRYPTION_KEY

# Start MCPbox
docker compose up -d

# Access the web UI
open http://localhost:3000
```

### Verify Installation

1. Open http://localhost:3000
2. Use Claude Code or another LLM with `mcpbox_create_server` and `mcpbox_create_tool` to create a server
3. Approve the tool in the Admin UI at `/approvals`
4. Start the server
5. Check the Activity page for logs

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     MCPbox (Docker Compose)                       │
│                                                                   │
│  LOCAL ONLY (127.0.0.1)           PRIVATE TUNNEL                  │
│  ┌──────────┐  ┌──────────┐     ┌──────────────┐                │
│  │ Frontend │  │ Backend  │     │ MCP Gateway  │◄── cloudflared  │
│  │ (React)  │◄─┤ (FastAPI)│     │ (FastAPI)    │                 │
│  │ :3000    │  │ :8000    │     │ :8002        │                 │
│  └──────────┘  └────┬─────┘     └──────┬───────┘                │
│                     │                  │                          │
│                     └──────┬───────────┘                         │
│                            ▼                                      │
│              ┌──────────────────────────┐  ┌────────────┐        │
│              │   Shared Sandbox :8001   │  │ PostgreSQL │        │
│              └──────────────────────────┘  │  :5432     │        │
│                                            └────────────┘        │
└──────────────────────────────────────────────────────────────────┘
                             │ Workers VPC (private)
                             ▼
                  ┌──────────────────────────┐
                  │ Cloudflare Worker         │
                  │ (OAuth 2.1 + OIDC)       │
                  └──────────┬───────────────┘
                             ▼
                    ┌───────────────┐
                    │  Claude Web   │
                    └───────────────┘
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - **Start here** - Project context for AI assistants and developers
- [Architecture Overview](docs/ARCHITECTURE.md) - Full technical design
- [Production Deployment](docs/PRODUCTION-DEPLOYMENT.md) - Deployment guide
- [Remote Access Setup](docs/REMOTE-ACCESS-SETUP.md) - Cloudflare tunnel configuration
- [MCP Management Tools](docs/MCP-MANAGEMENT-TOOLS.md) - MCP tool reference
- [Cloudflare Setup Wizard](docs/CLOUDFLARE-SETUP-WIZARD.md) - Automated remote access setup
- [Future Epics](docs/FUTURE-EPICS.md) - Post-MVP features

## Development Status

MCPbox is **stable and production-ready** with the following epics implemented:

| Epic | Status | Description |
|------|--------|-------------|
| Epic 1 | ✅ Complete | Foundation - Docker setup, backend skeleton, database |
| Epic 4 | ✅ Complete | Cloudflare Tunnel - Named tunnel support with Workers VPC |
| Epic 5 | ✅ Complete | Observability - Activity logging and monitoring |
| Epic 6 | ✅ Complete | Python Code Tools - Custom Python tool execution |
| Epic 7 | ✅ Complete | Tool Approval Workflow - Draft/review/publish lifecycle |

*Note: Legacy API Builder (Epic 2) and OpenAPI Import (Epic 3) were removed in favor of MCP-first architecture.*

### Recent Improvements

- ✅ Server secrets - encrypted key-value secrets per server (LLMs create placeholders, admins set values)
- ✅ Tool execution logging - per-tool invocation history with args, results, errors
- ✅ Server recovery - automatic re-registration after sandbox restart
- ✅ Tool change notifications - MCP `tools/list_changed` broadcast
- ✅ Tool versioning with rollback support
- ✅ Access for SaaS (OIDC) - Cloudflare Access as OIDC identity provider
- ✅ MCP session management - stateful `Mcp-Session-Id` support
- ✅ MCP-first architecture - tools created via 24 `mcpbox_*` MCP tools
- ✅ Tool approval workflow with draft/pending/approved states
- ✅ Separate MCP Gateway for secure tunnel access
- ✅ Workers VPC integration (no public tunnel URL)
- ✅ Cloudflare setup wizard for automated remote access configuration

## Running Tests

```bash
# Backend tests (requires PostgreSQL or Docker for testcontainers)
cd backend
pip install -r requirements-dev.txt
pytest tests -v

# Sandbox tests (includes sandbox escape prevention tests)
cd sandbox
pip install -r requirements.txt -r requirements-dev.txt
pytest tests -v

# Lint check
ruff check backend/app sandbox/app
ruff format --check backend/app sandbox/app
```

## License

MCPbox is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

- **Personal/Non-Commercial Use**: Free
- **Commercial Use**: Requires a commercial license (contact for pricing)

## Contributing

Contributions are welcome! Please:
1. Check existing issues before creating new ones
2. Run tests before submitting PRs
3. Follow the existing code style

## Security

If you discover a security vulnerability, please open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) on this repository instead of opening a public issue.

---

Built for the homelab community. [Competitive analysis](docs/COMPETITIVE-ANALYSIS.md) — how MCPBox compares to the MCP ecosystem.
