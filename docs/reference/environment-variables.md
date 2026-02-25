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
| `MCPBOX_ENCRYPTION_KEY` | 64 hex characters (32 bytes) for encrypting server secrets (AES-256-GCM) | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | PostgreSQL database password | `openssl rand -hex 16` |
| `SANDBOX_API_KEY` | Backend-to-sandbox authentication key (min 32 chars) | `openssl rand -hex 32` |

{: .important }
Each secret must be a unique value. MCPBox checks on startup that secrets are different and logs a warning if duplicates are detected (startup continues).

## Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_KEY` | derived from `MCPBOX_ENCRYPTION_KEY` | JWT signing key for admin panel auth. Set explicitly for better security. |
| `MCPBOX_FRONTEND_PORT` | `3000` | Host port for the web UI (Docker port binding only) |
| `MCPBOX_BACKEND_PORT` | `8000` | Host port for the backend API (Docker port binding only) |
| `CORS_ORIGINS` | `http://localhost:3000` | Admin CORS origins (only needed for direct backend access) |
| `MCP_CORS_ORIGINS` | `https://mcp.claude.ai,https://claude.ai,https://chatgpt.com,https://chat.openai.com,https://platform.openai.com` | MCP gateway CORS origins |
| `LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DEBUG` | `False` | Enable debug mode |
| `ENABLE_METRICS` | `True` | Enable Prometheus metrics endpoint at `/metrics` |

## HTTP Client

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_TIMEOUT` | `30.0` | HTTP client timeout in seconds |
| `HTTP_MAX_CONNECTIONS` | `10` | Maximum HTTP connection pool size |
| `HTTP_KEEPALIVE_CONNECTIONS` | `5` | HTTP keepalive connection pool size |

## JWT Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token expiry in minutes |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token expiry in days |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |

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

## Cloudflare Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `CF_WORKER_COMPATIBILITY_DATE` | `2025-03-01` | Cloudflare Worker compatibility date |
| `CF_WORKER_COMPATIBILITY_FLAGS` | `nodejs_compat` | Cloudflare Worker compatibility flags |

## Runtime Settings (Admin UI)

The following settings can be configured via the admin UI or API (`PATCH /api/settings/security-policy`). `RATE_LIMIT_REQUESTS_PER_MINUTE` and `ALERT_WEBHOOK_URL` can also be set as environment variables for initial defaults.

| Setting | Default | Description |
|---------|---------|-------------|
| Log retention days | `30` | How long to keep activity and execution logs |
| Rate limit requests per minute | `100` | Per-IP API rate limit (also settable via `RATE_LIMIT_REQUESTS_PER_MINUTE` env var) |
| Alert webhook URL | (none) | Webhook for critical alerts — Discord, Slack, or generic HTTP (also settable via `ALERT_WEBHOOK_URL` env var) |

## Remote Access

Remote access tokens (tunnel token, service token, OIDC credentials) are stored in the database and managed by the [setup wizard]({% link guides/remote-access.md %}). No additional environment variables are needed.

After completing the wizard, run `./scripts/deploy-worker.sh --set-secrets` to push tokens to the Cloudflare Worker.
