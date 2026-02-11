# MCPbox

**Self-hosted MCP server management for homelabs.**

Run your own Model Context Protocol (MCP) servers securely, manage them through a web UI, and connect them to Claude Web via Cloudflare tunnels.

[![CI](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml/badge.svg)](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml)

---

## What is MCPbox?

MCPbox is a Docker-based platform that lets you:

- **Create Custom Tools via MCP** - External LLMs (Claude Code, etc.) create tools programmatically using `mcpbox_*` MCP tools
- **Code-First Approach** - Write Python code for your MCP tools with full control
- **Connect to Claude Web** - Secure Cloudflare tunnel integration exposes your MCP servers to claude.ai
- **Manage Everything** - Web UI to start/stop servers, enable/disable individual tools, monitor activity
- **Tool Approval Workflow** - LLMs create tools in draft status, admins approve before publishing

## Key Features

### MCP-First Architecture

MCPbox exposes 18 management tools that external LLMs can use:
- `mcpbox_create_server`, `mcpbox_create_tool`, `mcpbox_test_code`
- `mcpbox_request_publish`, `mcpbox_request_module`, `mcpbox_request_network_access`
- Full CRUD for servers, tools, and approval workflow

See [MCP Management Tools](docs/MCP-MANAGEMENT-TOOLS.md) for details.

### Security-First Design

- **Sandboxed Execution**: All MCP tools run in a shared sandbox with:
  - Restricted builtins (no `eval`, `exec`, `type`, `getattr`, `open`)
  - Dunder attribute blocking prevents sandbox escape (`__class__`, `__mro__`, `__subclasses__`, etc.)
  - Whitelist-based import restrictions (only safe modules allowed)
  - Resource limits (256MB memory, 60s CPU, 256 file descriptors)
  - Code safety validation via regex pattern scanning before execution
- **SSRF Prevention**: URL validation blocks requests to private IPs, metadata endpoints, with DNS rebinding protection
- **Credential Encryption**: AES-256-GCM encryption for stored credentials
- **Separate MCP Gateway**: Tunnel-exposed service physically cannot serve admin endpoints
- **Rate Limiting**: API rate limiting prevents abuse (100 req/min default)
- **Timing-Safe Auth**: Constant-time token comparison prevents timing attacks

### Cloudflare Tunnel Integration

- Named tunnels for production (stable URLs)
- Workers VPC for truly private tunnel access
- Service token authentication
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
                  ┌─────────────────────┐
                  │ Cloudflare Worker   │
                  │ + MCP Server Portal │
                  └─────────┬───────────┘
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

- ✅ MCP-first architecture - tools created via `mcpbox_*` MCP tools
- ✅ Tool approval workflow with draft/pending/approved states
- ✅ Module and network access request system
- ✅ Separate MCP Gateway for secure tunnel access
- ✅ Workers VPC integration (no public tunnel URL)
- ✅ Activity log retention with automatic cleanup
- ✅ Cloudflare setup wizard for automated remote access configuration
- ✅ Production readiness review - security audit, bug fixes, test coverage

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

MCPbox uses a dual license model:

- **Personal/Non-Commercial Use**: AGPL-3.0 (free)
- **Commercial Use**: Commercial license (contact for pricing)

## Contributing

Contributions are welcome! Please:
1. Check existing issues before creating new ones
2. Run tests before submitting PRs
3. Follow the existing code style

## Security

If you discover a security vulnerability, please email security@example.com instead of opening a public issue.

---

Built for the homelab community.
