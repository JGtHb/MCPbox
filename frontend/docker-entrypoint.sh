#!/bin/sh
set -e

# Copy nginx config template (no variable substitution needed —
# nginx proxies to backend:8000 on the Docker network directly)
cp /etc/nginx/templates/default.conf.template /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
