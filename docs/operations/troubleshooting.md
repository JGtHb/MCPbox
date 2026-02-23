---
title: Troubleshooting
parent: Operations
nav_order: 3
---

# Troubleshooting

## Database Connection Errors

**Symptoms:** Health check returns `"database": "disconnected"`, API requests fail with 500.

```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check database logs
docker compose logs --tail=50 postgres

# Restart PostgreSQL
docker compose restart postgres

# Wait for recovery
watch -n2 'curl -s http://localhost:8000/health'
```

## Migration Failures

```bash
# Check current migration state
docker compose run --rm backend alembic current

# See what's pending
docker compose run --rm backend alembic history

# Re-run migrations
docker compose run --rm backend alembic upgrade head
```

## "Session Terminated" MCP Errors

**Symptoms:** MCP clients intermittently get "Session terminated" errors (~50% of requests fail).

**Cause:** The MCP gateway must run with exactly 1 worker. MCP Streamable HTTP is stateful — sessions are stored in memory, so multiple workers cause session mismatches.

```bash
# Verify mcp-gateway is running with --workers 1
docker compose logs mcp-gateway | grep -i "worker\|started"

# Restart
docker compose restart mcp-gateway
```

## Sandbox Failures

**Symptoms:** Tool execution fails, health shows `"sandbox": "disconnected"`.

```bash
# Check sandbox container
docker compose ps sandbox
docker compose logs --tail=50 sandbox

# Restart — server recovery happens automatically
docker compose restart sandbox

# If automatic recovery failed, restart backend too
docker compose restart backend mcp-gateway
```

After a sandbox restart, the backend automatically re-registers all running servers with the sandbox.

## Rate Limiting (429 Errors)

```bash
# Temporarily increase the limit
export RATE_LIMIT_REQUESTS_PER_MINUTE=500
docker compose up -d backend

# Or restart to clear in-memory state
docker compose restart backend
```

## Tunnel Not Connecting (Remote Access)

```bash
# Check cloudflared logs
docker compose logs --tail=50 cloudflared

# If tunnel token is invalid, re-run the setup wizard
# Navigate to http://localhost:3000/tunnel/setup

# Re-sync Worker secrets
./scripts/deploy-worker.sh --set-secrets
```

## Service Token Mismatch (403 on Remote MCP)

```bash
# Re-sync Worker secrets with database
./scripts/deploy-worker.sh --set-secrets

# Restart MCP gateway to clear token cache
docker compose restart mcp-gateway
```

## General Recovery Checklist

After any incident:

- [ ] All services healthy: `curl http://localhost:8000/health/services`
- [ ] Circuit breakers closed: `curl http://localhost:8000/health/circuits`
- [ ] Review activity logs for anomalies
- [ ] Test remote access if configured
