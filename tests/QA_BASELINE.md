# VoxWatch QA Baseline Manifest
# Version: 1.0 | Date: 2026-03-24 | Coverage: All endpoints, components, and behaviors

This manifest maps EVERY testable element in the VoxWatch system. If something
is not listed here, it is not covered in QA. Update this document whenever the
codebase changes.

---

## Section 1: API Endpoints

### Authentication (all /api/* routes)

| Field | Value |
|-------|-------|
| Mechanism | HTTP Bearer token via Authorization header |
| Env var | DASHBOARD_API_KEY |
| Dev mode | If DASHBOARD_API_KEY unset, all requests pass (warning logged) |
| Comparison | hmac.compare_digest() constant-time |
| Missing header | HTTP 401 with WWW-Authenticate |
| Wrong token | HTTP 403 |

### POST /api/audio/test
- Push test audio to camera speaker via go2rtc
- Request: camera_name (required, regex validated), message (optional, max 200)
- Response: success, camera, stream_name, message
- Errors: 400 (bad name), 404 (not found), 429 (rate limit), 503 (go2rtc down)
- Behavior: warmup silence → 2s wait → real audio

### POST /api/audio/preview
- Generate deterrent audio preview for browser playback
- Request: persona, voice, provider, provider_host, message, speed
- Response: audio/wav streaming
- Dispatch personas proxy to VoxWatch port 8892, fallback to local TTS

### POST /api/audio/upload-intro
- Upload custom dispatch channel intro audio file (WAV/MP3)
- Request: multipart/form-data with audio file (max 10MB)
- Response: saved path, file size, detected format
- Validates audio magic bytes (RIFF, MP3, Ogg, FLAC)
- Saves atomically to /config/audio/dispatch_intro.wav

### POST /api/audio/generate-intro
- Generate dispatch intro via TTS and optionally save
- Proxies to VoxWatch Preview API for local TTS providers
- Falls back to direct cloud synthesis (ElevenLabs, OpenAI, Cartesia)
- Returns WAV bytes with X-Intro-Saved header

### GET /api/cameras
- List all cameras (config + Frigate + go2rtc merged)
- Response: array of CameraStatus

### GET /api/cameras/{name}
- Single camera details; name validated against ^[a-zA-Z0-9_-]+$
- Errors: 400 (invalid chars), 404 (not found)

### GET /api/cameras/{name}/snapshot
- Proxied JPEG from Frigate
- Errors: 400, 404, 502 (Frigate down), 503

### POST /api/cameras/{name}/identify
- ONVIF WS-Security probe for camera model
- Response: identified, camera_ip, manufacturer, model, firmware, speaker_status

### GET /api/config
- Config as JSON with secrets masked (***MASKED***)
- ${ENV_VAR} tokens preserved as-is

### GET /api/config/raw
- Config as masked YAML text

### PUT /api/config
- Validate + atomically save config
- Restores masked secrets from disk before writing
- Errors: 400 (validation), 422 (malformed)

### POST /api/config/validate
- Dry-run validation, no file write

### GET /api/status
- Full system status: Frigate + go2rtc + cameras + last events

### GET /api/system/health
- Fast in-process check (no outbound requests)

### GET /api/system/info
- Hostname, platform, Python version, paths

### GET /api/system/frigate
- Live Frigate probe

### GET /api/system/go2rtc
- Live go2rtc probe

### POST /api/system/test-ai
- Test AI provider connectivity with masked key resolution

### POST /api/system/test-tts
- Test TTS provider connectivity

### GET /api/system/logs
- Tail log file with level filtering
- Supports both console and file log formats

### POST /api/system/mqtt-simulation
- Publish synthetic Frigate event to MQTT

### POST /api/wizard/detect
- Probe camera backchannel capabilities

### POST /api/wizard/test-audio
- Generate test tone and push via go2rtc

### GET /api/wizard/serve/{filename}
- Serve wizard WAV files (path traversal protected)

### POST /api/wizard/save
- Save camera config (upsert)

---

## Section 2: Frontend Routes

| Path | Page | Description |
|------|------|-------------|
| / | DashboardPage | System hero + camera grid + activity + quick actions |
| /cameras | CamerasPage | Camera hub with detail panel, deep-link via ?selected= |
| /config | ConfigPage | Form Editor (6 tabs) + Advanced YAML (Monaco) |
| /tests | TestsPage | 5 sections: Audio, TTS, Camera, MQTT Sim, Logs |
| /wizard | WizardPage | 7-step camera setup wizard |
| * | NotFoundPage | 404 |

---

## Section 3: Config Tabs

1. Services — Frigate + go2rtc connection settings
2. Mode — Active hours, cooldown, min_score
3. AI Provider — Primary + fallback with test connection
4. Pipeline — Initial Response → Escalation → Resolution
5. TTS/Personality — Engine selection + response mode picker
6. Logging — Level + file path

---

## Section 4: Config Fields (key defaults)

- frigate.host: "localhost", port: 5000
- go2rtc.host: "localhost", api_port: 1984
- conditions.min_score: 0.7, cooldown_seconds: 60
- ai.primary: gemini-3.1-flash, fallback: ollama/llava:7b
- tts.engine: "piper", model: "en_US-lessac-medium"
- audio.codec: "pcm_mulaw", sample_rate: 8000
- response_mode.name: "private_security"
- pipeline: initial_response enabled (delay 0), escalation enabled (delay 6)

---

## Section 5: Detection Pipeline

```
MQTT event (type=new, label=person)
  → Guard: active_hours → Guard: cooldown → Guard: min_score
  → Warmup push (concurrent with AI)
  → Initial Response (t=0): mode-specific pre-cached message
  → Escalation (t=6s): AI snapshot analysis + TTS
  → Resolution (optional): "Area clear" when person leaves
```

---

## Section 6: TTS Providers

piper → kokoro → elevenlabs → cartesia → polly → openai → espeak
(espeak always appended as final fallback)

---

## Section 7: AI Providers

gemini (video+images) → openai (images) → anthropic (images) → grok (images) → ollama (single image) → custom (images)

---

## Section 8: Known Issues

1. Backchannel warmup required (first push discarded)
2. Reolink=PCMU, Dahua=PCMA codec mismatch
3. ONVIF identify fails on some cameras
4. go2rtc stream name must match exactly
5. Rate limits reset on process restart
6. Masked secrets restored from disk on PUT
7. ${ENV_VAR} tokens unresolved in dashboard
8. Events log rotates at 5MB
9. Wizard temp files cleaned on next test-audio call
10. SPA catch-all has path traversal guard
11. Dispatch preview requires VoxWatch on port 8892
12. Config validators run in order (cameras → enabled)

---

*Generated: 2026-03-24 | Update on any API, component, or config change*
