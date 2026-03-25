#!/usr/bin/env python3
"""
test_websocket_audio.py -- Test pushing audio through go2rtc's WebSocket API

Instead of /api/ffmpeg (which spawns a new ffmpeg + RTSP connection each time),
this tests sending audio frames through go2rtc's existing RTSP connection via
WebSocket. This should eliminate the 5-7s RTSP negotiation overhead.

go2rtc's WebSocket protocol (based on source analysis):
  - Connect to ws://{host}/api/ws?src={stream}
  - Send binary frames containing raw audio data
  - go2rtc routes them to the backchannel of the existing RTSP producer

Test approaches:
  1. Raw WebSocket binary frames with PCM audio
  2. WebSocket with RTP-wrapped audio
  3. go2rtc's /api/webrtc endpoint with audio track

Usage:
    python tests/test_websocket_audio.py --camera frontdoor
    python tests/test_websocket_audio.py --camera frontdoor --method all
    python tests/test_websocket_audio.py --camera famroom --go2rtc http://localhost:1984
"""

import argparse
import asyncio
import os
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def generate_test_audio(message: str, output_path: str,
                        codec: str = "pcm_mulaw", sample_rate: int = 8000) -> bool:
    """Generate a test WAV file using espeak or a tone fallback.

    Args:
        message: Text to speak.
        output_path: Where to save the WAV.
        codec: ffmpeg audio codec.
        sample_rate: Target sample rate.

    Returns:
        True if file was generated successfully.
    """
    # Try espeak-ng first
    for cmd in ["espeak-ng", "espeak"]:
        try:
            tmp = output_path + ".raw.wav"
            result = subprocess.run(
                [cmd, "-w", tmp, "--", message],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp, "-ar", str(sample_rate),
                     "-ac", "1", "-acodec", codec, "-f", "wav", output_path],
                    capture_output=True, timeout=10,
                )
                os.unlink(tmp)
                return os.path.exists(output_path)
        except FileNotFoundError:
            continue

    # Fallback: generate 1kHz tone
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=1000:duration=2",
         "-ar", str(sample_rate), "-ac", "1",
         "-acodec", codec, "-f", "wav", output_path],
        capture_output=True, timeout=10,
    )
    return os.path.exists(output_path)


def read_wav_pcm(path: str) -> tuple:
    """Read a WAV file and return raw PCM bytes + metadata.

    Args:
        path: Path to WAV file.

    Returns:
        Tuple of (pcm_bytes, sample_rate, channels, sample_width).
    """
    with wave.open(path, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        return frames, wf.getframerate(), wf.getnchannels(), wf.getsampwidth()


def read_raw_bytes(path: str) -> bytes:
    """Read raw file bytes.

    Args:
        path: Path to file.

    Returns:
        Raw bytes of the file.
    """
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Method 1: WebSocket binary frames (raw PCM chunks)
# ---------------------------------------------------------------------------

async def test_ws_raw_pcm(go2rtc: str, camera: str, audio_path: str) -> dict:
    """Send raw PCM audio as WebSocket binary frames.

    Connects to go2rtc's WebSocket endpoint and sends the audio data
    as binary frames in chunks matching RTP packet size (160 bytes for
    PCMU at 8kHz = 20ms per packet).

    Args:
        go2rtc: go2rtc base URL (http://host:port).
        camera: Stream name.
        audio_path: Path to PCMU WAV file.

    Returns:
        Dict with method, elapsed_seconds, status, and notes.
    """
    try:
        import websockets
    except ImportError:
        return {"method": "ws_raw_pcm", "status": "SKIP",
                "notes": "pip install websockets"}

    ws_url = go2rtc.replace("http://", "ws://") + f"/api/ws?src={camera}"
    pcm_data, sr, ch, sw = read_wav_pcm(audio_path)

    start = time.monotonic()
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            # Send audio in 160-byte chunks (20ms of PCMU at 8kHz)
            chunk_size = 160
            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                await ws.send(chunk)
                # Pace the sending to match real-time playback
                await asyncio.sleep(0.02)  # 20ms per chunk

            elapsed = time.monotonic() - start
            return {"method": "ws_raw_pcm", "elapsed": elapsed,
                    "status": "OK", "notes": f"Sent {len(pcm_data)} bytes in {len(pcm_data)//chunk_size} chunks"}
    except Exception as e:
        elapsed = time.monotonic() - start
        return {"method": "ws_raw_pcm", "elapsed": elapsed,
                "status": "FAIL", "notes": str(e)}


# ---------------------------------------------------------------------------
# Method 2: WebSocket with full WAV file
# ---------------------------------------------------------------------------

async def test_ws_full_wav(go2rtc: str, camera: str, audio_path: str) -> dict:
    """Send complete WAV file as a single WebSocket binary frame.

    Some WebSocket audio implementations accept a full file rather than
    streamed chunks.

    Args:
        go2rtc: go2rtc base URL.
        camera: Stream name.
        audio_path: Path to WAV file.

    Returns:
        Dict with method, elapsed_seconds, status, and notes.
    """
    try:
        import websockets
    except ImportError:
        return {"method": "ws_full_wav", "status": "SKIP",
                "notes": "pip install websockets"}

    ws_url = go2rtc.replace("http://", "ws://") + f"/api/ws?src={camera}"
    wav_data = read_raw_bytes(audio_path)

    start = time.monotonic()
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            await ws.send(wav_data)
            # Wait a moment to see if go2rtc processes it
            await asyncio.sleep(2)
            elapsed = time.monotonic() - start
            return {"method": "ws_full_wav", "elapsed": elapsed,
                    "status": "OK", "notes": f"Sent {len(wav_data)} bytes as single frame"}
    except Exception as e:
        elapsed = time.monotonic() - start
        return {"method": "ws_full_wav", "elapsed": elapsed,
                "status": "FAIL", "notes": str(e)}


# ---------------------------------------------------------------------------
# Method 3: WebSocket with RTP-like framing
# ---------------------------------------------------------------------------

async def test_ws_rtp_frames(go2rtc: str, camera: str, audio_path: str) -> dict:
    """Send audio wrapped in RTP-like headers via WebSocket.

    go2rtc may expect RTP framing for backchannel audio. This wraps
    each 160-byte chunk in a minimal RTP header (12 bytes).

    RTP header format (12 bytes):
      - Byte 0: V=2, P=0, X=0, CC=0 -> 0x80
      - Byte 1: M=0, PT=0 (PCMU) -> 0x00
      - Bytes 2-3: Sequence number (big-endian)
      - Bytes 4-7: Timestamp (big-endian)
      - Bytes 8-11: SSRC (big-endian)

    Args:
        go2rtc: go2rtc base URL.
        camera: Stream name.
        audio_path: Path to PCMU WAV file.

    Returns:
        Dict with method, elapsed_seconds, status, and notes.
    """
    try:
        import websockets
    except ImportError:
        return {"method": "ws_rtp_frames", "status": "SKIP",
                "notes": "pip install websockets"}

    ws_url = go2rtc.replace("http://", "ws://") + f"/api/ws?src={camera}"
    pcm_data, sr, ch, sw = read_wav_pcm(audio_path)

    start = time.monotonic()
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            chunk_size = 160  # 20ms of PCMU at 8kHz
            seq = 0
            timestamp = 0
            ssrc = 0x12345678

            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]

                # Build RTP header
                header = struct.pack("!BBHII",
                    0x80,       # V=2, P=0, X=0, CC=0
                    0x00,       # M=0, PT=0 (PCMU)
                    seq & 0xFFFF,
                    timestamp & 0xFFFFFFFF,
                    ssrc,
                )
                await ws.send(header + chunk)
                seq += 1
                timestamp += chunk_size
                await asyncio.sleep(0.02)  # 20ms pacing

            elapsed = time.monotonic() - start
            return {"method": "ws_rtp_frames", "elapsed": elapsed,
                    "status": "OK", "notes": f"Sent {seq} RTP packets"}
    except Exception as e:
        elapsed = time.monotonic() - start
        return {"method": "ws_rtp_frames", "elapsed": elapsed,
                "status": "FAIL", "notes": str(e)}


# ---------------------------------------------------------------------------
# Method 4: HTTP chunked transfer to /api/streams
# ---------------------------------------------------------------------------

async def test_http_stream(go2rtc: str, camera: str, audio_path: str) -> dict:
    """Push audio via HTTP chunked transfer to /api/streams endpoint.

    Instead of giving go2rtc a URL to fetch from, we POST the audio
    data directly as the request body.

    Args:
        go2rtc: go2rtc base URL.
        camera: Stream name.
        audio_path: Path to WAV file.

    Returns:
        Dict with method, elapsed_seconds, status, and notes.
    """
    try:
        import aiohttp
    except ImportError:
        return {"method": "http_stream", "status": "SKIP",
                "notes": "pip install aiohttp"}

    wav_data = read_raw_bytes(audio_path)
    url = f"{go2rtc}/api/streams?dst={camera}"

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=wav_data,
                                    headers={"Content-Type": "audio/wav"},
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = time.monotonic() - start
                return {"method": "http_stream", "elapsed": elapsed,
                        "status": f"HTTP {resp.status}",
                        "notes": f"Sent {len(wav_data)} bytes"}
    except Exception as e:
        elapsed = time.monotonic() - start
        return {"method": "http_stream", "elapsed": elapsed,
                "status": "FAIL", "notes": str(e)}


# ---------------------------------------------------------------------------
# Method 5: go2rtc /api/webrtc with audio offer
# ---------------------------------------------------------------------------

async def test_webrtc_audio(go2rtc: str, camera: str, audio_path: str) -> dict:
    """Attempt to push audio via go2rtc's WebRTC endpoint.

    This replicates what happens when a browser sends mic audio through
    go2rtc's WebRTC connection. Requires aiortc for WebRTC support.

    Args:
        go2rtc: go2rtc base URL.
        camera: Stream name.
        audio_path: Path to audio file.

    Returns:
        Dict with method, elapsed_seconds, status, and notes.
    """
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from aiortc.mediastreams import AudioStreamTrack
    except ImportError:
        return {"method": "webrtc_audio", "status": "SKIP",
                "notes": "pip install aiortc (complex dependency)"}

    return {"method": "webrtc_audio", "status": "SKIP",
            "notes": "WebRTC requires full SDP negotiation - testing separately"}


# ---------------------------------------------------------------------------
# Method 6: Baseline comparison -- /api/ffmpeg (current method)
# ---------------------------------------------------------------------------

async def test_ffmpeg_baseline(go2rtc: str, camera: str, audio_path: str,
                                serve_port: int = 8893) -> dict:
    """Baseline test using the current /api/ffmpeg method.

    Starts a temporary HTTP server, pushes via /api/ffmpeg, measures time.
    This is what VoxWatch currently does.

    Args:
        go2rtc: go2rtc base URL.
        camera: Stream name.
        audio_path: Path to WAV file.
        serve_port: Port for temporary HTTP server.

    Returns:
        Dict with method, elapsed_seconds, status, and notes.
    """
    import http.server
    import threading
    try:
        import urllib.request
    except ImportError:
        return {"method": "ffmpeg_baseline", "status": "FAIL",
                "notes": "urllib not available"}

    audio_dir = os.path.dirname(audio_path)
    audio_file = os.path.basename(audio_path)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=audio_dir, **k)
        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("0.0.0.0", serve_port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host = go2rtc.split("://")[1].split(":")[0]
    audio_url = f"http://{host}:{serve_port}/{audio_file}"

    # Warmup first
    warmup_url = f"{go2rtc}/api/ffmpeg?dst={camera}&file={audio_url}"
    try:
        req = urllib.request.Request(warmup_url, method="POST")
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass
    await asyncio.sleep(2)

    # Real push
    push_url = f"{go2rtc}/api/ffmpeg?dst={camera}&file={audio_url}"
    start = time.monotonic()
    try:
        req = urllib.request.Request(push_url, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.monotonic() - start
            result = {"method": "ffmpeg_baseline", "elapsed": elapsed,
                      "status": f"HTTP {resp.status}",
                      "notes": f"go2rtc ffmpeg (current method)"}
    except Exception as e:
        elapsed = time.monotonic() - start
        result = {"method": "ffmpeg_baseline", "elapsed": elapsed,
                  "status": "FAIL", "notes": str(e)}

    server.shutdown()
    return result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_all(args):
    """Run all test methods and print comparison.

    Args:
        args: Parsed CLI arguments.
    """
    print(f"\n{'='*60}")
    print(f"  go2rtc Audio Push Method Comparison")
    print(f"{'='*60}")
    print(f"  Camera:  {args.camera}")
    print(f"  go2rtc:  {args.go2rtc}")
    print(f"  Methods: {args.method}")
    print(f"{'='*60}\n")

    # Generate test audio
    import tempfile
    work_dir = tempfile.mkdtemp(prefix="voxwatch_ws_")
    audio_path = os.path.join(work_dir, "test_audio.wav")

    print("Generating test audio...")
    if not generate_test_audio(
        "This is a WebSocket audio test. Testing one two three.",
        audio_path,
    ):
        # Fallback: use ffmpeg tone
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=800:duration=2",
             "-ar", "8000", "-ac", "1", "-acodec", "pcm_mulaw",
             "-f", "wav", audio_path],
            capture_output=True, timeout=10,
        )

    if not os.path.exists(audio_path):
        print("[FAIL] Could not generate test audio")
        return

    sz = os.path.getsize(audio_path)
    print(f"[OK] Test audio: {sz} bytes ({sz//8000:.1f}s at 8kHz)\n")

    methods = {
        "ws_pcm": ("WebSocket raw PCM chunks", test_ws_raw_pcm),
        "ws_wav": ("WebSocket full WAV frame", test_ws_full_wav),
        "ws_rtp": ("WebSocket RTP-wrapped", test_ws_rtp_frames),
        "http": ("HTTP POST to /api/streams", test_http_stream),
        "webrtc": ("WebRTC audio track", test_webrtc_audio),
        "ffmpeg": ("go2rtc /api/ffmpeg (baseline)", test_ffmpeg_baseline),
    }

    if args.method == "all":
        to_test = list(methods.keys())
    else:
        to_test = args.method.split(",")

    results = []
    for key in to_test:
        if key not in methods:
            print(f"  Unknown method: {key}")
            continue

        name, func = methods[key]
        print(f"--- Testing: {name} ---")
        result = await func(args.go2rtc, args.camera, audio_path)
        results.append(result)

        status = result.get("status", "?")
        elapsed = result.get("elapsed", 0)
        notes = result.get("notes", "")

        if "SKIP" in str(status):
            print(f"  [{status}] {notes}\n")
        elif "FAIL" in str(status):
            print(f"  [{status}] {elapsed:.3f}s -- {notes}\n")
        else:
            print(f"  [{status}] {elapsed:.3f}s -- {notes}")
            print(f"  >>> Did you hear audio from the camera? <<<\n")

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  {'Method':<25} {'Time':>8} {'Status':<10} Notes")
    print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*30}")
    for r in results:
        method = r.get("method", "?")
        elapsed = r.get("elapsed", 0)
        status = r.get("status", "?")
        notes = r.get("notes", "")[:40]
        if "SKIP" in str(status):
            print(f"  {method:<25} {'--':>8} {'SKIP':<10} {notes}")
        else:
            print(f"  {method:<25} {elapsed:>7.3f}s {status:<10} {notes}")
    print(f"{'='*60}\n")

    print(f"  Files in: {work_dir}")
    print(f"  If a method played audio, that's our new fast path!\n")


def main():
    """Parse arguments and run tests."""
    parser = argparse.ArgumentParser(
        description="Test alternative audio push methods for go2rtc",
    )
    parser.add_argument("--camera", required=True,
                        help="go2rtc stream name")
    parser.add_argument("--go2rtc", default="http://localhost:1984",
                        help="go2rtc base URL")
    parser.add_argument("--method", default="all",
                        help="Methods to test: all, or comma-separated "
                             "(ws_pcm,ws_wav,ws_rtp,http,webrtc,ffmpeg)")

    args = parser.parse_args()
    asyncio.run(run_all(args))


if __name__ == "__main__":
    main()
