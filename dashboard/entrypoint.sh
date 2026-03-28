#!/bin/sh
# entrypoint.sh — Fix bind-mount permissions then drop to non-root user.
#
# NAS-hosted bind mounts (/data, /config) are typically owned by root.
# The Dockerfile creates a 'dashboard' system user for security, but that
# user cannot write to root-owned directories.  This script runs as root
# at container start, fixes ownership, then exec's the server as the
# dashboard user.

set -e

# Fix ownership on writable directories if we are root
if [ "$(id -u)" = "0" ]; then
    chown -R dashboard:dashboard /config /tmp/voxwatch-wizard 2>/dev/null || true
    # /data is read-only mount — don't chown it, just ensure the user can read
    exec su -s /bin/sh dashboard -c "exec uvicorn backend.main:app --host 0.0.0.0 --port ${DASHBOARD_PORT:-33344}"
else
    exec uvicorn backend.main:app --host 0.0.0.0 --port ${DASHBOARD_PORT:-33344}
fi
