#!/bin/sh
set -e

# Default backend port if not set
MCPBOX_BACKEND_PORT="${MCPBOX_BACKEND_PORT:-8000}"
export MCPBOX_BACKEND_PORT

# Process nginx config template — only substitute our variable, not nginx's $uri etc.
envsubst '${MCPBOX_BACKEND_PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
