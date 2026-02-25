# MCPbox

**A self-extending MCP platform where LLMs create their own tools.**

MCPbox lets AI create, test, and manage its own MCP tools — write Python code, register it as a permanent tool, and use it in future conversations. Think of it as a tool forge: the LLM is both the toolmaker and the tool user.

[![CI](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml/badge.svg)](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml)

---

## See It in Action

> **You:** Is Claude having issues right now?
>
> **LLM:** I don't have a tool for that yet — let me build one.

```
1. mcpbox_create_server   → "news" server created
2. mcpbox_create_tool     → claude_status tool (Python: fetch Anthropic status page)
3. mcpbox_test_code       → test passes, returns JSON
4. mcpbox_request_publish → submitted for admin approval
```

> **Admin** approves the tool in the web UI.

```
5. mcpbox_start_server    → server is live
6. claude_status          → calls the tool it just built
```

> **LLM:** All Anthropic systems are operational. API, Console, and claude.ai are all up.

The tool now exists permanently. Next time anyone asks about Claude's status, the LLM just calls `claude_status` directly — no rebuilding needed.

---

## What is MCPbox?

MCPbox is a self-hosted platform where LLMs extend their own capabilities by writing tools. Unlike MCP gateways (which proxy existing servers) or MCP hosts (which deploy pre-built servers), MCPbox lets the LLM itself author new tools as Python code that persist across sessions.

- **LLM as Toolmaker** — write Python code via `mcpbox_create_tool`, it becomes a permanent MCP tool
- **Human-in-the-Loop** — tools are created in draft status; admins review and approve before publishing
- **Sandboxed Execution** — hardened sandbox with restricted builtins, import whitelisting, and SSRF prevention
- **Self-Hosted for Homelabs** — single `docker compose up`, no Kubernetes required
- **Remote Access** — optional Cloudflare Worker + tunnel integration for any remote MCP client

## Quick Start

```bash
git clone https://github.com/JGtHb/MCPbox.git
cd MCPbox

cp .env.example .env

# Generate required secrets and append to .env
echo "MCPBOX_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "SANDBOX_API_KEY=$(openssl rand -hex 32)" >> .env

# Run database migrations, then start
docker compose run --rm backend alembic upgrade head
docker compose up -d
```

Open http://localhost:3000 to access the web UI.

### Connect Your MCP Client

Add MCPbox to your MCP client config (Claude Code, Cursor, etc.):

```json
{
  "mcpServers": {
    "mcpbox": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

The LLM will discover all 28 `mcpbox_*` management tools automatically and can start building.

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
                    │  MCP Clients  │
                    └───────────────┘
```

Two modes: **Local** (no auth, MCP client connects to `localhost:8000/mcp`) and **Remote** (OAuth 2.1 + OIDC via Cloudflare Worker → VPC tunnel → gateway).

## Key Features

### Self-Extending via MCP

The LLM doesn't just use tools — it builds them. MCPbox exposes [28 management tools](docs/MCP-MANAGEMENT-TOOLS.md) (`mcpbox_*`) for creating servers, tools, secrets, modules, and managing the approval workflow.

### Security-First Design

- **Sandboxed Execution** — restricted builtins, dunder blocking, whitelist imports, resource limits (256MB/60s CPU)
- **SSRF Prevention** — URL validation blocks private IPs, metadata endpoints, with DNS rebinding protection
- **Server Secrets** — AES-256-GCM encrypted per-server secrets (LLMs create placeholders, admins set values)
- **Separate MCP Gateway** — tunnel-exposed service physically cannot serve admin endpoints
- **Timing-Safe Auth** — constant-time token comparison via `secrets.compare_digest`

### Cloudflare Remote Access

- Named tunnels with Workers VPC (no public URL)
- OAuth 2.1 + OIDC authentication via Cloudflare Access for SaaS
- [Automated setup wizard](docs/CLOUDFLARE-SETUP-WIZARD.md) handles tunnel, worker, DNS, and MCP server configuration
- Works with Claude, ChatGPT, Cursor, and any MCP-compatible client

## Documentation

**[View the full documentation](https://jgthb.github.io/MCPbox/)**

| Document | Description |
|----------|-------------|
| [Installation](https://jgthb.github.io/MCPbox/getting-started/installation.html) | Get MCPBox up and running |
| [Quick Start](https://jgthb.github.io/MCPbox/getting-started/quick-start.html) | First-time setup and UI tour |
| [Creating Your First Tool](https://jgthb.github.io/MCPbox/guides/first-tool.html) | End-to-end tool creation walkthrough |
| [MCP Management Tools](https://jgthb.github.io/MCPbox/reference/mcp-tools.html) | Full reference for all 28 `mcpbox_*` tools |
| [Remote Access Setup](https://jgthb.github.io/MCPbox/guides/remote-access.html) | Cloudflare tunnel configuration |
| [Developer Docs](https://jgthb.github.io/MCPbox/developer/) | Architecture, security, API contracts, and more |

## Running Tests

```bash
# All checks (format, lint, tests) — what CI runs
./scripts/pre-pr-check.sh

# Individual test suites
cd backend && pytest tests -v       # requires Docker (testcontainers)
cd sandbox && pytest tests -v
cd frontend && npm test
cd worker && npm test
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

MCPbox is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

- **Personal/Non-Commercial Use**: Free
- **Commercial Use**: Requires a commercial license (contact for pricing)

## Security

If you discover a security vulnerability, please open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) on this repository instead of opening a public issue.
