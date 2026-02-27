# MCPbox

**A self-extending MCP platform where LLMs create their own tools.**

MCPbox lets AI create, test, and manage its own MCP tools — write Python code, register it as a permanent tool, and use it in future conversations. Think of it as a tool forge: the LLM is both the toolmaker and the tool user.

[![CI](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml/badge.svg)](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml)

![MCPbox Dashboard](docs/images/dashboard.png)

> [!WARNING]
> **Active Development** — This project is under active development. Expect breaking changes, incomplete features, and rough edges. Pin to a specific commit if you need stability.

> [!CAUTION]
> **AI-Generated Codebase** — This repository was entirely coded by Claude (Opus 4.6). While it includes tests, security reviews, and CI checks, you should review the code yourself before running it in any environment. Evaluate your own comfort level with AI-generated code, especially for the sandbox execution and authentication components.

---

## What is MCPbox?

MCPbox is a self-hosted platform that puts you in complete control of your AI's capabilities.

**Your tools, your way.** The LLM writes Python code, you review and approve it, and it becomes a permanent tool — totally personal, built for your exact workflow. No marketplace, no generic plugins, no vendor lock-in. You own every line of code.

**Fully observable.** Every tool execution is logged with inputs, outputs, duration, and errors. Built-in dashboards show request volume, error rates, and execution history. You always know exactly what your AI is doing.

**You set the boundaries.** Tools start in draft. You review the code, approve what you trust, and control which modules and network hosts each tool can access. The LLM proposes — you decide. But within those boundaries, the sky's the limit.

- **LLM as Toolmaker** — write Python code via `mcpbox_create_tool`, it becomes a permanent MCP tool
- **MCP Gateway** — proxy existing MCP servers through MCPbox with `mcpbox_add_external_source`
- **Human-in-the-Loop** — tools are created in draft; admins review and approve before publishing
- **Sandboxed Execution** — restricted builtins, import whitelisting, network controls, SSRF prevention
- **Self-Hosted** — single `docker compose up`, runs on any homelab or VPS
- **Remote Access** — optional Cloudflare tunnel with OAuth 2.1 for access from anywhere

---

## See It in Action

> **You:** Is Claude having issues right now?
>
> **LLM:** I don't have a tool for that yet — let me build one.

```
1. mcpbox_create_server   → "uptime" server created
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

Open http://localhost:3000 to create your admin account and access the web UI.

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

For remote access from claude.ai, ChatGPT, or any MCP client outside your network, see [Remote Access Setup](https://jgthb.github.io/MCPbox/guides/remote-access.html) to configure a Cloudflare tunnel with OAuth 2.1 authentication.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MCPbox (Docker Compose)                   │
│                                                             │
│  ┌──────────┐  ┌──────────┐           ┌──────────────┐     │
│  │ Frontend │  │ Backend  │           │ MCP Gateway  │     │
│  │ (React)  │──│ (FastAPI)│           │ (FastAPI)    │     │
│  │ :3000    │  │ :8000    │           │ :8002        │     │
│  └──────────┘  └────┬─────┘           └──────┬───────┘     │
│                     │                        │              │
│                     └────────┬───────────────┘              │
│                              ▼                              │
│                ┌──────────────────────┐  ┌────────────┐     │
│                │   Sandbox  :8001     │  │ PostgreSQL │     │
│                │  (Python executor)   │  │  :5432     │     │
│                └──────────────────────┘  └────────────┘     │
└─────────────────────────────────────────────────────────────┘
       ▲                              ▲
       │ Local MCP clients            │ cloudflared tunnel (outbound)
       │ localhost:8000/mcp           │
                               ┌──────┴───────────────┐
                               │  Cloudflare Edge      │
                               │  Worker (OAuth 2.1)   │
                               └──────┬───────────────┘
                                      │
                               Remote MCP Clients
```

Two modes: **Local** (MCP client connects to `localhost:8000/mcp`, no auth) and **Remote** (OAuth 2.1 via Cloudflare Worker + tunnel to the MCP gateway).

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

## License

MCPbox is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

- **Personal/Non-Commercial Use**: Free
- **Commercial Use**: Requires a commercial license (contact for pricing)

## Security

If you discover a security vulnerability, please open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) on this repository instead of opening a public issue.
