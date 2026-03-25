# VoxWatch v0.2.0 — AI-Powered Security Audio Deterrent
# Runs on the same Docker LXC host as Frigate/go2rtc so it can
# access the go2rtc API at localhost:1984 with minimal latency.

FROM python:3.11-slim

# Install system dependencies:
# - ffmpeg: audio format conversion (WAV -> PCMU 8kHz mono for Reolink backchannel)
# - espeak-ng: fallback TTS engine (always available)
# - curl: health checks and debugging
# - wget: for downloading Piper TTS
RUN apt-get update && apt-get install -y \
    ffmpeg \
    espeak-ng \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Piper TTS — high quality neural text-to-speech
# Using the prebuilt amd64 binary release
ARG PIPER_VERSION=2023.11.14-2
RUN wget -q "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
    -O /tmp/piper.tar.gz \
    && tar xzf /tmp/piper.tar.gz -C /usr/local/bin/ --strip-components=1 \
    && rm /tmp/piper.tar.gz \
    && chmod +x /usr/local/bin/piper

# Download the Piper voice model so TTS works without network access at runtime.
# en_US-lessac-medium is a natural-sounding American English voice.
RUN mkdir -p /usr/share/piper-voices \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
    -O /usr/share/piper-voices/en_US-lessac-medium.onnx \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
    -O /usr/share/piper-voices/en_US-lessac-medium.onnx.json

# Set Piper model path so the service can find the baked-in voice
ENV PIPER_MODEL_PATH=/usr/share/piper-voices/en_US-lessac-medium.onnx

WORKDIR /app

# Copy requirements first for Docker layer caching —
# dependencies change less often than code, so this layer gets reused
COPY requirements.txt .
# Install core requirements first, then optional TTS cloud provider SDKs.
# elevenlabs, cartesia, and boto3 are installed unconditionally so the image
# supports all providers without rebuilding.  kokoro-onnx is excluded because
# it requires GPU-specific ONNX runtime dependencies that vary by hardware.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir elevenlabs cartesia boto3

# Copy application code
COPY voxwatch/ /app/voxwatch/
COPY config/ /app/config/

# Create directories for runtime data
RUN mkdir -p /data/audio /data/logs /config

# Create a non-root system user to run the service.
# -r  creates a system account (no home directory, no login shell by default)
# -s /bin/false  explicitly disables interactive login for this account
# The account has no password and cannot be used to log in — it only exists so
# the process does not run as root inside the container.
RUN useradd -r -s /bin/false voxwatch

# Grant the voxwatch user ownership of the directories it writes to at runtime.
# /data       — audio cache, event log, status.json written by the service
# /config     — config.yaml is read (not written) but the user needs read access;
#               granting ownership is the simplest way to handle bind-mount
#               scenarios where the host file owner may be root.
# /app        — application code directory; ownership allows Python to write
#               __pycache__ files without requiring a root-owned layer.
RUN chown -R voxwatch:voxwatch /data /config /app

# Copy and mark entrypoint executable.
# The entrypoint runs as root to fix bind-mount permissions, then drops
# to the voxwatch user before exec'ing the Python service.
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Health check — verifies the service is running by checking the audio HTTP server
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8891/ || exit 1

# Start via entrypoint which fixes permissions then drops to non-root
ENTRYPOINT ["/app/entrypoint.sh"]
