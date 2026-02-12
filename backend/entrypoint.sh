#!/bin/bash
set -e

# Only run migrations from the main backend (port 8000), not the MCP gateway.
# Both services share the same Docker image; this prevents a race condition
# where two containers try to migrate simultaneously on first startup.
if echo "$@" | grep -q "8000"; then
    echo "Running database migrations..."
    alembic upgrade head
fi

echo "Starting application..."
exec "$@"
