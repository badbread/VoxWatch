#!/usr/bin/env python3
"""
test_full_pipeline.py -- End-to-End Voxwatch Latency Test

Simulates the real Voxwatch flow: generate TTS on the fly, convert to
camera-compatible format, push to speaker via go2rtc API, and measure
latency at each step.

Prerequisites:
  - go2rtc running with camera configured
  - ffmpeg on PATH
  - pyttsx3 (Windows TTS) or piper/espeak for TTS
  - pip install requests pyttsx3

Usage:
  python test_full_pipeline.py --camera front_door --go2rtc-url http://localhost:1984
  python test_full_pipeline.py --camera front_door --go2rtc-url http://localhost:1984 --message "Leave now!"
"""

import argparse
import http.server
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

try:
    import requests
except ImportError:
    print("[FAIL] requests is not installed. Run: pip install requests")
    sys.exit(1)


# Timeouts
FFMPEG_TIMEOUT = 30
HTTP_TIMEOUT = 15

# Default message -- what Voxwatch would actually say to an intruder
DEFAULT_MESSAGE = (
    "Attention. You have been detected on a monitored security camera. "
    "The property owner has been notified and is watching. "
    "Please leave the area immediately."
)


def parse_args():
    """Parse CLI arguments for pipeline configuration.

    Returns:
        argparse.Namespace with all pipeline parameters.
    """
    parser = argparse.ArgumentParser(
        description="End-to-end Voxwatch pipeline test with latency measurement."
    )
    parser.add_argument(
        "--go2rtc-url", default="http://localhost:1984",
        help="go2rtc base URL (default: http://localhost:1984)"
    )
    parser.add_argument("--camera", required=True, help="Camera stream name in go2rtc")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="Message to speak")
    parser.add_argument(
        "--serve-ip", default=None,
        help="IP address for the temporary HTTP server (auto-detected if omitted)."
    )
    parser.add_argument(
        "--serve-port", type=int, default=8888,
        help="Port for the temporary HTTP server (default: 8888)."
    )
    return parser.parse_args()


def get_local_ip() -> str:
    """Detect this machine's LAN IP address.

    Returns:
        Local IP address as a string.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_tts(message: str, output_path: str) -> bool:
    """Generate speech audio from text using the best available TTS engine.

    Tries pyttsx3 (Windows SAPI) first, then Piper, then espeak.

    Args:
        message: Text to convert to speech.
        output_path: Where to write the WAV file.

    Returns:
        True if TTS succeeded, False otherwise.
    """
    # Try pyttsx3 first -- works on Windows using SAPI5 voices
    try:
        import pyttsx3
        print("[INFO] Generating TTS with pyttsx3 (Windows SAPI)...")
        engine = pyttsx3.init()
        engine.save_to_file(message, output_path)
        engine.runAndWait()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
    except ImportError:
        print("[INFO] pyttsx3 not installed, trying other engines...")
    except Exception as e:
        print(f"[WARN] pyttsx3 failed: {e}")

    # Try Piper -- high quality neural TTS
    if shutil.which("piper"):
        print("[INFO] Generating TTS with Piper...")
        try:
            result = subprocess.run(
                ["piper", "--model", "en_US-lessac-medium", "--output_file", output_path],
                input=message.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and os.path.exists(output_path):
                return True
        except Exception as e:
            print(f"[WARN] Piper failed: {e}")

    # Fallback to espeak
    for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
            print(f"[INFO] Generating TTS with {cmd}...")
            try:
                result = subprocess.run(
                    [cmd, "-w", output_path, message],
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0 and os.path.exists(output_path):
                    return True
            except Exception as e:
                print(f"[WARN] {cmd} failed: {e}")

    print("[FAIL] No TTS engine available (need pyttsx3, piper, or espeak).")
    return False


def convert_to_camera_format(input_wav: str, output_wav: str) -> bool:
    """Convert the TTS WAV to G.711 mu-law 8 kHz mono for Reolink cameras.

    The CX410's backchannel uses PCMU (mu-law).

    Args:
        input_wav: Path to the source TTS audio.
        output_wav: Path for the converted camera-compatible audio.

    Returns:
        True if conversion succeeded.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_wav,
        "-acodec", "pcm_mulaw",  # Reolink CX410 backchannel uses PCMU (G.711 mu-law)
        "-ar", "8000",            # 8 kHz sample rate
        "-ac", "1",               # Mono
        output_wav,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT)
        return result.returncode == 0
    except Exception as e:
        print(f"[FAIL] ffmpeg conversion error: {e}")
        return False


def start_http_server(directory: str, port: int) -> http.server.HTTPServer:
    """Start a background HTTP server so go2rtc can fetch the audio file.

    Args:
        directory: Directory containing the audio files.
        port: Port to listen on.

    Returns:
        The running HTTPServer instance.
    """
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        """HTTP handler that suppresses log output to keep terminal clean."""
        def __init__(self, *args, **kwargs):
            """Override default directory so files are served from the temp dir."""
            super().__init__(*args, directory=directory, **kwargs)
        def log_message(self, format, *args):
            """Suppress default stderr logging to avoid cluttering test output."""
            pass

    server = http.server.HTTPServer(("0.0.0.0", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def push_audio_via_go2rtc(base_url: str, camera: str, audio_filename: str,
                           serve_ip: str, serve_port: int) -> bool:
    """Push audio to the camera using go2rtc's API (proven working method).

    Tells go2rtc to fetch the audio file from our HTTP server and play it
    through the camera's backchannel.

    Args:
        base_url: go2rtc base URL.
        camera: Camera stream name.
        audio_filename: Filename of the audio file (just the name, not full path).
        serve_ip: IP of the local HTTP server.
        serve_port: Port of the local HTTP server.

    Returns:
        True if go2rtc accepted the request.
    """
    audio_url = f"http://{serve_ip}:{serve_port}/{audio_filename}"
    api_url = f"{base_url}/api/streams?dst={camera}&src={audio_url}"

    try:
        resp = requests.post(api_url, timeout=HTTP_TIMEOUT)
        return resp.status_code == 200
    except Exception as e:
        print(f"[FAIL] go2rtc API error: {e}")
        return False


def print_latency_estimate(tts_time: float, convert_time: float, push_time: float):
    """Print pipeline latency breakdown and full-system estimates.

    Args:
        tts_time: Seconds spent generating TTS audio.
        convert_time: Seconds spent converting audio format.
        push_time: Seconds spent pushing audio to camera.
    """
    pipeline_total = tts_time + convert_time + push_time

    print("\n" + "=" * 60)
    print("  LATENCY BREAKDOWN")
    print("=" * 60)
    print(f"  TTS generation   : {tts_time:.2f}s")
    print(f"  Audio conversion : {convert_time:.2f}s")
    print(f"  Audio push (API) : {push_time:.2f}s")
    print(f"  --------------------------")
    print(f"  Pipeline total   : {pipeline_total:.2f}s")

    # Estimated latencies for components not tested in this script.
    # These are empirical estimates from the author's test environment —
    # your numbers will vary based on hardware, network, and model choice.
    frigate_ha_latency = 1.5   # Frigate person detection + HA automation trigger
    gemini_latency = 2.0       # Gemini Flash API for image description
    llava_latency = 4.0        # Local LLaVA on RTX 4000 for image description

    print("\n--- Estimated Full Voxwatch System Latency ---")
    print(f"  Frigate detection + HA trigger : ~{frigate_ha_latency:.1f}s")
    print()

    total_cloud = frigate_ha_latency + gemini_latency + pipeline_total
    print(f"  With Gemini Flash (cloud):")
    print(f"    AI vision analysis           : ~{gemini_latency:.1f}s")
    print(f"    Audio pipeline               :  {pipeline_total:.2f}s")
    print(f"    ================================")
    print(f"    TOTAL (detection -> speaker)  : ~{total_cloud:.1f}s")

    total_local = frigate_ha_latency + llava_latency + pipeline_total
    print()
    print(f"  With LLaVA on RTX 4000 (local):")
    print(f"    AI vision analysis           : ~{llava_latency:.1f}s")
    print(f"    Audio pipeline               :  {pipeline_total:.2f}s")
    print(f"    ================================")
    print(f"    TOTAL (detection -> speaker)  : ~{total_local:.1f}s")

    print()


def main():
    """Entry point -- run the full TTS -> convert -> push pipeline with timing."""
    args = parse_args()
    base_url = args.go2rtc_url.rstrip("/")
    serve_ip = args.serve_ip or get_local_ip()
    serve_port = args.serve_port

    print("=" * 60)
    print("  VOXWATCH -- Full Pipeline Test")
    print("=" * 60)
    print(f"  Camera  : {args.camera}")
    print(f"  go2rtc  : {base_url}")
    print(f"  Message : {args.message[:60]}{'...' if len(args.message) > 60 else ''}")
    print()

    # Use a temp directory for intermediate files
    with tempfile.TemporaryDirectory(prefix="voxwatch_") as tmpdir:
        tts_wav = os.path.join(tmpdir, "tts_output.wav")
        camera_wav = os.path.join(tmpdir, "camera_ready.wav")

        # -- Step 1: Generate TTS ---------------------------------
        print("--- Step 1: TTS Generation ---")
        t0 = time.time()
        if not generate_tts(args.message, tts_wav):
            print("[FAIL] TTS generation failed. Install pyttsx3: pip install pyttsx3")
            sys.exit(1)
        tts_time = time.time() - t0
        print(f"[OK] TTS generated in {tts_time:.2f}s ({os.path.getsize(tts_wav):,} bytes)")

        # -- Step 2: Convert to camera format ---------------------
        print("\n--- Step 2: Audio Conversion ---")
        t0 = time.time()
        if not convert_to_camera_format(tts_wav, camera_wav):
            print("[FAIL] Audio conversion failed. Is ffmpeg installed?")
            sys.exit(1)
        convert_time = time.time() - t0
        print(f"[OK] Audio converted in {convert_time:.2f}s ({os.path.getsize(camera_wav):,} bytes)")

        # -- Step 3: Start HTTP server and push to camera ---------
        print("\n--- Step 3: Audio Push ---")
        server = start_http_server(tmpdir, serve_port)
        print(f"[OK] HTTP server started on {serve_ip}:{serve_port}")

        print(">>> Pushing audio now... listen to your camera speaker! <<<")
        t0 = time.time()
        success = push_audio_via_go2rtc(
            base_url, args.camera, "camera_ready.wav", serve_ip, serve_port
        )
        push_time = time.time() - t0

        if success:
            print(f"[OK] Audio push request accepted in {push_time:.2f}s")
            # Wait for the audio to finish playing before shutting down the server.
            # The audio file is ~7s long; we add 3s buffer for network latency.
            # If we shut down the HTTP server too early, go2rtc can't finish fetching.
            print("[INFO] Waiting for audio playback to complete...")
            time.sleep(10)
        else:
            print(f"[FAIL] Audio push failed after {push_time:.2f}s")

        # -- Latency Report ---------------------------------------
        print_latency_estimate(tts_time, convert_time, push_time)

        if success:
            print("[OK] Pipeline complete! Did you hear audio from the camera?")
        else:
            print("[FAIL] Pipeline failed at the push step.")
            print("[INFO] Re-run test_audio_push.py to verify the working method.")

        # Clean up
        server.shutdown()


if __name__ == "__main__":
    main()
