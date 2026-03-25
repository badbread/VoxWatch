# VoxWatch Audio Push Research — Latency Optimization

## Context

VoxWatch is an AI-powered security deterrent system. When a person is detected on a security camera (via Frigate NVR + MQTT), VoxWatch generates a personalized warning using AI vision + TTS and plays it through the camera's built-in speaker via the RTSP backchannel.

The system uses **go2rtc** (v1.9.10, bundled with Frigate 0.17.0) as the intermediary between VoxWatch and the camera. go2rtc maintains persistent RTSP connections to all cameras for video streaming to Frigate.

## The Problem

The current audio push method (`/api/ffmpeg`) adds 5-7 seconds of overhead per push on Reolink CX410/CX420 cameras. This is unacceptable for a security deterrent — every second of delay reduces psychological impact.

### Latency Breakdown (Current Method)

| Step | E1 Zoom | CX410 | CX420 | Dahua IPC-Color4K-T180 |
|------|---------|-------|-------|------------------------|
| Kokoro TTS (remote) | 2.5s | 2.5s | 2.5s | 2.5s |
| ffmpeg codec convert | 0.04s | 0.04s | 0.04s | 0.04s |
| **go2rtc push** | **0.8s** | **1.2s** | **1.2s** | **instant** |
| **Warmup (first push)** | **5-7s** | **10-13s** | **10-17s** | **instant** |
| **Total (cold)** | **~8s** | **~11s** | **~14s** | **~3s** |
| **Total (warm)** | **~3.3s** | **~4.6s** | **~4.6s** | **~3s** |

The warmup step (RTSP backchannel negotiation) is the major bottleneck on Reolink cameras. Dahua cameras establish backchannel instantly and have no warmup penalty.

## What's Currently Working

### Method: go2rtc /api/ffmpeg endpoint

```
POST http://go2rtc:1984/api/ffmpeg?dst={stream}&file={audio_url}
```

**How it works:**
1. VoxWatch generates a WAV file (TTS + ffmpeg convert to PCMU 8kHz mono)
2. VoxWatch serves the WAV on an HTTP server (port 8891)
3. VoxWatch calls `POST /api/ffmpeg?dst=frontdoor&file=http://host:8891/audio.wav`
4. go2rtc spawns a **new ffmpeg process** for each push
5. ffmpeg opens a **new RTSP connection** to the camera
6. ffmpeg negotiates the backchannel track
7. ffmpeg downloads the WAV from our HTTP server
8. ffmpeg transcodes and streams audio as RTP to the camera
9. Camera plays audio through speaker
10. ffmpeg exits, RTSP connection closes

**The 5-7 second overhead is steps 4-6**: spawning ffmpeg + establishing a new RTSP connection + backchannel negotiation. The actual audio streaming (step 8) takes only the duration of the audio.

### Warmup Pattern Required (Reolink Only)

**Reolink cameras (CX410, CX420, E1 Zoom):** The first push after idle establishes the backchannel but audio often doesn't play. A throwaway "warmup" push is needed before the real audio. This doubles the overhead.

**Dahua cameras (IPC-Color4K-T180, etc.):** No warmup needed. Backchannel establishes instantly on first push.

**Camera behavior differences:**
- **Reolink CX410/CX420**:
  - ffmpeg blocks for 12-20s per push (stays connected for full duration)
  - Warmup pattern: First push establishes backchannel but audio may not play; second push works
  - Warmup latency: 10-20s
  - Subsequent push latency: 1-3s (depends on warmup cache)
  - Backchannel stays warm for 15-30s

- **Reolink E1 Zoom**:
  - ffmpeg blocks for 0.5-3s per push (disconnects quickly)
  - Warmup latency: 5-7s (faster than CX410/CX420)
  - Audio plays but cuts off at end
  - Needs 1.5s silence padding appended to WAV files to ensure full playback
  - Backchannel stays warm for 15-30s

- **Dahua IPC-Color4K-T180**:
  - ffmpeg returns instantly (HTTP 200 in <0.1s)
  - Audio still plays through speaker asynchronously
  - **Important:** Do NOT treat instant return as failure—check camera speaker, not HTTP response
  - No warmup pattern needed
  - Backchannel responsive on every push
  - Backchannel latency: ~3s (TTS + encoding overhead only, no RTSP negotiation)

### Stale Sender Problem

Each `/api/ffmpeg` call creates a "sender" entry in go2rtc's stream metadata that never gets cleaned up. After 10-20 pushes, the backchannel becomes unreliable. Only fix: restart Frigate to clear all stale senders.

## What We've Tried to Improve Latency

### Attempt 1: /api/streams endpoint (FAILED)

```
POST /api/streams?dst={stream}&src=http://host:8891/audio.wav
```

Returns instantly (~0.1s) but **audio never plays**. go2rtc accepts the source but doesn't route it through the backchannel. This endpoint is designed for adding video/audio sources to a stream, not for backchannel injection.

### Attempt 2: Keep-alive warmup pushes (PARTIAL)

Send silent WAV pushes every 15-25 seconds to keep the backchannel warm. Reduces subsequent push latency from 7s to ~4-5s but still spawns a new ffmpeg process each time. Stale senders accumulate.

### Attempt 3: Concatenated silence prefix (FAILED)

Prepend 2s of silence to the beginning of the WAV file so the backchannel establishes during the silence. Single push, one ffmpeg process. **Did not work** — the backchannel needs a separate establishment step; concatenating silence doesn't help because the RTSP negotiation happens before any audio data flows.

### Attempt 4: WebRTC audio injection (IN PROGRESS)

This is the approach go2rtc's own web UI uses for its microphone button:

1. Open WebSocket to `ws://go2rtc:1984/api/ws?dst={stream}` (signaling only)
2. Create WebRTC offer with sendonly audio track
3. Exchange SDP offer/answer via WebSocket
4. Audio flows as RTP through the WebRTC peer connection
5. go2rtc routes RTP to camera's existing RTSP backchannel

**Results so far:**
- WebSocket signaling: **WORKS** (go2rtc responds with SDP answer)
- ICE negotiation: **WORKS** (ICE state reaches "completed", connection state "connected")
- SDP codec negotiation: **WORKS** (PCMU/8000 in both offer and answer)
- WebRTC connection: **WORKS** (fully established in 0.05s)
- **Actual audio playback: DOES NOT WORK** (no sound from camera despite connection being fully established)

The WebRTC connection is established and RTP packets are being sent from our side, but go2rtc is either not receiving them, not transcoding them, or not forwarding them to the camera's RTSP backchannel.

**Implementation details:**
- Using Python `aiortc` library for WebRTC
- Audio source is a custom `AudioStreamTrack` subclass that reads from a WAV file
- WAV file is PCM S16LE, 8000 Hz, mono
- SDP offer includes PCMU/8000 codec (payload type 0)
- go2rtc answers with PCMU/8000 + Opus/48000
- ICE candidates exchange properly (UDP on port 8555)
- Connection state reaches "connected", ICE reaches "completed"

**Possible reasons audio doesn't play:**
1. go2rtc might not forward WebRTC audio to the RTSP backchannel in producer (dst) mode — maybe only consumer (src) mode supports this
2. The audio track might need to be negotiated differently (different payload type, different codec parameters)
3. go2rtc might expect the audio in Opus format (since it's listed first in the answer) rather than PCMU
4. There might be an RTCP feedback mechanism that's not being handled
5. The RTP timestamp/sequence numbering might not match what go2rtc expects
6. go2rtc v1.9.10 might have a bug in WebRTC producer mode for backchannel audio
7. The audio might need to be sent through a specific transceiver or media ID that matches the camera's backchannel track

## Environment

- **go2rtc version**: 1.9.10 (bundled with Frigate 0.17.0-93016c6)
- **go2rtc host**: localhost:1984 (Docker container, host networking)
- **Cameras tested**:
  - Reolink CX410 (frontdoor, 192.168.1.100) — PoE Bullet, PCMU/8000 backchannel, warmup 10-13s
  - Reolink CX420 (backdoor, 192.168.1.103) — PoE Bullet, PCMU/8000 backchannel, warmup 10-17s
  - Reolink E1 Zoom (famroom, 192.168.1.101) — PoE PTZ, PCMU/8000 backchannel, warmup 5-7s, needs 1.5s silence padding
  - Dahua IPC-Color4K-T180 (frontyard, 192.168.1.102) — PoE Turret, PCMA/8000 backchannel, no warmup, instant return
  - Dahua IPC-T54IR-AS-2.8mm-S3 (backyard, 192.168.1.104) — PoE Turret, PCMA/8000 backchannel, RCA out only (no speaker)
  - Dahua IPC-B54IR-ASE-2.8MM-S3 (sidegate, 192.168.1.105) — PoE Bullet, PCMA/8000 backchannel, RCA out only (no speaker)
  - Dahua IPC-T58IR-ZE-S3 (driveway, 192.168.1.106) — PoE Turret, no audio (incompatible)
- **VoxWatch**: Python 3.11 in Docker container, same host as go2rtc
- **TTS**: Kokoro-82M on remote server (localhost:8880), Piper as fallback
- **Audio format**: PCMU (G.711 mu-law), 8000 Hz, mono, WAV container

## go2rtc Source Code References

From analysis of AlexxIT/go2rtc source:

- **WebSocket API**: `internal/api/ws/ws.go` — JSON message exchange, types: `webrtc/offer`, `webrtc/answer`, `webrtc/candidate`
- **WebRTC signaling**: `internal/webrtc/webrtc.go` — handles `dst` param for producer mode (`ModePassiveProducer`)
- **RTP forwarding**: `pkg/webrtc/conn.go` — `OnTrack()` reads RTP packets and forwards via `track.WriteRTP()`
- **Audio codecs**: `pkg/webrtc/consumer.go` — supports PCM L/U, G711, AAC, Opus, FLAC
- **Browser JS**: `www/video-rtc.js` — browser mic uses `navigator.mediaDevices.getUserMedia({audio: true})` then `pc.addTransceiver(track, {direction: 'sendonly'})`

Key: The browser sends audio as RTP over WebRTC, NOT via WebSocket binary frames. WebSocket is signaling only.

## What We Need Help With

1. **Why does the WebRTC connection establish successfully but no audio plays through the camera?** The ICE state reaches "completed" and connection state reaches "connected", but the camera speaker doesn't produce sound.

2. **Is there a better way to inject audio into go2rtc's existing RTSP backchannel?** We want to avoid spawning a new ffmpeg process and RTSP connection for each audio push.

3. **Are there other go2rtc API endpoints or methods we haven't tried?** Maybe a direct RTP injection endpoint, or a way to reuse the ffmpeg connection across multiple pushes.

4. **Could the Reolink HTTP Talk API be faster?** Reolink cameras have a proprietary HTTP API for two-way audio. The `reolink-aio` Python library supports it. Would this bypass the go2rtc overhead entirely?

## Ideal Solution

- **Sub-1-second** from "audio file ready" to "audio playing through camera speaker"
- Works with the existing go2rtc RTSP connection (no new connections)
- No stale senders accumulating
- No warmup pushes needed
- Compatible with Reolink (PCMU) and Dahua (PCMA) cameras
