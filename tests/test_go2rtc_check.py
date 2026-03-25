#!/usr/bin/env python3
"""
test_go2rtc_check.py — Verify go2rtc Sees the Camera & Check Backchannel Support

Queries the go2rtc HTTP API to confirm it is running, finds the specified camera
stream, looks for backchannel (two-way audio) indicators, and prints step-by-step
instructions for the critical manual browser microphone test.

Prerequisites:
  - go2rtc running (typically inside Frigate) with its API exposed on port 1984
  - pip install requests

Usage:
  python test_go2rtc_check.py --camera front_door
  python test_go2rtc_check.py --url http://192.168.1.50:1984 --camera front_door
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("[FAIL] requests is not installed. Run: pip install requests")
    sys.exit(1)


# Timeout for all HTTP requests to go2rtc (seconds)
REQUEST_TIMEOUT = 10


def parse_args():
    """Parse CLI arguments for go2rtc URL and camera name.

    Returns:
        argparse.Namespace with url and camera fields.
    """
    parser = argparse.ArgumentParser(
        description="Check go2rtc for camera streams and two-way audio backchannel support."
    )
    parser.add_argument(
        "--url", default="http://localhost:1984",
        help="go2rtc base URL (default: http://localhost:1984)"
    )
    parser.add_argument("--camera", required=True, help="Camera stream name as configured in go2rtc")
    return parser.parse_args()


def check_go2rtc_running(base_url: str) -> bool:
    """Hit the go2rtc API to confirm it is reachable.

    Args:
        base_url: go2rtc base URL (e.g. http://localhost:1984).

    Returns:
        True if the API responds, False otherwise.
    """
    try:
        resp = requests.get(f"{base_url}/api/streams", timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            print(f"[OK] go2rtc is running at {base_url}")
            return True
        else:
            print(f"[FAIL] go2rtc returned HTTP {resp.status_code}")
            return False
    except requests.ConnectionError:
        print(f"[FAIL] Cannot connect to go2rtc at {base_url}")
        print("[INFO] Is go2rtc running? Is the port correct?")
        return False
    except requests.Timeout:
        print(f"[FAIL] go2rtc request timed out ({REQUEST_TIMEOUT}s)")
        return False


def list_streams(base_url: str) -> dict:
    """Fetch all configured streams from go2rtc.

    Args:
        base_url: go2rtc base URL.

    Returns:
        dict of stream configs, or empty dict on failure.
    """
    try:
        resp = requests.get(f"{base_url}/api/streams", timeout=REQUEST_TIMEOUT)
        streams = resp.json()
        print(f"\n[INFO] go2rtc has {len(streams)} configured stream(s):")
        for name in sorted(streams.keys()):
            print(f"  • {name}")
        return streams
    except Exception as e:
        print(f"[FAIL] Could not list streams: {e}")
        return {}


def check_backchannel(base_url: str, camera: str):
    """Look for two-way audio / backchannel indicators on the camera stream.

    go2rtc exposes codec and direction info through /api/streams.  We look for
    audio codecs (PCMA, PCMU) with 'sendonly' direction — that indicates the
    camera accepts audio input (backchannel).

    Args:
        base_url: go2rtc base URL.
        camera: Camera stream name.
    """
    print(f"\n--- Backchannel Analysis for '{camera}' ---")

    # The /api/streams endpoint returns config; /api/webrtc?src= or /api/streams?src=
    # may give runtime codec info depending on go2rtc version
    try:
        # Try fetching detailed info via the webrtc SDP or streams endpoint
        resp = requests.get(f"{base_url}/api/streams?src={camera}", timeout=REQUEST_TIMEOUT)
        data = resp.json() if resp.status_code == 200 else None
    except Exception:
        data = None

    if data:
        print(f"[INFO] Stream config/state for '{camera}':")
        print(f"       {json.dumps(data, indent=2)[:1000]}")

        # Scan the response for backchannel clues
        data_str = json.dumps(data).lower()
        backchannel_hints = ["sendonly", "backchannel", "pcma", "pcmu", "two-way", "talkback"]
        found = [h for h in backchannel_hints if h in data_str]
        if found:
            print(f"[OK] Backchannel indicators found: {', '.join(found)}")
        else:
            print("[WARN] No obvious backchannel indicators in stream data.")
            print("[INFO] This doesn't necessarily mean it won't work — the manual test is definitive.")
    else:
        print("[WARN] Could not fetch detailed stream info. Proceeding to manual test instructions.")


def print_manual_test_instructions(base_url: str, camera: str):
    """Print clear, step-by-step instructions for the browser microphone test.

    This is THE most important validation step.  If the mic test works in the
    browser, we know the backchannel is functional and just need to replicate
    it programmatically.

    Args:
        base_url: go2rtc base URL.
        camera: Camera stream name.
    """
    print("\n" + "=" * 60)
    print("  *** CRITICAL: Manual Browser Microphone Test ***")
    print("=" * 60)
    print()
    print("  This is the single most important step.  If audio plays from")
    print("  the camera speaker during this test, we know the backchannel")
    print("  works and the programmatic push will too.")
    print()
    print("  Step 1: Open this URL in your browser (Chrome recommended):")
    print(f"          {base_url}/stream.html?src={camera}")
    print()
    print("  Step 2: Look for a MICROPHONE ICON in the video player controls.")
    print("          If you see it, click it and SPEAK — listen at your camera.")
    print()
    print("  Step 3: If no mic icon, try this alternative page:")
    print(f"          {base_url}/links.html?src={camera}")
    print('          Click "video+audio+microphone" link.')
    print()
    print("  Step 4: If audio came out of the camera speaker — SUCCESS!")
    print("          The backchannel works.  Proceed to test_audio_push.py.")
    print()
    print("  Step 5: If NO audio, check these things:")
    print("          - Camera speaker volume is turned up in the camera web UI")
    print("          - Browser microphone permission was granted")
    print("          - go2rtc config has the two-way audio RTSP source line")
    print()


def print_go2rtc_config_snippet(camera: str, camera_ip: str = "CAMERA_IP",
                                 user: str = "admin", password: str = "PASSWORD"):
    """Print the go2rtc YAML config snippet needed for two-way audio.

    Reolink cameras need an RTSP source with backchannel=1 to enable the
    audio return path.

    Args:
        camera: Camera stream name.
        camera_ip: Camera IP placeholder.
        user: Camera username placeholder.
        password: Camera password placeholder.
    """
    print("\n--- go2rtc Config Snippet (if camera not configured for two-way audio) ---")
    print()
    print("  Add this to your go2rtc.yaml (or Frigate's go2rtc section):")
    print()
    print("  streams:")
    print(f"    {camera}:")
    print(f"      - rtsp://{user}:{password}@{camera_ip}:554/h264Preview_01_sub")
    print(f"      - \"ffmpeg:{camera}#audio=opus\"    # transcode audio for WebRTC")
    print()
    print("  For two-way audio, some cameras also need this variant:")
    print()
    print("  streams:")
    print(f"    {camera}:")
    print(f"      - rtsp://{user}:{password}@{camera_ip}:554/h264Preview_01_sub?backchannel=1")
    print()
    print("  After changing config, restart go2rtc / Frigate and re-run this script.")
    print()


def main():
    """Entry point — run all go2rtc checks and print manual test instructions."""
    args = parse_args()
    base_url = args.url.rstrip("/")
    camera = args.camera

    print("=" * 60)
    print("  VOXWATCH — go2rtc Backchannel Check")
    print("=" * 60)
    print()

    # 1. Is go2rtc running?
    if not check_go2rtc_running(base_url):
        sys.exit(1)

    # 2. List all streams, confirm our camera exists
    streams = list_streams(base_url)
    if camera not in streams:
        print(f"\n[FAIL] Camera '{camera}' not found in go2rtc streams.")
        print(f"[INFO] Available streams: {', '.join(streams.keys()) if streams else '(none)'}")
        print_go2rtc_config_snippet(camera)
        sys.exit(1)
    else:
        print(f"\n[OK] Camera '{camera}' is configured in go2rtc.")

    # 3. Check for backchannel indicators
    check_backchannel(base_url, camera)

    # 4. The big one — manual browser test
    print_manual_test_instructions(base_url, camera)

    # 5. Config help in case they need it
    print_go2rtc_config_snippet(camera)

    print("[OK] go2rtc check complete. Perform the manual mic test above before continuing.")


if __name__ == "__main__":
    main()
