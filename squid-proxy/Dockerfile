# MCPbox Squid Proxy — egress filter for sandbox
# All sandbox outbound traffic is forced through this proxy via Docker
# network isolation. Blocks private IPs; per-server domain filtering
# is enforced at the application layer (SSRF client).

FROM alpine:3.23

RUN apk add --no-cache squid && \
    rm -rf /var/cache/apk/*

# Copy configuration and entrypoint
COPY squid.conf /etc/squid/squid.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Squid needs to write to certain directories
RUN mkdir -p /var/spool/squid /var/log/squid /var/run/squid /tmp && \
    chown -R squid:squid /var/spool/squid /var/log/squid /var/run/squid /etc/squid /tmp

USER squid

EXPOSE 3128

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD squidclient -h localhost -p 3128 mgr:info 2>/dev/null | grep -q "Squid Object Cache" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
