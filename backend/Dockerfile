# MCPbox Backend - Production Dockerfile
# Multi-stage build for smaller image size and better security
#
# NOTE: Build context is the project root (not ./backend) so that
# worker source files can be included for Cloudflare Workers deployment.

FROM python:3.12.8-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.12.8-slim

# Security: Create non-root user
RUN useradd -m -u 1000 -s /bin/bash mcpbox && \
    mkdir -p /app && \
    chown -R mcpbox:mcpbox /app

WORKDIR /app

# Install runtime dependencies (curl for health checks, Node 20 for wrangler v4)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install wrangler globally for Cloudflare Workers deployment (v4 requires Node 20+)
RUN npm install -g wrangler@4

# Copy installed packages from builder
COPY --from=builder /root/.local /home/mcpbox/.local
RUN chown -R mcpbox:mcpbox /home/mcpbox/.local

# Copy application code
COPY --chown=mcpbox:mcpbox backend/app/ /app/app/
COPY --chown=mcpbox:mcpbox backend/alembic/ /app/alembic/
COPY --chown=mcpbox:mcpbox backend/alembic.ini /app/
COPY --chown=mcpbox:mcpbox backend/entrypoint.sh /app/

# Copy worker source for Cloudflare Workers deployment via the wizard.
# The wizard's deploy_worker() reads these files at runtime when deploying
# the Worker to Cloudflare. Without them, deployment fails.
COPY --chown=mcpbox:mcpbox worker/src/ /app/worker/src/
COPY --chown=mcpbox:mcpbox worker/package.json /app/worker/package.json

# Switch to non-root user
USER mcpbox

# Add local packages to PATH
ENV PATH=/home/mcpbox/.local/bin:$PATH

# Expose ports
# 8000 = Main backend (admin API + MCP, local-only)
# 8002 = MCP Gateway (MCP only, tunnel-exposed)
EXPOSE 8000 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run migrations then start the app
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--timeout-graceful-shutdown", "30"]
