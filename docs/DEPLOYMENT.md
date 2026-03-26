# VoxWatch Deployment Guide

## Architecture

VoxWatch runs as two Docker containers on the same host as Frigate/go2rtc. Host networking gives localhost access to the go2rtc API (port 1984) for minimal audio push latency.

```
Docker Host
├── Frigate container (NVR + go2rtc)
│   └── go2rtc API on port 1984
├── VoxWatch container (~911MB image)
│   └── Core deterrent service — AI analysis, TTS, audio push
└── VoxWatch Dashboard container (~200MB image, optional after setup)
    └── Web UI on port 33344 — setup wizard, config editor, logs
```

## Prerequisites

- Docker and Docker Compose installed
- Frigate/go2rtc already running on the same host
- Reolink camera(s) with two-way audio configured in go2rtc

## Deployment via Docker Compose

This is the simplest way to get running.

### Step 1: Clone or copy the project

```bash
git clone <repo-url> voxwatch && cd voxwatch
```

### Step 2: Start the stack

```bash
docker compose up -d
```

That's it. No configuration files to edit beforehand.

### Step 3: Run the setup wizard

Open `http://your-host:33344` in a browser. On first run the dashboard
auto-redirects to the setup wizard, which will:

1. Discover your Frigate instance and MQTT broker
2. Detect connected cameras
3. Walk you through AI provider, TTS engine, and deterrent mode selection
4. Write `./config/config.yaml` for you

API keys (Gemini, OpenAI, ElevenLabs) can be entered in the wizard — no
need to put them in docker-compose.yml.

### Step 4: Verify

```bash
# Both containers should be running
docker compose ps

# Test audio push from inside the container
docker exec voxwatch python tests/test_full_pipeline.py \
  --go2rtc-url http://localhost:1984 --camera frontdoor
```

### Updating

```bash
cd /path/to/voxwatch
docker compose pull          # or rebuild: docker compose build
docker compose up -d
```

### Dashboard is optional after setup

Once you are happy with your configuration the dashboard can be stopped
to save resources. The core VoxWatch service runs independently using
`./config/config.yaml`.

```bash
docker compose stop voxwatch-dashboard
```

Bring it back any time with `docker compose start voxwatch-dashboard`.

## Environment Variables

All environment variables are set in `docker-compose.yml`. The defaults
work for most setups; adjust as needed.

| Variable | Default | Description |
|---|---|---|
| `TZ` | `America/Los_Angeles` | Container timezone (affects log timestamps and schedules) |
| `DASHBOARD_PORT` | `33344` | Port the dashboard listens on (host networking) |
| `DASHBOARD_API_KEY` | *(unset)* | Protect the dashboard with a bearer token (recommended for remote access) |
| `GEMINI_API_KEY` | *(unset)* | Google Gemini API key (can also be entered in the dashboard) |
| `OPENAI_API_KEY` | *(unset)* | OpenAI API key (can also be entered in the dashboard) |
| `ELEVENLABS_API_KEY` | *(unset)* | ElevenLabs TTS API key (can also be entered in the dashboard) |
| `PYTHONUNBUFFERED` | `1` | Ensures real-time log output |

## First Run

On the very first start, `./config/config.yaml` does not exist yet. The
system behaves as follows:

1. **voxwatch** starts but waits for a valid config file before
   processing events.
2. **voxwatch-dashboard** detects the missing config and automatically
   redirects every page to the setup wizard at
   `http://your-host:33344/setup`.
3. The wizard discovers Frigate, MQTT, and cameras on the local network,
   then writes `config.yaml`.
4. VoxWatch picks up the new config and begins monitoring.

After the first run you can edit configuration through the dashboard UI
or by editing `./config/config.yaml` directly.

## Volumes and Data

Both containers share two bind-mount directories relative to the
project root:

| Host Path | Container Path | Purpose |
|---|---|---|
| `./config` | `/config` | `config.yaml`, TTS cache, credentials |
| `./data` | `/data` | Logs, generated audio, event history |

The dashboard mounts `./data` as read-only (`:ro`).

## Resource Limits

Defined in `docker-compose.yml`:

| Container | Memory | CPUs |
|---|---|---|
| `voxwatch` | 512 MB | 2.0 |
| `voxwatch-dashboard` | 256 MB | 1.0 |

Logging is capped at 3 rotated files of 10 MB each per container.

## Deployment via Portainer

If you manage your Docker host through Portainer, you can deploy VoxWatch
as a stack.

**IMPORTANT:** Portainer requires ALL environment variables to be inline
literals. No `env_file:` directives, no `${VARIABLE}` substitution.

### Step 1: Create the stack

Paste the contents of `docker-compose.yml` into a new Portainer stack
(Stacks > Add stack > Web editor), or use the API:

```bash
cat docker-compose.yml | \
  python3 -c "import sys, json; print(json.dumps({'name': 'voxwatch', 'stackFileContent': sys.stdin.read()}))" \
  > /tmp/deploy_voxwatch.json

curl -X POST "http://PORTAINER_HOST:9000/api/stacks/create/standalone/string?endpointId=YOUR_ENDPOINT_ID" \
  -H "X-API-Key: YOUR_PORTAINER_API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/deploy_voxwatch.json
```

### Step 2: Open the dashboard

Navigate to `http://your-docker-host:33344` and complete the setup wizard.

### Updating via Portainer

Portainer caches the compose file internally — stop/start does **not**
pick up changes. To update:

1. Delete the existing stack via Portainer API or UI.
2. Re-create the stack with the updated `docker-compose.yml`.

## Running Test Scripts Inside the Container

```bash
# Discovery
docker exec voxwatch python tests/discovery.py --host 192.168.1.100 --password YOUR_CAMERA_PASSWORD

# Generate test audio
docker exec voxwatch python tests/generate_test_audio.py --output-dir /app/audio

# Check go2rtc (localhost since same host)
docker exec voxwatch python tests/test_go2rtc_check.py --url http://localhost:1984 --camera frontdoor

# Push audio test
docker exec voxwatch python tests/test_audio_push.py --url http://localhost:1984 --camera frontdoor

# Full pipeline
docker exec voxwatch python tests/test_full_pipeline.py --go2rtc-url http://localhost:1984 --camera frontdoor
```

## Troubleshooting

**Container can't reach go2rtc:**
- Verify `network_mode: host` is set (not bridge)
- Test: `docker exec voxwatch curl http://localhost:1984/api/streams`

**Audio doesn't play from camera:**
- Check go2rtc can see the camera: `curl http://localhost:1984/api/streams`
- Verify the camera stream name matches exactly
- See [tests/README.md](../tests/README.md) for the tested cameras table

**TTS fails:**
- espeak-ng should be installed in the image
- For higher quality: install piper in the Dockerfile
- Check: `docker exec voxwatch espeak-ng --version`

**Dashboard won't load:**
- Confirm the dashboard container is running: `docker compose ps`
- Check port 33344 is not in use: `ss -tlnp | grep 33344`
- Review logs: `docker compose logs voxwatch-dashboard`

**Portainer stack creation fails:**
- Remove any `env_file:` directives
- Replace all `${VARIABLE}` with literal values
- See your Portainer deployment docs for known Portainer quirks
