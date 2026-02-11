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
| `MCPBOX_ENCRYPTION_KEY` | 32-byte hex key for credential encryption | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `openssl rand -hex 16` |
| `SANDBOX_API_KEY` | Backend-to-sandbox auth (min 32 chars) | `openssl rand -hex 32` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (from compose) | PostgreSQL connection string |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `LOG_RETENTION_DAYS` | `30` | Days to keep activity logs |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `100` | API rate limit |
### Remote Access

For Claude Web access via Cloudflare, all tokens (tunnel token, service token) are
stored in the database and managed by the setup wizard. No additional environment
variables are needed. Run `./scripts/deploy-worker.sh --set-secrets` to push
tokens to the Worker after completing the wizard.

## Database Setup

### Using Alembic Migrations (Recommended)

Always use Alembic migrations in production instead of auto-creation:

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

Integrate with your monitoring stack by scraping the health endpoints. Key metrics to watch:

- Request latency (p50, p95, p99)
- Error rates by endpoint
- Database connection pool usage
- Rate limiter bucket count

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
