# MCPbox Frontend - Production Dockerfile
# Multi-stage build: build with Node, serve with nginx

# Build stage
FROM node:20.11-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --legacy-peer-deps

# Copy source
COPY . .

# Build with backend port — derives VITE_API_URL automatically
ARG MCPBOX_BACKEND_PORT=8000
ENV VITE_API_URL=http://localhost:${MCPBOX_BACKEND_PORT}
RUN npm run build

# Production stage
FROM nginx:1.25.4-alpine

# Security: Create non-root user and pre-create nginx temp dirs
RUN adduser -D -u 1000 mcpbox && \
    mkdir -p /var/cache/nginx/client_temp \
             /var/cache/nginx/proxy_temp \
             /var/cache/nginx/fastcgi_temp \
             /var/cache/nginx/uwsgi_temp \
             /var/cache/nginx/scgi_temp \
             /etc/nginx/templates && \
    chown -R mcpbox:mcpbox /var/cache/nginx && \
    chown -R mcpbox:mcpbox /var/log/nginx && \
    chown -R mcpbox:mcpbox /etc/nginx/templates && \
    touch /var/run/nginx.pid && \
    chown -R mcpbox:mcpbox /var/run/nginx.pid

# Copy nginx config template (processed at runtime by entrypoint)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy built files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html
RUN chown -R mcpbox:mcpbox /usr/share/nginx/html

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Switch to non-root user
USER mcpbox

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:3000/nginx-health || exit 1

# Entrypoint processes nginx config template then starts nginx
ENTRYPOINT ["/docker-entrypoint.sh"]
