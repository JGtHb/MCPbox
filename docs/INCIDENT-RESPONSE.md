# Incident Response Runbooks

Operational runbooks for common failure scenarios in MCPbox.

---

## 1. Database Failure

**Symptoms:** Health check returns `"database": "disconnected"`, 503 on `/health`, API requests fail with 500 errors.

### Diagnosis

```bash
# Check PostgreSQL container
docker-compose ps postgres

# Check database logs
docker-compose logs --tail=50 postgres

# Test connection from backend
docker-compose exec backend python -c "
from app.core.database import engine
import asyncio
print(asyncio.run(engine.dialect.do_ping(engine)))
"

# Check connection pool status
curl http://localhost:8000/health/services | python -m json.tool
```

### Resolution

```bash
# Restart PostgreSQL
docker-compose restart postgres

# Wait for health check to recover
watch -n2 'curl -s http://localhost:8000/health | python -m json.tool'

# If data corruption suspected, restore from backup
docker-compose stop postgres
docker-compose exec -T postgres psql -U mcpbox mcpbox < backup.sql
docker-compose start postgres
```

### If Database Is Unrecoverable

```bash
# Stop all services
docker-compose down

# Restore from latest backup
docker-compose up -d postgres
docker-compose exec -T postgres psql -U mcpbox mcpbox < /backups/latest.sql.gz

# Re-run migrations in case backup is from an older version
docker-compose run --rm backend alembic upgrade head

# Restart all services
docker-compose up -d
```

---

## 2. Sandbox Failure / Tool Registration Loss

**Symptoms:** Tool execution fails, health check shows `"sandbox": "disconnected"`, circuit breaker opens. After sandbox restart, servers show "running" but tools return "not found".

### Diagnosis

```bash
# Check sandbox container
docker-compose ps sandbox

# Check sandbox logs
docker-compose logs --tail=50 sandbox

# Check circuit breaker state
curl http://localhost:8000/health/circuits | python -m json.tool

# Test sandbox health directly
docker-compose exec sandbox curl -s http://localhost:8001/health
```

### Resolution

```bash
# Restart sandbox container
docker-compose restart sandbox

# Server recovery happens automatically — backend and mcp-gateway both run
# a background task (server_recovery.py) that re-registers all "running"
# servers with the sandbox on startup. Check logs for recovery status:
docker-compose logs --tail=20 backend | grep -i "recover"
docker-compose logs --tail=20 mcp-gateway | grep -i "recover"

# If automatic recovery failed, restart backend/mcp-gateway to trigger it again:
docker-compose restart backend mcp-gateway

# If circuit breaker is stuck open, reset it (requires admin JWT)
curl -X POST http://localhost:8000/health/circuits/reset \
  -H "Authorization: Bearer <admin-jwt-token>"

# If sandbox is OOM-killed, check resource limits
docker-compose logs sandbox | grep -i "killed\|oom"

# Increase memory limit if needed (in docker-compose.yml)
# sandbox service: mem_limit: 2g (default: 1g)
```

---

## 3. Encryption Key Compromise

**Symptoms:** Suspected unauthorized access to `MCPBOX_ENCRYPTION_KEY`.

### Immediate Actions

1. **Rotate the key immediately:**

```bash
# Generate a new key
NEW_KEY=$(openssl rand -hex 32)

# Run the rotation utility
python scripts/rotate_encryption_key.py \
  --old-key "$CURRENT_KEY" \
  --new-key "$NEW_KEY" \
  --dry-run  # Verify first

# Execute the rotation
python scripts/rotate_encryption_key.py \
  --old-key "$CURRENT_KEY" \
  --new-key "$NEW_KEY"
```

2. **Update the environment:**

```bash
# Update .env file
sed -i "s/MCPBOX_ENCRYPTION_KEY=.*/MCPBOX_ENCRYPTION_KEY=$NEW_KEY/" .env

# Restart services
docker-compose restart backend mcp-gateway
```

3. **Rotate all stored server secrets** — even after re-encryption, treat any stored API keys/tokens as potentially compromised. Re-issue them at their respective providers and update the secret values in the MCPbox admin UI.

---

## 4. Tunnel Disconnection

**Symptoms:** Remote users (Claude Web) cannot reach MCPbox, cloudflared logs show connection errors.

### Diagnosis

```bash
# Check cloudflared container
docker-compose ps cloudflared

# Check tunnel logs
docker-compose logs --tail=50 cloudflared

# Verify tunnel token is valid
docker-compose exec backend curl -s http://localhost:8000/internal/active-tunnel-token \
  -H "Authorization: Bearer $SANDBOX_API_KEY" | python -m json.tool
```

### Resolution

```bash
# Restart cloudflared
docker-compose restart cloudflared

# If tunnel token expired or invalid, re-run setup wizard
# Navigate to http://localhost:3000/tunnel/setup

# Re-deploy Worker if needed
./scripts/deploy-worker.sh --set-secrets
```

---

## 5. Service Token Mismatch

**Symptoms:** Remote MCP requests return 403, logs show "Service token mismatch".

### Diagnosis

```bash
# Check MCP gateway logs
docker-compose logs --tail=50 mcp-gateway | grep -i "service.token\|403"

# Verify service token is configured
docker-compose exec backend python -c "
import asyncio
from app.api.auth_simple import ServiceTokenCache
cache = ServiceTokenCache()
# Token is loaded from database on first access
"
```

### Resolution

```bash
# Re-sync Worker secrets with database
./scripts/deploy-worker.sh --set-secrets

# Restart MCP gateway to clear token cache
docker-compose restart mcp-gateway
```

---

## 6. Rate Limiting / 429 Errors

**Symptoms:** Users receive 429 Too Many Requests.

### Diagnosis

```bash
# Check rate limiter state (in-memory, resets on restart)
docker-compose logs backend | grep -i "rate.limit\|429"
```

### Resolution

```bash
# Temporarily increase rate limit
export RATE_LIMIT_REQUESTS_PER_MINUTE=500
docker-compose up -d backend

# Or restart to clear in-memory state
docker-compose restart backend
```

**Note:** Rate limit state is in-memory and per-worker. Restarting clears all state.

---

## 7. "Session Terminated" MCP Errors

**Symptoms:** MCP clients intermittently receive "Session terminated" errors. Roughly 50% of requests fail.

### Diagnosis

This is almost always caused by running the MCP gateway with more than 1 worker. MCP Streamable HTTP is stateful — the `Mcp-Session-Id` header must always reach the same worker process.

```bash
# Check if mcp-gateway is running with multiple workers
docker-compose logs mcp-gateway | grep -i "worker\|started"

# Check session creation/termination in logs
docker-compose logs mcp-gateway | grep -i "session"
```

### Resolution

```bash
# Ensure docker-compose.yml has --workers 1 for mcp-gateway
# The command should be:
# ["python", "-m", "uvicorn", "app.mcp_only:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1", ...]

# Restart mcp-gateway
docker-compose restart mcp-gateway
```

**Root cause:** `--workers N` spawns N separate Python processes, each with its own in-memory `_active_sessions` dict. Session created on Worker A gets routed to Worker B on the next request, which doesn't know about it.

---

## 8. Sandbox Escape Attempt

**Symptoms:** Activity logs show blocked code patterns, `validate_code_safety` rejections.

### Diagnosis

```bash
# Check activity logs for safety violations
docker-compose logs sandbox | grep -i "safety\|forbidden\|blocked\|__class__\|__subclasses__"

# Check the admin activity log UI
# Navigate to http://localhost:3000/activity
```

### Response

1. Identify the tool and user that triggered the violation
2. Review the tool's code in the admin UI at `/tools`
3. If the tool was approved, revoke it (set status to `rejected`)
4. Review the approval queue for any pending tools from the same source
5. Check if the attempt was via remote access — if so, review Cloudflare Access logs

---

## General Recovery Checklist

After any incident:

- [ ] Verify all services healthy: `curl http://localhost:8000/health/services`
- [ ] Check circuit breakers are closed: `curl http://localhost:8000/health/circuits`
- [ ] Review activity logs for anomalies
- [ ] Verify remote access works (if configured): test from Claude Web
- [ ] Document the incident and update this runbook if needed
