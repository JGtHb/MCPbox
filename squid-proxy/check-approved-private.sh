#!/bin/sh
# External ACL helper for squid — checks if a destination hostname/IP
# has been admin-approved for private network access.
#
# Protocol (concurrency=0):
#   stdin:  "<destination>\n"   (one per line, from %DST token)
#   stdout: "OK\n" or "ERR\n"
#
# The approved-private.txt file is maintained by the sandbox registry
# via a shared Docker volume.  It contains one hostname or IP per line.
#
# Debug: helper stderr goes to squid cache_log (container stderr).
# Set ACL_HELPER_DEBUG=1 to enable verbose logging.

APPROVED_FILE="/shared/squid-acl/approved-private.txt"
DEBUG="${ACL_HELPER_DEBUG:-0}"

# Log startup so we know the helper actually initialized
echo "ACL_HELPER: started, approved_file=$APPROVED_FILE exists=$(test -f "$APPROVED_FILE" && echo yes || echo no)" >&2

while read -r dst; do
    # Strip leading/trailing whitespace (defensive)
    dst=$(printf '%s' "$dst" | tr -d '[:space:]')

    if [ -z "$dst" ]; then
        echo "ERR"
        continue
    fi

    if [ "$DEBUG" = "1" ]; then
        echo "ACL_HELPER: query dst='$dst'" >&2
    fi

    # Match: check if dst appears as an exact line in the approved file.
    # Use a shell loop instead of grep -x to avoid BusyBox compatibility
    # issues with combined flags (-qxiF).
    found=0
    if [ -f "$APPROVED_FILE" ]; then
        while IFS= read -r line; do
            # Case-insensitive comparison via lowercasing
            line_lower=$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')
            dst_lower=$(printf '%s' "$dst" | tr '[:upper:]' '[:lower:]')
            if [ "$line_lower" = "$dst_lower" ]; then
                found=1
                break
            fi
        done < "$APPROVED_FILE"
    fi

    if [ "$found" = "1" ]; then
        if [ "$DEBUG" = "1" ]; then
            echo "ACL_HELPER: OK for '$dst'" >&2
        fi
        echo "OK"
    else
        echo "ACL_HELPER: ERR for '$dst' (file_exists=$(test -f "$APPROVED_FILE" && echo yes || echo no))" >&2
        echo "ERR"
    fi
done
