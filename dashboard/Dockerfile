# VoxWatch Dashboard — Multi-stage Docker build
# Stage 1: Build React frontend with Vite
# Stage 2: Serve with FastAPI/Uvicorn
#
# Default port: 33344 (configurable via DASHBOARD_PORT env var)

# ── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Install dependencies first for Docker layer caching —
# package.json changes less often than source code
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY frontend/ ./
RUN npm run build
# Output: /app/frontend/dist/

# ── Stage 2: Production image ───────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg + espeak-ng — ffmpeg is needed by the Camera Setup Wizard
# to generate test tones, and espeak-ng provides a local TTS fallback for
# audio preview when Piper/Kokoro are not available in this container
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy built frontend static files
COPY --from=frontend-build /app/frontend/dist/ ./static/

# Default port — matches VoxWatch's registered port
ENV DASHBOARD_PORT=33344

EXPOSE 33344

# Create a non-root system user to run the dashboard.
# -r  creates a system account (no home directory, no login shell by default)
# -s /bin/false  explicitly disables interactive login for this account
RUN useradd -r -s /bin/false dashboard

# Grant the dashboard user ownership of the application directory.
# /app        — application code and static files; ownership allows Python to
#               write __pycache__ without requiring root.
# /data       — the dashboard reads /data/status.json and /data/events.jsonl
#               written by the VoxWatch service.  The volume is typically owned
#               by root on the host; granting ownership here is best-effort for
#               non-volume scenarios.  In production the host volume permissions
#               should also grant read access to the dashboard user's UID.
RUN mkdir -p /data /config /tmp/voxwatch-wizard && chown -R dashboard:dashboard /app /data /config /tmp/voxwatch-wizard

# Note: Running as root for now because the /config volume is typically
# owned by root on the host, and the dashboard needs write access to save
# config.yaml. For production hardening, configure the container to run
# with the same UID that owns the config volume (e.g. --user 1026).
# USER dashboard

# Health check — verifies the dashboard API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:33344/api/system/health')" || exit 1

# Run with Uvicorn — production ASGI server
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${DASHBOARD_PORT}"]
