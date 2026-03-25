# Voxwatch — Audio Push Test Scripts

Voxwatch is an AI-powered security deterrent that detects people on security cameras at night, uses AI vision to describe them, and plays a personalized audio warning through the camera's built-in speaker. These test scripts validate the first milestone: programmatically pushing audio to Reolink camera speakers via go2rtc.

## Tested Cameras

If you've tested Voxwatch with a camera not listed here, please open a PR to add your results!

| Camera | Model | Type | Speaker | Backchannel Codec | Status | Notes |
|--------|-------|------|---------|-------------------|--------|-------|
| **frontdoor** | Reolink CX410 | PoE Bullet | Built-in | PCMU/8000 | Working | Primary test device. go2rtc /api/ffmpeg blocks 12-20s per push. |
| **backdoor** | Reolink CX420 | PoE Bullet | Built-in | PCMU/8000 | Working | Same behavior as CX410. |
| **famroom** | Reolink E1 Zoom | PoE Indoor PTZ | Built-in | PCMU/8000 | Working | Audio slightly garbled on sub stream. Tail end of audio may cut off — needs 1.5s silence padding at end. |
| **frontyard** | Dahua IPC-Color4K-T180 | PoE Turret | Built-in | PCMA/8000 | Working | MUST use Dahua native RTSP URL — ONVIF URL does NOT expose backchannel. go2rtc returns instantly (doesn't block like Reolink). |
| **backyard** | Dahua IPC-T54IR-AS-2.8mm-S3 | PoE Turret | RCA audio out only | PCMA/8000 | No built-in speaker | Has RCA audio output — could work with external speaker connected to RCA. SDP advertises backchannel but no speaker hardware. |
| **sidegate** | Dahua IPC-B54IR-ASE-2.8MM-S3 | PoE Bullet | RCA audio out only | PCMA/8000 | No built-in speaker | Same as backyard — RCA out only, no built-in speaker. |
| **driveway** | Dahua IPC-T58IR-ZE-S3 | PoE Turret | None | N/A | Incompatible | No speaker, no RCA out, no audio output of any kind. |

### Working Audio Push Method

**Endpoint:** `POST /api/ffmpeg?dst={stream}&file={audio_url}`
- This is the same endpoint go2rtc's web UI "Play audio" uses
- `/api/streams` does NOT work for backchannel audio
- WebRTC producer mode (`/api/ws?dst=`) connects but does NOT route audio to RTSP backchannel

**Warmup pattern:** First push after idle establishes backchannel but may not play audio. Second push works. Backchannel stays warm for 15-30s.

**Reolink behavior:** /api/ffmpeg blocks for 12-20s while audio plays (the blocking time IS the audio duration + RTSP setup).

**Dahua behavior:** /api/ffmpeg returns instantly (HTTP 200 in <0.1s) but audio still plays through speaker. Do NOT treat instant return as failure for Dahua cameras.

**RTSP URL matters for Dahua:** ONVIF URLs (`?subtype=MediaProfile00002`) do NOT expose backchannel. MUST use Dahua native format: `rtsp://user:pass@ip:554/cam/realmonitor?channel=1&subtype=2&unicast=true&proto=Onvif`

### Latency (Measured)

| Camera | Warmup | TTS (Kokoro) | Push | Total (cold) | Total (warm) |
|--------|--------|-------------|------|-------------|-------------|
| CX410 | 10-13s | 2.5s | 1.2s | ~11s | ~4.6s |
| CX420 | 10-17s | 2.5s | 1.2s | ~14s | ~4.6s |
| E1 Zoom | 5-7s | 2.5s | 0.8s | ~8s | ~3.3s |
| IPC-Color4K-T180 | instant | 2.5s | instant | ~3s | ~3s |

## Prerequisites

- [ ] **Frigate NVR** running with go2rtc (web UI on port 1984)
- [ ] **Reolink PoE camera** with built-in speaker, connected and accessible
- [ ] **ffmpeg** installed and on PATH
- [ ] **Python 3.10+** with pip
- [ ] (Optional) **pyttsx3** for Windows TTS, or **Piper** / **espeak** on Linux
- [ ] Camera settings: RTSP enabled, HTTP enabled, ONVIF enabled, speaker volume > 0

## Setup

```bash
pip install -r ../requirements.txt
pip install pyttsx3  # Optional: for Windows TTS in pipeline test
```

## Execution Order

Run the scripts in order. Each builds on the previous one.

### 1. Discover camera capabilities

```bash
python discovery.py --host 192.168.1.100 --password YOUR_PASSWORD
```

Confirms the camera supports two-way audio and prints stream URLs.

### 2. Generate test audio files

```bash
python generate_test_audio.py
```

Creates audio files in multiple formats. The mu-law 8 kHz file is preferred for Reolink cameras.

### 3. Verify go2rtc sees the camera

```bash
python test_go2rtc_check.py --url http://YOUR_GO2RTC_IP:1984 --camera YOUR_CAMERA_NAME
```

Checks go2rtc configuration and prints instructions for the **critical manual browser microphone test**. Do not skip this step.

### 4. Test audio push methods

```bash
python test_audio_push.py --url http://YOUR_GO2RTC_IP:1984 --camera YOUR_CAMERA_NAME
```

Tries multiple methods to push audio to the camera speaker. Method 1 (go2rtc API) is the proven approach.

### 5. Full pipeline latency test

```bash
python test_full_pipeline.py --go2rtc-url http://YOUR_GO2RTC_IP:1984 --camera YOUR_CAMERA_NAME
```

Generates TTS on the fly, converts to camera format, pushes to speaker, and measures end-to-end latency.

## What To Do With Results

- Confirm you heard audio from the camera speaker during the test
- Record the **pipeline latency** from script 5
- These results determine how the main Voxwatch system will push audio in production
- If you tested a new camera model, please add it to the Tested Cameras table above

## Project Links

- [Main Voxwatch README](../README.md)

---

*This project is built with Claude Code — all code is AI-assisted and thoroughly documented for readability.*
