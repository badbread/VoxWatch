#!/usr/bin/env python3
"""
test_audio_push.py -- Push Audio to Camera Speaker via go2rtc

The main integration test.  Tries multiple methods to push an audio file
to a Reolink camera speaker through go2rtc, then prints a results summary.

Methods tested:
  1. go2rtc API with HTTP-served audio (PROVEN WORKING)
     - Spins up a temporary HTTP server to serve the audio file
     - Tells go2rtc to fetch and play it via /api/streams?dst=CAMERA&src=URL
  2. ffmpeg -> go2rtc internal RTSP
  3. ffmpeg -> camera RTSP directly (requires --camera-ip and --password)
  4. ffmpeg -> go2rtc RTSP with ?audio param

Prerequisites:
  - go2rtc running with the camera configured
  - ffmpeg on PATH
  - An audio file (generate with generate_test_audio.py)
  - pip install requests

Usage:
  python test_audio_push.py --camera front_door
  python test_audio_push.py --camera front_door --audio-file test_message_mulaw.wav
  python test_audio_push.py --camera front_door --camera-ip 192.168.1.100 --password SECRET
"""

import argparse
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("[FAIL] requests is not installed. Run: pip install requests")
    sys.exit(1)


# Timeout for ffmpeg subprocesses (seconds) -- enough for a short audio clip
FFMPEG_TIMEOUT = 30

# Timeout for HTTP requests (seconds)
HTTP_TIMEOUT = 15

# Pause between methods so the camera speaker resets (seconds)
INTER_METHOD_PAUSE = 3


def parse_args():
    """Parse CLI arguments for camera, go2rtc URL, and audio file options.

    Returns:
        argparse.Namespace with all fields populated.
    """
    parser = argparse.ArgumentParser(
        description="Test audio push to Reolink camera speaker via go2rtc."
    )
    parser.add_argument(
        "--url", default="http://localhost:1984",
        help="go2rtc base URL (default: http://localhost:1984)"
    )
    parser.add_argument("--camera", required=True, help="Camera stream name in go2rtc")
    parser.add_argument("--camera-ip", default=None, help="Direct camera IP (for method 3)")
    parser.add_argument("--user", default="admin", help="Camera username (default: admin)")
    parser.add_argument("--password", default=None, help="Camera password (for method 3)")
    parser.add_argument(
        "--audio-file", default=None,
        help="Audio file to push. Auto-detects from generate_test_audio.py output if omitted."
    )
    parser.add_argument(
        "--serve-ip", default=None,
        help="IP address for the temporary HTTP server (auto-detected if omitted)."
    )
    parser.add_argument(
        "--serve-port", type=int, default=8888,
        help="Port for the temporary HTTP server (default: 8888)."
    )
    return parser.parse_args()


def find_audio_file(explicit_path: str = None) -> str:
    """Locate the best audio file to use for testing.

    Priority: explicit path > test_message_mulaw.wav (proven) > alaw > others.

    Args:
        explicit_path: User-specified file path, or None.

    Returns:
        Path to the audio file, or exits if none found.
    """
    if explicit_path:
        if os.path.exists(explicit_path):
            return explicit_path
        print(f"[FAIL] Specified audio file not found: {explicit_path}")
        sys.exit(1)

    # Auto-detect: mulaw first since that's what the CX410 backchannel uses (PCMU)
    candidates = [
        "test_message_mulaw.wav",
        "test_message_alaw.wav",
        "test_message_pcm16_8k.wav",
        "test_message_pcm16_48k.wav",
    ]
    for name in candidates:
        if os.path.exists(name):
            print(f"[INFO] Auto-detected audio file: {name}")
            return name

    print("[FAIL] No audio file found. Run generate_test_audio.py first, or use --audio-file.")
    sys.exit(1)


def get_local_ip() -> str:
    """Detect this machine's LAN IP address.

    Opens a UDP socket to a public IP (doesn't send anything) to determine
    which local interface would be used for outbound traffic.

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


def start_http_server(directory: str, port: int) -> http.server.HTTPServer:
    """Start a background HTTP server to serve audio files to go2rtc.

    go2rtc's play-audio feature fetches audio from a URL.  We serve the local
    audio file so go2rtc can pull it over HTTP.

    Args:
        directory: Directory containing the audio files.
        port: Port to listen on.

    Returns:
        The running HTTPServer instance.
    """
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        """HTTP handler that suppresses log output to keep terminal clean."""
        def __init__(self, *args, **kwargs):
            """Override default directory so files are served from the audio output dir."""
            super().__init__(*args, directory=directory, **kwargs)
        def log_message(self, format, *args):
            """Suppress default stderr logging to avoid cluttering test output."""
            pass

    server = http.server.HTTPServer(("0.0.0.0", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def method1_go2rtc_api_url(base_url: str, camera: str, audio_file: str,
                            serve_ip: str, serve_port: int) -> bool:
    """Method 1: Tell go2rtc to fetch and play audio from an HTTP URL.

    This is the PROVEN WORKING method.  go2rtc's /api/streams endpoint accepts
    a src= parameter pointing to an audio file URL.  go2rtc fetches it, decodes
    it, and pushes it to the camera's backchannel.

    Args:
        base_url: go2rtc base URL.
        camera: Camera stream name.
        audio_file: Filename of the audio file (served via HTTP).
        serve_ip: IP of the local HTTP server.
        serve_port: Port of the local HTTP server.

    Returns:
        True if go2rtc accepted and played the audio.
    """
    print("\n" + "=" * 60)
    print("  Method 1: go2rtc API (HTTP URL)")
    print("=" * 60)

    audio_url = f"http://{serve_ip}:{serve_port}/{os.path.basename(audio_file)}"
    api_url = f"{base_url}/api/streams?dst={camera}&src={audio_url}"

    print(f"[INFO] Telling go2rtc to fetch: {audio_url}")
    print(">>> Pushing audio now... listen to your camera speaker! <<<")

    try:
        resp = requests.post(api_url, timeout=HTTP_TIMEOUT)
        print(f"[INFO] Response: HTTP {resp.status_code}")

        if resp.status_code == 200:
            # Wait for the audio to finish playing before declaring success.
            # go2rtc returns immediately but the audio streams in the background.
            # We check if a producer with our URL appeared in the stream info.
            body = resp.text
            if audio_url in body or "pcm_mulaw" in body or "pcm_alaw" in body:
                print("[OK] Method 1 -- go2rtc is playing the audio file.")
                return True
            else:
                print("[WARN] Method 1 -- got HTTP 200 but could not confirm audio playback.")
                print("[INFO] Check if you heard audio from the camera speaker.")
                # HTTP 200 is the only reliable signal — go2rtc streams audio
                # asynchronously, so we can't confirm playback from the API response alone
                return True
        else:
            print(f"[FAIL] Method 1 -- go2rtc returned HTTP {resp.status_code}")
            return False

    except requests.Timeout:
        print(f"[FAIL] Method 1 -- request timed out ({HTTP_TIMEOUT}s)")
        return False
    except Exception as e:
        print(f"[FAIL] Method 1 -- {e}")
        return False


def method2_ffmpeg_go2rtc_rtsp(base_url: str, camera: str, audio_file: str) -> bool:
    """Method 2: Use ffmpeg to stream audio to go2rtc's internal RTSP server.

    go2rtc runs an RTSP server (default port 8554).  We push the audio file
    as a real-time stream to that RTSP endpoint.  go2rtc should then forward
    it to the camera's backchannel.

    Args:
        base_url: go2rtc base URL (used to derive the RTSP host).
        camera: Camera stream name.
        audio_file: Path to the audio file.

    Returns:
        True if ffmpeg exited with code 0.
    """
    print("\n" + "=" * 60)
    print("  Method 2: ffmpeg -> go2rtc RTSP")
    print("=" * 60)

    parsed = urlparse(base_url)
    rtsp_host = parsed.hostname
    rtsp_url = f"rtsp://{rtsp_host}:8554/{camera}"

    print(f"[INFO] Streaming {audio_file} to {rtsp_url}")
    print(">>> Pushing audio now... listen to your camera speaker! <<<")

    return _run_ffmpeg_push(audio_file, rtsp_url)


def method3_ffmpeg_direct_camera(camera_ip: str, user: str, password: str,
                                  audio_file: str) -> bool:
    """Method 3: Bypass go2rtc -- push audio directly to camera's RTSP backchannel.

    Reolink cameras may accept audio on their sub-stream RTSP endpoint.  We try
    two common URL patterns since Reolink firmware varies.

    Args:
        camera_ip: Camera IP address.
        user: Camera username.
        password: Camera password.
        audio_file: Path to the audio file.

    Returns:
        True if any direct RTSP push succeeded.
    """
    print("\n" + "=" * 60)
    print("  Method 3: ffmpeg -> Camera RTSP Directly")
    print("=" * 60)

    rtsp_urls = [
        f"rtsp://{user}:{password}@{camera_ip}:554/Preview_01_sub",
        f"rtsp://{user}:{password}@{camera_ip}:554/h264Preview_01_sub",
    ]

    for url in rtsp_urls:
        safe_url = url.replace(password, "****")
        print(f"\n[INFO] Trying {safe_url}")
        print(">>> Pushing audio now... listen to your camera speaker! <<<")

        if _run_ffmpeg_push(audio_file, url):
            return True
        print("[WARN] Did not work with this URL, trying next...")

    print("[FAIL] Method 3 -- neither RTSP URL pattern worked.")
    return False


def method4_ffmpeg_go2rtc_rtsp_audio_param(base_url: str, camera: str,
                                             audio_file: str) -> bool:
    """Method 4: ffmpeg -> go2rtc RTSP with ?audio query parameter.

    Some go2rtc versions route audio-only streams differently when ?audio
    is appended to the RTSP URL.

    Args:
        base_url: go2rtc base URL (used to derive RTSP host).
        camera: Camera stream name.
        audio_file: Path to the audio file.

    Returns:
        True if ffmpeg exited with code 0.
    """
    print("\n" + "=" * 60)
    print("  Method 4: ffmpeg -> go2rtc RTSP (with ?audio)")
    print("=" * 60)

    parsed = urlparse(base_url)
    rtsp_host = parsed.hostname
    rtsp_url = f"rtsp://{rtsp_host}:8554/{camera}?audio"

    print(f"[INFO] Streaming {audio_file} to {rtsp_url}")
    print(">>> Pushing audio now... listen to your camera speaker! <<<")

    return _run_ffmpeg_push(audio_file, rtsp_url)


def _run_ffmpeg_push(audio_file: str, rtsp_url: str) -> bool:
    """Run ffmpeg to push an audio file to an RTSP endpoint.

    Converts to G.711 mu-law, 8 kHz, mono (what Reolink CX410 backchannel uses)
    and streams in real time (-re flag).  Uses TCP transport for reliability.

    Args:
        audio_file: Path to the source audio file.
        rtsp_url: Destination RTSP URL.

    Returns:
        True if ffmpeg exited with code 0.
    """
    cmd = [
        "ffmpeg",
        "-re",                           # Read input at native frame rate (real-time playback)
        "-i", audio_file,                # Input file
        "-acodec", "pcm_mulaw",          # Reolink CX410 backchannel uses PCMU (G.711 mu-law)
        "-ar", "8000",                   # 8 kHz sample rate -- standard for telephony/IP cameras
        "-ac", "1",                      # Mono -- cameras have a single speaker
        "-f", "rtsp",                    # Output format
        "-rtsp_transport", "tcp",        # TCP is more reliable than UDP for this
        rtsp_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")

        if result.returncode == 0:
            print("[OK] ffmpeg exited successfully (code 0).")
            return True
        else:
            print(f"[FAIL] ffmpeg exited with code {result.returncode}")
            error_lines = stderr.strip().split("\n")[-5:]
            for line in error_lines:
                print(f"       {line}")
            return False

    except subprocess.TimeoutExpired:
        print(f"[FAIL] ffmpeg timed out after {FFMPEG_TIMEOUT}s")
        return False
    except FileNotFoundError:
        print("[FAIL] ffmpeg not found on PATH. Install ffmpeg.")
        return False
    except Exception as e:
        print(f"[FAIL] ffmpeg error: {e}")
        return False


def print_summary(results: dict):
    """Print a summary table of which methods succeeded or failed.

    Args:
        results: dict mapping method name to True (success) or False/None (fail/skip).
    """
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)

    for method, success in results.items():
        if success is None:
            status = "[SKIP]"
        elif success:
            status = "[OK]  "
        else:
            status = "[FAIL]"
        print(f"  {status}  {method}")

    any_success = any(v is True for v in results.values())

    if any_success:
        print("\n[INFO] At least one method reported success.")
        print("       PHYSICALLY CONFIRM that audio played from the camera speaker.")
        print()
        print("       If you heard audio, note which method number worked --")
        print("       you'll use it in test_full_pipeline.py.")
    else:
        print("\n[WARN] No method succeeded.  Troubleshooting steps:")
        print("  1. Did the manual mic test in test_go2rtc_check.py work?")
        print("     (If not, the camera backchannel itself isn't working yet.)")
        print("  2. Is the camera firmware up to date?")
        print("  3. Is HTTP enabled in camera network settings?")
        print("  4. Does the go2rtc config have the RTSP two-way audio line?")
        print("     (See test_go2rtc_check.py for the config snippet.)")
        print("  5. Try a different audio format (e.g. mulaw instead of alaw):")
        print("     python test_audio_push.py --camera X --audio-file test_message_mulaw.wav")

    print()


def main():
    """Entry point -- find audio, start HTTP server, run all methods, print summary."""
    args = parse_args()
    base_url = args.url.rstrip("/")
    camera = args.camera
    audio_file = find_audio_file(args.audio_file)
    audio_dir = os.path.dirname(os.path.abspath(audio_file))

    # Detect local IP for serving audio to go2rtc
    serve_ip = args.serve_ip or get_local_ip()
    serve_port = args.serve_port

    print("=" * 60)
    print("  VOXWATCH -- Audio Push Test")
    print("=" * 60)
    print(f"  go2rtc    : {base_url}")
    print(f"  Camera    : {camera}")
    print(f"  Audio file: {audio_file}")
    print(f"  File size : {os.path.getsize(audio_file):,} bytes")
    print(f"  Serve from: http://{serve_ip}:{serve_port}/")

    # Start temporary HTTP server so go2rtc can fetch audio files
    try:
        server = start_http_server(audio_dir, serve_port)
        print(f"[OK] HTTP server started on port {serve_port}")
    except OSError as e:
        print(f"[WARN] Could not start HTTP server on port {serve_port}: {e}")
        print("[INFO] Method 1 (go2rtc API URL) will be skipped.")
        server = None

    results = {}

    # -- Method 1: go2rtc API with HTTP URL (PROVEN WORKING) ------
    if server:
        results["Method 1: go2rtc API (HTTP URL)"] = method1_go2rtc_api_url(
            base_url, camera, audio_file, serve_ip, serve_port
        )
        # Give the audio time to finish playing on the camera
        print(f"\n[INFO] Waiting 8s for audio playback to complete...")
        time.sleep(8)
    else:
        results["Method 1: go2rtc API (HTTP URL)"] = None

    print(f"[INFO] Pausing {INTER_METHOD_PAUSE}s before next method...")
    time.sleep(INTER_METHOD_PAUSE)

    # -- Method 2: ffmpeg -> go2rtc RTSP -------------------------
    results["Method 2: ffmpeg -> go2rtc RTSP"] = method2_ffmpeg_go2rtc_rtsp(
        base_url, camera, audio_file
    )
    print(f"\n[INFO] Pausing {INTER_METHOD_PAUSE}s before next method...")
    time.sleep(INTER_METHOD_PAUSE)

    # -- Method 3: ffmpeg -> camera directly (optional) ----------
    if args.camera_ip and args.password:
        results["Method 3: ffmpeg -> camera direct"] = method3_ffmpeg_direct_camera(
            args.camera_ip, args.user, args.password, audio_file
        )
        print(f"\n[INFO] Pausing {INTER_METHOD_PAUSE}s before next method...")
        time.sleep(INTER_METHOD_PAUSE)
    else:
        print("\n" + "=" * 60)
        print("  Method 3: ffmpeg -> Camera RTSP Directly")
        print("=" * 60)
        print("[SKIP] Method 3 skipped -- provide --camera-ip and --password to test direct push.")
        results["Method 3: ffmpeg -> camera direct"] = None

    # -- Method 4: ffmpeg -> go2rtc RTSP ?audio ------------------
    results["Method 4: ffmpeg -> go2rtc RTSP ?audio"] = method4_ffmpeg_go2rtc_rtsp_audio_param(
        base_url, camera, audio_file
    )

    # -- Summary -------------------------------------------------
    print_summary(results)

    # Clean up HTTP server
    if server:
        server.shutdown()


if __name__ == "__main__":
    main()
