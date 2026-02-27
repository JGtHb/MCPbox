---
title: Upgrading
parent: Guides
nav_order: 5
---

# Upgrading

## Before You Upgrade

Always back up your database first:

```bash
docker compose exec -T postgres pg_dump -U mcpbox mcpbox > backup_pre_upgrade.sql
```

## Upgrade Steps

```bash
# 1. Pull latest release
git checkout main
git pull

# 2. Rebuild containers
docker compose build

# 3. Run database migrations
docker compose run --rm backend alembic upgrade head

# 4. Restart services
docker compose up -d
```

If you use remote access, also restart the tunnel:

```bash
docker compose --profile remote up -d cloudflared
```

## Verify

```bash
curl http://localhost:8000/health
```

Check the admin UI at [http://localhost:3000](http://localhost:3000) to confirm everything is working.

## Rollback

If something goes wrong:

```bash
# Stop services
docker compose down

# Revert code
git checkout <previous-commit>
docker compose build

# Restore database
docker compose up -d postgres
docker compose exec -T postgres psql -U mcpbox mcpbox < backup_pre_upgrade.sql

# Restart
docker compose up -d
```

{: .important }
Always take a database backup before upgrading. Alembic `downgrade` can reverse schema changes, but it cannot restore deleted data.
