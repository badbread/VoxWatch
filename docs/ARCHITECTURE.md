# VoxWatch Architecture

Technical architecture reference for VoxWatch, an AI-powered security audio deterrent system that detects persons on camera via Frigate and delivers escalating vocal warnings through camera speakers.

## System Overview

VoxWatch runs as two Docker containers on host networking:

| Container | Stack | Resources | Purpose |
|-----------|-------|-----------|---------|
| `voxwatch` | Python 3.11 | 512MB / 2 CPU | Core detection and audio pipeline |
| `voxwatch-dashboard` | React 18 + FastAPI | 256MB / 1 CPU | Web UI and setup wizard |

**Core ports:**

| Port | Service | Container |
|------|---------|-----------|
| 33344 | Dashboard (FastAPI + React SPA) | voxwatch-dashboard |
| 8891 | Audio HTTP server (serves files to go2rtc) | voxwatch |
| 8892 | Preview API (internal aiohttp) | voxwatch |

Both containers use `network_mode: host` to access Frigate, go2rtc, and MQTT on localhost.

## High-Level Data Flow

```
                         ┌─────────────┐
                         │   Frigate    │
                         │ (Detection)  │
                         └──────┬───────┘
                                │ MQTT: frigate/events
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                        VoxWatch Service                       │
│                                                               │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────┐  │
│  │ MQTT Client  │──▶│  3-Stage     │──▶│  Audio Pipeline   │  │
│  │ (subscriber) │   │  Pipeline    │   │  TTS → ffmpeg →   │  │
│  └─────────────┘   │              │   │  HTTP → go2rtc    │  │
│                     │  AI Vision ──┤   └────────┬──────────┘  │
│                     │  (7 provs)  │            │              │
│                     └──────────────┘            │              │
│                                                 │              │
│  ┌──────────────────┐                           │              │
│  │ MQTT Publisher    │◀── events, status ───────┤              │
│  └────────┬─────────┘                           │              │
└───────────┼─────────────────────────────────────┼──────────────┘
            │                                     │
            ▼                                     ▼
   ┌─────────────────┐                   ┌────────────────┐
   │ Home Assistant   │                   │  go2rtc        │
   │ (automations)    │                   │  (backchannel) │
   └────────┬─────────┘                   └───────┬────────┘
            │                                     │
            │ MQTT: voxwatch/announce              ▼
            └──────────▶ VoxWatch ──▶ TTS ──▶ Camera Speaker
```

**Three integration paths:**

1. **Detection flow:** Frigate → MQTT → VoxWatch → AI + TTS → go2rtc → Camera Speaker
2. **Event publishing:** VoxWatch → MQTT events → Home Assistant
3. **Announcement flow:** Home Assistant → `voxwatch/announce` → VoxWatch → TTS → Camera Speaker

## Three-Stage Deterrent Pipeline

### Stage 1: Pre-Cached Instant Warning (0-2s)

- Plays a pre-cached warning message immediately on person detection
- Backchannel warmup (silent push + 2s wait) runs concurrently with AI analysis start
- No AI analysis required; fixed latency, highly reliable

### Stage 2: AI Snapshot Description (5-8s)

- 3 snapshots captured and sent to AI vision provider
- AI generates a context-aware description of the person and situation
- Natural cadence speech: phrase-level pauses based on punctuation, speed variation
- Response mode templates with 8 substitution variables (see Response Modes)
- Queued after Stage 1 audio completes

### Stage 3: Behavioral Video Analysis (15-25s)

- Video clips sent when supported (Gemini); snapshots fallback for other providers
- Person-still-present check via Frigate API before executing
- Escalated warning based on behavioral analysis
- Only triggers if person remains after Stage 2

## AI Vision Providers

Seven providers with automatic fallback chain:

| Provider | Type | Video Support | Notes |
|----------|------|---------------|-------|
| Gemini | Cloud | Yes (clips) | Primary recommended provider |
| OpenAI | Cloud | No (snapshots) | GPT-4 Vision |
| Anthropic Claude | Cloud | No (snapshots) | Claude vision |
| xAI Grok | Cloud | No (snapshots) | Grok vision |
| Ollama | Local | No (snapshots) | Self-hosted, offline capable |
| Custom OpenAI-compatible | Cloud/Local | No (snapshots) | Any OpenAI-API-compatible endpoint |
| Fallback | N/A | N/A | Generic pre-cached message |

- Automatic fallback chain: if the configured provider fails, the next available provider is tried
- Nightvision-aware prompts: when IR mode is detected, prompts instruct the AI to avoid color descriptions

## TTS Providers

Seven providers with automatic fallback chain:

| Provider | Type | Quality | Notes |
|----------|------|---------|-------|
| Kokoro | Local | High | Neural TTS |
| Piper | Local | High | Neural TTS, pre-installed voice |
| ElevenLabs | Cloud | Very High | Premium voice cloning |
| Cartesia | Cloud | High | Low-latency streaming |
| Amazon Polly | Cloud | High | AWS neural voices |
| OpenAI TTS | Cloud | Very High | Multiple voice options |
| espeak-ng | Local | Low | Always available, robotic fallback |

**Natural cadence speech system:**
- Phrase-level pauses inserted based on punctuation (commas, periods, ellipses)
- Speed variation across phrases for natural rhythm
- Audio postprocessing: loudnorm (EBU R128), compression, silence trimming

## Response Modes

14 built-in modes plus custom mode support, loaded from `voxwatch/modes/loader.py`.

**Mode resolution order:**
1. Camera-specific override (`response_modes.camera_overrides`)
2. `active_mode` setting
3. `response_mode.name` setting
4. Default: `standard`

**AI description variables (8):**

| Variable | Description |
|----------|-------------|
| `{clothing_description}` | What the person is wearing |
| `{location_on_property}` | Where on the property they are |
| `{behavior_description}` | What they are doing |
| `{suspect_count}` | Number of persons detected |
| `{address_street}` | Street address |
| `{address_full}` | Full address |
| `{time_of_day}` | Current time context |
| `{camera_name}` | Name of the detecting camera |

**Persona customization:** mood presets, system names, guard dog names, operator names, surveillance presets.

## Radio Dispatch System

Specialized dispatch modes (`police_dispatch`, `tony_montana_dispatch`) that simulate radio communications.

**Multi-segment architecture:**
1. Channel intro
2. Main dispatch (location/description, crime-in-progress)
3. Squelch pauses between segments
4. Officer response

**Radio effects processing:**
- Bandpass filtering (300-3400Hz telephone band)
- Dynamic compression
- Radio noise overlay
- Squelch sound effects

**Configurable parameters:** address, agency name, callsign, officer voice, radio intensity level.

## Audio Pipeline

```
TTS Output
  │
  ▼
ffmpeg codec conversion (PCM 16-bit 44.1kHz mono → PCMU 8kHz or PCMA 8kHz)
  │
  ▼
Optional attention tone prepend
  │
  ▼
Audio HTTP server (port 8891)
  │
  ▼
go2rtc fetches file via HTTP → pushes to camera backchannel
  │
  ▼
Camera Speaker
```

**Working format:** PCM 16-bit 44.1kHz mono internally, converted to target camera codec (PCMU/G.711 mu-law at 8kHz or PCMA/G.711 A-law at 8kHz).

**Backchannel warmup:** Silent audio push + 2-second wait before real audio. Required for Reolink cameras to initialize the RTSP backchannel.

**Per-camera push locks:** `asyncio.Lock` per camera prevents overlapping audio pushes.

## MQTT Integration

### Inbound Topics

| Topic | Purpose | Filtering |
|-------|---------|-----------|
| `frigate/events` (configurable) | Person detection events | `type: "new"`, `label: "person"`, `score >= min_score` |
| `voxwatch/announce` | TTS announcements from Home Assistant | Camera name + message text |

### Outbound Topics (mqtt_publisher.py)

| Topic | Purpose |
|-------|---------|
| `voxwatch/events/detection` | New person detection |
| `voxwatch/events/stage` | Pipeline stage transitions |
| `voxwatch/events/ended` | Detection event completed |
| `voxwatch/events/error` | Pipeline errors |
| `voxwatch/status` | Service status (LWT: online/offline, retained, QoS 1) |

All outbound payloads are JSON with `event_id`, `timestamp`, `camera`, and context-specific fields. Publishing is fire-and-forget and never blocks the detection pipeline.

## Dashboard Architecture

### Stack

- **Frontend:** React 18 + TypeScript + Tailwind CSS + Vite
- **Backend:** FastAPI + Pydantic + aiohttp

### Key Routers

| Router | Purpose |
|--------|---------|
| `audio.py` | Audio test, announce, preview proxy |
| `cameras.py` | Camera listing and configuration |
| `config.py` | Configuration read/write |
| `system.py` | System status and health |
| `wizard.py` | Setup wizard API |
| `setup.py` | Initial setup flow |

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/audio/test` | POST | Test audio push to a camera |
| `/api/audio/announce` | POST | Send TTS announcement |
| `/api/audio/preview` | POST | Preview TTS output |
| `/api/cameras` | GET | List configured cameras |
| `/api/config` | GET/PUT | Read/write configuration |

### Setup Wizard

9-step auto-discovery flow:
1. Frigate connection
2. MQTT broker
3. Camera discovery
4. AI provider configuration
5. TTS provider configuration
6. Response mode selection
7. Camera-specific configuration
8. Review and confirm
9. Apply and start

### Camera Database

`camera_db.py` contains 7 known camera models with codec and backchannel parameters. Uses fuzzy matching on model strings. Falls back to ONVIF identification for unknown cameras.

## Preview API (Port 8892)

Internal aiohttp server running inside the `voxwatch` service container.

| Endpoint | Purpose |
|----------|---------|
| `/api/preview` | Generate and return TTS audio preview |
| `/api/preview/generate-intro` | Generate mode intro audio |
| `/api/announce` | Push TTS announcement to camera |
| `/api/health` | Health check |

Shares the same `AudioPipeline` instance as the main service (same TTS engines, same codec conversion). The dashboard container proxies preview and announce requests to this API.

## Security

| Mechanism | Implementation |
|-----------|---------------|
| API authentication | Bearer token via `DASHBOARD_API_KEY` env var, validated with `hmac.compare_digest` |
| Rate limiting | 5 audio pushes per camera per 60 seconds on test/wizard endpoints |
| Camera name validation | Regex `^[a-zA-Z0-9_-]+$` (SSRF prevention) |
| Path traversal protection | Validated on SPA static file serving |
| Secrets masking | API keys displayed as `***MASKED**` in API responses |
| CORS | Configurable origins via `CORS_ORIGINS` env var |
| TTS input sanitization | Control character removal before synthesis |

## Configuration System

Single `config.yaml` file with environment variable substitution: `${ENV_VAR}` and `${ENV_VAR:default}`.

### Hot-Reload

The service polls the config file every 10 seconds.

**Hot-reloadable (no restart needed):**
- TTS settings
- Stage 1 message text
- Active hours schedule
- Cooldown timers
- Response mode and active mode
- Dispatch configuration

**Requires container restart:**
- Frigate / go2rtc / MQTT connection parameters
- Camera list
- AI provider API keys
- Audio codec settings
- Pipeline stage enable/disable toggles

**Write safety:** Atomic writes via `tempfile` + `os.replace()`.

## Telemetry and Logging

| File | Format | Rotation | Content |
|------|--------|----------|---------|
| `status.json` | JSON | Written every 5s (overwrite) | Service state, uptime, per-camera stats (detections, audio pushes, cooldowns) |
| `events.jsonl` | JSON Lines | 5MB rotation | One entry per detection event |
| `voxwatch.log` | Text | 10MB/file, 5 backups (50MB total) | Application log |

**Docker logging:** `json-file` driver, `max-size: 10m`, `max-file: 3`.

## Concurrency Model

- **Event loop:** `asyncio` for all I/O (HTTP, audio pipeline, Frigate API)
- **MQTT thread:** `paho-mqtt` runs its own background thread; events bridged to asyncio via `call_soon_threadsafe`
- **Per-camera locks:** `asyncio.Lock` per camera prevents overlapping audio pushes
- **Task tracking:** Active async tasks tracked with automatic cleanup via done callbacks
- **Graceful shutdown:** Drains active tasks, publishes offline LWT status, disconnects MQTT

## Docker Build

Multi-stage Dockerfile producing a non-root container.

| Property | Value |
|----------|-------|
| Base | Python 3.11 |
| System dependencies | ffmpeg, espeak-ng, curl, piper (with `en_US-lessac-medium` voice) |
| Final image size | ~911MB (optimized from 1769MB) |
| Health check | `curl -f http://localhost:8891/` |
| Run user | `voxwatch` (non-root) |
| Docker logging | `json-file`, max-size 10m, max-file 3 |

**Resource limits (docker-compose):**

| Container | Memory | CPU |
|-----------|--------|-----|
| `voxwatch` | 512MB | 2 |
| `voxwatch-dashboard` | 256MB | 1 |
