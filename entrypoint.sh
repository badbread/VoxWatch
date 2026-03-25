#!/bin/sh
# entrypoint.sh — Fix bind-mount permissions then drop to non-root user.
#
# NAS-hosted bind mounts (/data, /config) are typically owned by root.
# The Dockerfile creates a 'voxwatch' system user for security, but that
# user cannot write to root-owned directories.  This script runs as root
# at container start, fixes ownership, then exec's the service as the
# voxwatch user via gosu (or su-exec).
#
# If the container is already running as non-root (e.g. Kubernetes
# securityContext), the chown will fail silently and we proceed anyway.

set -e

# Fix ownership on writable directories if we are root
if [ "$(id -u)" = "0" ]; then
    chown -R voxwatch:voxwatch /data /config 2>/dev/null || true
    exec su -s /bin/sh voxwatch -c "exec python -u -m voxwatch.voxwatch_service --config /config/config.yaml"
else
    exec python -u -m voxwatch.voxwatch_service --config /config/config.yaml
fi
