---
title: Installation
parent: Getting Started
nav_order: 1
---

# Installation

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- ~5.5 CPU cores and ~3 GB RAM available (container ceilings; actual usage is typically lower)

No other dependencies are required — everything runs in containers.

## Install

```bash
git clone -b main https://github.com/JGtHb/MCPbox.git
cd MCPbox
```

The `main` branch contains stable releases. The `develop` branch has the latest changes and is used for contributions.

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
Each secret must be a unique value. MCPBox checks on startup and logs a warning if duplicates are detected.

See [Environment Variables]({{ site.baseurl }}/reference/environment-variables.html) for the full list of optional settings.

## Start

```bash
docker compose up -d
```

Database migrations run automatically on first startup. You can check the backend logs to confirm:

```bash
docker compose logs backend | grep "migrations"
```

Open [http://localhost:3000](http://localhost:3000) in your browser to access the admin UI.

## Next Steps

- [Quick Start]({{ site.baseurl }}/getting-started/quick-start.html) — Set up your admin account and tour the UI
- [Connecting MCP Clients]({{ site.baseurl }}/getting-started/connecting-clients.html) — Point your LLM at MCPBox
