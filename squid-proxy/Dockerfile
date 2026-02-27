# MCPbox Squid Proxy — egress filter for sandbox
# All sandbox outbound traffic is forced through this proxy via Docker
# network isolation. Blocks private IPs; per-server domain filtering
# is enforced at the application layer (SSRF client).
# Admin-approved private hosts are allowed via an external ACL helper
# that reads from a shared volume written by the sandbox registry.

FROM alpine:3.23

RUN apk add --no-cache squid && \
    rm -rf /var/cache/apk/*

# Copy configuration, entrypoint, and external ACL helper
COPY squid.conf /etc/squid/squid.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY check-approved-private.sh /usr/local/bin/check-approved-private.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/check-approved-private.sh

# Squid needs to write to certain directories.
# /shared/squid-acl is the mount point for the shared volume with sandbox.
RUN mkdir -p /var/spool/squid /var/log/squid /var/run/squid /tmp /shared/squid-acl && \
    chown -R squid:squid /var/spool/squid /var/log/squid /var/run/squid /etc/squid /tmp /shared/squid-acl

USER squid

EXPOSE 3128

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD test -f /var/run/squid/squid.pid && kill -0 $(cat /var/run/squid/squid.pid)

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
