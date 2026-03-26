# VoxWatch

[![CI](https://github.com/badbread/VoxWatch/actions/workflows/ci.yml/badge.svg)](https://github.com/badbread/VoxWatch/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**AI-powered security deterrent that makes your cameras talk back.**

VoxWatch turns passive security cameras into active deterrents. When Frigate detects a person, VoxWatch instantly warns them over the camera speaker, then escalates with AI-generated descriptions of their appearance and behavior — all in real-time.

> *"All units, 10-97 at 482 Elm Street. One suspect, dark hoodie, approaching the front gate."*
> [radio pause]
> *"Copy dispatch. Unit 7 en route."*

That's what an intruder hears. Not a beep. Not silence. A specific, real-time callout that makes it obvious someone is watching.

---

## Quick Start

```bash
git clone https://github.com/badbread/VoxWatch.git
cd VoxWatch
docker compose up -d
```

Open `http://your-host:33344` — the setup wizard auto-discovers Frigate, MQTT, and your cameras, then walks you through AI provider, TTS engine, and response mode selection. No manual config needed for first run.

**Prerequisites:** [Frigate NVR](https://frigate.video) + MQTT broker + [go2rtc](https://github.com/AlexxIT/go2rtc) + a camera with a speaker.

---

## How It Works

```
Frigate NVR        MQTT         VoxWatch Service         MQTT        Home Assistant
   ┌──────┐        Event    ┌──────────────────┐       Events    ┌─────────────────┐
   │Detect│ ──────────────> │ Stage 1: Instant │ ──────────────> │ Lights, Locks,  │
   │Person│                 │ Pre-cached Msg   │                 │ Notifications,  │
   └──────┘                 │                  │                 │ Automations     │
                            │ Stage 2: AI      │                 └────────┬────────┘
                            │ Description      │  voxwatch/announce       │
                            │                  │ <───────────────────────┘
                            │ Stage 3: Video   │  (TTS on camera speakers)
                            │ Behavior         │
                            └──────┬───────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    v                             v
              Audio Pipeline              go2rtc Audio Push
              (TTS + Effects)             (RTSP Backchannel)
                    │                             │
                    └──────────────┬──────────────┘
                                   v
                            Camera Speaker
```

### Three-Stage Escalating Deterrent

| Stage | Timing | What Happens |
|-------|--------|-------------|
| **Stage 1: Instant Warning** | 0-2 seconds | Pre-cached warning plays immediately. AI analysis starts in parallel. |
| **Stage 2: AI Description** | 5-8 seconds | AI analyzes snapshots. Describes appearance: clothing, build, height, distinctive features. The intruder hears themselves being described in real-time. |
| **Stage 3: Behavioral Analysis** | 15-25 seconds | If person is still present, AI analyzes video/snapshots for behavior — approaching gate, testing doors, looking around. Escalates the warning. |

Each stage only fires if the person is still detected (Frigate re-check). AI adapts automatically for nightvision — no color descriptions from IR footage.

---

## Response Modes

Control not just *what* is said, but *how* it's said. 14 built-in response modes + custom mode.

### Professional

| Mode | Style | Example |
|------|-------|---------|
| **police_dispatch** | Full radio dispatch with 10-codes, officer response, radio effects | *"All units, 10-97 at 482 Elm. One suspect, dark hoodie..."* |
| **live_operator** | Simulates a real person watching live | *"I can see you moving to the left."* |
| **private_security** | Corporate security firm, firm and professional | *"You are on private property and under surveillance."* |
| **recorded_evidence** | Cold, system-driven, forensic | *"Subject recorded. Entry logged. Authorities notified."* |
| **homeowner** | Personal, calm, direct | *"Hey. I can see you. You need to leave."* |
| **automated_surveillance** | Neutral AI monitoring voice | *"Movement detected. Behavior flagged."* |
| **standard** | Clear, authoritative default | *"Attention. You are being recorded. Leave immediately."* |

### Situational

| Mode | Use Case |
|------|----------|
| **guard_dog** | Imply dog threat. *"They haven't been fed yet."* |
| **neighborhood_watch** | Community pressure. *"Neighbors have been alerted."* |
| **silent_pressure** | Delayed, tension-building response |
| **evidence_collection** | Emphasizes forensic evidence capture |

### Fun / Novelty

| Mode | Persona |
|------|---------|
| **mafioso** | Italian-American wiseguy. *"You picked the wrong house, pal."* |
| **tony_montana** | Scarface energy — aggressive, territorial |
| **pirate_captain** | *"What scallywag dares approach me vessel?"* |
| **disappointed_parent** | Guilt-tripping. *"Really? At this hour?"* |

### Custom Mode

Write your own persona via `response_mode.custom_prompt` in config. Full control over tone, vocabulary, and escalation style.

---

## Police Dispatch: The Crown Jewel

The flagship feature. Simulates a complete police radio transmission with authentic radio effects, 10-codes, and an officer response.

**Full sequence:**

1. **Channel Intro** — Clean voice: *"Connecting to County Sheriff dispatch frequency..."* + radio tuning static + tail end of another call
2. **Main Dispatch** — [beep] Female dispatcher (radio-processed): *"All units, 10-97 at 482 Elm Street. One suspect on property. Subject wearing dark hoodie, estimated six feet tall."*
3. **Officer Response** — [beep] Male officer (different voice, radio-processed): *"Copy dispatch. Unit 7 en route. ETA two minutes."*

All customizable — address, agency, callsign, officer voice, radio intensity, channel intro toggle.

### Radio Effect Presets

| Preset | Sound | Use Case |
|--------|-------|----------|
| **low** | Natural, conversational | Casual radio chatter |
| **medium** | Standard police radio (default) | Realistic dispatch |
| **high** | Gritty scanner sound | Maximum intimidation |

Fine-grained control: bandpass frequency, compression, noise level, squelch toggle.

---

## AI Vision Providers

7 providers with automatic fallback chain. Primary fails? Secondary kicks in seamlessly.

| Provider | Latency | Cost/Detection | Video Support | Local/Cloud |
|----------|---------|----------------|---------------|-------------|
| **Google Gemini Flash** | 2-5s | ~$0.001 | Yes (native) | Cloud |
| **OpenAI GPT-4o** | 3-5s | ~$0.005-0.012 | Snapshots | Cloud |
| **Anthropic Claude Haiku** | 3-5s | ~$0.003 | Snapshots | Cloud |
| **xAI Grok** | 3-5s | ~$0.005 | Snapshots | Cloud |
| **Ollama (LLaVA)** | 5-15s | Free | Snapshots | Local |
| **Custom OpenAI-compatible** | Varies | Varies | Varies | Either |
| **Fallback error handling** | <1s | Free | N/A | Local |

**Nightvision-aware:** Automatically adapts prompts for IR footage — focuses on silhouette, build, and clothing type instead of unreliable colors.

---

## TTS Providers

7 text-to-speech engines with automatic fallback chain.

| Provider | Quality | Latency | Cost | Local/Cloud |
|----------|---------|---------|------|-------------|
| **Kokoro-82M** | Near-human | 1-3s | Free | Local |
| **Piper** | Natural | <1s | Free | Local (bundled) |
| **ElevenLabs** | Highest | 1-3s | $5-99/mo | Cloud |
| **Cartesia Sonic** | Excellent | 0.5-1s | Paid | Cloud |
| **Amazon Polly** | Good | 1-3s | $0.02/1k chars | Cloud |
| **OpenAI TTS** | Good | 1-3s | $0.015/1k chars | Cloud |
| **espeak-ng** | Robotic | <1s | Free | Local (always available) |

**Natural cadence speech:** AI responses are broken into phrases with human-like pauses between thoughts, not read as a single flat script. Punctuation-aware timing and optional per-phrase speed variation across all providers.

---

## Home Assistant Integration

Two-way MQTT integration — no custom components needed.

| Direction | Topic | Purpose |
|-----------|-------|---------|
| VoxWatch → HA | `voxwatch/events/detection` | Person detected — trigger lights, notifications |
| VoxWatch → HA | `voxwatch/events/stage` | Stage fired — escalating automations |
| VoxWatch → HA | `voxwatch/events/ended` | Detection over — restore normal state |
| VoxWatch → HA | `voxwatch/status` | Online/offline (LWT) — availability sensor |
| HA → VoxWatch | `voxwatch/announce` | Play TTS on camera speakers on demand |

### TTS Announcements from HA

Use VoxWatch as a general-purpose announcement system for any camera with a speaker:

```yaml
automation:
  - alias: "Doorbell announcement"
    trigger:
      - platform: state
        entity_id: binary_sensor.doorbell
        to: "on"
    action:
      - service: mqtt.publish
        data:
          topic: "voxwatch/announce"
          payload: '{"camera": "driveway", "message": "Someone is at the front door.", "tone": "short"}'
```

Supports: `camera`, `message`, `voice`, `provider`, `speed`, `tone`. Also available via REST at `POST /api/audio/announce`.

**Full docs with automation examples:** [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md)

---

## Camera Compatibility

VoxWatch pushes audio through camera backchannels via **go2rtc**. One-way outbound only — no recording.

| Camera | Codec | Speaker | Status |
|--------|-------|---------|--------|
| Reolink CX410 | PCMU/8000 | Built-in | Working |
| Reolink CX420 | PCMU/8000 | Built-in | Working |
| Reolink E1 Zoom | PCMU/8000 | Built-in | Working |
| Dahua IPC-Color4K-T180 | PCMA/8000 | Built-in | Working |
| Dahua IPC-T54IR | PCMA/8000 | RCA out | Compatible |
| Dahua IPC-B54IR | PCMA/8000 | RCA out | Compatible |

Per-camera codec override supported. The setup wizard auto-detects backchannel codec.

**Latency:** Stage 1 in 0-2s (pre-cached), Stage 2 in 5-8s (AI hidden behind Stage 1).

---

## Web Dashboard

Full-featured React + TypeScript + Tailwind dashboard at `http://your-host:33344`.

- **Setup Wizard** — 5-step guided flow: discover cameras, detect codecs, test audio, configure, save
- **Camera Management** — Backchannel status, last detection timestamps, ONVIF identification
- **Configuration Editor** — Form-based with dropdowns, connection testing, in-browser voice preview
- **Audio Test Player** — Push test audio to any camera speaker (rate-limited, mobile-friendly)
- **System Status** — Real-time connectivity to Frigate, go2rtc, MQTT, AI providers
- **Dark Mode** — Full dark theme support
- **Hot-Reload** — Config changes apply in ~10 seconds without restart

---

## Configuration

Single `config.yaml` with environment variable substitution (`${GEMINI_API_KEY}`).

```yaml
frigate:
  host: "localhost"
  mqtt_host: "localhost"

go2rtc:
  host: "localhost"

cameras:
  frontdoor:
    enabled: true

conditions:
  min_score: 0.7
  cooldown_seconds: 60
  active_hours:
    mode: "sunset_sunrise"    # or "fixed" or "always"

ai:
  primary:
    provider: "gemini"
    model: "gemini-2.5-flash"
    api_key: "${GEMINI_API_KEY}"

tts:
  provider: "kokoro"
  fallback_chain: ["piper", "espeak"]

response_mode:
  name: "police_dispatch"
  dispatch:
    address: "123 Main Street"
    agency: "County Sheriff"

mqtt_publish:
  enabled: true
  topic_prefix: "voxwatch"
  announce_enabled: true
```

**Active hours:** Always, sunset-to-sunrise (solar calculation via `astral`), or fixed time window with automatic midnight crossing.

**Hot-reload:** Service polls config every 10 seconds. Changes apply without restart — in-flight detections continue on old config.

---

## Deployment

```yaml
# docker-compose.yml (simplified)
services:
  voxwatch:
    image: voxwatch:latest
    network_mode: host
    volumes: [./config:/config, ./data:/data]
    mem_limit: 512m
    restart: unless-stopped

  voxwatch-dashboard:
    image: voxwatch-dashboard:latest
    network_mode: host      # Dashboard on port 33344
    volumes: [./config:/config, ./data:/data:ro]
    mem_limit: 256m
    restart: unless-stopped
```

- **Docker image:** 911MB (optimized from 1769MB — 49% reduction)
- **Network:** Host mode for direct camera/MQTT/go2rtc access
- **Dashboard is optional** after setup — stop it to save resources, deterrent keeps running
- **Data directory:** `status.json` (real-time, 5s interval), `events.jsonl` (detection log), `voxwatch.log`

---

## Architecture

**Core Service** — Python 3.11, ~24k LOC
- MQTT listener for Frigate events + announce topic
- Three-stage async detection pipeline with concurrent warmup
- 7 TTS providers with automatic fallback chain
- Natural cadence speech system (phrase-level pauses + speed variation)
- Full radio dispatch audio composition (multi-segment, multi-voice, radio effects)
- Audio codec conversion via ffmpeg + go2rtc backchannel push
- MQTT event publishing for Home Assistant
- 10-second config hot-reload with environment variable substitution

**Dashboard** — React 18 + TypeScript + FastAPI, ~21k LOC
- Interactive setup wizard with camera auto-discovery
- Form-based config editor with live voice preview
- Camera ONVIF identification cross-referenced against compatibility database
- REST API with Bearer token auth, rate limiting, SSRF protection

**Security:** Camera name validation (strict allowlist pattern), API key authentication, per-camera rate limiting on audio push, input sanitization on all TTS inputs.

---

## Active Hours & Scheduling

| Mode | Config | Behavior |
|------|--------|----------|
| **Always** | `mode: "always"` | 24/7 active |
| **Sunset to Sunrise** | `mode: "sunset_sunrise"` | Solar calculation via `astral` library |
| **Fixed Window** | `mode: "fixed"` | Custom start/end times (handles midnight crossing) |

---

## Legal Considerations

VoxWatch broadcasts one-way audio deterrents — no recording from the intruder.

- Two-party recording consent laws generally do NOT apply (one-directional broadcast)
- Property owners have the right to deter trespassers with reasonable measures
- Signage (e.g., "Audio Deterrent Active") strengthens your legal position

**Consult a licensed attorney in your jurisdiction before deployment.** See [docs/LEGAL.md](docs/LEGAL.md) for guidance covering US, UK, EU (GDPR), and Australia.

---

## Contributing

We welcome contributions — especially camera compatibility reports, bug fixes, and performance improvements.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cd dashboard/frontend && npm install && npm run dev
# In another terminal:
cd dashboard/backend && uvicorn main:app --reload
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for code style and PR guidelines.

---

## Roadmap

**Recently shipped:** Home Assistant two-way MQTT, TTS announce API, persona customization, Docker optimization (49% size reduction), natural cadence speech, email camera reports

**In progress:** Camera zones (group cameras so one detection triggers one speaker)

**Planned:** Dynamic TTS library loading, custom voice models, SMS/Telegram notifications

---

## Why This Exists

> "What if cameras didn't just detect... but actually *confronted*?"

Everything here is built around that idea. If it ever becomes bloated, overcomplicated, or loses that core purpose — call it out.

Built using an AI-assisted workflow (primarily Claude) with a focus on making the codebase easy to read, fork, and extend. If you see something that could be better, I'd genuinely appreciate the feedback.

https://it.badbread.com

---

## License

**GNU General Public License v3.0** — Free for open-source and personal use. Commercial use in closed-source products requires a commercial license. Contact `jason@voxwatch.dev`.

---

## Support VoxWatch

If VoxWatch made your setup more powerful (or just more fun): https://buymeacoffee.com/badbread

---

**Built with:** [Frigate NVR](https://frigate.video) | [go2rtc](https://github.com/AlexxIT/go2rtc) | [Google Gemini](https://ai.google.dev) | [Kokoro TTS](https://huggingface.co/hexgrad/Kokoro-82M) | [Piper TTS](https://github.com/rhasspy/piper) | [FastAPI](https://fastapi.tiangolo.com) | [React](https://react.dev) | [Tailwind CSS](https://tailwindcss.com) | [Docker](https://www.docker.com)

**Docs:** [Home Assistant](docs/HOME_ASSISTANT.md) | [Architecture](docs/ARCHITECTURE.md) | [Supported Cameras](docs/SUPPORTED_CAMERAS.md) | [Audio Research](docs/AUDIO_PUSH_RESEARCH.md) | [Legal](docs/LEGAL.md)
