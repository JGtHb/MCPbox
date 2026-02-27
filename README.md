# MCPbox

A self-hosted platform where your LLM creates its own tools. When it needs a capability that doesn't exist yet, it writes Python code, you approve it, and it becomes a permanent MCP tool running in a sandbox. Optionally approve each tool, library, and network request before it goes live.

[![CI](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml/badge.svg)](https://github.com/JGtHb/MCPbox/actions/workflows/ci.yml)

![MCPbox Dashboard](docs/images/dashboard.png)

> [!WARNING]
> **Active Development** — Expect breaking changes, incomplete features, and rough edges. Pin to a specific release if you need stability.

> [!CAUTION]
> **AI-Generated Codebase** — This repository was entirely coded by Claude (Opus 4.6). It includes tests, security reviews, and CI, but review the code yourself before running it — especially the sandbox execution and authentication components.

---

## How It Works

MCPbox exposes 28 `mcpbox_*` management tools over MCP. The LLM uses them to create servers, write tool code, request approval, and manage the lifecycle. Admins approve tools through the web UI before they go live.

Example — you ask "Is Claude having issues right now?" and no tool exists for that yet:

```
1. mcpbox_create_server   → "uptime" server created
2. mcpbox_create_tool     → claude_status tool (Python: fetch Anthropic status page)
3. mcpbox_test_code       → test passes, returns JSON
4. mcpbox_request_publish → submitted for admin approval
```

Admin approves in the web UI.

```
5. mcpbox_start_server    → server is live
6. claude_status          → calls the tool it just built
```

The tool persists. Next time, the LLM calls `claude_status` directly.

---

## Features

- **Tool creation via MCP** — LLM writes Python, it becomes a permanent MCP tool
- **External MCP sources** — proxy existing MCP servers through MCPbox
- **Approval workflow** — tools start as drafts, admin reviews code and approves before publishing
- **Sandboxed execution** — restricted builtins, import whitelisting, network controls, SSRF prevention, 256MB/60s limits
- **Encrypted secrets** — AES-256-GCM per-server; LLM creates placeholders, admin sets values
- **Execution logging** — inputs, outputs, duration, and errors for every call
- **Self-hosted** — single `docker compose up`, runs on any homelab or VPS
- **Remote access** — optional Cloudflare tunnel with OAuth 2.1 (works with claude.ai, ChatGPT, Cursor, etc.)

---

## Quick Start

```bash
git clone https://github.com/JGtHb/MCPbox.git
cd MCPbox

cp .env.example .env

# Generate required secrets
echo "MCPBOX_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "SANDBOX_API_KEY=$(openssl rand -hex 32)" >> .env

# Run migrations, then start
docker compose run --rm backend alembic upgrade head
docker compose up -d
```

Open http://localhost:3000 to create your admin account.

### Connect an MCP Client

Add to your MCP client config (Claude Code, Cursor, etc.):

```json
{
  "mcpServers": {
    "mcpbox": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

The 28 `mcpbox_*` management tools are discovered automatically.

For remote access outside your network, see [Remote Access Setup](https://jgthb.github.io/MCPbox/guides/remote-access.html).

## Documentation

**[Full docs](https://jgthb.github.io/MCPbox/)**

| Document | Description |
|----------|-------------|
| [Installation](https://jgthb.github.io/MCPbox/getting-started/installation.html) | Setup and requirements |
| [Quick Start](https://jgthb.github.io/MCPbox/getting-started/quick-start.html) | First-time setup and UI tour |
| [Creating Your First Tool](https://jgthb.github.io/MCPbox/guides/first-tool.html) | End-to-end tool creation walkthrough |
| [MCP Tools Reference](https://jgthb.github.io/MCPbox/reference/mcp-tools.html) | All 28 `mcpbox_*` tools |
| [Remote Access](https://jgthb.github.io/MCPbox/guides/remote-access.html) | Cloudflare tunnel setup |
| [Developer Docs](https://jgthb.github.io/MCPbox/developer/) | Architecture, security, API contracts |

## License

[PolyForm Noncommercial License 1.0.0](LICENSE). Free for personal/non-commercial use. Commercial use requires a separate license.

## Security

Found a vulnerability? Open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) instead of a public issue.
