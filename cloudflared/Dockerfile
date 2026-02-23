# Custom cloudflared container that fetches tunnel token from backend at startup.
# Replaces the stock cloudflare/cloudflared image which has no shell or curl.

FROM alpine:3.20

# Install curl for health checks and token fetching
RUN apk add --no-cache curl ca-certificates

# Download cloudflared binary (multi-arch via Docker's TARGETARCH)
ARG CLOUDFLARED_VERSION=2026.1.2
ARG TARGETARCH
RUN ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')}" && \
    echo "Downloading cloudflared for linux/${ARCH}" && \
    curl -L "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${ARCH}" \
    -o /usr/local/bin/cloudflared && \
    chmod +x /usr/local/bin/cloudflared && \
    cloudflared --version

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN adduser -D -u 1000 cloudflared
USER cloudflared

ENTRYPOINT ["/entrypoint.sh"]
