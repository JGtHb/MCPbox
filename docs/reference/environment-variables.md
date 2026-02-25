---
title: Environment Variables
parent: Reference
nav_order: 2
---

# Environment Variables

All configuration is done via the `.env` file in the project root.

## Required

| Variable | Description | How to generate |
|----------|-------------|-----------------|
| `MCPBOX_ENCRYPTION_KEY` | 32-byte hex key for encrypting server secrets (AES-256-GCM) | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | PostgreSQL database password | `openssl rand -hex 16` |
| `SANDBOX_API_KEY` | Backend-to-sandbox authentication key (min 32 chars) | `openssl rand -hex 32` |

{: .important }
Each secret must be a unique value. MCPBox validates on startup that secrets are different and logs a warning if duplicates are detected.

## Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_KEY` | derived from `MCPBOX_ENCRYPTION_KEY` | JWT signing key for admin panel auth. Set explicitly for better security. |
| `MCPBOX_FRONTEND_PORT` | `3000` | Host port for the web UI (Docker port binding only) |
| `MCPBOX_BACKEND_PORT` | `8000` | Host port for the backend API (Docker port binding only) |
| `CORS_ORIGINS` | `http://localhost:3000` | Admin CORS origins (only needed for direct backend access) |
| `MCP_CORS_ORIGINS` | `https://mcp.claude.ai,https://claude.ai,https://chatgpt.com,https://chat.openai.com,https://platform.openai.com` | MCP gateway CORS origins |
| `LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

{: .warning }
**Port changes affect MCP client config.** If you change `MCPBOX_BACKEND_PORT`, you must also update your MCP client configuration to match. For example, if you set `MCPBOX_BACKEND_PORT=9000`, your MCP client URL becomes `http://localhost:9000/mcp` instead of `http://localhost:8000/mcp`.

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (from compose) | PostgreSQL connection string |
| `DB_POOL_SIZE` | `20` | Base connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Additional connections allowed above pool size |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a connection |
| `DB_POOL_RECYCLE` | `1800` | Recycle connections after this many seconds |

## Runtime Settings (Admin UI)

The following settings are configured via the admin UI or API (`PATCH /api/settings/security-policy`), not environment variables:

- **Log retention days** (default: 30)
- **Rate limit requests per minute** (default: 100)
- **Alert webhook URL** for critical alerts (Discord, Slack, or generic HTTP)

## Remote Access

Remote access tokens (tunnel token, service token, OIDC credentials) are stored in the database and managed by the [setup wizard]({% link guides/remote-access.md %}). No additional environment variables are needed.

After completing the wizard, run `./scripts/deploy-worker.sh --set-secrets` to push tokens to the Cloudflare Worker.
