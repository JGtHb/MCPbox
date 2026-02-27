#!/bin/sh
# MCPbox Squid Proxy Entrypoint
#
# Copies the base config to a writable tmpfs location and starts squid.
# The external ACL helper (check-approved-private.sh) reads admin-approved
# private hosts from /shared/squid-acl/approved-private.txt, which is
# maintained by the sandbox registry via a shared Docker volume.
set -eu

CONFIG_BASE="/etc/squid/squid.conf"
CONFIG_RUNTIME="/tmp/squid.conf"

cp "$CONFIG_BASE" "$CONFIG_RUNTIME"

exec squid -N -f "$CONFIG_RUNTIME"
