#!/bin/sh
# External ACL helper for squid — checks if a destination hostname/IP
# (and optionally port) has been admin-approved for private network access.
#
# Protocol (concurrency=0):
#   stdin:  "<DST> <PORT> [extra tokens]\n"  (from %DST %PORT)
#   stdout: "OK\n" or "ERR\n"
#
# The approved-private.txt file is maintained by the sandbox registry
# via a shared Docker volume.  Each line is either:
#   - "host"       → any port on that host is approved
#   - "host:port"  → only that specific port is approved
#
# Debug: helper stderr goes to squid cache_log (container stderr).
# Set ACL_HELPER_DEBUG=1 to enable verbose logging.

APPROVED_FILE="/shared/squid-acl/approved-private.txt"
DEBUG="${ACL_HELPER_DEBUG:-0}"

# Log startup so we know the helper actually initialized
echo "ACL_HELPER: started, approved_file=$APPROVED_FILE exists=$(test -f "$APPROVED_FILE" && echo yes || echo no)" >&2

while read -r dst port _rest; do
    # read -r dst port _rest: first two tokens are %DST and %DSTPORT.
    # Squid 7 may append extra tokens (e.g. "-" for no-ident).

    if [ -z "$dst" ]; then
        echo "ERR"
        continue
    fi

    if [ "$DEBUG" = "1" ]; then
        echo "ACL_HELPER: query dst='$dst' port='$port'" >&2
    fi

    # Match against the approved file.
    # A line "host:port" matches only that specific port.
    # A line "host" (no port) matches ANY port on that host.
    found=0
    if [ -f "$APPROVED_FILE" ]; then
        dst_lower=$(printf '%s' "$dst" | tr '[:upper:]' '[:lower:]')
        hp_lower="${dst_lower}:${port}"
        while IFS= read -r line; do
            line_lower=$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')
            # Check host:port match first, then host-only (any-port wildcard)
            if [ "$line_lower" = "$hp_lower" ] || [ "$line_lower" = "$dst_lower" ]; then
                found=1
                break
            fi
        done < "$APPROVED_FILE"
    fi

    if [ "$found" = "1" ]; then
        if [ "$DEBUG" = "1" ]; then
            echo "ACL_HELPER: OK for '$dst:$port'" >&2
        fi
        echo "OK"
    else
        echo "ACL_HELPER: ERR for '$dst:$port' (file_exists=$(test -f "$APPROVED_FILE" && echo yes || echo no))" >&2
        echo "ERR"
    fi
done
