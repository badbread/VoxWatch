# VoxWatch Dashboard — 3-stage Docker build
#
# Stage 1 (node-builder):   npm ci + npm run build → static HTML/JS/CSS (~5MB)
# Stage 2 (python-deps):    install Python wheels into an isolated virtualenv
# Stage 3 (runtime):        copy static files + virtualenv + backend code only
#                           No Node.js, no node_modules, no build tools at runtime
#
# Default port: 33344 (configurable via DASHBOARD_PORT env var)

# ── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:20-alpine AS node-builder

WORKDIR /app/frontend

# Install dependencies first for Docker layer caching —
# package.json changes less often than source code.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy source and build static assets.
# Output: /app/frontend/dist/ (~5MB of HTML/JS/CSS)
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python dependency builder ──────────────────────────────────────
FROM python:3.11-slim AS python-deps

# Install build tools needed for any packages with C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create a virtualenv so the entire Python environment can be copied to the
# runtime stage as a single directory without needing pip in the final image.
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install only what the dashboard backend actually uses.
# aiomqtt is listed in the source requirements.txt but is not imported in any
# backend Python file — it is intentionally excluded here to keep the image lean.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        "fastapi>=0.111.0" \
        "uvicorn[standard]>=0.29.0" \
        "pydantic>=2.0" \
        "pyyaml>=6.0" \
        "aiohttp>=3.9.0" \
        "python-multipart>=0.0.9" \
        "paho-mqtt>=2.0.0" \
    && find /venv/lib -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && find /venv/lib -name "*.pyc" -delete 2>/dev/null || true

# ── Stage 3: Runtime image ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# No ffmpeg or espeak-ng in the dashboard image — the dashboard backend does
# not perform audio processing itself.  All audio generation happens in the
# voxwatch service container.  Removing these two packages saves ~120MB.

# Copy the pre-built virtualenv from the python-deps stage.
# This brings in all Python dependencies without pip or build tools.
COPY --from=python-deps /venv /venv
ENV PATH="/venv/bin:$PATH"

# Copy backend application code
COPY backend/ ./backend/

# Copy built frontend static files from the node-builder stage.
# At this point node_modules (~300MB) and Node.js itself are discarded.
COPY --from=node-builder /app/frontend/dist/ ./static/

# Default port — matches VoxWatch's registered port
ENV DASHBOARD_PORT=33344

EXPOSE 33344

# Create a non-root system user to run the dashboard.
# -r  creates a system account (no home directory, no login shell by default)
# -s /bin/false  explicitly disables interactive login for this account
RUN useradd -r -s /bin/false dashboard

# Grant the dashboard user ownership of the application directory.
# /app    — application code and static files
# /data   — the dashboard reads /data/status.json and /data/events.jsonl
#           written by the VoxWatch service
# /config — config.yaml read/write access for the setup wizard
RUN mkdir -p /data /config /tmp/voxwatch-wizard \
    && chown -R dashboard:dashboard /app /data /config /tmp/voxwatch-wizard

# Note: Running as root for now because the /config volume is typically
# owned by root on the host, and the dashboard needs write access to save
# config.yaml.  For production hardening, configure the container to run
# with the same UID that owns the config volume (e.g. --user 1026).
# USER dashboard

# Health check — verifies the dashboard API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:33344/api/system/health')" || exit 1

# Run with Uvicorn — production ASGI server
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${DASHBOARD_PORT}"]
