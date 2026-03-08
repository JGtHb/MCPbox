FROM python:3.11-slim

# Non-root user
RUN useradd -m -u 1000 -s /bin/sh proxy

COPY proxy.py /app/proxy.py

USER proxy
WORKDIR /app

EXPOSE 1080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 1080)); s.close()"

CMD ["python", "-u", "proxy.py"]
