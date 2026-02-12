# MCPbox Frontend - Production Dockerfile
# Multi-stage build: build with Node, serve with nginx

# Build stage
FROM node:20.11-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production=false

# Copy source
COPY . .

# Build with optional API URL override
# Default: http://localhost:8000 (set in src/api/client.ts)
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# Production stage
FROM nginx:1.25.4-alpine

# Security: Create non-root user
RUN adduser -D -u 1000 mcpbox && \
    chown -R mcpbox:mcpbox /var/cache/nginx && \
    chown -R mcpbox:mcpbox /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R mcpbox:mcpbox /var/run/nginx.pid

# Copy nginx configuration template
# Note: HSTS is enabled by default for production (behind HTTPS proxy like Cloudflare)
# Set ENABLE_HSTS=false to disable if running behind non-HTTPS proxy
COPY <<EOF /etc/nginx/conf.d/default.conf
server {
    listen 3000;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
    # HSTS - enforces HTTPS for 1 year (enabled for production behind Cloudflare)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    # CSP - production policy for React SPA with Monaco Editor
    # - script-src: 'self' + 'unsafe-inline' for React, blob: for Monaco workers
    # - style-src: 'self' + 'unsafe-inline' for styled components
    # - worker-src: blob: for Monaco Editor web workers
    # - connect-src: 'self' + localhost:8000 for API calls + ws:/wss: for WebSocket
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' http://localhost:8000 ws: wss:; worker-src 'self' blob:; frame-ancestors 'self';" always;

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # SPA routing - fallback to index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Health check endpoint
    location /nginx-health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
EOF

# Copy built files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html
RUN chown -R mcpbox:mcpbox /usr/share/nginx/html

# Switch to non-root user
USER mcpbox

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:3000/nginx-health || exit 1

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
