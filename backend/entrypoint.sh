#!/bin/bash
set -e

# Only run migrations from the main backend (port 8000), not the MCP gateway.
# Both services share the same Docker image; this prevents a race condition
# where two containers try to migrate simultaneously on first startup.
if echo "$@" | grep -q "8000"; then
    echo "Running database migrations..."
    if ! alembic upgrade head 2>&1; then
        echo ""
        echo "ERROR: Database migration failed."
        echo "  Check that PostgreSQL is running and DATABASE_URL is correct."
        echo "  To retry manually: docker compose run --rm backend alembic upgrade head"
        echo ""
        exit 1
    fi
    echo "Database migrations completed successfully."
fi

echo "Starting application..."
exec "$@"
