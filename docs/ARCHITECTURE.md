# VoxWatch Architecture

VoxWatch is an AI-powered security audio deterrent system that detects intruders on camera and delivers escalating vocal warnings through camera speakers. This document describes the complete system architecture, data flow, and technical implementation details.

## System Overview

VoxWatch integrates with Frigate video surveillance to detect persons on camera and responds with AI-generated audio warnings delivered to the camera's speaker in real-time.

### High-Level Flow

```
Security Camera
    ↓
Frigate (Person Detection via Coral TPU)
    ↓
MQTT (Person detected event)
    ↓
VoxWatch Service (Alert Handler)
    ↓
AI Vision (Gemini Flash / Ollama fallback)
    ↓
TTS (Piper / espeak)
    ↓
Audio Pipeline (ffmpeg encoding)
    ↓
HTTP Server (Audio file serving)
    ↓
go2rtc API (Audio push request)
    ↓
Camera Speaker (Backchannel audio playback)
```

## Three-Stage Deterrent Pipeline

VoxWatch implements a three-stage escalating warning system, balancing response speed with situational awareness.

### Stage 1: Instant Pre-Cached Warning (0-2 seconds)

**Purpose:** Immediate response to deter intruders before they take action.

**Execution:**
- Triggered immediately when Frigate detects a person
- Plays a pre-recorded or cached warning message: "Warning! This property is under surveillance. You are being recorded. Leave immediately."
- Runs in parallel with Stage 2 analysis
- Audio codec: PCMU (G.711 mu-law), 8000 Hz, mono
- Delivery method: go2rtc backchannel API

**Characteristics:**
- No AI analysis required
- Fixed latency, highly reliable
- Single-threaded audio push
- Blocks until audio playback completes

### Stage 2: AI Snapshot Description (5-10 seconds)

**Purpose:** Provide context-aware deterrent message based on captured snapshot.

**Execution:**
- Parallel task started with Stage 1, completes independently
- Frigate captures snapshot when person is first detected
- VoxWatch sends snapshot to AI vision model (Gemini Flash primary, Ollama/LLaVA fallback)
- AI generates description: "I see a person in dark clothing near your front door"
- TTS converts description to audio
- Audio queued for playback after Stage 1 completes
- Message format: "I can see [AI description]. Police have been notified. Leave immediately."

**Characteristics:**
- Runs asynchronously with Stage 1
- AI latency: 2-4 seconds (Gemini Flash)
- Fallback to local Ollama/LLaVA if cloud API fails
- Audio wait: Stage 2 blocks until Stage 1 audio completes before playing
- Requires internet connectivity (or local LLaVA)
- Jitter compensation for network delays

### Stage 3: Behavioral Video Analysis (After Stage 2)

**Purpose:** Detect prolonged presence or suspicious behavior, escalate warnings.

**Execution:**
- Only triggered if person remains present after Stage 2 (configurable threshold, default 30 seconds)
- Analyzes 5-10 second video clip of person's behavior
- VoxWatch sends video frames to AI for behavioral analysis
- AI generates assessment: "You are trespassing on private property. This is your final warning."
- Only executes if person detection is still active (prevents false triggers)
- Longer timeout between repeat warnings (60+ seconds) to avoid harassing legitimate visitors

**Characteristics:**
- Slowest stage (video analysis overhead)
- Only executes after confirmed persistence
- Person-still-present check prevents ghost warnings
- Configurable repeat interval to prevent spam
- Can request emergency services integration (future capability)

## Component Architecture

### Core Components

#### Frigate (Person Detection Engine)
- **Role:** Video analysis and person detection
- **Hardware:** Coral TPU for efficient inference
- **Output:** MQTT events with detection confidence, camera name, snapshot path
- **Integration:** Publishes `frigate/events/person/detected` messages
- **Latency:** 0-2 seconds per frame at 5 FPS

#### VoxWatch Service (Alert Orchestration)
- **Role:** Orchestrates multi-stage pipeline and manages state
- **Language:** Python 3.8+
- **Architecture:**
  - MQTT subscriber (listens for Frigate events)
  - Stage coordinator (manages parallel execution and ordering)
  - Config manager (YAML-based, environment variable substitution)
  - Error handler with fallback chains
- **State Management:** Per-camera cooldown tracking, person detection timestamps
- **Concurrency:** Python `asyncio` for I/O, `threading` for parallel stages

#### AI Vision (Dual-Model Strategy)
- **Primary:** Google Gemini 1.5 Flash
  - Cloud-based, low latency (2-3 seconds)
  - Requires API key and internet connectivity
  - Supports image and video analysis
  - Fallback if quota exceeded or network fails

- **Fallback:** Ollama + LLaVA (Local)
  - Runs on-premise, no internet required
  - Higher latency (5-15 seconds on CPU, <2s on GPU)
  - Fully offline operation
  - Requires additional hardware allocation
  - Automatic fallback if Gemini unavailable

#### TTS Engine (Text-to-Speech)
- **Primary:** Piper
  - Fast, high-quality neural TTS
  - Runs locally, no internet required
  - Multiple voice options available
  - Low resource footprint (~100MB)
  - Typical latency: 0.5-2 seconds

- **Fallback:** espeak
  - Lightweight, instant fallback
  - Robotic but functional
  - ~5MB resource footprint
  - Always available (no dependencies)

#### Audio Pipeline (ffmpeg Encoding)
- **Input:** PCM WAV from TTS
- **Processing Steps:**
  1. Decode WAV → PCM s16le 44.1kHz stereo
  2. Resample to 8000 Hz mono
  3. Convert to camera-specific codec (auto-detected):
     - PCMU (G.711 µ-law) for Reolink cameras
     - PCMA (G.711 A-law) for Dahua cameras
  4. Wrap in raw audio format for go2rtc
- **Output:** Codec-specific audio stream ready for camera backchannel
- **Codec Details (Common to Both):**
  - Sample rate: 8000 Hz (telephony standard)
  - Channels: Mono
  - Bit rate: 64 kbps
  - Frame duration: 20ms
- **Codec-Specific Details:**
  - **PCMU (Reolink):** Pulse Code Modulation µ-law (North American standard)
  - **PCMA (Dahua):** Pulse Code Modulation A-law (European/Asian standard)
  - Both provide similar quality and bandwidth (MOS ~3.85-3.9)

#### HTTP Audio Server
- **Role:** Serves encoded audio files to go2rtc
- **Mechanism:**
  - Temporary HTTP server spawned per audio stream
  - File served on localhost, high port (8001+)
  - Accessible from Frigate/go2rtc container via Docker host networking
  - Single-use files cleaned up after transfer
- **Protocol:** HTTP 1.1, no authentication required (localhost only)
- **Latency:** <100ms per request

#### go2rtc (RTSP/Streaming Gateway)
- **Role:** Bridges HTTP audio to RTSP camera backchannel
- **API Endpoint:** `POST /api/ffmpeg` (working method)
- **Request Format:**
  ```
  POST http://go2rtc:1984/api/ffmpeg?dst={camera_stream_name}&file=http://{host_ip}:{port}/{filename}
  ```
- **Alternative (non-working) endpoint:** `/api/streams` returns instantly but audio never plays
- **Processing:**
  1. Receives POST request with source HTTP URL and destination stream
  2. Fetches audio file from HTTP server
  3. Encodes/transcodes to target codec if needed
  4. Pushes stream to camera's RTSP backchannel
  5. Camera speaker plays audio
- **Camera-Specific Behavior:**
  - **Reolink:** Blocks until audio completes (12-20s response time)
  - **Dahua:** Returns instantly (0.1s) but audio continues playing asynchronously
- **Configuration:** Frigate config includes go2rtc section with camera stream definitions
- **Important Notes:**
  - Do NOT add `backchannel=1` to stream URL—breaks Frigate's video detection
  - For Dahua cameras: Use native RTSP format, not ONVIF URLs
  - Warmup pattern (Reolink only): First push may not play audio; second push succeeds

#### Camera (Supported Models)
- **Role:** End-point audio playback device
- **Hardware:** Built-in speaker, RTSP backchannel support
- **Audio Codecs:**
  - Reolink cameras (CX410, CX420, E1 Zoom): PCMU (G.711 µ-law) at 8000 Hz
  - Dahua cameras (IPC-Color4K-T180, etc.): PCMA (G.711 A-law) at 8000 Hz
- **Latency:**
  - Reolink: 0.5-1 second from backchannel start to speaker output
  - Dahua: Nearly instant (no warmup required)
- **Network:** PoE (all tested models)
- **Integration:**
  - Frigate maintains RTSP connection; go2rtc uses same connection for backchannel
  - Reolink: Uses standard RTSP URLs (e.g., `/Preview_01_sub`)
  - Dahua: **MUST use native format** `rtsp://user:pass@ip:554/cam/realmonitor?channel=1&subtype=2&unicast=true&proto=Onvif` (ONVIF URLs do NOT expose backchannel)

## Concurrency Model

### Execution Flow

VoxWatch uses Python's `asyncio` and `threading` to implement safe parallel execution:

```
Person Detection Event
    ↓
├─→ [Stage 1] Instant Warning (blocking)
│   └─ Play pre-cached "Warning" audio
│   └ ~5 seconds total (TTS + encoding + push)
│   └ BLOCKS Stage 2 audio (not Stage 2 analysis)
│
├─→ [Stage 2] AI Analysis (parallel async task)
│   ├─ Download snapshot from Frigate
│   ├─ Send to AI (Gemini or Ollama)
│   ├─ Generate description
│   ├─ TTS encode description
│   └─ WAIT for Stage 1 audio to complete
│   └─ Play Stage 2 audio
│   └ ~8-12 seconds total
│
└─→ [Stage 3] Behavioral Analysis (spawned after Stage 2)
    └─ Only if person still detected
    └─ Analyze video behavior
    └─ Generate escalated warning
    └ ~15-25 seconds total
```

### Thread Safety

- **MQTT Subscriber Thread:** Processes events from Frigate, enqueues stage tasks
- **Stage Executor Thread Pool:** Handles parallel AI analysis and TTS
- **Audio Playback Thread:** Serialized queue, plays audio sequentially (one speaker stream at a time)
- **State Lock:** Per-camera mutex protects cooldown and presence tracking
- **Event Queue:** Thread-safe queue for MQTT events to stage executor

### Race Condition Prevention

1. **Multiple Detections:** If person detected while Stage 1 playing, new detection ignored (cooldown)
2. **Person Leaves During Stage 2:** Stage 2 audio still plays (committed), Stage 3 never spawns
3. **Person Leaves During Stage 3:** Stage 3 cancels gracefully, no audio pushed
4. **Network Failure During AI:** Fallback chain triggered automatically
5. **Go2rtc Timeout:** Logged as non-fatal, next detection retries

## Configuration System

### YAML Configuration with Environment Substitution

VoxWatch uses YAML configuration with support for `${ENV_VAR}` substitution:

```yaml
# voxwatch.yml example
voxwatch:
  # AI Vision Configuration
  vision:
    # Primary: Google Gemini
    gemini:
      enabled: true
      api_key: ${GEMINI_API_KEY}  # Set via environment variable
      model: "gemini-1.5-flash"

    # Fallback: Local Ollama
    ollama:
      enabled: false
      endpoint: "http://localhost:11434"
      model: "llava"

  # TTS Configuration
  tts:
    # Primary: Piper
    piper:
      enabled: true
      voice: "en_US-lessac-medium"

    # Fallback: espeak
    espeak:
      enabled: true
      language: "en"

  # Camera Configuration
  cameras:
    frontdoor:
      # Frigate stream name (from go2rtc config)
      stream_name: "frontdoor"
      # go2rtc base URL for API calls
      go2rtc_url: "http://localhost:1984"
      # Camera IP for snapshot retrieval (optional)
      camera_ip: "192.168.1.100"

  # Pipeline Thresholds
  pipeline:
    # Cooldown between warnings (seconds)
    cooldown: 30
    # Person must be present this long to trigger Stage 3 (seconds)
    stage3_threshold: 30
    # Time before Stage 3 repeat on same person (seconds)
    stage3_repeat_interval: 60

  # MQTT Configuration
  mqtt:
    broker: "localhost"
    port: 1883
    # Topic Frigate publishes detection events to
    detection_topic: "frigate/events/person/detected"

# Substitution Examples:
# voxwatch:
#   vision:
#     gemini:
#       api_key: ${GEMINI_API_KEY}  → reads from GEMINI_API_KEY env var
```

### Environment Variable Handling

- Read at service startup
- Substituted into YAML before parsing
- Supports default values: `${VAR:default_value}`
- Validates required keys on load
- Secrets (API keys) never logged

## Docker Deployment

### Host Networking Requirement

VoxWatch requires **host networking** mode to access localhost services:

```yaml
version: '3.8'
services:
  voxwatch:
    image: voxwatch:latest
    network_mode: "host"  # CRITICAL: Required for localhost access
    environment:
      GEMINI_API_KEY: "${GEMINI_API_KEY}"
    volumes:
      - /path/to/voxwatch.yml:/app/config/voxwatch.yml
      - /tmp/voxwatch:/tmp/voxwatch  # Audio files cache
    restart: unless-stopped
```

**Why host networking is required:**
- Frigate (go2rtc) runs on Docker host (localhost:1984)
- VoxWatch container needs to call `http://localhost:1984` (host's go2rtc)
- With bridge networking, localhost = container's localhost (not host)
- Host networking = container sees host's network interfaces directly
- Security: Only safe because container is trusted (internal infrastructure)

### Frigate Integration

VoxWatch subscribes to MQTT topics published by Frigate:
- **Topic:** `frigate/events/person/detected`
- **Payload:** JSON with event details, camera name, snapshot path
- **Expected Fields:**
  ```json
  {
    "before": { "person": 0 },
    "after": { "person": 1 },
    "event_id": "1234567890",
    "camera": "frontdoor",
    "snapshot": "/tmp/frigate/tmp/detection-frontdoor-1234567890.jpg"
  }
  ```

### Audio File Handling

1. **Temporary Storage:** Audio files written to `/tmp/voxwatch/` in container
2. **Lifecycle:**
   - Created: When TTS generates audio
   - Served: Via temporary HTTP server
   - Fetched: By go2rtc via HTTP
   - Deleted: 10 seconds after creation (cleanup timer)
3. **Size:** Typical 2KB per second of audio (PCMU 8kHz mono)
4. **Permissions:** World-readable during serving window

## Error Handling and Fallbacks

### Cascade Strategy

1. **AI Vision Failure:**
   - Try Gemini (cloud) first
   - On timeout/error → fall back to Ollama (local)
   - On both fail → use generic pre-recorded message
   - Log error and continue

2. **TTS Failure:**
   - Try Piper (neural) first
   - On fail → fall back to espeak
   - Guaranteed to complete (espeak always available)

3. **Audio Push Failure:**
   - Retry up to 3 times with exponential backoff
   - Log failure
   - Do not block subsequent detections
   - Stage 3 still executes if Stage 1 failed

4. **Network Failure:**
   - All API calls have 10-second timeout
   - Graceful degradation to fallback mode
   - Offline operation possible with Ollama + Piper + cached warnings

## Performance Characteristics

### Latency (End-to-End)

| Stage | Component | Reolink (CX410/CX420) | Reolink E1 Zoom | Dahua (IPC-Color4K) | Notes |
|-------|-----------|----------------------|-----------------|-------------------|-------|
| 1 | Person detection (Frigate) | 0-2s | 0-2s | 0-2s | Depends on camera FPS |
| 1 | TTS (Piper) | 0.5-2s | 0.5-2s | 0.5-2s | Neural encoding |
| 1 | ffmpeg encoding | 0.05-0.2s | 0.05-0.2s | 0.05-0.2s | Codec conversion |
| 1 | HTTP server setup | <0.1s | <0.1s | <0.1s | Localhost only |
| 1 | Backchannel warmup (first push only) | 10-20s | 5-7s | instant | RTSP negotiation |
| 1 | go2rtc push | 1-2s | 0.8s | instant | Audio streaming (subsequent) |
| **Stage 1 Total (cold)** | **~11-14s** | **~8s** | **~3s** | **First push** |
| **Stage 1 Total (warm)** | **~4-6s** | **~3s** | **~3s** | **After warmup** |
| 2 | Snapshot download | 0.1-0.5s | 0.1-0.5s | 0.1-0.5s | From Frigate cache |
| 2 | AI analysis (Gemini) | 2-4s | 2-4s | 2-4s | Cloud API latency |
| 2 | AI analysis (Ollama) | 5-15s | 5-15s | 5-15s | CPU-dependent |
| 2 | TTS encoding | 0.5-2s | 0.5-2s | 0.5-2s | Text length dependent |
| 2 | ffmpeg encoding | 0.05-0.2s | 0.05-0.2s | 0.05-0.2s | Codec conversion |
| 2 | Audio queue wait | 0-10s | 0-10s | 0-10s | Waits for Stage 1 |
| **Stage 2 Total** | **~8-30s** | **~8-30s** | **~8-30s** | **Depends on AI backend** |
| 3 | Video download | 0.5-1s | 0.5-1s | 0.5-1s | 5-10 frames |
| 3 | Behavioral analysis | 5-10s | 5-10s | 5-10s | Ollama/Gemini analysis |
| 3 | TTS encoding | 1-3s | 1-3s | 1-3s | Longer message |
| **Stage 3 Total** | **~15-25s** | **~15-25s** | **~15-25s** | **Only on persistence** |

**Key differences:**
- **Reolink:** Warmup required (10-20s first push), subsequent pushes 1-2s. CX420 has higher warmup variance.
- **E1 Zoom:** Faster warmup (5-7s), but audio may cut off without 1.5s silence padding. Fastest warmup after CX410.
- **Dahua:** No warmup, instant on all pushes. Best latency for repeated deterrents.

### Resource Utilization

**CPU:**
- Idle: <5% (MQTT listening only)
- TTS (Piper): 15-25% single-core, 1 second
- TTS (espeak): 5-10% single-core, 0.1 seconds
- ffmpeg encoding: 20-30% single-core, 0.2 seconds

**Memory:**
- Base: ~200MB (Python runtime + dependencies)
- Per audio operation: +50MB (ffmpeg buffer)
- AI models: +200-500MB (Ollama cache, if enabled)

**Network:**
- Gemini API call: ~5-10 KB request, ~2-5 KB response
- Ollama local: Internal network only
- Audio push (PCMU): ~64 kbps × duration (e.g., 5 seconds = 40 KB)

### Scalability Notes

- **Multi-camera:** Runs sequentially per detection (low QPS to Frigate MQTT)
- **Concurrent stages:** Async design handles 3+ simultaneous pipelines
- **Rate limiting:** Cooldown prevents spam (default 30 seconds)
- **Storage:** Audio files auto-cleaned (10-second TTL)

## Integration Points

### Frigate Dependencies

- MQTT broker (Frigate provides)
- Person detection events (Frigate publishes)
- Snapshot images (Frigate saves to disk)
- Stream URLs (Frigate config provides)
- Go2rtc endpoint (Frigate includes)
- Audio codec auto-detection (from SDP stream descriptor)

### Camera Auto-Codec Detection

VoxWatch automatically detects supported audio codecs from go2rtc stream information:
- **PCMU cameras (Reolink):** Detected as `pcmu/8000` or `g711u`
- **PCMA cameras (Dahua):** Detected as `pcma/8000` or `g711a`
- **Fallback:** If codec not detected, defaults to PCMU (Reolink standard)
- No manual codec configuration needed

### External Services

- Google Gemini API (optional, recommended)
  - Requires API key
  - ~$0.075 per 1M input tokens (image analysis)
  - ~5GB free tier monthly (sufficient for home use)

- Ollama (optional, for offline operation)
  - Self-hosted on local hardware
  - LLaVA model (~7GB download)
  - Requires GPU for <5s latency

### Hardware Requirements

- **Minimum:** VoxWatch container + Piper TTS + cached warnings
  - 1 CPU core, 512 MB RAM, 1 GB storage

- **Recommended:** Gemini API + Piper TTS
  - 1-2 CPU cores, 1 GB RAM, 2 GB storage

- **Full offline:** Ollama + LLaVA + Piper TTS
  - 4+ CPU cores or GPU, 4+ GB RAM, 10 GB storage

## Future Enhancements

1. **Two-Way Audio:** Return audio from camera microphone (intercom mode)
2. **Action Logging:** Send detection events to home automation (lights, siren)
3. **Emergency Integration:** Direct 911 API for confirmed intrusions
4. **Multi-Language Support:** Auto-detect intruder language, respond in their language
5. **Behavioral ML:** Learn intruder patterns over time, improve Stage 3 accuracy
6. **Distributed Deployment:** Multiple cameras with shared AI inference backend
