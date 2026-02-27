#!/bin/sh
# MCPbox Squid Proxy Entrypoint
#
# Generates runtime squid config from the base config, injecting ACL rules
# for admin-approved private IP ranges (MCPBOX_ALLOWED_PRIVATE_RANGES).
#
# Format: comma-separated "IP_OR_CIDR" or "IP_OR_CIDR:PORT" entries.
# Example: MCPBOX_ALLOWED_PRIVATE_RANGES=192.168.1.50,10.0.1.0/24:8080
set -eu

CONFIG_BASE="/etc/squid/squid.conf"
CONFIG_RUNTIME="/tmp/squid.conf"
SNIPPET="/tmp/allowed-private-rules.conf"

# Generate ACL snippet for admin-approved private ranges
: > "$SNIPPET"

if [ -n "${MCPBOX_ALLOWED_PRIVATE_RANGES:-}" ]; then
    echo "# Admin-approved private ranges (MCPBOX_ALLOWED_PRIVATE_RANGES)" >> "$SNIPPET"
    n=0
    # Split on commas using positional parameters
    OIFS="$IFS"
    IFS=','
    # shellcheck disable=SC2086
    set -- $MCPBOX_ALLOWED_PRIVATE_RANGES
    IFS="$OIFS"

    for raw in "$@"; do
        # Trim whitespace
        raw="$(echo "$raw" | tr -d '[:space:]')"
        [ -z "$raw" ] && continue
        n=$((n + 1))
        name="allowed_priv_$n"

        # Detect optional port suffix: "1.2.3.0/24:8080" or "1.2.3.4:443"
        port=""
        suffix="${raw##*:}"
        prefix="${raw%:*}"
        # If suffix differs from raw AND is purely numeric, treat as port
        if [ "$suffix" != "$raw" ]; then
            case "$suffix" in
                ''|*[!0-9]*) ;;  # Not a number — no port
                *) port="$suffix"; raw="$prefix" ;;
            esac
        fi

        # Normalise bare IPs to /32 CIDR
        case "$raw" in
            */*) cidr="$raw" ;;
            *)   cidr="${raw}/32" ;;
        esac

        echo "acl $name dst $cidr" >> "$SNIPPET"
        if [ -n "$port" ]; then
            echo "acl ${name}_port port $port" >> "$SNIPPET"
            echo "http_access allow $name ${name}_port" >> "$SNIPPET"
        else
            echo "http_access allow $name" >> "$SNIPPET"
        fi
    done
fi

# Build runtime config: insert snippet before "http_access deny blocked_dst"
awk '/^http_access deny blocked_dst/ {
    while ((getline line < "'"$SNIPPET"'") > 0)
        print line
}
{ print }' "$CONFIG_BASE" > "$CONFIG_RUNTIME"

exec squid -N -f "$CONFIG_RUNTIME"
