# MCPbox Shared Sandbox Service
# Dynamically loads and executes MCP tools
# Multi-stage build: excludes setuptools/wheel from runtime image
# NOTE: pip is kept because package_installer.py uses `python -m pip install`

# Builder stage — install Python dependencies
FROM python:3.14.3-slim AS builder

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Runtime stage — minimal image without setuptools/wheel
FROM python:3.14.3-slim

# Security: Create non-root user
RUN useradd -m -u 1000 -s /bin/bash sandbox && \
    mkdir -p /app /app/site-packages && \
    chown -R sandbox:sandbox /app

# Copy installed packages from builder (includes our deps + their transitive deps)
COPY --from=builder /usr/local/lib/python3.14/site-packages/ /usr/local/lib/python3.14/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Remove setuptools and wheel from runtime (pip kept for package_installer.py)
RUN pip uninstall -y setuptools wheel 2>/dev/null || true && \
    rm -rf /usr/local/lib/python3.14/ensurepip \
           /usr/local/lib/python3.14/lib2to3

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

# Health check (uses stdlib — no external tools needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=5)" || exit 1

# Run the service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
