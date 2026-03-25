# VoxWatch Deployment Guide

## Architecture

VoxWatch runs as a Docker container on the same host as Frigate/go2rtc. This gives it localhost access to the go2rtc API (port 1984) for minimal audio push latency.

```
Docker LXC Host (your-docker-host)
├── Frigate container (NVR + go2rtc)
│   └── go2rtc API on port 1984
└── VoxWatch container
    └── Pushes audio via go2rtc API
```

## Prerequisites

- Docker LXC with Frigate/go2rtc already running
- Portainer managing Docker stacks
- NFS storage for persistent data (your-nas)
- Reolink camera(s) with two-way audio configured in go2rtc

## Deployment via Portainer

### Step 1: Create directories on your-nas

```bash
ssh user@your-docker-host "mkdir -p /volume1/docker/voxwatch/audio /volume1/docker/voxwatch/logs"
```

### Step 2: Copy files to your-nas

```bash
# From your dev machine
cd /path/to/voxwatch
tar cf - Dockerfile docker-compose.yml requirements.txt tests/ | \
  ssh user@your-docker-host "cd /volume1/docker/voxwatch && tar xf -"
```

### Step 3: Edit docker-compose.yml with real values

SSH into your-nas and edit `/volume1/docker/voxwatch/docker-compose.yml`:
- Fill in `GEMINI_API_KEY` or `OLLAMA_URL`
- Fill in `CAMERA_USER` and `CAMERA_PASSWORD`
- Uncomment the AI vision option you want

**IMPORTANT:** Portainer requires ALL environment variables to be inline literals.
No `env_file:` directives, no `${VARIABLE}` substitution.

### Step 4: Deploy via Portainer API

```bash
# Read the compose file and create the API payload
cat /volume1/docker/voxwatch/docker-compose.yml | \
  python3 -c "import sys, json; print(json.dumps({'name': 'voxwatch', 'stackFileContent': sys.stdin.read()}))" \
  > /tmp/deploy_voxwatch.json

# Create the stack (endpointId=YOUR_ENDPOINT_ID matches your Docker LXC in Portainer)
curl -X POST "http://YOUR_NAS_IP:9000/api/stacks/create/standalone/string?endpointId=YOUR_ENDPOINT_ID" \
  -H "X-API-Key: YOUR_PORTAINER_API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/deploy_voxwatch.json
```

### Step 5: Verify

```bash
# Check container is running
curl -s "http://YOUR_NAS_IP:9000/api/endpoints/YOUR_ENDPOINT_ID/docker/containers/json?filters=%7B%22name%22%3A%5B%22voxwatch%22%5D%7D" \
  -H "X-API-Key: YOUR_PORTAINER_API_KEY" | python3 -m json.tool

# Test audio push from inside the container
docker exec voxwatch python tests/test_full_pipeline.py \
  --go2rtc-url http://localhost:1984 --camera frontdoor
```

## Updating

To update VoxWatch after code changes:

1. Delete the existing stack via Portainer API or UI
2. Re-copy files to your-nas
3. Re-create the stack (Step 4 above)

Portainer caches the docker-compose.yml internally — stop/start does NOT pick up changes.

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

**Portainer stack creation fails:**
- Remove any `env_file:` directives
- Replace all `${VARIABLE}` with literal values
- See your Portainer deployment docs for known Portainer quirks
