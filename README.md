# VoxWatch

**Make your cameras talk back.**

VoxWatch turns your security system into something that actually reacts. Instead of silent recordings or generic alarms, it calls out intruders in real-time, describes exactly what they're doing, and escalates if they stay.

## What It Feels Like

Someone walks up to your property...

> "All units, be advised. Subject at front entrance."
> [pause]
> "Copy dispatch. Unit 7 en route."

That's what they hear.

---

## The Problem

Most security systems don't deter anything. A loud beep doesn't mean someone is watching. Intruders know that.

VoxWatch changes that. It makes it obvious:
- you see them
- you're describing them
- and you're reacting in real-time

---

## Why It Works

Generic alarms are ignored.

Specific, real-time callouts create immediate psychological pressure.

The moment someone hears:
> "We can see the black hoodie and you testing the gate"

They know this isn't automated noise. Someone is actually watching. That changes behavior immediately.

---

## How It Works

```
Frigate NVR        MQTT         VoxWatch Service
   ┌──────┐        Event    ┌──────────────────┐
   │Detect│ ──────────────> │ Stage 1: Instant │
   │Person│                 │ Pre-cached Msg   │
   └──────┘                 │                  │
                            │ (AI analysis in  │
                            │  background)     │
                            │                  │
                            │ Stage 2: AI      │
                            │ Description      │
                            │ (if person wait) │
                            │                  │
                            │ Stage 3: Video   │
                            │ Behavior         │
                            │ (if still there) │
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

---

## Three-Stage Escalating Deterrent

### Stage 1: Instant Pre-Cached Warning (0-2 seconds)
- Plays immediately when person detected
- Generic warning message (pre-generated at startup)
- Runs in parallel with AI analysis to hide latency
- Tells intruder they are on camera and recorded

### Stage 2: AI Appearance Description (5-8 seconds later)
- AI analyzes 3 snapshots of the person
- Describes appearance: hoodie, tattoos, build, height, clothing colors
- Personalized, specific description delivered by configured response mode
- Psychological impact: "You've been identified"

### Stage 3: Behavioral Analysis (15-25 seconds later, if person still present)
- AI analyzes video clip (or snapshots if video unavailable)
- Describes actions: approaching gate, looking around, testing door
- Behavioral escalation: "We see what you're doing"
- Only fires if person still detected (Frigate re-check)

---

## Response Modes (9 Core + 2 Situational + 5 Fun)

Control not just what is said, but *how it's said*. Response modes inject personality into the deterrent — from professional security guard to theatrical pirate.

### Core Modes (Professional Security Use)

| Mode | Speaking Style | Typical Use |
|------|---|---|
| **police_dispatch** | Female dispatcher voice with full radio effects, 10-codes, officer response | Default. Sounds like real law enforcement being dispatched. Crown jewel. |
| **live_operator** | Simulates real person watching live | "I can see you moving to the left." |
| **private_security** | Professional, firm, corporate | "You are on private property and under surveillance." |
| **recorded_evidence** | Cold, robotic, system-driven | "Subject recorded. Entry logged. Authorities notified." |
| **homeowner** | Personal, calm, direct | "Hey. I can see you. You need to leave." |
| **automated_surveillance** | Neutral AI voice | "Movement detected. Behavior flagged." |

### Situational Modes

| Mode | Use Case |
|------|----------|
| **guard_dog** | Imply dog threat. "They haven't been fed yet." |
| **neighborhood_watch** | Community pressure. "Neighbors have been alerted." |

### Fun / Novelty Modes (Demos + Entertainment)

| Mode | Persona |
|------|---------|
| **mafioso** | Tough Italian-American wiseguy watching cameras |
| **tony_montana** | Scarface energy — aggressive, territorial |
| **pirate_captain** | Boisterous pirate. "Walk the plank!" |
| **british_butler** | Proper butler. Polite but absolutely clear you're unwelcome. |
| **disappointed_parent** | Guilt-tripping. "Really? At this hour?" |

### Custom Mode

Write your own persona modifier via `response_mode.custom_prompt` in config.

---

## Police Dispatch: The Crown Jewel

The **police_dispatch** response mode is the flagship feature. It simulates a complete police radio transmission with full radio effects, 10-codes, and an officer response.

### The Full Dispatch Sequence

When activated, the system plays:

1. **Channel Intro (optional, configurable)**
   - Clean voice: "Connecting to County Sheriff dispatch frequency..."
   - ~1 second of radio tuning static
   - Tail end of another dispatch call (radio-processed, random)
   - Brief squelch pause

2. **Main Dispatch Call**
   - [beep] Dispatcher (female, radio-processed): "All units, 10-97 at 482 Elm Street. One suspect on property. Subject wearing dark hoodie, estimated six feet tall. Last seen near the gate."

3. **Officer Response (optional, configurable)**
   - 1.5–2.5 second pause (authentic radio gap)
   - [beep] Officer (male, different voice, radio-processed): "Copy dispatch. Unit 7 en route. ETA two minutes."

### Customization Options

All fully configurable via `response_mode.dispatch` in config:

```yaml
response_mode:
  name: "police_dispatch"
  dispatch:
    address: "482 Elm Street"           # Property street address
    city: "Springfield"                  # City name
    state: "CA"                          # State code
    agency: "County Sheriff"             # Responding agency name
    callsign: "Unit 7"                   # Dispatcher unit designation
    officer_callsign: "Unit 7"           # Officer unit (uses callsign if empty)
    officer_voice: "am_fenrir"           # Male voice ID for officer (Kokoro-only)
    include_address: true                # false = use generic "the property"
    channel_intro: true                  # Play intro before dispatch
    officer_response: true               # Append officer acknowledgment
```

---

## AI Vision Providers (6 Options + Custom)

Choose based on cost, latency, video support, and local vs. cloud preference.

### Provider Comparison

| Provider | Quality | Latency | Cost per Detection | Video Support | Local/Cloud | Setup |
|----------|---------|---------|----|----|----|----|
| **Google Gemini Flash** | Excellent | 2-5s | ~$0.001 | Yes (native) | Cloud | API key |
| **OpenAI GPT-4o** | Excellent | 3-5s | ~$0.005-0.012 | No (snapshots) | Cloud | API key |
| **Anthropic Claude Haiku** | Excellent | 3-5s | ~$0.003 | No (snapshots) | Cloud | API key |
| **xAI Grok** | Good | 3-5s | ~$0.005 | No (snapshots) | Cloud | API key |
| **Ollama (LLaVA)** | Good | 5-15s | Free | No (snapshots) | Local | Self-hosted |
| **Custom OpenAI-compatible** | Varies | Varies | Varies | Varies | Either | Custom endpoint |
| **Fallback Error Handling** | Safe | <1s | Free | N/A | Local | Auto |

### Nightvision Awareness

VoxWatch automatically adapts prompts for infrared/nightvision footage:
- **Does NOT** describe colors (unreliable in IR)
- **Focuses on:** Silhouette, build, height, gait, posture
- **Describes:** Clothing type (hoodie, jacket, cap), shape, distinctive features
- **Avoids:** Color-dependent identification

This prevents false descriptions like "person in blue shirt" when the IR image shows only shades of gray.

### Fallback Chain

Automatic fallback to secondary provider if primary fails. Degrades gracefully.

```yaml
ai:
  primary:
    provider: "gemini"
    model: "gemini-3.1-flash"
    api_key: "${GEMINI_API_KEY}"
    timeout_seconds: 5
  fallback:
    provider: "ollama"
    model: "llava:7b"
    host: "http://ollama-server:11434"
    timeout_seconds: 8
```

---

## TTS Providers (7 Options with Fallback Chain)

Seven text-to-speech engines with automatic fallback. Each optimized for different priorities (quality, speed, cost, local, cloud).

### Provider Comparison

| Provider | Quality | Latency | Cost | Local/Cloud | Setup |
|----------|---------|---------|------|----|----|
| **Kokoro-82M** | Near-human | 1-3s | Free | Local | ONNX server or local |
| **Piper** | Natural | <1s | Free | Local | Bundled in Docker |
| **ElevenLabs** | Highest quality | 1-3s | $5-99/month | Cloud | API key + voice ID |
| **Cartesia Sonic** | Excellent | 0.5-1s (fastest) | Paid | Cloud | API key |
| **Amazon Polly** | Good | 1-3s | $0.02/1k chars | Cloud | AWS credentials |
| **OpenAI TTS** | Good | 1-3s | $0.015/1k chars | Cloud | API key |
| **espeak-ng** | Robotic but clear | <1s | Free | Local | Always available |

### Recommended Setup

**Best Quality + Cost Efficiency:**
```yaml
tts:
  provider: "kokoro"           # Near-human local quality
  fallback_chain: ["piper", "espeak"]  # Fallback chain
  kokoro:
    host: "http://kokoro-server:8880"
    voice: "af_heart"
    speed: 1.0
```

**Budget Option (all local):**
```yaml
tts:
  provider: "piper"
  fallback_chain: ["espeak"]
```

**Premium Quality (cloud):**
```yaml
tts:
  provider: "elevenlabs"
  fallback_chain: ["piper", "espeak"]
  elevenlabs:
    api_key: "${ELEVENLABS_API_KEY}"
    voice_id: "your-voice-id"
    model: "eleven_flash_v2_5"
```

### Fallback Chain Behavior

1. Primary provider attempts TTS
2. If it fails, fallback_chain providers are tried in order
3. espeak is always the last resort (guaranteed success if installed)

---

## Audio Push & Camera Backchannel

VoxWatch pushes audio through the camera's backchannel using **go2rtc**. All audio is one-way (outbound only — no recording).

### Tested Cameras

| Camera | Manufacturer | Audio Codec | Speaker | Status |
|--------|--------------|------------|---------|--------|
| **Reolink CX410** | Reolink | PCMU/8000 (G.711 μ-law) | Built-in | Working |
| **Reolink CX420** | Reolink | PCMU/8000 (G.711 μ-law) | Built-in | Working |
| **Reolink E1 Zoom** | Reolink | PCMU/8000 (G.711 μ-law) | Built-in | Working |
| **Dahua IPC-Color4K-T180** | Dahua | PCMA/8000 (G.711 A-law) | Built-in | Working |
| **Dahua IPC-T54IR** | Dahua | PCMA/8000 (G.711 A-law) | RCA out only | Compatible (external speaker) |
| **Dahua IPC-B54IR** | Dahua | PCMA/8000 (G.711 A-law) | RCA out only | Compatible (external speaker) |

### Per-Camera Codec Override

Different cameras use different audio codecs. VoxWatch auto-detects via the setup wizard, or override manually:

```yaml
cameras:
  frontdoor:
    enabled: true
    go2rtc_stream: "frontdoor"
    audio_codec: "pcmu_mulaw"    # Reolink — G.711 μ-law
  backyard:
    enabled: true
    go2rtc_stream: "backyard"
    audio_codec: "pcma_alaw"     # Dahua — G.711 A-law
```

### Latency Research

See [docs/AUDIO_PUSH_RESEARCH.md](docs/AUDIO_PUSH_RESEARCH.md) for deep-dive latency analysis, warmup patterns, and go2rtc backchannel behavior on different camera models.

**Current method:** go2rtc `/api/ffmpeg` endpoint
- **Stage 1 latency:** 0-2 seconds (pre-cached)
- **Stage 2 latency:** 5-8 seconds (AI analysis hidden behind Stage 1)
- **Stage 3 latency:** 15-25 seconds (behavioral analysis)

---

## Attention Tones

An optional attention tone (beep/alert) can be played before each TTS message to grab attention.

### Built-in Tones

| Tone | Duration | Sound | Use Case |
|------|----------|-------|----------|
| **short** | 0.5s | Sharp 800 Hz beep | Quick attention grab |
| **long** | 1.0s | Two-tone alert (800 + 1000 Hz) | Fuller alert for Stage 2 |
| **siren** | 1.5s | Rising sweep (400–1200 Hz) | Escalation for Stage 3 |
| **none** | 0s | (disabled) | Silent (no tone) |

### Custom Tones

Provide an absolute path to a WAV file (must be in camera codec, e.g., PCMU 8kHz mono):
```yaml
audio:
  attention_tone: "/data/my_custom_tone.wav"
```

### Per-Stage Overrides

Different tones for each stage:
```yaml
messages:
  stage1_tone: "short"    # Quick beep for instant warning
  stage2_tone: "long"     # Fuller alert for AI description
  stage3_tone: "siren"    # Escalating siren for behavioral warning
```

---

## Web Dashboard

Full-featured React + FastAPI dashboard for configuration, testing, and monitoring.

**Access at:** `http://your-host:33344`

### Features

- **System Status Dashboard** — Real-time connectivity status to Frigate, go2rtc, and AI providers with cost estimates
- **Camera Setup Wizard** — Interactive 5-step guided flow to test camera audio compatibility
  - Detect your camera in go2rtc
  - Identify backchannel codec (PCMU vs. PCMA)
  - Generate and test a tone
  - Configure audio settings
  - Save to config.yaml
- **Camera Management** — View all cameras, backchannel detection status, last detection timestamps
- **Configuration Editor** — Form-based YAML editor with dropdowns, smart defaults, and validation
  - Response mode picker with Core/Situational/Fun groupings
  - AI provider configuration with connection testing
  - TTS provider config with in-browser voice preview
  - Per-camera audio codec override
- **Audio Test Player** — Push test audio to any camera (mobile-friendly big tap targets, rate-limited)
- **Advanced YAML Editor** — CodeMirror-based syntax highlighting for manual config editing
- **Dark Mode** — Eye-friendly theme
- **Hot-Reload** — Changes to config.yaml take effect without restarting the service

---

## Configuration

All settings in a single `config.yaml` file with environment variable substitution.

### Quick Example

```yaml
# Frigate connection
frigate:
  host: "localhost"
  port: 5000
  mqtt_host: "localhost"
  mqtt_port: 1883

# go2rtc connection
go2rtc:
  host: "localhost"
  api_port: 1984

# Cameras to monitor
cameras:
  frontdoor:
    enabled: true
    go2rtc_stream: "frontdoor"

# Detection conditions
conditions:
  min_score: 0.7
  cooldown_seconds: 60
  active_hours:
    mode: "sunset_sunrise"  # or "fixed" or "always"

# AI Vision — primary + fallback
ai:
  primary:
    provider: "gemini"
    model: "gemini-3.1-flash"
    api_key: "${GEMINI_API_KEY}"
  fallback:
    provider: "ollama"
    host: "http://ollama-server:11434"

# Text-to-Speech
tts:
  provider: "kokoro"
  fallback_chain: ["piper", "espeak"]

# Audio output format
audio:
  codec: "pcm_mulaw"
  sample_rate: 8000
  channels: 1
  attention_tone: "short"

# Response Mode
response_mode:
  name: "police_dispatch"
  dispatch:
    address: "123 Main Street"
    city: "Springfield"
    agency: "County Sheriff"

# Pipeline escalation
pipeline:
  initial_response:
    enabled: true
    delay: 0
  escalation:
    enabled: true
    delay: 6
  resolution:
    enabled: false

# Property details
property:
  street: "123 Main Street"
  city: "Springfield"
  state: "CA"
```

**See [config/config.yaml](config/config.yaml) for the complete reference** with all options, defaults, and inline documentation.

---

## Quick Start

### 1. Prerequisites

- **Frigate NVR** — running and detecting people
- **MQTT broker** — accessible from VoxWatch
- **go2rtc** — running and configured with audio backchannel support
- **Docker + Docker Compose**
- **Camera with speaker** — built-in or external via RCA audio out

### 2. Clone and Configure

```bash
git clone https://github.com/badbread/VoxWatch.git
cd VoxWatch
cp config/config.yaml config/my-config.yaml
nano config/my-config.yaml
```

### 3. Set Environment Variables

```bash
export GEMINI_API_KEY="your-api-key"
export MQTT_USER="mqtt-username"
export MQTT_PASSWORD="mqtt-password"
```

Or in `.env` file:
```
GEMINI_API_KEY=your-api-key
MQTT_USER=mqtt-username
MQTT_PASSWORD=mqtt-password
```

### 4. Deploy with Docker Compose

```bash
docker-compose up -d
```

Two containers start:
- `voxwatch` — core deterrent service (listens for detections, generates audio, pushes to cameras)
- `voxwatch-dashboard` — web UI for setup and management (optional after initial config)

### 5. Open the Dashboard

Navigate to `http://your-host:33344`

If this is a fresh install (no config.yaml), you'll be automatically redirected to the **Setup Wizard** which walks you through:
1. Connect to Frigate (auto-discovers cameras and MQTT)
2. Choose AI provider and enter API key
3. Choose TTS voice engine
4. Pick your response mode (Live Operator, Police Dispatch, etc.)
5. Select cameras with speakers and test audio
6. Review and generate config — VoxWatch starts automatically

> **Note:** The dashboard is optional after initial setup. VoxWatch runs independently using config.yaml. You can stop the dashboard container to save resources — your deterrent system keeps working. Edit config.yaml manually via SSH if needed — changes are hot-reloaded within 10 seconds.

---

## Active Hours & Scheduling

VoxWatch can be configured to only respond during certain times.

### Mode: Always Active (24/7)

```yaml
conditions:
  active_hours:
    mode: "always"
```

### Mode: Sunset to Sunrise (Nighttime Only)

```yaml
conditions:
  active_hours:
    mode: "sunset_sunrise"
    latitude: 37.7749
    longitude: -122.4194
```

Uses solar calculation via `astral` library. Recommended for residential use.

### Mode: Fixed Clock Window

```yaml
conditions:
  active_hours:
    mode: "fixed"
    start: "22:00"  # 10 PM
    end: "06:00"    # 6 AM
```

Handles midnight crossing automatically.

---

## Legal Considerations

VoxWatch broadcasts one-way audio deterrents through camera speakers. This is not recording. Laws vary significantly by jurisdiction.

**Key points:**
- VoxWatch broadcasts warnings (one-directional only)
- No audio is recorded from the intruder
- Two-party recording consent laws generally do NOT apply
- Property owners have the right to deter trespassers with reasonable measures
- Audio warnings are considered reasonable in most jurisdictions
- Signage (e.g., "Audio Deterrent Active") strengthens your legal position

**Important:** Consult a licensed attorney in your jurisdiction before deployment.

See [docs/LEGAL.md](docs/LEGAL.md) for detailed guidance covering US (all states), UK, EU (GDPR), and Australia.

---

## Architecture

### Service Structure

**Core Service** (`voxwatch`)
- Python 3.11 + FastAPI
- MQTT listener for Frigate detection events
- Three-stage escalating deterrent pipeline
- TTS generation with automatic fallback
- Audio push via go2rtc HTTP API
- Hot-reload configuration (changes apply without restart)
- Event logging (events.jsonl) and status monitoring (status.json)

**Dashboard** (`voxwatch-dashboard`)
- React 18 + TypeScript + Tailwind CSS frontend
- FastAPI backend with configuration and camera APIs
- Real-time system status
- Interactive camera setup wizard
- Audio test player with rate limiting

### Configuration Hot-Reload

The service polls `config.yaml` every 10 seconds. When the file changes:
1. Config is reloaded (environment variables re-substituted)
2. Only modified components are reinitialized
3. In-flight detections continue using old config
4. Dashboard shows updated status

**No restart needed.**

### Data Files

All runtime data in `/data`:
- `status.json` — Real-time service status (updated every 5s)
- `events.jsonl` — JSON Lines log of all detections (one per line)
- `audio/` — Cached TTS audio files
- `voxwatch.log` — Service logs

---

## Radio Effects

The **police_dispatch** mode includes authentic radio processing:

### Radio Intensity Presets

| Preset | Bandpass | Compression | Noise | Use Case |
|--------|----------|-------------|-------|----------|
| **low** | 250–3400 Hz | Gentle | Subtle | Natural, conversational radio |
| **medium** | 300–3000 Hz | Moderate | Moderate | Standard police radio (default) |
| **high** | 400–2800 Hz | Aggressive | Heavy | Tight, gritty radio scanner sound |

### Customization

```yaml
radio_effect:
  enabled: true
  intensity: "medium"        # low, medium, high
  bandpass_low: 300          # Hz — high-pass cutoff
  bandpass_high: 3000        # Hz — low-pass cutoff
  noise_level: 0.03          # 0.0–1.0 background static
  squelch_enabled: true      # add squelch release sound
```

---

## Need Help Setting This Up?

If you want VoxWatch running without the hassle, I offer setup services:

- **Remote Setup ($200)** — You already have Frigate running. I connect remotely, install VoxWatch, configure everything, and test audio.
- **Full System Setup ($600+)** — I set up Frigate + VoxWatch end-to-end on your hardware.

If you're interested, reach out: jason@voxwatch.dev

---

## Built in the Open (AI-Assisted)

VoxWatch was built using a heavily **AI-assisted workflow** (primarily Claude), with a focus on making the codebase:

- easy to read
- easy to fork
- easy to extend

A lot of effort went into structuring this so other people can jump in without fighting the code.

I've also used agent-based reviews to run **security and architecture audits**, but I want to be clear:

> This is my first time putting something like this out publicly at this level.

If you see:
- weird patterns
- over-engineering
- things that feel "AI-ish"
- or just a better way to do something

I'd genuinely appreciate the feedback.

---

## Help Make This Better

If you're coming from the Frigate / homelab world, your input is especially valuable.

Things I'd love help with:
- tightening performance
- simplifying config flows
- improving camera compatibility
- catching security issues

Even small PRs or issues are useful right now.

---

## Why This Exists

This project started as:

> "What if cameras didn't just detect... but actually *confronted*?"

Everything here is built around that idea.

If it ever becomes:
- bloated
- overcomplicated
- or loses that core purpose

Call it out.

---

## Side Note

I tend to build fast and refine in public.

If you're curious how I approach stuff like this:
https://badbread.com

---

## Contributing

We welcome contributions, especially:
- **Camera compatibility reports** — Test on your camera and report results
- **Bug fixes** — File issues with reproduction steps
- **Feature requests** — Open a discussion before starting code

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR guidelines.

**Development Setup:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cd dashboard/frontend
npm install
npm run dev

# In another terminal, from dashboard/backend:
uvicorn main:app --reload
```

---

## Roadmap

### In Progress
- **Camera Zones** — Group cameras (front door + front yard) so one detection triggers one speaker

### Planned
- **Home Assistant Integration** — Push notifications, HA automation triggers
- **Dynamic TTS Libraries** — Install providers on demand instead of bundling all

### Community Requests
- More persona characters
- Custom voice models for TTS
- Video clip retention for evidence
- SMS/Telegram notifications on detection

---

## License

VoxWatch is licensed under **GNU General Public License v3.0**.

- **Open-source & personal use:** Free, forever.
- **Commercial use in closed-source products:** Requires a commercial license.

Contact `jason@voxwatch.dev` for licensing inquiries.

---

## Support VoxWatch

If VoxWatch made your setup more powerful (or just more fun), consider supporting development.

Supporters get:
- advanced response modes (Dispatch, Surveillance, etc.)
- radio audio effects
- smarter escalation behavior
- early access to new features

https://buymeacoffee.com/badbread

---

## Built With

[Frigate NVR](https://frigate.video) | [go2rtc](https://github.com/AlexxIT/go2rtc) | [Google Gemini](https://ai.google.dev) | [Kokoro TTS](https://huggingface.co/hexgrad/Kokoro-82M) | [Piper TTS](https://github.com/rhasspy/piper) | [FastAPI](https://fastapi.tiangolo.com) | [React](https://react.dev) | [Tailwind CSS](https://tailwindcss.com) | [Docker](https://www.docker.com)

---

## More Information

- [Architecture Guide](docs/ARCHITECTURE.md) — Deep dive into system design
- [Supported Cameras](docs/SUPPORTED_CAMERAS.md) — Full camera compatibility database
- [Audio Push Research](docs/AUDIO_PUSH_RESEARCH.md) — Latency analysis and backchannel optimization
- [Legal Guidance](docs/LEGAL.md) — Jurisdiction-specific legal considerations

---

**GitHub:** [github.com/badbread/VoxWatch](https://github.com/badbread/VoxWatch)
