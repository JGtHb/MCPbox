# Production Deployment Guide

This guide covers deploying MCPbox in a production environment.

## Prerequisites

- Docker and Docker Compose
- PostgreSQL database (or use the included container)
- (Optional) Cloudflare account for remote access

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/your-org/MCPbox.git
cd MCPbox

# 2. Create environment file
cp .env.example .env

# 3. Generate secrets
echo "MCPBOX_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "SANDBOX_API_KEY=$(openssl rand -hex 32)" >> .env

# 4. Run database migrations
docker-compose run --rm backend alembic upgrade head

# 5. Start all services
docker-compose up -d
```

## Environment Variables

### Required Variables

| Variable | Description | Generation |
|----------|-------------|------------|
| `MCPBOX_ENCRYPTION_KEY` | 32-byte hex key for server secret encryption | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `openssl rand -hex 16` |
| `SANDBOX_API_KEY` | Backend-to-sandbox auth (min 32 chars) | `openssl rand -hex 32` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (from compose) | PostgreSQL connection string |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `LOG_RETENTION_DAYS` | `30` | Days to keep activity logs |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `100` | API rate limit |
| `ENABLE_METRICS` | `true` | Enable Prometheus `/metrics` endpoint |
| `ALERT_WEBHOOK_URL` | (none) | Webhook URL for critical alerts (Discord, Slack) |

### Remote Access

For Claude Web access via Cloudflare, all tokens (tunnel token, service token) are
stored in the database and managed by the setup wizard. No additional environment
variables are needed. Run `./scripts/deploy-worker.sh --set-secrets` to push
tokens to the Worker after completing the wizard.

## Database Setup

### Using Alembic Migrations (Recommended)

Always use Alembic migrations in production instead of auto-creation.

**Recent migrations:**
- `0029_add_server_secrets` — Creates `server_secrets` table for encrypted per-server key-value secrets
- `0030_add_tool_execution_logs` — Creates `tool_execution_logs` table for tool invocation history

```bash
# Run all pending migrations
docker-compose run --rm backend alembic upgrade head

# Check current migration state
docker-compose run --rm backend alembic current

# View migration history
docker-compose run --rm backend alembic history
```

### Database Backup

Set up regular PostgreSQL backups:

```bash
# Create a backup
docker-compose exec postgres pg_dump -U mcpbox mcpbox > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
docker-compose exec -T postgres psql -U mcpbox mcpbox < backup.sql
```

Consider using a cron job for automated backups:

```bash
# Add to crontab (daily at 2am)
0 2 * * * cd /path/to/MCPbox && docker-compose exec -T postgres pg_dump -U mcpbox mcpbox | gzip > /backups/mcpbox_$(date +\%Y\%m\%d).sql.gz
```

### Connection Pool Tuning

Default pool settings are suitable for most deployments:

| Setting | Default | Description |
|---------|---------|-------------|
| `DB_POOL_SIZE` | 20 | Base pool size |
| `DB_MAX_OVERFLOW` | 20 | Additional connections allowed |
| `DB_POOL_TIMEOUT` | 30 | Seconds to wait for connection |
| `DB_POOL_RECYCLE` | 1800 | Recycle connections after 30 min |

Increase pool size if you see connection timeouts under load.

## HTTPS Configuration

MCPbox should always run behind an HTTPS reverse proxy in production.

### Using Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name mcpbox.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Health checks
    location /health {
        proxy_pass http://localhost:8000;
    }
}
```

### Using Cloudflare Tunnel

For remote access, see [REMOTE-ACCESS-SETUP.md](./REMOTE-ACCESS-SETUP.md).

## Monitoring

### Health Checks

MCPbox provides health check endpoints:

```bash
# Basic health check
curl http://localhost:8000/health

# Detailed health with service status
curl http://localhost:8000/health/detail

# Individual service health
curl http://localhost:8000/health/services
```

### Prometheus Metrics

MCPbox exposes a `/metrics` endpoint (enabled by default via `ENABLE_METRICS=true`).

```bash
# Scrape metrics
curl http://localhost:8000/metrics

# MCP gateway metrics (internal network only)
curl http://mcp-gateway:8002/metrics
```

Key metrics available:

- `http_request_duration_seconds` — request latency histogram (p50, p95, p99)
- `http_requests_total` — request count by method, handler, status
- `http_request_size_bytes` — request body sizes
- `http_response_size_bytes` — response body sizes

To disable metrics, set `ENABLE_METRICS=false`.

### Webhook Alerting

Configure `ALERT_WEBHOOK_URL` to receive critical alerts via webhook. Supports Discord, Slack, and generic HTTP endpoints.

```bash
# Discord
ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/your-webhook-id/your-token

# Slack
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/your/webhook/url

# Generic HTTP
ALERT_WEBHOOK_URL=https://your-service.com/webhook
```

Alerts are sent on `log_alert()` calls (circuit breaker trips, security events, etc.).

### Log Aggregation

MCPbox logs to stdout in structured JSON format (when `DEBUG=false`). Configure your Docker logging driver:

```yaml
# docker-compose.override.yml
services:
  backend:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

For centralized logging, use a syslog driver or ship to ELK/Loki/Datadog.

## Security Checklist

Before going live, verify:

- [ ] All secrets are unique (different values for each key)
- [ ] `DEBUG=false` in production
- [ ] HTTPS configured with valid certificates
- [ ] Database backups automated
- [ ] Log aggregation configured
- [ ] Rate limiting appropriate for your use case
- [ ] CORS origins restricted to your domains
- [ ] Firewall rules: only expose ports 80/443
- [ ] Run `alembic upgrade head` to apply all migrations (including partial unique indexes)
- [ ] `SANDBOX_API_KEY` is at least 32 characters
- [ ] Remote access wizard completed and `./scripts/deploy-worker.sh --set-secrets` run (if using remote access)
- [ ] `VITE_API_URL` set at frontend build time for production builds

### Secrets Management

Generate unique secrets for each variable:

```bash
# Verify secrets are different
openssl rand -hex 32  # MCPBOX_ENCRYPTION_KEY
openssl rand -hex 32  # SANDBOX_API_KEY
# Service token is auto-generated by the wizard and stored in the database
```

MCPbox validates on startup that secrets are unique and logs a warning if duplicates are detected.

## Scaling Considerations

MCPbox is designed for single-instance homelab deployment:

- No horizontal scaling support (no Redis, no distributed state)
- Single PostgreSQL instance
- In-memory rate limiting

For higher traffic:
- Increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`
- Adjust `RATE_LIMIT_REQUESTS_PER_MINUTE`
- Consider PostgreSQL connection pooler (PgBouncer)

## Troubleshooting

### Common Issues

**Database connection errors:**
```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Check connection from backend
docker-compose exec backend python -c "from app.core.database import engine; print('OK')"
```

**Migration failures:**
```bash
# Check current state
docker-compose run --rm backend alembic current

# See what's pending
docker-compose run --rm backend alembic upgrade head --sql
```

**Rate limiting:**
```bash
# Temporarily increase limit
export RATE_LIMIT_REQUESTS_PER_MINUTE=500
docker-compose up -d backend
```

### Logs

```bash
# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f backend

# View last 100 lines
docker-compose logs --tail=100 backend
```

## Upgrading

1. Backup your database
2. Pull latest changes
3. Run migrations
4. Restart services

```bash
# Backup
docker-compose exec -T postgres pg_dump -U mcpbox mcpbox > backup_pre_upgrade.sql

# Update
git pull
docker-compose build

# Migrate
docker-compose run --rm backend alembic upgrade head

# Restart
docker-compose up -d
```

## Rollback

If an upgrade introduces issues, roll back to the previous version:

```bash
# 1. Stop services
docker-compose down

# 2. Revert to previous code
git checkout <previous-tag-or-commit>
docker-compose build

# 3. Downgrade database migrations (if the upgrade added new migrations)
# First, identify the target revision:
docker-compose run --rm backend alembic history
# Then downgrade:
docker-compose run --rm backend alembic downgrade <target-revision>

# 4. Restore database from pre-upgrade backup (if schema changes are complex)
docker-compose up -d postgres
docker-compose exec -T postgres psql -U mcpbox mcpbox < backup_pre_upgrade.sql

# 5. Restart all services
docker-compose up -d

# 6. Verify health
curl http://localhost:8000/health/services
```

**Important:** Always take a database backup before upgrading. Alembic `downgrade` reverses schema changes but cannot restore deleted data.

## Incident Response

See [INCIDENT-RESPONSE.md](./INCIDENT-RESPONSE.md) for operational runbooks covering:

- Database failure recovery
- Sandbox failure and circuit breaker reset
- Encryption key rotation
- Tunnel disconnection
- Rate limiting issues
- Sandbox escape attempts

## Configuration Reference

Hardcoded limits and timeouts across the codebase:

| Setting | Value | Location | Description |
|---------|-------|----------|-------------|
| Circuit breaker failure threshold | 5 | `core/retry.py` | Failures before circuit opens |
| Circuit breaker recovery timeout | 60s | `core/retry.py` | Seconds before half-open attempt |
| JWKS cache TTL | 300s (5 min) | `api/auth_simple.py` | Cloudflare Access JWKS cache duration |
| Tool execution timeout | 30s default | `sandbox/app/routes.py` | Per-tool, configurable up to 300s |
| Max SSE connections | 50 | `api/mcp_gateway.py` | Concurrent MCP SSE connections |
| Sandbox memory limit | 256MB | `sandbox/app/executor.py` | RLIMIT_AS per process |
| Sandbox CPU limit | 60s | `sandbox/app/executor.py` | RLIMIT_CPU (cumulative per worker) |
| Sandbox FD limit | 64 | `sandbox/app/executor.py` | RLIMIT_NOFILE per process |
| Code size limit | 100KB | `sandbox/app/routes.py` | Max python_code field size |
| Stdout capture limit | 10KB | `sandbox/app/routes.py` | Max stdout returned in response |
| SizeLimitedStringIO cap | 1MB | `sandbox/app/executor.py` | Max stdout buffer in memory |
| DB pool size | 20 | `core/config.py` | `DB_POOL_SIZE` env var |
| DB max overflow | 20 | `core/config.py` | `DB_MAX_OVERFLOW` env var |
| DB pool timeout | 30s | `core/config.py` | `DB_POOL_TIMEOUT` env var |
| Rate limit | 100/min | `core/config.py` | `RATE_LIMIT_REQUESTS_PER_MINUTE` env var |
| Log retention | 30 days | `core/config.py` | `LOG_RETENTION_DAYS` env var |
| pip install timeout | 300s | `package_installer.py` | Package installation timeout |

## Resource Requirements

Minimum recommended resources:

| Service | CPU | Memory |
|---------|-----|--------|
| Backend | 0.5 | 512MB |
| Frontend | 0.25 | 256MB |
| Sandbox | 1.0 | 1GB |
| PostgreSQL | 0.5 | 512MB |
| MCP Gateway | 0.25 | 256MB |

Total: ~2.5 CPU cores, ~2.5GB RAM
