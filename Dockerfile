# VoxWatch v0.2.0 — AI-Powered Security Audio Deterrent
# Multi-stage build:
#   Stage 1 (builder): install build tools, compile Python wheels
#   Stage 2 (runtime): copy only compiled wheels + minimal runtime deps

# ── Stage 1: Python dependency builder ──────────────────────────────────────
FROM python:3.11-slim AS builder

# Install build tools needed to compile certain wheels (e.g. Pillow, reolink-aio)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Build wheels for core runtime deps into /wheels.
# Packages are listed explicitly rather than via -r requirements.txt because
# optional cloud TTS SDKs (elevenlabs, cartesia, boto3) are NOT pre-installed
# — they use lazy imports and can be added by the user at runtime.
RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels \
        aiohttp \
        pyyaml \
        "paho-mqtt>=2.0.0" \
        "astral>=3.2" \
        "Pillow>=10.0.0" \
        requests \
        "reolink-aio>=0.9.0"
# NOTE: google-generativeai is NOT installed — Gemini uses REST API via aiohttp

# ── Stage 2: Runtime image ───────────────────────────────────────────────────
FROM python:3.11-slim

# Install runtime system dependencies in a single layer:
#   ffmpeg        — audio format conversion (WAV -> PCMU/PCMA 8kHz mono,
#                   lavfi sine tone generation via -f lavfi)
#   espeak-ng     — fallback TTS engine (always available, no network needed)
#   curl          — health check endpoint probe
# wget is NOT included — all downloads happen at build time, not runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Piper TTS — high-quality neural text-to-speech.
# The prebuilt amd64 binary is self-contained (glibc-linked, not musl) which
# is why we use python:3.11-slim (Debian) rather than Alpine for this image.
ARG PIPER_VERSION=2023.11.14-2
RUN curl -fsSL "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
    -o /tmp/piper.tar.gz \
    && tar xzf /tmp/piper.tar.gz -C /usr/local/bin/ --strip-components=1 \
    && rm /tmp/piper.tar.gz \
    && chmod +x /usr/local/bin/piper

# Download the en_US-lessac-medium voice model — the default baked-in voice.
# Only this one model is included; additional models can be mounted at runtime
# via the PIPER_MODEL_PATH environment variable.
RUN mkdir -p /usr/share/piper-voices \
    && curl -fsSL "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
       -o /usr/share/piper-voices/en_US-lessac-medium.onnx \
    && curl -fsSL "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
       -o /usr/share/piper-voices/en_US-lessac-medium.onnx.json

# Set Piper model path so the service can find the baked-in voice
ENV PIPER_MODEL_PATH=/usr/share/piper-voices/en_US-lessac-medium.onnx

WORKDIR /app

# Install pre-built wheels from the builder stage.
# --no-index forces pip to use only the local wheel directory (no PyPI),
# --find-links points to the wheel cache from the builder stage.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels /wheels/*.whl \
    && rm -rf /wheels \
    && find /usr/local/lib/python3.11 -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && find /usr/local/lib/python3.11 -name "*.pyc" -delete 2>/dev/null || true

# Copy application code — requirements are already installed above so this
# layer only invalidates when the source code actually changes.
COPY voxwatch/ /app/voxwatch/
COPY config/ /app/config/

# Create directories for runtime data
RUN mkdir -p /data/audio /data/logs /config

# Create a non-root system user to run the service.
# -r  creates a system account (no home directory, no login shell by default)
# -s /bin/false  explicitly disables interactive login for this account
RUN useradd -r -s /bin/false voxwatch

# Grant the voxwatch user ownership of the directories it writes to at runtime.
# /data   — audio cache, event log, status.json written by the service
# /config — config.yaml is read (not written) but ownership simplifies
#           bind-mount scenarios where the host file owner may be root
# /app    — application code; ownership lets Python write __pycache__ files
RUN chown -R voxwatch:voxwatch /data /config /app

# Copy and mark entrypoint executable.
# The entrypoint runs as root to fix bind-mount permissions, then drops to
# the voxwatch user before exec'ing the Python service.
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Health check — verifies the service is running by checking the audio HTTP server
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8891/ || exit 1

# Start via entrypoint which fixes permissions then drops to non-root
ENTRYPOINT ["/app/entrypoint.sh"]
