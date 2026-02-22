#!/bin/sh
set -e

# Default backend port if not set
MCPBOX_BACKEND_PORT="${MCPBOX_BACKEND_PORT:-8000}"
export MCPBOX_BACKEND_PORT

# Generate runtime config for React app (served via nginx alias from /tmp)
# This allows changing MCPBOX_BACKEND_PORT without rebuilding the image
cat > /tmp/config.js <<EOF
window.__MCPBOX_CONFIG__ = {
  API_URL: "http://localhost:${MCPBOX_BACKEND_PORT}"
};
EOF

# Process nginx config template — only substitute our variable, not nginx's $uri etc.
envsubst '${MCPBOX_BACKEND_PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
