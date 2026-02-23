---
title: Backups & Recovery
parent: Operations
nav_order: 2
---

# Backups & Recovery

MCPBox stores all state in PostgreSQL. Regular backups protect against data loss.

## Manual Backup

```bash
docker compose exec -T postgres pg_dump -U mcpbox mcpbox > backup_$(date +%Y%m%d_%H%M%S).sql
```

## Automated Backups

Add a cron job for daily backups:

```bash
# Add to crontab (daily at 2am)
0 2 * * * cd /path/to/MCPbox && docker compose exec -T postgres pg_dump -U mcpbox mcpbox | gzip > /backups/mcpbox_$(date +\%Y\%m\%d).sql.gz
```

## Restore from Backup

```bash
# Stop services (keep postgres running)
docker compose stop backend mcp-gateway sandbox frontend

# Restore
docker compose exec -T postgres psql -U mcpbox mcpbox < backup.sql

# Re-run migrations in case the backup is from an older version
docker compose run --rm backend alembic upgrade head

# Restart
docker compose up -d
```

## Export/Import

MCPBox also supports JSON export/import for tool configurations via the admin API:

- **Export:** `POST /api/export` — exports servers, tools, and configuration as JSON
- **Import:** `POST /api/import` — imports from a JSON export

This is useful for migrating tools between MCPBox instances. Note that this does not include secret values or database state — use PostgreSQL backups for full recovery.
