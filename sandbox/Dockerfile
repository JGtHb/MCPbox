# MCPbox Shared Sandbox Service
# Dynamically loads and executes MCP tools

FROM python:3.12.8-slim

# Security: Create non-root user
RUN useradd -m -u 1000 -s /bin/bash sandbox && \
    mkdir -p /app /app/site-packages && \
    chown -R sandbox:sandbox /app

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Set PYTHONPATH to include custom site-packages for dynamically installed packages
ENV PYTHONPATH="/app/site-packages:${PYTHONPATH}"

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=sandbox:sandbox app/ /app/app/

# Switch to non-root user
USER sandbox

# Expose service port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8001/health', timeout=5)" || exit 1

# Run the service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
