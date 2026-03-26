# Supported Cameras

This document provides information about cameras tested with VoxWatch, including audio codec support, known limitations, and testing procedures.

## Camera Compatibility Matrix

| Model | Type | Network | Speaker | Backchannel Codec | Status | Tested | Notes |
|-------|------|---------|---------|-------------------|--------|--------|-------|
| Reolink CX410 | PoE Bullet | PoE | Built-in | PCMU (G.711 µ-law) | Working | 2026-03-20 | Primary test device; stable audio. go2rtc /api/ffmpeg blocks 12-20s per push. |
| Reolink CX420 | PoE Bullet | PoE | Built-in | PCMU (G.711 µ-law) | Working | 2026-03-24 | Same behavior as CX410. |
| Reolink E1 Zoom | PoE Indoor PTZ | PoE | Built-in | PCMU (G.711 µ-law) | Working | 2026-03-24 | Audio slightly garbled on sub stream. Tail end of audio may cut off — needs 1.5s silence padding at end. |
| Dahua IPC-Color4K-T180 | PoE Turret | PoE | Built-in | PCMA (G.711 A-law) | Working | 2026-03-24 | MUST use Dahua native RTSP URL — ONVIF URL does NOT expose backchannel. go2rtc returns instantly (doesn't block like Reolink). |
| Dahua IPC-T54IR-AS-2.8mm-S3 | PoE Turret | PoE | RCA audio out only | PCMA (G.711 A-law) | No built-in speaker | 2026-03-24 | Has RCA audio output — could work with external speaker connected to RCA. SDP advertises backchannel but no speaker hardware. |
| Dahua IPC-B54IR-ASE-2.8MM-S3 | PoE Bullet | PoE | RCA audio out only | PCMA (G.711 A-law) | No built-in speaker | 2026-03-24 | Same as IPC-T54IR-AS — RCA out only, no built-in speaker. |
| Dahua IPC-T58IR-ZE-S3 | PoE Turret | PoE | None | N/A | Incompatible | 2026-03-24 | No speaker, no RCA out, no audio output of any kind. |

## Backchannel Audio Specifications

### Reolink Cameras (CX410, CX420, E1 Zoom)

All Reolink cameras in the test fleet use PCMU (G.711 µ-law) backchannel audio with similar characteristics:

**Common Specifications:**
- **Audio Codec:** PCMU (G.711 µ-law)
- **Sample Rate:** 8000 Hz (standard)
- **Channels:** Mono
- **Bit Depth:** 8-bit compressed
- **Bitrate:** 64 kbps
- **Frame Duration:** 20ms

**API Behavior:**
- Uses go2rtc `/api/ffmpeg?dst={stream}&file={audio_url}` endpoint
- Blocks while audio plays (HTTP response waits for playback completion)
- Typical blocking time: 12-20s (includes RTSP setup + audio duration)
- Warmup pattern: First push may not play; second push succeeds
- Backchannel stays warm for 15-30s

**Network Integration:**
- PoE powered (reliable, no WiFi variance)
- RTSP stream: `rtsp://admin:password@{camera-ip}/Preview_01_sub` (sub stream recommended)
- Backchannel: Enabled automatically when RTSP stream established
- **Important:** Do NOT add `backchannel=1` to stream URL in go2rtc config—breaks Frigate's video detection

### Reolink CX410 (Working)

**General Specifications:**
- **Type:** Fixed bullet camera (outdoor, PoE)
- **IP Codec:** H.264 video
- **Audio Codec Support:** PCMU (G.711 µ-law)
- **Sample Rates:** 8000 Hz (standard), 16000 Hz (optional)
- **Channels:** Mono
- **Bit Depth:** 8-bit compressed
- **Bitrate:** 64 kbps at 8000 Hz mono (telephony standard)
- **Microphone:** Built-in (for two-way if enabled)
- **Speaker:** Built-in 1W speaker
- **RTSP Backchannel:** Supported (tested working)

**Audio Configuration Details:**
```
Codec: PCMU (Pulse Code Modulation, µ-law variant)
Frame Size: 20ms (160 samples at 8000 Hz)
Profile: ITU-T G.711 (standard VoIP/telephony)
Compatibility: Works with standard SIP phones, VoIP equipment
```

**Network Requirements:**
- PoE power (802.3at, 30W sufficient)
- Gigabit Ethernet recommended (supports higher video bitrates)
- Static IP or DHCP reservation recommended for reliability
- Typical power draw: 8-12W in normal operation

**Integration with Frigate:**
- RTSP stream: `rtsp://admin:password@{camera-ip}/Preview_01_sub` (sub stream, lower bandwidth)
- Backchannel: Enabled automatically when RTSP stream established
- **Important:** Do NOT add `backchannel=1` to stream URL in go2rtc config—breaks Frigate's video detection pipeline

### Reolink E1 Zoom (Working)

**General Specifications:**
- **Type:** PoE PTZ (pan-tilt-zoom, indoor)
- **IP Codec:** H.264 video
- **Audio Codec Support:** PCMU (G.711 µ-law)
- **Sample Rates:** 8000 Hz
- **Speaker:** Built-in speaker (PTZ model)
- **Microphone:** Built-in
- **RTSP Backchannel:** Supported (tested working)
- **Status:** WORKING with VoxWatch
- **Special Notes:** Audio slightly garbled on sub stream. Tail end of audio may cut off — needs 1.5s silence padding appended to WAV files before push.

**Tested Behavior:**
- Backchannel establishes successfully
- Audio plays through built-in speaker
- Warmup pattern: First push after idle may not play; second push works
- Warmup latency: 5-7 seconds
- Subsequent push latency: 0.8 seconds (faster than Reolink CX410/CX420)
- Backchannel stays warm for 15-30 seconds

**Known Limitations:**
- Audio quality degradation on sub stream (can be mitigated with audio level normalization)
- Audio tail may cut off without silence padding
- Recommend 1.5 seconds of silence appended to all audio files for reliable playback

**Integration with Frigate:**
- RTSP stream: `rtsp://admin:password@{camera-ip}/Preview_01_sub` (sub stream, lower bandwidth)
- Backchannel: Enabled automatically when RTSP stream established
- **Important:** Do NOT add `backchannel=1` to stream URL in go2rtc config—breaks Frigate's video detection pipeline

## Audio Codec Reference

### PCMU (G.711 µ-law) - Primary

**Technical Details:**
```
Standard:           ITU-T G.711 Recommendation
Variant:            µ-law (mu-law) - used in North America, Japan
Alternatives:       A-law (Europe, rest of world)
Frame Size:         20ms (typically)
Sample Rate:        8000 Hz (standard) or 16000 Hz (wideband)
Bit Depth:          8-bit (compressed from 13-bit PCM)
Bitrate:            64 kbps (8000 Hz × 8-bit)
Channels:           Mono (standard for backchannel)
Latency:            Minimal (inherent codec feature)
Quality:            Adequate for speech (MOS ~3.9/5.0)
Commonality:        Used in VoIP, telephony, intercom systems
```

**Why PCMU Works Well:**
- Standard VoIP codec (widespread support)
- Low bitrate (network efficient)
- Low computational overhead
- Optimized for human speech (not music)
- Universal support across telephony equipment

**ffmpeg Encoding Command:**
```bash
ffmpeg -i input.wav \
  -acodec pcm_mulaw \
  -ac 1 \
  -ar 8000 \
  -f mulaw \
  output.raw
```

### PCMA (G.711 A-law) - Dahua Cameras

**Technical Details:**
```
Standard:           ITU-T G.711 Recommendation
Variant:            A-law - used in Europe, rest of world
Compression:        Similar to µ-law (different curve)
Bitrate:            64 kbps (same as µ-law)
Quality:            Slightly better for quiet sounds (MOS ~3.85/5.0)
Regional Use:       Europe, Africa, Asia-Pacific
```

**Dahua Cameras:** All tested Dahua cameras use PCMA (A-law) codec with 8000 Hz sample rate.

**Dahua RTSP URL Requirement (CRITICAL):**
- **DO USE:** `rtsp://user:pass@ip:554/cam/realmonitor?channel=1&subtype=2&unicast=true&proto=Onvif`
- **DO NOT USE:** ONVIF standard URL (`/axis-media/media.amp?streamprofile=MediaProfile00002`)

**Why:** ONVIF URLs do NOT expose backchannel audio track. Backchannel only available through Dahua's native RTSP format.

**ffmpeg Encoding Command (PCMA/8000):**
```bash
ffmpeg -i input.wav \
  -acodec pcm_alaw \
  -ac 1 \
  -ar 8000 \
  -f alaw \
  output.raw
```

**Verification:** Check camera's web interface under Audio Settings to confirm PCMA codec support and sample rate.

## Dahua Cameras

### Dahua IPC-Color4K-T180 (Working)

**General Specifications:**
- **Type:** Fixed turret camera (outdoor, PoE)
- **IP Codec:** H.265 video
- **Audio Codec Support:** PCMA (G.711 A-law), also supports PCMU, G726, L16
- **Sample Rates:** 8000 Hz (standard)
- **Channels:** Mono
- **Bit Depth:** 8-bit compressed
- **Bitrate:** 64 kbps at 8000 Hz mono
- **Microphone:** Built-in (for two-way if enabled)
- **Speaker:** Built-in speaker
- **RTSP Backchannel:** Supported (tested working)

**Audio Configuration Details:**
```
Codec: PCMA (Pulse Code Modulation, A-law variant)
Frame Size: 20ms (160 samples at 8000 Hz)
Profile: ITU-T G.711 (standard VoIP/telephony)
Compatibility: Works with standard SIP phones, VoIP equipment
```

**Network Requirements:**
- PoE power (802.3at, sufficient for turret)
- Gigabit Ethernet recommended
- Static IP or DHCP reservation recommended
- Typical power draw: 10-15W in normal operation

**Integration with Frigate:**
- **CRITICAL:** RTSP stream MUST use Dahua native format: `rtsp://admin:password@{camera-ip}:554/cam/realmonitor?channel=1&subtype=2&unicast=true&proto=Onvif`
- Backchannel: Enabled automatically when RTSP stream established
- **Important:** Do NOT use ONVIF standard URL—backchannel will not work

**go2rtc Behavior:**
- Endpoint: `POST /api/ffmpeg?dst={stream}&file={audio_url}`
- Returns instantly (HTTP 200 in <0.1s) but audio still plays through speaker
- **Important:** Do NOT treat instant return as failure—audio continues playing asynchronously
- No warmup pattern needed (unlike Reolink)
- Backchannel latency: Nearly instant (3-5s total with TTS overhead)

### Dahua IPC-T54IR-AS-2.8mm-S3 (RCA Audio Out Only)

**General Specifications:**
- **Type:** Fixed turret camera (outdoor, PoE)
- **Audio Codec Support:** PCMA (G.711 A-law)
- **Speaker:** NONE (RCA audio output only)
- **Microphone:** Built-in
- **Audio Output:** RCA jack (analog audio out)
- **RTSP Backchannel:** Advertised in SDP but no speaker hardware

**Compatibility:**
- Backchannel audio is technically available but cannot be heard without external speaker
- Could work with powered RCA speaker connected to camera's RCA output jack
- Not suitable for VoxWatch (requires built-in speaker)

**Network Integration:**
- PoE power
- RTSP stream: Same Dahua native format as IPC-Color4K-T180

### Dahua IPC-B54IR-ASE-2.8MM-S3 (RCA Audio Out Only)

**General Specifications:**
- **Type:** Fixed bullet camera (outdoor, PoE)
- **Audio Codec Support:** PCMA (G.711 A-law)
- **Speaker:** RCA audio out only
- **Microphone:** Built-in
- **Audio Output:** RCA jack (analog audio out)
- **RTSP Backchannel:** Advertised in SDP but no speaker hardware

**Compatibility:**
- Identical to IPC-T54IR-AS in audio capabilities
- Bullet form factor vs turret form factor (same hardware internals)
- Could work with external RCA speaker
- Not suitable for VoxWatch (requires built-in speaker)

### Dahua IPC-T58IR-ZE-S3 (Incompatible)

**General Specifications:**
- **Type:** Fixed turret camera (outdoor, PoE)
- **Audio Codec Support:** Not specified (no backchannel in SDP)
- **Speaker:** NONE
- **Microphone:** NONE
- **Audio Output:** NONE (no RCA, no other output)
- **RTSP Backchannel:** NOT available

**Compatibility:**
- No audio capabilities whatsoever
- Not suitable for VoxWatch
- Video-only camera

## Testing Your Camera

### Prerequisites

- Camera network accessible from Frigate system
- go2rtc running and configured (part of Frigate)
- RTSP stream URL and credentials
- Test audio file (WAV format)

### Step 1: Discover Your Camera's RTSP Stream

**Using discovery.py (if available in VoxWatch tools):**
```bash
python discovery.py --network 192.168.1.0/24 --verbose
```

**Output should include:**
```
Camera: Reolink CX410 at 192.168.1.100
  RTSP: rtsp://admin:password@192.168.1.100/Preview_01_sub
  Codec: h264
  Resolution: 1920x1080 (main), 640x480 (sub)
  Audio: PCMU/8000 (backchannel detected)
```

**Manual discovery (if no script available):**
1. Access camera web interface: `http://{camera-ip}:8080` (Reolink default)
2. Log in with admin credentials
3. Navigate to **Settings** > **Network** > **RTSP**
4. Copy RTSP URL from camera's interface
5. Test with VLC: `vlc rtsp://admin:password@{camera-ip}/Preview_01_sub`

### Step 2: Verify Audio Codec in go2rtc Web UI

**Access go2rtc web interface:**
```
http://localhost:1984
```

**Verify stream:**
1. Click on your camera stream (e.g., "frontdoor")
2. Check "Codecs" section in stream details
3. Verify audio codec is listed: should show `pcmu` or `g711u` or `PCMU`
4. Verify sample rate: `8000 Hz` (or 16000 for wideband)

**Expected output:**
```
Stream: frontdoor
  Video: h264 (1920x1080)
  Audio: pcmu/8000
  Status: Active
```

**If audio codec not showing:**
- Camera may not have audio codec information in SDP (stream descriptor)
- Try adding to go2rtc config explicitly: see "Advanced Configuration" below
- Test anyway (audio support may be implicit)

### Step 3: Test Audio Backchannel (One-Shot Test)

**Prepare test audio file:**
```bash
# Generate 3-second test tone (1000 Hz beep)
ffmpeg -f lavfi -i sine=f=1000:d=3 -acodec pcm_s16le -ar 44100 test_input.wav

# Convert to PCMU 8000 Hz mono (camera-ready format)
ffmpeg -i test_input.wav -acodec pcm_mulaw -ac 1 -ar 8000 -f mulaw test.raw
```

**Start HTTP server (from VoxWatch or manually):**
```bash
# From X:/voxwatch directory (or any directory with test.raw)
python -m http.server 8001 --directory .
```

**Push audio to camera via go2rtc API:**
```bash
curl -X POST "http://localhost:1984/api/streams?dst=frontdoor&src=http://localhost:8001/test.raw"
```

**Expected result:**
- go2rtc console shows successful connection to camera backchannel
- Camera speaker emits beep tone
- Curl returns HTTP 200 OK

**If it fails:**
- Check camera is powered and online
- Verify RTSP stream URL is correct (test in VLC first)
- Check firewall (port 1984 accessible from Frigate container)
- Verify HTTP server is running on port 8001
- Check audio file is valid PCMU format: `file test.raw` should show "raw audio data"

### Step 4: Integration with Frigate

**Verify Frigate detects person on this camera:**
1. Access Frigate web UI: `http://localhost:5000`
2. Navigate to camera's live view
3. Walk in front of camera (or trigger motion)
4. Verify "Person" label appears in live view
5. Check MQTT: `mosquitto_sub -h localhost -t frigate/events/person/detected` (should see event JSON)

**Expected MQTT message:**
```json
{
  "after": {
    "person": 1,
    "id": "1234567890",
    "camera": "frontdoor"
  },
  "camera": "frontdoor",
  "snapshot": "/tmp/frigate/tmp/detection-frontdoor-1234567890.jpg"
}
```

### Step 5: Full VoxWatch Pipeline Test

**Prepare VoxWatch configuration:**
```yaml
voxwatch:
  vision:
    gemini:
      enabled: false  # Disable AI for this test
  tts:
    piper:
      enabled: true
  cameras:
    frontdoor:
      stream_name: "frontdoor"
      go2rtc_url: "http://localhost:1984"
  pipeline:
    cooldown: 10  # Shorter for testing
```

**Run VoxWatch service:**
```bash
docker run --rm -it \
  --network host \
  -e MQTT_BROKER=localhost \
  -v /path/to/voxwatch.yml:/app/config/voxwatch.yml \
  voxwatch:latest
```

**Trigger detection by walking in front of camera:**
1. Watch VoxWatch logs for "Person detected" event
2. Listen for audio from camera speaker
3. Verify audio message is spoken (not garbled)
4. Check latency (audio should play within 5-10 seconds of person detected)

**Success criteria:**
- VoxWatch logs show all three stages executing
- Audio plays on camera speaker
- Message is intelligible (not static or corruption)
- No errors in logs

## Advanced Configuration

### Reolink-Specific go2rtc Config

**If camera audio not detected automatically, add explicit codec support:**
```yaml
# In your Frigate go2rtc config
streams:
  frontdoor:
    # Main RTSP stream (video + audio)
    - rtsp://admin:password@192.168.1.100/Preview_01_sub
    # Explicitly declare audio codec if not auto-detected
    # Note: This is informational; go2rtc usually detects automatically
    # Format: codec_name @ sample_rate
```

**Do NOT do this:**
```yaml
# WRONG: backchannel=1 breaks Frigate
streams:
  frontdoor:
    - rtsp://admin:password@192.168.1.100/Preview_01_sub?backchannel=1
```

### Testing Alternative Audio Codecs

**If camera supports multiple codecs, test each:**

**Test PCMA (A-law, if supported):**
```bash
# Convert to PCMA (alternative G.711 codec)
ffmpeg -i input.wav -acodec pcm_alaw -ac 1 -ar 8000 -f alaw test_alaw.raw

# Push to camera
curl -X POST "http://localhost:1984/api/streams?dst=frontdoor&src=http://localhost:8001/test_alaw.raw"
```

**Test 16kHz wideband (if camera supports):**
```bash
# Convert to PCMU 16kHz wideband
ffmpeg -i input.wav -acodec pcm_mulaw -ac 1 -ar 16000 -f mulaw test_16k.raw

# Push to camera
curl -X POST "http://localhost:1984/api/streams?dst=frontdoor&src=http://localhost:8001/test_16k.raw"
```

## Contributing Test Results

If you have tested VoxWatch with cameras not listed above, please contribute your findings:

### Information to Provide

1. **Camera Model and Serial Number**
   - Exact model (e.g., "Reolink CX410")
   - Firmware version (check camera settings)
   - Year manufactured (if known)

2. **Network Setup**
   - Connection type (PoE, WiFi, USB)
   - Network speed (100Mbps, Gigabit, WiFi 5/6)
   - Any special configuration needed

3. **Audio Codec Testing**
   - Codec type (PCMU, PCMA, AAC, etc.)
   - Sample rate (8000, 16000, 44100 Hz)
   - Channels (mono, stereo)
   - Working codec(s) and non-working ones

4. **Test Results**
   - Audio plays: Yes / No / Partial
   - Audio quality: Intelligible / Robotic / Distorted / Silent
   - Latency: Estimated end-to-end (from detection to speaker output)
   - Any errors in logs

5. **Frigate Integration**
   - RTSP stream URL format
   - Person detection works: Yes / No
   - go2rtc config needed

6. **Special Notes**
   - Any workarounds required
   - Any limitations discovered
   - Recommendations for other users
   - Whether you'd recommend this camera

### How to Contribute

1. **Open an issue on GitHub** with category "Camera Compatibility"
2. **Include all information above** (use the template provided)
3. **Attach logs** if testing failed (VoxWatch logs, go2rtc output)
4. **Share your success!** (tests that pass help other users)

### Recognition

Contributors who test cameras receive:
- Credit in `SUPPORTED_CAMERAS.md` (your name/handle)
- Mention in project CHANGELOG
- Access to contributor-only Discord channel (if applicable)

## Important Notes

### Reolink Home Assistant Integration Does NOT Support Speakers

The official Home Assistant Reolink integration does **NOT** expose camera speakers as `media_player` entities. TTS/audio playback through the HA Reolink integration is explicitly unsupported. You **cannot** use Home Assistant's `tts.speak` or `media_player.play_media` services to push audio to Reolink camera speakers.

VoxWatch bypasses this limitation entirely by using go2rtc's RTSP backchannel directly — it never touches Home Assistant for audio output.

### Speaker Channel Locking (Reolink)

Reolink cameras can lock the speaker channel when another session is using it. If you see "A user is using the speaker" errors, it means another application (or a previous VoxWatch push that hasn't fully disconnected) still holds the backchannel.

VoxWatch handles this automatically — if a speaker lock is detected, it retries once after a 3-second delay. If you frequently see speaker lock errors in the logs, check for other applications that might be using the camera's two-way audio (e.g., Reolink's own app, Home Assistant, or a browser with the go2rtc WebRTC page open).

### ONVIF URL vs Native RTSP URL (Dahua Cameras)

Dahua cameras configured with ONVIF URLs (`?subtype=MediaProfile00002`) do **NOT** expose the backchannel track in their SDP. You **must** use the Dahua native RTSP URL format:

```
# WRONG — no backchannel
rtsp://admin:password@<camera-ip>?subtype=MediaProfile00002

# CORRECT — backchannel available
rtsp://admin:password@<camera-ip>:554/cam/realmonitor?channel=1&subtype=2&unicast=true&proto=Onvif
```

This is a go2rtc/Dahua firmware behavior — the ONVIF RTSP profile simply doesn't include the backchannel media description in the SDP response.

---

## Troubleshooting

### Audio Plays But Distorted

**Likely cause:** Codec mismatch or sample rate incorrect

**Solutions:**
1. Verify audio file format: `ffmpeg -i test.raw -hide_banner` should show `pcm_mulaw`
2. Verify sample rate: should be `8000 Hz` (not 44100 or other)
3. Check audio file is mono (not stereo): should show `1 channel`
4. Try re-encoding with explicit parameters: `ffmpeg -i input.wav -acodec pcm_mulaw -ac 1 -ar 8000 -f mulaw output.raw`

### Audio Not Playing (Silent)

**Likely cause:** Backchannel not enabled or stream mismatch

**Solutions:**
1. Verify Frigate has active RTSP stream to camera: `go2rtc` console should show stream active
2. Test stream in VLC: `vlc rtsp://admin:password@{camera-ip}/Preview_01_sub` should play video
3. Verify camera speaker is enabled (check camera web UI audio settings)
4. Try different go2rtc URL (some cameras have alternate main stream: `/Preview_02_main`)
5. Manually test backchannel with different codec:
   ```bash
   # Try PCMA instead of PCMU
   ffmpeg -i test.wav -acodec pcm_alaw -ac 1 -ar 8000 -f alaw test_alaw.raw
   curl -X POST "http://localhost:1984/api/streams?dst=frontdoor&src=http://localhost:8001/test_alaw.raw"
   ```

### Camera Not Detected by Frigate

**Likely cause:** Network connectivity or RTSP URL incorrect

**Solutions:**
1. Ping camera: `ping 192.168.1.100` should respond
2. Test RTSP stream: `ffplay rtsp://admin:password@192.168.1.100/Preview_01_sub` should play
3. Check Frigate logs: `docker logs frigate` should show connection attempts
4. Verify camera stream URL in Frigate config matches actual camera capabilities
5. Try main stream instead of substream: `/Preview_02_main` or `/stream1` (varies by manufacturer)

### VoxWatch Service Fails to Connect to go2rtc

**Likely cause:** Host networking not enabled in Docker, or go2rtc not accessible

**Solutions:**
1. Verify Docker container running with `--network host`: `docker inspect voxwatch | grep NetworkMode` should show `"host"`
2. Verify go2rtc is running: `curl http://localhost:1984` should return HTML
3. Verify port 1984 is accessible: `netstat -an | grep 1984` should show listening socket
4. Check VoxWatch logs for connection errors: `docker logs voxwatch | grep "go2rtc"`
5. Verify `/api/streams` endpoint: `curl http://localhost:1984/api/streams` should return JSON list

## Camera Recommendations

**For Home Deployment:**
- **Reolink CX410:** Recommended primary choice
  - Proven working with VoxWatch
  - PoE powered (reliable, no WiFi)
  - Good build quality, Reolink support responsive
  - Backhaul audio latency acceptable for deterrent

**Future Testing Candidates:**
- Reolink RLC-810A (PoE, 8MP, higher res)
- Reolink RLC-810 (PoE, 4MP, lower cost)
- Amcrest UltraHD (PoE, GStreamer compatibility)
- Hikvision DS-2CD21xx (PoE, industry standard)
- Uniview (PoE, backchannel support)

---

**Last Updated:** 2026-03-20
**Status:** Initial Baseline (CX410 Working, E1 Zoom Untested)
