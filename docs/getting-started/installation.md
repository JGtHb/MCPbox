---
title: Installation
parent: Getting Started
nav_order: 1
---

# Installation

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- ~2.5 CPU cores and ~2.5 GB RAM available

No other dependencies are required — everything runs in containers.

## Install

```bash
git clone https://github.com/JGtHb/MCPbox.git
cd MCPbox
```

## Configure

Copy the example environment file and generate the required secrets:

```bash
cp .env.example .env

# Generate secrets and append to .env
echo "MCPBOX_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "SANDBOX_API_KEY=$(openssl rand -hex 32)" >> .env
```

| Variable | Purpose |
|----------|---------|
| `MCPBOX_ENCRYPTION_KEY` | Encrypts server secrets (AES-256-GCM). Must be 64 hex characters. |
| `POSTGRES_PASSWORD` | PostgreSQL database password. |
| `SANDBOX_API_KEY` | Authenticates backend-to-sandbox communication. Min 32 characters. |

{: .important }
Each secret must be a unique value. MCPBox validates this on startup.

See [Environment Variables]({% link reference/environment-variables.md %}) for the full list of optional settings.

## Start

```bash
# Run database migrations
docker compose run --rm backend alembic upgrade head

# Start all services
docker compose up -d
```

## Verify

Check that all services are healthy:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "healthy"}
```

Open [http://localhost:3000](http://localhost:3000) in your browser to access the admin UI.

## Next Steps

- [Quick Start]({% link getting-started/quick-start.md %}) — Set up your admin account and tour the UI
- [Connecting MCP Clients]({% link getting-started/connecting-clients.md %}) — Point your LLM at MCPBox
