#!/bin/sh
# MCPbox Squid Proxy Entrypoint
#
# Copies the base config to a writable tmpfs location and starts squid.
# The external ACL helper (check-approved-private.sh) reads admin-approved
# private hosts from /shared/squid-acl/approved-private.txt, which is
# maintained by the sandbox registry via a shared Docker volume.
set -eu

# Fix shared ACL directory permissions for sandbox interoperability.
# The sandbox (UID 1000) needs write access to this volume. On fresh
# deployments the Dockerfile sets mode 1777, but existing volumes from
# before this fix retain restrictive permissions (UID 31, mode 755).
# As the squid user (UID 31) owns the directory on old volumes, chmod
# succeeds here.  On new volumes (root-owned, already 1777) chmod
# harmlessly fails — the "|| true" ensures the script continues.
chmod 1777 /shared/squid-acl 2>/dev/null || true

CONFIG_BASE="/etc/squid/squid.conf"
CONFIG_RUNTIME="/tmp/squid.conf"

cp "$CONFIG_BASE" "$CONFIG_RUNTIME"

exec squid -N -f "$CONFIG_RUNTIME"
