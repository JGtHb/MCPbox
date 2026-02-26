#!/bin/sh
set -e

# Conditionally enable HSTS header (only behind a TLS-terminating proxy)
if [ "$MCPBOX_ENABLE_HSTS" = "true" ]; then
    export MCPBOX_HSTS_HEADER='add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;'
else
    export MCPBOX_HSTS_HEADER='# HSTS disabled (set MCPBOX_ENABLE_HSTS=true to enable)'
fi

# Substitute only MCPBOX_HSTS_HEADER (preserves nginx $variables like $binary_remote_addr)
envsubst '${MCPBOX_HSTS_HEADER}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
