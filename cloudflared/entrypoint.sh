#!/bin/sh

BACKEND_URL="${BACKEND_URL:-http://backend:8000}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
TOKEN_CHECK_INTERVAL="${TOKEN_CHECK_INTERVAL:-15}"

echo "cloudflared: waiting for backend to be healthy..."

while true; do
    if curl -sf "${BACKEND_URL}/health" > /dev/null 2>&1; then
        echo "cloudflared: backend is healthy"
        break
    fi
    echo "cloudflared: waiting for backend..."
    sleep 2
done

# Internal API auth header (shared secret with backend)
AUTH_HEADER="Authorization: Bearer ${SANDBOX_API_KEY}"

# Fetch the current tunnel token from the backend
fetch_token() {
    RESPONSE=$(curl -sf -H "$AUTH_HEADER" "${BACKEND_URL}/internal/active-tunnel-token" 2>&1) || true
    echo "$RESPONSE" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

# Main loop: fetch token → run tunnel with watchdog → on change, restart
while true; do
    echo "cloudflared: fetching active tunnel token..."

    CURRENT_TOKEN=""
    while [ -z "$CURRENT_TOKEN" ] || [ "$CURRENT_TOKEN" = "null" ]; do
        CURRENT_TOKEN=$(fetch_token)

        if [ -n "$CURRENT_TOKEN" ] && [ "$CURRENT_TOKEN" != "null" ]; then
            break
        fi

        echo "cloudflared: no tunnel configured yet, retrying in ${POLL_INTERVAL}s..."
        sleep "$POLL_INTERVAL"
    done

    echo "cloudflared: token retrieved, starting tunnel..."

    # Start cloudflared in the background
    cloudflared tunnel --no-autoupdate run --token "$CURRENT_TOKEN" &
    CF_PID=$!

    # Watchdog: periodically check if the token has changed
    while kill -0 "$CF_PID" 2>/dev/null; do
        sleep "$TOKEN_CHECK_INTERVAL"

        NEW_TOKEN=$(fetch_token)

        # If token changed (new tunnel) or was removed (teardown), restart
        if [ -n "$NEW_TOKEN" ] && [ "$NEW_TOKEN" != "null" ] && [ "$NEW_TOKEN" != "$CURRENT_TOKEN" ]; then
            echo "cloudflared: tunnel token changed, restarting with new token..."
            kill "$CF_PID" 2>/dev/null
            wait "$CF_PID" 2>/dev/null
            break
        fi

        # If token was removed, stop and go back to polling
        if [ -z "$NEW_TOKEN" ] || [ "$NEW_TOKEN" = "null" ]; then
            echo "cloudflared: tunnel token removed, stopping tunnel..."
            kill "$CF_PID" 2>/dev/null
            wait "$CF_PID" 2>/dev/null
            break
        fi
    done

    # If cloudflared exited on its own (crash/disconnect), we'll loop back
    # and re-fetch the token before restarting
    wait "$CF_PID" 2>/dev/null
    echo "cloudflared: tunnel stopped, will re-fetch token in ${POLL_INTERVAL}s..."
    sleep "$POLL_INTERVAL"
done
