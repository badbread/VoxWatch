#!/usr/bin/env python3
"""
test_webrtc_audio.py -- Push audio to camera via go2rtc WebRTC backchannel

This uses the SAME method as go2rtc's browser microphone button:
  1. Open WebSocket to /api/ws?dst={camera} (signaling)
  2. Create WebRTC offer with a sendonly audio track
  3. Exchange SDP/ICE candidates via WebSocket
  4. Send audio as RTP through the WebRTC peer connection
  5. go2rtc routes RTP to the camera's existing RTSP backchannel

This bypasses /api/ffmpeg entirely -- no new ffmpeg process, no new
RTSP connection, no 5-7 second negotiation overhead.

Requirements:
    pip install aiortc websockets

Usage:
    python tests/test_webrtc_audio.py --camera frontdoor
    python tests/test_webrtc_audio.py --camera frontdoor --message "You are being watched"
    python tests/test_webrtc_audio.py --camera famroom --rounds 3
"""

import argparse
import asyncio
import fractions
import json
import os
import subprocess
import struct
import sys
import tempfile
import time
import wave

try:
    import websockets
except ImportError:
    print("[FAIL] pip install websockets")
    sys.exit(1)

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
    from aiortc.mediastreams import AudioStreamTrack, MediaStreamTrack
    from av import AudioFrame
    import numpy as np
except ImportError:
    print("[FAIL] pip install aiortc numpy")
    sys.exit(1)


# ---------------------------------------------------------------------------
# WAV File Audio Track -- plays a WAV file through WebRTC
# ---------------------------------------------------------------------------

class WavFileTrack(AudioStreamTrack):
    """AudioStreamTrack that reads from a WAV file and sends as RTP.

    Reads PCM audio from a WAV file and packages it into AudioFrames
    that aiortc sends as RTP packets through the WebRTC connection.
    go2rtc receives these and forwards them to the camera backchannel.

    Args:
        wav_path: Path to a WAV file (any format -- will be read as PCM).
        sample_rate: Output sample rate (must match camera backchannel).
        loop: If True, loop the audio indefinitely.
    """

    kind = "audio"

    def __init__(self, wav_path: str, sample_rate: int = 8000, loop: bool = False):
        super().__init__()
        self._path = wav_path
        self._sample_rate = sample_rate
        self._loop = loop
        self._samples = self._load_wav(wav_path)
        self._position = 0
        self._start_time = None
        # 960 samples per frame at 48kHz = 20ms
        # 160 samples per frame at 8kHz = 20ms
        self._samples_per_frame = sample_rate // 50  # 20ms frames

    def _load_wav(self, path: str) -> np.ndarray:
        """Load WAV file as numpy array of int16 samples.

        Args:
            path: Path to WAV file.

        Returns:
            numpy array of int16 PCM samples, mono.
        """
        with wave.open(path, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            channels = wf.getnchannels()
            sw = wf.getsampwidth()

        if sw == 1:
            # 8-bit unsigned -> 16-bit signed
            samples = np.frombuffer(raw, dtype=np.uint8).astype(np.int16)
            samples = (samples - 128) * 256
        elif sw == 2:
            samples = np.frombuffer(raw, dtype=np.int16)
        else:
            # Assume 16-bit
            samples = np.frombuffer(raw, dtype=np.int16)

        # Convert to mono if stereo
        if channels == 2:
            samples = samples[::2]

        return samples

    async def recv(self) -> AudioFrame:
        """Produce the next audio frame for WebRTC transmission.

        Called by aiortc's RTP sender. Returns 20ms of audio per call.

        Returns:
            AudioFrame with PCM samples ready for RTP encoding.
        """
        if self._start_time is None:
            self._start_time = time.monotonic()

        # Calculate expected time for this frame and wait to maintain real-time pacing
        frame_index = self._position // self._samples_per_frame
        expected_time = self._start_time + (frame_index * 0.02)  # 20ms per frame
        now = time.monotonic()
        if now < expected_time:
            await asyncio.sleep(expected_time - now)

        # Extract samples for this frame
        end = self._position + self._samples_per_frame
        if end > len(self._samples):
            if self._loop:
                self._position = 0
                end = self._samples_per_frame
            else:
                # Pad with silence if we're at the end
                remaining = len(self._samples) - self._position
                if remaining <= 0:
                    # Signal end by sending silence
                    chunk = np.zeros(self._samples_per_frame, dtype=np.int16)
                else:
                    chunk = np.zeros(self._samples_per_frame, dtype=np.int16)
                    chunk[:remaining] = self._samples[self._position:]
                self._position = len(self._samples)

                frame = AudioFrame(samples=self._samples_per_frame, layout="mono",
                                   format="s16")
                frame.sample_rate = self._sample_rate
                frame.pts = frame_index * self._samples_per_frame
                frame.time_base = fractions.Fraction(1, self._sample_rate)
                frame.planes[0].update(chunk.tobytes())
                return frame

        chunk = self._samples[self._position:end]
        self._position = end

        frame = AudioFrame(samples=self._samples_per_frame, layout="mono",
                           format="s16")
        frame.sample_rate = self._sample_rate
        frame.pts = frame_index * self._samples_per_frame
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        frame.planes[0].update(chunk.tobytes())
        return frame

    @property
    def finished(self) -> bool:
        """True when all audio has been sent."""
        return not self._loop and self._position >= len(self._samples)

    @property
    def duration_seconds(self) -> float:
        """Total duration of the WAV file in seconds."""
        return len(self._samples) / self._sample_rate


# ---------------------------------------------------------------------------
# WebRTC Audio Push
# ---------------------------------------------------------------------------

async def push_audio_webrtc(go2rtc_url: str, camera: str,
                             wav_path: str, timeout: float = 30.0) -> dict:
    """Push audio to camera via go2rtc WebRTC backchannel.

    Replicates what happens when a browser sends microphone audio:
    1. Connect WebSocket to /api/ws?dst={camera}
    2. Create RTCPeerConnection with sendonly audio track
    3. Exchange SDP offer/answer via WebSocket
    4. Audio flows as RTP to go2rtc -> camera backchannel

    Args:
        go2rtc_url: go2rtc base URL (http://host:port).
        camera: go2rtc stream name.
        wav_path: Path to WAV file to play.
        timeout: Maximum seconds to wait.

    Returns:
        Dict with elapsed, status, and notes.
    """
    ws_url = go2rtc_url.replace("http://", "ws://") + f"/api/ws?dst={camera}"

    start = time.monotonic()
    pc = RTCPeerConnection()
    track = WavFileTrack(wav_path, sample_rate=8000)

    # Add sendonly audio track (microphone equivalent)
    pc.addTransceiver(track, direction="sendonly")

    result = {"method": "webrtc", "status": "FAIL", "notes": ""}

    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            connect_time = time.monotonic() - start

            # Create and send offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            await ws.send(json.dumps({
                "type": "webrtc/offer",
                "value": pc.localDescription.sdp,
            }))

            offer_time = time.monotonic() - start

            # Wait for answer and ICE candidates
            answer_received = False
            ice_done = False

            async def listen_ws():
                nonlocal answer_received, ice_done
                try:
                    async for message in ws:
                        data = json.loads(message)
                        msg_type = data.get("type", "")

                        if msg_type == "webrtc":
                            # SDP answer
                            value = data.get("value", {})
                            if isinstance(value, dict) and value.get("type") == "answer":
                                answer = RTCSessionDescription(
                                    sdp=value["sdp"],
                                    type="answer",
                                )
                                await pc.setRemoteDescription(answer)
                                answer_received = True

                        elif msg_type == "webrtc/candidate":
                            # ICE candidate
                            candidate_str = data.get("value", "")
                            if candidate_str:
                                # Parse ICE candidate
                                try:
                                    parts = candidate_str.split()
                                    if len(parts) >= 8:
                                        candidate = RTCIceCandidate(
                                            component=int(parts[1]),
                                            foundation=parts[0].replace("candidate:", ""),
                                            ip=parts[4],
                                            port=int(parts[5]),
                                            priority=int(parts[3]),
                                            protocol=parts[2],
                                            type=parts[7],
                                        )
                                        await pc.addIceCandidate(candidate)
                                except (ValueError, IndexError) as e:
                                    pass  # Skip malformed candidates

                except websockets.exceptions.ConnectionClosed:
                    pass

            # Start listening for answer
            ws_task = asyncio.create_task(listen_ws())

            # Wait for answer
            deadline = time.monotonic() + timeout
            while not answer_received and time.monotonic() < deadline:
                await asyncio.sleep(0.1)

            if not answer_received:
                result["notes"] = "No SDP answer received from go2rtc"
                return result

            answer_time = time.monotonic() - start

            # Wait for audio to finish playing
            duration = track.duration_seconds
            print(f"    WebRTC connected in {answer_time:.3f}s, "
                  f"playing {duration:.1f}s of audio...")

            # Wait for the track to finish + buffer
            await asyncio.sleep(duration + 1.5)

            elapsed = time.monotonic() - start
            result = {
                "method": "webrtc",
                "elapsed": elapsed,
                "status": "OK",
                "notes": (f"Connect={connect_time:.2f}s "
                          f"Offer={offer_time:.2f}s "
                          f"Answer={answer_time:.2f}s "
                          f"Audio={duration:.1f}s"),
                "connect_time": connect_time,
                "offer_time": offer_time,
                "answer_time": answer_time,
                "audio_duration": duration,
            }

            ws_task.cancel()

    except Exception as e:
        elapsed = time.monotonic() - start
        result = {
            "method": "webrtc",
            "elapsed": elapsed,
            "status": "FAIL",
            "notes": str(e),
        }
    finally:
        await pc.close()

    return result


# ---------------------------------------------------------------------------
# Persistent WebRTC connection for multiple pushes
# ---------------------------------------------------------------------------

class PersistentWebRTCAudio:
    """Maintains a persistent WebRTC connection for repeated audio pushes.

    Opens the WebRTC connection once, then allows pushing multiple audio
    files through it without re-negotiating. This is the "holy grail"
    approach -- sub-second latency for every push after the first.

    Args:
        go2rtc_url: go2rtc base URL.
        camera: go2rtc stream name.
    """

    def __init__(self, go2rtc_url: str, camera: str):
        self._ws_url = go2rtc_url.replace("http://", "ws://") + f"/api/ws?dst={camera}"
        self._pc = None
        self._ws = None
        self._connected = False
        self._current_track = None

    async def connect(self) -> float:
        """Establish the WebRTC connection.

        Returns:
            Connection time in seconds.
        """
        start = time.monotonic()

        self._pc = RTCPeerConnection()

        # Create a silence track to establish the audio channel
        silence_path = self._generate_silence()
        self._current_track = WavFileTrack(silence_path, sample_rate=8000, loop=True)
        self._pc.addTransceiver(self._current_track, direction="sendonly")

        self._ws = await websockets.connect(self._ws_url, open_timeout=5)

        # Create and send offer
        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        await self._ws.send(json.dumps({
            "type": "webrtc/offer",
            "value": self._pc.localDescription.sdp,
        }))

        # Wait for answer
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                data = json.loads(message)
                if data.get("type") == "webrtc":
                    value = data.get("value", {})
                    if isinstance(value, dict) and value.get("type") == "answer":
                        answer = RTCSessionDescription(
                            sdp=value["sdp"], type="answer",
                        )
                        await self._pc.setRemoteDescription(answer)
                        self._connected = True
                        break
            except asyncio.TimeoutError:
                continue

        elapsed = time.monotonic() - start

        if not self._connected:
            raise RuntimeError("WebRTC connection failed -- no SDP answer")

        # Clean up temp silence
        try:
            os.unlink(silence_path)
        except OSError:
            pass

        return elapsed

    def _generate_silence(self) -> str:
        """Generate a short silence WAV for initial connection.

        Returns:
            Path to the silence WAV file.
        """
        path = os.path.join(tempfile.gettempdir(), "webrtc_silence.wav")
        # Generate 100ms of silence at 8kHz mono 16-bit
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b'\x00' * 1600)  # 100ms
        return path

    async def push(self, wav_path: str) -> float:
        """Push audio through the existing WebRTC connection.

        Note: This is a simplified approach. Full implementation would
        need to replace the audio track on the existing connection,
        which requires renegotiation or track replacement support.
        For now, this creates a new connection per push but measures
        the overhead separately.

        Args:
            wav_path: Path to WAV file to push.

        Returns:
            Push latency in seconds.
        """
        if not self._connected:
            raise RuntimeError("Not connected -- call connect() first")

        # TODO: Implement track replacement on existing connection
        # For now, measure what a push would cost if the connection
        # were already established
        start = time.monotonic()

        track = WavFileTrack(wav_path, sample_rate=8000)
        duration = track.duration_seconds

        # In a full implementation, we'd replace self._current_track
        # with the new track. For testing, we'll send through a new
        # connection to measure total time.

        await asyncio.sleep(duration + 1.0)
        return time.monotonic() - start

    async def close(self):
        """Close the WebRTC connection."""
        if self._pc:
            await self._pc.close()
        if self._ws:
            await self._ws.close()


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

def generate_test_audio(message: str, output_path: str) -> bool:
    """Generate a PCMU WAV test file.

    Args:
        message: Text to speak.
        output_path: Where to save the WAV.

    Returns:
        True on success.
    """
    for cmd in ["espeak-ng", "espeak"]:
        try:
            tmp = output_path + ".raw.wav"
            r = subprocess.run([cmd, "-w", tmp, "--", message],
                               capture_output=True, timeout=10)
            if r.returncode == 0:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp, "-ar", "8000", "-ac", "1",
                     "-acodec", "pcm_s16le", "-f", "wav", output_path],
                    capture_output=True, timeout=10,
                )
                os.unlink(tmp)
                return os.path.exists(output_path)
        except FileNotFoundError:
            continue

    # Fallback: 1kHz tone
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
         "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le",
         "-f", "wav", output_path],
        capture_output=True, timeout=10,
    )
    return os.path.exists(output_path)


async def run_tests(args):
    """Run WebRTC audio push tests.

    Args:
        args: Parsed CLI arguments.
    """
    print(f"\n{'='*60}")
    print(f"  go2rtc WebRTC Audio Push Test")
    print(f"{'='*60}")
    print(f"  Camera:  {args.camera}")
    print(f"  go2rtc:  {args.go2rtc}")
    print(f"  Rounds:  {args.rounds}")
    print(f"{'='*60}\n")

    # Generate test audio files
    work_dir = tempfile.mkdtemp(prefix="voxwatch_webrtc_")

    for i in range(1, args.rounds + 1):
        path = os.path.join(work_dir, f"test_{i}.wav")
        msg = args.message or f"This is WebRTC test {i}. Test {i}. Test {i}."
        if not generate_test_audio(msg, path):
            print(f"[FAIL] Could not generate test audio {i}")
            return
        sz = os.path.getsize(path)
        with wave.open(path, "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
        print(f"[OK] test_{i}.wav: {sz} bytes, {dur:.1f}s")

    print()

    # --- Test 1: Single WebRTC push ---
    print("--- Test 1: Single WebRTC Push ---")
    wav_path = os.path.join(work_dir, "test_1.wav")
    result = await push_audio_webrtc(args.go2rtc, args.camera, wav_path)
    print(f"  Status:  {result['status']}")
    print(f"  Elapsed: {result.get('elapsed', 0):.3f}s")
    print(f"  Details: {result.get('notes', '')}")
    if result["status"] == "OK":
        print(f"  >>> Did you hear 'This is WebRTC test 1'? <<<")
    print()

    if args.rounds > 1 and result["status"] == "OK":
        # --- Test 2: Multiple sequential pushes ---
        print("--- Test 2: Sequential WebRTC Pushes ---")
        for i in range(2, args.rounds + 1):
            wav_path = os.path.join(work_dir, f"test_{i}.wav")
            r = await push_audio_webrtc(args.go2rtc, args.camera, wav_path)
            print(f"  Push {i}: {r.get('elapsed', 0):.3f}s  [{r['status']}]  {r.get('notes', '')}")
        print()

    # --- Comparison with ffmpeg baseline ---
    print("--- Baseline: /api/ffmpeg Push ---")
    import http.server
    import threading
    import urllib.request

    class Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=work_dir, **k)
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("0.0.0.0", 8894), Q)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    host = args.go2rtc.split("://")[1].split(":")[0]

    # Warmup
    try:
        url = f"{args.go2rtc}/api/ffmpeg?dst={args.camera}&file=http://{host}:8894/test_1.wav"
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass
    await asyncio.sleep(2)

    # Timed push
    start = time.monotonic()
    try:
        url = f"{args.go2rtc}/api/ffmpeg?dst={args.camera}&file=http://{host}:8894/test_1.wav"
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req, timeout=30)
        baseline = time.monotonic() - start
        print(f"  ffmpeg push: {baseline:.3f}s")
    except Exception as e:
        baseline = time.monotonic() - start
        print(f"  ffmpeg push: {baseline:.3f}s [FAIL: {e}]")

    srv.shutdown()

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"  COMPARISON")
    print(f"{'='*60}")
    webrtc_time = result.get("answer_time", result.get("elapsed", 0))
    print(f"  WebRTC connection setup: {webrtc_time:.3f}s")
    print(f"  ffmpeg baseline push:    {baseline:.3f}s")
    if webrtc_time > 0 and baseline > 0:
        speedup = baseline / webrtc_time
        print(f"  Speedup:                 {speedup:.1f}x faster")
    print(f"\n  Files in: {work_dir}")
    print(f"{'='*60}\n")


def main():
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(
        description="Test WebRTC audio push to go2rtc camera backchannel",
    )
    parser.add_argument("--camera", required=True, help="go2rtc stream name")
    parser.add_argument("--go2rtc", default="http://localhost:1984",
                        help="go2rtc base URL")
    parser.add_argument("--message", default=None,
                        help="Custom message (default: numbered test messages)")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Number of test pushes (default: 3)")
    args = parser.parse_args()
    asyncio.run(run_tests(args))


if __name__ == "__main__":
    main()
