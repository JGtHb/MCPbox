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

APPROVED_FILE="/shared/squid-acl/approved-private.txt"

while read -r dst; do
    if [ -f "$APPROVED_FILE" ] && grep -qxiF "$dst" "$APPROVED_FILE"; then
        echo "OK"
    else
        echo "ERR"
    fi
done
