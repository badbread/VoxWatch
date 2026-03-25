#!/usr/bin/env python3
"""
test_latency.py — VoxWatch Audio Push Latency Test Suite

Measures end-to-end latency of every step in the audio pipeline:
  1. TTS generation (Piper, Kokoro, espeak)
  2. ffmpeg codec conversion
  3. go2rtc warmup push
  4. go2rtc real audio push
  5. Full pipeline: TTS -> convert -> push

Tests each step independently and reports a comparison table.
Useful for finding bottlenecks and testing new cameras.

Usage:
    python tests/test_latency.py --camera frontdoor
    python tests/test_latency.py --camera e1zoom --go2rtc http://localhost:1984
    python tests/test_latency.py --camera frontdoor --rounds 5
    python tests/test_latency.py --camera frontdoor --kokoro http://localhost:8880
"""

import argparse
import asyncio
import http.server
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# --- Configuration ----------------------------------------------------------

DEFAULT_GO2RTC = "http://localhost:1984"
DEFAULT_MESSAGE = "Attention. Individual detected near the entrance. You have been recorded."
DEFAULT_CODEC = "pcm_mulaw"
DEFAULT_SAMPLE_RATE = 8000
SERVE_PORT = 8892  # Different from VoxWatch's 8891 to avoid conflict


# --- Helpers ----------------------------------------------------------------

def generate_silence_wav(path: str, duration_s: float = 0.5,
                         sample_rate: int = 8000, codec: str = "pcm_mulaw") -> None:
    """Generate a short silence WAV file for warmup pushes.

    Args:
        path: Output file path.
        duration_s: Duration in seconds.
        sample_rate: Sample rate in Hz.
        codec: Audio codec name for ffmpeg.
    """
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=mono",
        "-t", str(duration_s),
        "-acodec", codec, "-ar", str(sample_rate), "-ac", "1",
        "-f", "wav", path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=10)


def generate_tts_espeak(message: str, output_path: str) -> float:
    """Generate TTS with espeak-ng and return elapsed time in seconds.

    Args:
        message: Text to speak.
        output_path: Where to write the WAV file.

    Returns:
        Elapsed time in seconds.
    """
    start = time.monotonic()
    for cmd_name in ["espeak-ng", "espeak"]:
        try:
            result = subprocess.run(
                [cmd_name, "-w", output_path, "--", message],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0:
                elapsed = time.monotonic() - start
                return elapsed
        except FileNotFoundError:
            continue
    return -1.0


def generate_tts_piper(message: str, output_path: str) -> float:
    """Generate TTS with Piper and return elapsed time in seconds.

    Args:
        message: Text to speak.
        output_path: Where to write the WAV file.

    Returns:
        Elapsed time in seconds, or -1 if piper not found.
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["piper", "--model", "en_US-lessac-medium",
             "--output_file", output_path],
            input=message.encode("utf-8"),
            capture_output=True, timeout=30,
        )
        if proc.returncode == 0:
            return time.monotonic() - start
    except FileNotFoundError:
        pass
    return -1.0


def generate_tts_kokoro(message: str, output_path: str,
                        kokoro_url: str, voice: str = "am_fenrir") -> float:
    """Generate TTS with remote Kokoro server and return elapsed time.

    Args:
        message: Text to speak.
        output_path: Where to save the WAV.
        kokoro_url: Base URL of the Kokoro HTTP server.
        voice: Kokoro voice name.

    Returns:
        Elapsed time in seconds, or -1 on failure.
    """
    import json
    try:
        import urllib.request
        start = time.monotonic()
        data = json.dumps({"text": message, "voice": voice, "speed": 1.0}).encode()
        req = urllib.request.Request(
            f"{kokoro_url}/tts",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(output_path, "wb") as f:
                f.write(resp.read())
        return time.monotonic() - start
    except Exception as e:
        print(f"    Kokoro error: {e}")
        return -1.0


def convert_audio(input_path: str, output_path: str,
                  codec: str = "pcm_mulaw", sample_rate: int = 8000) -> float:
    """Convert audio to camera-compatible codec and return elapsed time.

    Args:
        input_path: Source WAV file.
        output_path: Destination WAV file.
        codec: Target codec for ffmpeg.
        sample_rate: Target sample rate.

    Returns:
        Elapsed time in seconds.
    """
    start = time.monotonic()
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", str(sample_rate), "-ac", "1",
        "-acodec", codec, "-f", "wav", output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=15)
    return time.monotonic() - start


def push_audio(go2rtc_url: str, camera: str, audio_url: str) -> tuple:
    """Push audio to camera via go2rtc /api/ffmpeg endpoint.

    Args:
        go2rtc_url: go2rtc base URL.
        camera: Stream name in go2rtc.
        audio_url: HTTP URL of the audio file to push.

    Returns:
        Tuple of (elapsed_seconds, http_status_code).
    """
    import urllib.request
    start = time.monotonic()
    url = f"{go2rtc_url}/api/ffmpeg?dst={camera}&file={audio_url}"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            elapsed = time.monotonic() - start
            return elapsed, resp.status
    except Exception as e:
        elapsed = time.monotonic() - start
        return elapsed, str(e)


def get_audio_duration(path: str) -> float:
    """Get audio duration using ffprobe.

    Args:
        path: Path to audio file.

    Returns:
        Duration in seconds, or 0.0 on failure.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=5,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def start_http_server(directory: str, port: int) -> http.server.HTTPServer:
    """Start a simple HTTP server to serve audio files to go2rtc.

    Args:
        directory: Directory to serve files from.
        port: Port to listen on.

    Returns:
        The running HTTPServer instance.
    """
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)
        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("0.0.0.0", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# --- Test Runner ------------------------------------------------------------

def run_tests(args):
    """Run the full latency test suite.

    Args:
        args: Parsed command-line arguments.
    """
    work_dir = tempfile.mkdtemp(prefix="voxwatch_latency_")
    print(f"\n{'='*60}")
    print(f"  VoxWatch Audio Latency Test Suite")
    print(f"{'='*60}")
    print(f"  Camera:    {args.camera}")
    print(f"  go2rtc:    {args.go2rtc}")
    print(f"  Codec:     {args.codec}")
    print(f"  Rounds:    {args.rounds}")
    print(f"  Message:   {args.message[:60]}...")
    if args.kokoro:
        print(f"  Kokoro:    {args.kokoro}")
    print(f"  Work dir:  {work_dir}")
    print(f"{'='*60}\n")

    # Start HTTP server for serving audio to go2rtc
    server = start_http_server(work_dir, SERVE_PORT)
    serve_host = args.go2rtc.split("://")[1].split(":")[0]
    print(f"[OK] HTTP server started on 0.0.0.0:{SERVE_PORT}")
    print(f"     Serve URL base: http://{serve_host}:{SERVE_PORT}/\n")

    # Generate warmup silence
    warmup_path = os.path.join(work_dir, "warmup.wav")
    generate_silence_wav(warmup_path, 0.5, args.sample_rate, args.codec)
    print(f"[OK] Warmup file generated: {os.path.getsize(warmup_path)} bytes\n")

    results = {}

    # -- Test 1: TTS Generation ------------------------------------------
    print("--- Test 1: TTS Generation -------------------------------")
    tts_providers = []

    # espeak
    espeak_path = os.path.join(work_dir, "tts_espeak.wav")
    t = generate_tts_espeak(args.message, espeak_path)
    if t >= 0:
        dur = get_audio_duration(espeak_path)
        sz = os.path.getsize(espeak_path)
        tts_providers.append(("espeak", t, dur, sz))
        print(f"  espeak:  {t:.3f}s  ({dur:.1f}s audio, {sz//1024}KB)")
    else:
        print(f"  espeak:  [SKIP] not found")

    # piper
    piper_path = os.path.join(work_dir, "tts_piper.wav")
    t = generate_tts_piper(args.message, piper_path)
    if t >= 0:
        dur = get_audio_duration(piper_path)
        sz = os.path.getsize(piper_path)
        tts_providers.append(("piper", t, dur, sz))
        print(f"  piper:   {t:.3f}s  ({dur:.1f}s audio, {sz//1024}KB)")
    else:
        print(f"  piper:   [SKIP] not found")

    # kokoro
    if args.kokoro:
        kokoro_path = os.path.join(work_dir, "tts_kokoro.wav")
        t = generate_tts_kokoro(args.message, kokoro_path, args.kokoro, args.voice)
        if t >= 0:
            dur = get_audio_duration(kokoro_path)
            sz = os.path.getsize(kokoro_path)
            tts_providers.append(("kokoro", t, dur, sz))
            print(f"  kokoro:  {t:.3f}s  ({dur:.1f}s audio, {sz//1024}KB)")
        else:
            print(f"  kokoro:  [FAIL]")

    results["tts"] = tts_providers
    print()

    # -- Test 2: Codec Conversion ----------------------------------------
    print("--- Test 2: Codec Conversion -----------------------------")
    conversion_results = []
    for name, _, _, _ in tts_providers:
        src = os.path.join(work_dir, f"tts_{name}.wav")
        dst = os.path.join(work_dir, f"converted_{name}.wav")
        t = convert_audio(src, dst, args.codec, args.sample_rate)
        sz = os.path.getsize(dst) if os.path.exists(dst) else 0
        conversion_results.append((name, t, sz))
        print(f"  {name:8s} -> {args.codec}: {t:.3f}s  ({sz//1024}KB)")
    results["conversion"] = conversion_results
    print()

    # -- Test 3: Warmup Push ---------------------------------------------
    print("--- Test 3: Warmup Push ----------------------------------")
    warmup_url = f"http://{serve_host}:{SERVE_PORT}/warmup.wav"
    warmup_times = []
    for i in range(min(args.rounds, 3)):
        t, status = push_audio(args.go2rtc, args.camera, warmup_url)
        warmup_times.append(t)
        print(f"  Warmup {i+1}: {t:.3f}s  (HTTP {status})")
    results["warmup"] = warmup_times
    print()

    # -- Test 4: Audio Push (per provider) -------------------------------
    print("--- Test 4: Audio Push -----------------------------------")
    push_results = []

    # Wait after warmup
    time.sleep(2)

    for name, _, _, _ in tts_providers:
        converted = os.path.join(work_dir, f"converted_{name}.wav")
        if not os.path.exists(converted):
            continue
        audio_url = f"http://{serve_host}:{SERVE_PORT}/converted_{name}.wav"
        round_times = []
        for i in range(args.rounds):
            t, status = push_audio(args.go2rtc, args.camera, audio_url)
            round_times.append(t)
            print(f"  {name:8s} push {i+1}: {t:.3f}s  (HTTP {status})")
            if i < args.rounds - 1:
                time.sleep(3)  # Let backchannel stay warm
        push_results.append((name, round_times))
    results["push"] = push_results
    print()

    # -- Test 5: Full Pipeline -------------------------------------------
    print("--- Test 5: Full Pipeline (TTS -> Convert -> Push) ------")
    pipeline_results = []
    for name, tts_time, _, _ in tts_providers:
        converted = os.path.join(work_dir, f"converted_{name}.wav")
        if not os.path.exists(converted):
            continue
        audio_url = f"http://{serve_host}:{SERVE_PORT}/converted_{name}.wav"

        # Do a fresh warmup
        push_audio(args.go2rtc, args.camera, warmup_url)
        time.sleep(2)

        # Measure full pipeline
        start = time.monotonic()

        # TTS
        fresh_tts = os.path.join(work_dir, f"pipeline_{name}_tts.wav")
        if name == "espeak":
            generate_tts_espeak(args.message, fresh_tts)
        elif name == "piper":
            generate_tts_piper(args.message, fresh_tts)
        elif name == "kokoro":
            generate_tts_kokoro(args.message, fresh_tts, args.kokoro, args.voice)
        tts_done = time.monotonic()

        # Convert
        fresh_converted = os.path.join(work_dir, f"pipeline_{name}_ready.wav")
        convert_audio(fresh_tts, fresh_converted, args.codec, args.sample_rate)
        convert_done = time.monotonic()

        # Push
        fresh_url = f"http://{serve_host}:{SERVE_PORT}/pipeline_{name}_ready.wav"
        push_time, status = push_audio(args.go2rtc, args.camera, fresh_url)
        total = time.monotonic() - start

        pipeline_results.append({
            "provider": name,
            "tts": tts_done - start,
            "convert": convert_done - tts_done,
            "push": push_time,
            "total": total,
            "status": status,
        })
        print(f"  {name:8s}: TTS={tts_done-start:.3f}s  "
              f"Convert={convert_done-tts_done:.3f}s  "
              f"Push={push_time:.3f}s  "
              f"TOTAL={total:.3f}s  (HTTP {status})")
        time.sleep(3)

    results["pipeline"] = pipeline_results
    print()

    # -- Summary Table ---------------------------------------------------
    print("=" * 60)
    print("  SUMMARY — End-to-End Pipeline Latency")
    print("=" * 60)
    print(f"  {'Provider':<12} {'TTS':>8} {'Convert':>8} {'Push':>8} {'TOTAL':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for p in pipeline_results:
        print(f"  {p['provider']:<12} {p['tts']:>7.2f}s {p['convert']:>7.2f}s "
              f"{p['push']:>7.2f}s {p['total']:>7.2f}s")
    print()

    # Fastest
    if pipeline_results:
        fastest = min(pipeline_results, key=lambda x: x["total"])
        print(f"  Fastest: {fastest['provider']} at {fastest['total']:.2f}s total")
        print()

    # Breakdown of where time is spent
    if pipeline_results:
        avg_tts = sum(p["tts"] for p in pipeline_results) / len(pipeline_results)
        avg_convert = sum(p["convert"] for p in pipeline_results) / len(pipeline_results)
        avg_push = sum(p["push"] for p in pipeline_results) / len(pipeline_results)
        total = avg_tts + avg_convert + avg_push
        if total > 0:
            print(f"  Time breakdown (average):")
            print(f"    TTS:     {avg_tts:.2f}s ({avg_tts/total*100:.0f}%)")
            print(f"    Convert: {avg_convert:.2f}s ({avg_convert/total*100:.0f}%)")
            print(f"    Push:    {avg_push:.2f}s ({avg_push/total*100:.0f}%)")
            print()
            if avg_push / total > 0.5:
                print(f"  ! Push is the bottleneck ({avg_push/total*100:.0f}% of total).")
                print(f"    This is go2rtc/ffmpeg overhead — consider:")
                print(f"    - Using /api/streams instead of /api/ffmpeg (if it works with your camera)")
                print(f"    - Keeping backchannel warm with periodic silent pushes")
                print(f"    - Using a camera with faster backchannel negotiation")
            elif avg_tts / total > 0.5:
                print(f"  ! TTS is the bottleneck ({avg_tts/total*100:.0f}% of total).")
                print(f"    Consider switching to a faster TTS provider.")

    print(f"\n  Files saved in: {work_dir}")
    print(f"{'='*60}\n")

    server.shutdown()


def main():
    """Parse arguments and run the latency test suite."""
    parser = argparse.ArgumentParser(
        description="VoxWatch Audio Push Latency Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--camera", required=True,
                        help="go2rtc stream name to push audio to")
    parser.add_argument("--go2rtc", default=DEFAULT_GO2RTC,
                        help=f"go2rtc base URL (default: {DEFAULT_GO2RTC})")
    parser.add_argument("--message", default=DEFAULT_MESSAGE,
                        help="Message to speak")
    parser.add_argument("--codec", default=DEFAULT_CODEC,
                        help=f"Audio codec (default: {DEFAULT_CODEC})")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE,
                        help=f"Sample rate (default: {DEFAULT_SAMPLE_RATE})")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Number of push rounds per provider (default: 3)")
    parser.add_argument("--kokoro", default=None,
                        help="Kokoro TTS server URL (e.g. http://localhost:8880)")
    parser.add_argument("--voice", default="am_fenrir",
                        help="Kokoro voice name (default: am_fenrir)")
    args = parser.parse_args()
    run_tests(args)


if __name__ == "__main__":
    main()
