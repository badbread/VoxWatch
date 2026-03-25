#!/usr/bin/env python3
"""
discovery.py — Reolink Camera Capability Discovery

Connects to a Reolink camera via the reolink-aio library and prints
hardware info, audio/speaker capabilities, stream URLs, and a
checklist of settings the user should verify in the camera's web UI.

Prerequisites:
  pip install reolink-aio aiohttp

Usage:
  python discovery.py --host 192.168.1.100 --password YOUR_PASSWORD
  python discovery.py --host 192.168.1.100 --user admin --password YOUR_PASSWORD
"""

import argparse
import asyncio
import sys

try:
    from reolink_aio.api import Host
except ImportError:
    print("[FAIL] reolink-aio is not installed. Run: pip install reolink-aio aiohttp")
    sys.exit(1)


def parse_args():
    """Parse command-line arguments for camera connection details.

    Returns:
        argparse.Namespace with host, user, and password fields.
    """
    parser = argparse.ArgumentParser(
        description="Discover Reolink camera capabilities for Voxwatch audio push."
    )
    parser.add_argument("--host", required=True, help="Camera IP address (e.g. 192.168.1.100)")
    parser.add_argument("--user", default="admin", help="Camera username (default: admin)")
    parser.add_argument("--password", required=True, help="Camera password")
    return parser.parse_args()


async def discover_camera(host: str, user: str, password: str):
    """Connect to the camera, pull its info, and print a full capability report.

    Args:
        host: IP address of the Reolink camera.
        user: Login username.
        password: Login password.
    """
    # reolink-aio uses an HTTP session under the hood; port 80 is the default
    camera = Host(host, user, password)

    print("=" * 60)
    print("  VOXWATCH — Camera Discovery")
    print("=" * 60)
    print(f"\n[INFO] Connecting to {host} as '{user}'...")

    try:
        await camera.get_host_data()
    except Exception as e:
        print(f"[FAIL] Could not connect to camera at {host}: {e}")
        print("[INFO] Check that the IP is correct and the camera is powered on.")
        await camera.logout()
        return

    # ── Hardware Info ─────────────────────────────────────────────
    print("\n--- Hardware Info ---")
    print(f"  Model          : {camera.model}")
    print(f"  Hardware ver   : {camera.hardware_version}")
    print(f"  Firmware ver   : {camera.sw_version}")
    print(f"  MAC address    : {camera.mac_address}")
    print(f"  Channels       : {camera.channels}")

    # ── Audio / Speaker Capabilities ─────────────────────────────
    print("\n--- Audio & Speaker Capabilities (per channel) ---")
    for ch in camera.channels:
        print(f"\n  Channel {ch}:")
        # audio_support tells us if the camera can record/send audio
        audio = camera.audio_support(ch) if hasattr(camera, "audio_support") else "unknown"
        print(f"    Audio support : {audio}")

        # Two-way audio / talkback is what we need for Voxwatch
        talkback = camera.audio_talkback(ch) if hasattr(camera, "audio_talkback") else "unknown"
        print(f"    Talkback      : {talkback}")

        # Some firmware versions expose a speaker_support flag
        speaker = camera.speaker_support(ch) if hasattr(camera, "speaker_support") else "unknown"
        print(f"    Speaker       : {speaker}")

    # ── Stream URLs ──────────────────────────────────────────────
    # We pre-format these with the user's credentials so they can
    # copy/paste directly into VLC, ffplay, or go2rtc config.
    print("\n--- Stream URLs (copy/paste ready) ---")
    for ch in camera.channels:
        print(f"\n  Channel {ch}:")
        # RTSP main stream — high resolution
        print(f"    RTSP main : rtsp://{user}:{password}@{host}:554/h264Preview_{ch + 1:02d}_main")
        # RTSP sub stream — lower resolution, often used for two-way audio
        print(f"    RTSP sub  : rtsp://{user}:{password}@{host}:554/h264Preview_{ch + 1:02d}_sub")
        # Alternate RTSP path used by some Reolink firmware versions
        print(f"    RTSP alt  : rtsp://{user}:{password}@{host}:554/Preview_{ch + 1:02d}_sub")
        # HTTP-FLV stream via the camera's built-in web server
        print(f"    HTTP-FLV  : http://{host}/flv?port=1935&app=bcs&stream=channel{ch}_main.bcs&user={user}&password={password}")

    # ── ONVIF ────────────────────────────────────────────────────
    print("\n--- ONVIF ---")
    print(f"  Endpoint : http://{host}:8000/onvif/device_service")
    print("  (Port may be 80 or 8000 depending on firmware)")

    # ── Checklist ────────────────────────────────────────────────
    print("\n--- Camera Web UI Checklist ---")
    print(f"  Open http://{host} in your browser and verify:")
    print("  [ ] Network > Advanced > Server Port: RTSP is ENABLED (port 554)")
    print("  [ ] Network > Advanced > Server Port: HTTP is ENABLED (port 80)")
    print("  [ ] Network > Advanced > Server Port: ONVIF is ENABLED")
    print("  [ ] Audio > Audio toggle is ON")
    print("  [ ] Device Settings > Speaker volume is above 0")
    print("  [ ] Firmware is up to date (check Reolink support site)")
    print()

    # Clean up the HTTP session
    await camera.logout()
    print("[OK] Discovery complete.")


def main():
    """Entry point — parse args and run the async discovery."""
    args = parse_args()
    try:
        asyncio.run(discover_camera(args.host, args.user, args.password))
    except KeyboardInterrupt:
        print("\n[INFO] Cancelled by user.")


if __name__ == "__main__":
    main()
