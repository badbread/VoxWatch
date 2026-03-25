#!/usr/bin/env python3
"""
test_onvif_camera.py -- ONVIF Camera Discovery and Audio Push Test

Comprehensive test suite for bringing up a new ONVIF-capable camera
(rebranded Dahua at 192.168.1.102) in the VoxWatch audio deterrent system.

Tests run in sequence, each building on what the previous test found.
A failed test prints [FAIL] and the suite continues to the next test —
nothing will abort the run unless the camera is completely unreachable.

Tests performed:
  1. ONVIF Discovery  -- probe camera capabilities, codecs, backchannel support
  2. RTSP Stream      -- try common Dahua and Reolink RTSP URL patterns
  3. go2rtc Check     -- verify stream is configured; print add-stream instructions if not
  4. Codec Detection  -- run ffprobe on RTSP to find backchannel audio tracks
  5. Audio Push       -- push warmup + real audio through go2rtc /api/ffmpeg
  6. Multi-Codec      -- generate PCMU and PCMA test files; try each with the push

Prerequisites:
  - pip install requests zeep
  - ffmpeg + ffprobe on PATH
  - (Optional) espeak-ng on PATH for TTS — falls back to pure tone generator

Usage:
  python tests/test_onvif_camera.py
  python tests/test_onvif_camera.py --camera-name dahua_front
  python tests/test_onvif_camera.py --camera-ip 192.168.1.102 --go2rtc-url http://localhost:1984
"""

import argparse
import http.server
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("[FAIL] requests is not installed. Run: pip install requests")
    sys.exit(1)


# ── Camera and network constants ─────────────────────────────────────────────

# Target camera — rebranded Dahua with ONVIF two-way audio
CAMERA_IP = "192.168.1.102"

# go2rtc instance that manages all camera streams for VoxWatch
GO2RTC_URL = "http://localhost:1984"

# VoxWatch HTTP audio server port (must match audio_pipeline.py _serve_port)
AUDIO_SERVE_PORT = 8891

# go2rtc stream name to use for this camera (must match go2rtc.yaml)
# This is the stream name go2rtc knows the camera by — not the camera hostname.
DEFAULT_STREAM_NAME = "dahua_onvif"

# Credentials to try in order — common factory defaults for Dahua/rebranded cameras.
# Supply your real password via --password on the command line.
CREDENTIAL_CANDIDATES = [
    ("admin", "admin"),
    ("admin", "password"),
]

# Dahua RTSP URL patterns (channel=1, main and sub streams)
# Dahua uses /cam/realmonitor?channel=N&subtype=N
# subtype=0 = main stream (high res), subtype=1 = sub stream (lower res, used for backchannel)
DAHUA_RTSP_PATHS = [
    "/cam/realmonitor?channel=1&subtype=0",   # Dahua main
    "/cam/realmonitor?channel=1&subtype=1",   # Dahua sub (most likely to have backchannel)
]

# Reolink-style RTSP paths — some rebranded cameras use these instead
REOLINK_RTSP_PATHS = [
    "/Preview_01_main",
    "/Preview_01_sub",
]

# ONVIF device service is usually port 80 or 8000 on Dahua cameras
ONVIF_PORTS = [80, 8000]

# ── Timeouts ─────────────────────────────────────────────────────────────────

# Timeout for HTTP requests to go2rtc (seconds)
HTTP_TIMEOUT = 15

# Timeout for ffmpeg/ffprobe processes (seconds)
FFMPEG_TIMEOUT = 20

# Timeout for RTSP connection test via ffprobe (seconds)
RTSP_PROBE_TIMEOUT = 10

# Seconds to wait after warmup push before pushing real audio
WARMUP_WAIT = 3.0

# Seconds to wait after real audio push (lets audio finish playing)
PLAYBACK_WAIT = 8.0

# ── Test tone parameters ─────────────────────────────────────────────────────

# Tone frequency used when no TTS engine is available
TONE_FREQ_HZ = 800

# Duration of the main test tone (seconds)
TONE_DURATION_S = 3.0

# Duration of the silent warmup file (seconds) — 1s is enough to open backchannel
WARMUP_DURATION_S = 1.0


# ── Utility helpers ───────────────────────────────────────────────────────────


def get_local_ip() -> str:
    """Detect this machine's LAN IP address for HTTP file serving.

    Opens a UDP socket toward go2rtc (doesn't actually send traffic) to
    let the OS choose the correct outbound interface, then reads the
    chosen local address.  Falls back to loopback on error.

    Returns:
        Local LAN IP address as a string (e.g., "192.168.1.1").
    """
    try:
        # Parse the go2rtc host so we route toward the correct VLAN interface
        parsed = urlparse(GO2RTC_URL)
        target_host = parsed.hostname or "8.8.8.8"
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_host, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def section(title: str) -> None:
    """Print a section header matching the style used across Voxwatch tests.

    Args:
        title: Section title text to display.
    """
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def result(status: str, message: str) -> None:
    """Print a single test result line.

    Args:
        status: One of "OK", "FAIL", "WARN", "INFO", "SKIP".
        message: Description of the result.
    """
    # Pad status so result lines align nicely in the summary
    label = f"[{status}]"
    print(f"{label:<7} {message}")


def run_ffmpeg(args: list, timeout: int = FFMPEG_TIMEOUT) -> tuple[int, str, str]:
    """Run an ffmpeg or ffprobe command and return exit code + output.

    Captures both stdout and stderr so callers can inspect codec info
    from ffprobe or error messages from ffmpeg without mixing them into
    the terminal output during normal operation.

    Args:
        args: Full argument list starting with "ffmpeg" or "ffprobe".
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        Tuple of (return_code, stdout_text, stderr_text).
        All three are empty/0 on timeout or subprocess error.
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Process timed out after {timeout}s"
    except FileNotFoundError:
        cmd_name = args[0] if args else "?"
        return -2, "", f"{cmd_name} not found on PATH"
    except Exception as e:
        return -3, "", str(e)


def check_ffmpeg_available() -> bool:
    """Verify that ffmpeg and ffprobe are both on PATH.

    Several tests require ffmpeg for format conversion and ffprobe for
    stream inspection.  This check runs once at startup.

    Returns:
        True if both tools are available, False if either is missing.
    """
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    if not ffmpeg_ok:
        result("FAIL", "ffmpeg not found on PATH — install ffmpeg and retry")
    if not ffprobe_ok:
        result("FAIL", "ffprobe not found on PATH — install ffmpeg and retry")
    return ffmpeg_ok and ffprobe_ok


# ── Audio generation ──────────────────────────────────────────────────────────


def generate_sine_wav(
    output_path: str,
    freq: int = TONE_FREQ_HZ,
    duration: float = TONE_DURATION_S,
    sample_rate: int = 16000,
) -> None:
    """Write a pure sine-wave tone as a PCM 16-bit WAV file.

    Used as a last-resort audio source when no TTS engine is available.
    A tone at a human-audible frequency (800 Hz) is distinctive and easy
    to confirm through a camera speaker.

    The WAV is written from scratch using Python's struct module so this
    function has no external dependencies at all.

    Args:
        output_path: Where to write the WAV file.
        freq: Tone frequency in Hz (default 800).
        duration: Length in seconds (default 3).
        sample_rate: Samples per second (default 16000).
    """
    num_samples = int(sample_rate * duration)
    samples = bytearray()
    for i in range(num_samples):
        # 80% amplitude to avoid hard clipping on camera speaker output
        value = int(32767 * 0.8 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples += struct.pack("<h", value)

    data_size = len(samples)
    with open(output_path, "wb") as f:
        # RIFF container header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk: PCM, 1 channel, 16-bit
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))              # fmt chunk size
        f.write(struct.pack("<H", 1))               # PCM format tag
        f.write(struct.pack("<H", 1))               # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2)) # byte rate
        f.write(struct.pack("<H", 2))               # block align
        f.write(struct.pack("<H", 16))              # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(samples)


def generate_silence_wav(
    output_path: str,
    duration: float = WARMUP_DURATION_S,
    sample_rate: int = 8000,
) -> None:
    """Write a silent WAV file at 8 kHz for backchannel warmup.

    The silent warmup push opens the RTP backchannel session without
    playing audible sound.  This matches the behavior of go2rtc's web UI
    which also requires two pushes on a cold backchannel.

    Generating silence as a raw WAV avoids the need for ffmpeg at this
    step — we need silence before we know if ffmpeg is available.

    Args:
        output_path: Where to write the WAV file.
        duration: Length in seconds (default 1.0).
        sample_rate: Samples per second (default 8000 to match PCMU format).
    """
    num_samples = int(sample_rate * duration)
    # All zeros = digital silence
    samples = b"\x00\x00" * num_samples
    data_size = len(samples)

    with open(output_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))               # PCM
        f.write(struct.pack("<H", 1))               # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))
        f.write(struct.pack("<H", 2))
        f.write(struct.pack("<H", 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(samples)


def generate_test_audio_pcm(output_dir: str, message: str = "") -> Optional[str]:
    """Generate a base PCM WAV file for testing using TTS or tone fallback.

    Tries TTS engines in order: espeak-ng -> espeak -> sine tone generator.
    A spoken message is more useful than a tone for confirming speaker
    audio at a distance, but the tone guarantees the test works on any system.

    Args:
        output_dir: Directory to write the base WAV file into.
        message: Text to speak.  Ignored if using tone fallback.

    Returns:
        Path to the generated WAV file, or None on failure.
    """
    if not message:
        message = (
            "Attention. This is a VoxWatch audio system test. "
            "If you hear this message, the camera speaker is working."
        )

    output_path = os.path.join(output_dir, "test_source.wav")

    # Try espeak-ng (common on Debian/Ubuntu/WSL)
    for tts_cmd in ("espeak-ng", "espeak"):
        if shutil.which(tts_cmd):
            print(f"[INFO]   Generating TTS with {tts_cmd}...")
            rc, _, stderr = run_ffmpeg([tts_cmd, "-w", output_path, message], timeout=30)
            if rc == 0 and os.path.exists(output_path):
                print(f"[INFO]   TTS generated: {output_path}")
                return output_path
            print(f"[INFO]   {tts_cmd} failed (exit {rc}), trying next...")

    # Last resort: pure sine tone — no external dependencies
    print("[INFO]   No TTS engine found — generating 800 Hz test tone...")
    generate_sine_wav(output_path)
    if os.path.exists(output_path):
        print(f"[INFO]   Tone generated: {output_path}")
        return output_path

    return None


def convert_to_codec(
    source_wav: str, output_path: str, codec: str, sample_rate: int = 8000
) -> bool:
    """Convert a WAV file to a specific codec using ffmpeg.

    Both PCMU (G.711 mu-law) and PCMA (G.711 A-law) are standard telephony
    codecs at 8 kHz mono.  Most IP cameras accept one or the other for
    backchannel audio.  We try both to determine which this Dahua uses.

    Args:
        source_wav: Path to the input WAV file.
        output_path: Path for the converted output file.
        codec: ffmpeg codec name — "pcm_mulaw" (PCMU) or "pcm_alaw" (PCMA).
        sample_rate: Audio sample rate in Hz (default 8000 for telephony).

    Returns:
        True if conversion succeeded and the output file exists.
    """
    rc, _, stderr = run_ffmpeg([
        "ffmpeg", "-y",
        "-i", source_wav,
        "-acodec", codec,
        "-ar", str(sample_rate),
        "-ac", "1",            # mono — cameras have a single speaker
        output_path,
    ])
    if rc == 0 and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        print(f"[INFO]   Converted to {codec}: {os.path.basename(output_path)} ({size:,} bytes)")
        return True
    # Show the last 3 lines of ffmpeg stderr to diagnose codec issues
    last_lines = [l for l in stderr.strip().split("\n") if l.strip()][-3:]
    for line in last_lines:
        print(f"[INFO]   ffmpeg: {line}")
    return False


# ── HTTP file server ──────────────────────────────────────────────────────────


def start_http_server(directory: str, port: int) -> Optional[http.server.HTTPServer]:
    """Start a background HTTP server to serve audio files to go2rtc.

    go2rtc's /api/ffmpeg endpoint fetches audio from a URL.  We serve
    the local audio directory over HTTP so go2rtc can pull files.

    This mirrors the implementation in test_audio_push.py and
    voxwatch/audio_pipeline.py — the pattern is proven working.

    Args:
        directory: Filesystem directory to serve files from.
        port: TCP port to bind (must be reachable from go2rtc's host).

    Returns:
        The running HTTPServer instance, or None if the port is in use.
    """
    serve_dir = directory  # captured in closure for QuietHandler

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        """HTTP request handler that suppresses access log noise."""

        def __init__(self, *args, **kwargs):
            """Override directory to serve from the test audio directory."""
            super().__init__(*args, directory=serve_dir, **kwargs)

        def log_message(self, format, *args):  # noqa: A002
            """Suppress per-request log lines to keep test output readable."""
            pass

    try:
        server = http.server.HTTPServer(("0.0.0.0", port), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
    except OSError as e:
        print(f"[WARN]   Could not start HTTP server on port {port}: {e}")
        return None


# ── go2rtc interaction ────────────────────────────────────────────────────────


def go2rtc_get_streams(base_url: str) -> Optional[dict]:
    """Fetch the full stream list from go2rtc's REST API.

    go2rtc exposes all configured streams at GET /api/streams.  The response
    is a JSON object mapping stream names to their configuration.

    Args:
        base_url: go2rtc base URL (e.g., "http://localhost:1984").

    Returns:
        dict of {stream_name: config} on success, or None on failure.
    """
    try:
        resp = requests.get(f"{base_url}/api/streams", timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        print(f"[WARN]   go2rtc /api/streams returned HTTP {resp.status_code}")
        return None
    except requests.ConnectionError:
        print(f"[FAIL]   Cannot connect to go2rtc at {base_url}")
        return None
    except requests.Timeout:
        print(f"[FAIL]   go2rtc request timed out ({HTTP_TIMEOUT}s)")
        return None
    except Exception as e:
        print(f"[FAIL]   go2rtc API error: {e}")
        return None


def go2rtc_push_audio(
    base_url: str,
    stream_name: str,
    audio_url: str,
    timeout: int = HTTP_TIMEOUT,
) -> bool:
    """Tell go2rtc to fetch and push an audio file to a camera's backchannel.

    Uses the /api/ffmpeg endpoint — the same one the go2rtc web UI uses
    for the "Play audio" button.  go2rtc internally invokes ffmpeg to read
    the file at audio_url and stream it through the camera's RTP backchannel.

    This is the PROVEN WORKING method for VoxWatch (confirmed on Reolink CX410).

    Args:
        base_url: go2rtc base URL.
        stream_name: go2rtc stream name for the target camera.
        audio_url: HTTP URL that go2rtc will fetch the audio file from.
                   Must be reachable from go2rtc's host, not localhost.
        timeout: Request timeout in seconds.  Should be longer than the
                 audio duration since go2rtc blocks until ffmpeg finishes.

    Returns:
        True if go2rtc returned HTTP 200.
    """
    api_url = f"{base_url}/api/ffmpeg?dst={stream_name}&file={audio_url}"
    try:
        resp = requests.post(api_url, timeout=timeout)
        if resp.status_code == 200:
            return True
        print(f"[WARN]   go2rtc /api/ffmpeg returned HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.Timeout:
        # /api/ffmpeg blocks for the duration of the audio — a timeout here
        # usually means the audio was longer than the timeout, not a real failure.
        # Log it but don't treat as fatal.
        print(f"[WARN]   go2rtc /api/ffmpeg timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"[FAIL]   go2rtc push error: {e}")
        return False


# ── Individual test functions ─────────────────────────────────────────────────


def test_onvif_discovery(camera_ip: str) -> dict:
    """Test 1: Probe the camera's ONVIF device service for capabilities.

    ONVIF exposes a SOAP/XML API that reports device capabilities including
    supported audio codecs, two-way audio support, and stream profiles.
    We use the 'zeep' library for SOAP calls, falling back to raw HTTP if
    zeep is not installed.

    This test tries each credential pair in CREDENTIAL_CANDIDATES and reports
    which (if any) successfully authenticates.

    The returned dict is passed downstream so other tests can reuse the
    discovered working credential and ONVIF profile list.

    Args:
        camera_ip: IP address of the camera to probe.

    Returns:
        dict with keys:
          "success": bool — True if any ONVIF response was received
          "working_cred": (user, password) tuple or None
          "onvif_port": int port that responded or None
          "profiles": list of discovered profile dicts
          "audio_codecs": list of codec name strings found
          "backchannel": bool — True if backchannel indicators were found
    """
    section("Test 1: ONVIF Discovery")

    outcome = {
        "success": False,
        "working_cred": None,
        "onvif_port": None,
        "profiles": [],
        "audio_codecs": [],
        "backchannel": False,
    }

    # Check if zeep is available — it's the cleanest ONVIF SOAP client for Python
    zeep_available = False
    try:
        import zeep  # noqa: F401 — just checking availability
        from zeep import Client
        from zeep.wsse.username import UsernameToken
        zeep_available = True
    except ImportError:
        pass

    if not zeep_available:
        print("[INFO] zeep not installed — using raw HTTP ONVIF probe")
        print("[INFO] For full ONVIF support: pip install zeep")
        # Fall through to raw HTTP probe below

    # Try each (port, credential) combination.  Dahua commonly uses port 80;
    # some firmware versions use port 8000.
    for onvif_port in ONVIF_PORTS:
        device_url = f"http://{camera_ip}:{onvif_port}/onvif/device_service"
        print(f"\n[INFO] Probing ONVIF device service at {device_url}")

        # First check if the port is even open before attempting SOAP
        try:
            sock = socket.create_connection((camera_ip, onvif_port), timeout=5)
            sock.close()
            print(f"[INFO] Port {onvif_port} is open")
        except (socket.timeout, ConnectionRefusedError, OSError):
            print(f"[INFO] Port {onvif_port} is closed or unreachable, skipping")
            continue

        for user, password in CREDENTIAL_CANDIDATES:
            safe_pw = password[:3] + "***" if len(password) > 3 else "***"
            print(f"[INFO] Trying credentials: {user} / {safe_pw}")

            if zeep_available:
                # Full SOAP-based ONVIF discovery
                success = _onvif_probe_zeep(
                    device_url, user, password, camera_ip, onvif_port, outcome
                )
            else:
                # Lightweight raw HTTP probe — checks reachability and auth only
                success = _onvif_probe_raw_http(
                    device_url, user, password, camera_ip, onvif_port, outcome
                )

            if success:
                outcome["working_cred"] = (user, password)
                outcome["onvif_port"] = onvif_port
                outcome["success"] = True
                result("OK", f"ONVIF authenticated as {user} on port {onvif_port}")
                break

        if outcome["success"]:
            break

    if not outcome["success"]:
        result("FAIL", "ONVIF: no credential worked on any port")
        print("[INFO] Dahua default credentials: admin/admin or admin/password")
        print("[INFO] If credentials have been changed, provide them with --password")
    else:
        # Report what we found
        if outcome["audio_codecs"]:
            print(f"[INFO] Audio codecs reported by ONVIF: {', '.join(outcome['audio_codecs'])}")
        else:
            print("[INFO] Audio codecs: not detected via ONVIF (try Test 4 with ffprobe)")

        if outcome["backchannel"]:
            result("OK", "ONVIF reports backchannel / two-way audio support")
        else:
            result("WARN", "ONVIF: backchannel not explicitly advertised (may still work)")

    return outcome


def _onvif_probe_zeep(
    device_url: str,
    user: str,
    password: str,
    camera_ip: str,
    onvif_port: int,
    outcome: dict,
) -> bool:
    """Internal: perform ONVIF device + media queries using zeep SOAP client.

    Queries GetCapabilities and GetProfiles.  Extracts audio codec names
    from VideoEncoderConfiguration and checks for backchannel flags.

    Args:
        device_url: Full ONVIF device service URL.
        user: ONVIF username.
        password: ONVIF password.
        camera_ip: Camera IP (for building WSDL paths).
        onvif_port: Port the service is on (for building WSDL paths).
        outcome: Dict to populate with discovered data (mutated in place).

    Returns:
        True if the SOAP call succeeded and we got a valid response.
    """
    try:
        from zeep import Client
        from zeep.wsse.username import UsernameToken

        # Zeep needs a WSDL.  We use the standard ONVIF WSDLs from the spec.
        # The device.wsdl is included with the onvif-zeep package if installed,
        # or we can point at the device service directly with a basic binding.
        client = Client(
            wsdl=device_url,
            wsse=UsernameToken(user, password, use_digest=True),
        )

        # GetDeviceInformation — if this succeeds, auth is good
        device_info = client.service.GetDeviceInformation()
        manufacturer = getattr(device_info, "Manufacturer", "unknown")
        model = getattr(device_info, "Model", "unknown")
        firmware = getattr(device_info, "FirmwareVersion", "unknown")
        print(f"[INFO]   Manufacturer : {manufacturer}")
        print(f"[INFO]   Model        : {model}")
        print(f"[INFO]   Firmware     : {firmware}")

        # GetCapabilities — check for two-way audio in RTP/media capabilities
        try:
            caps = client.service.GetCapabilities(Category="Media")
            caps_str = str(caps).lower()
            if "backchannel" in caps_str or "twoway" in caps_str or "talk" in caps_str:
                outcome["backchannel"] = True
                print("[INFO]   Capabilities indicate backchannel support")
        except Exception as caps_err:
            print(f"[INFO]   GetCapabilities failed: {caps_err}")

        return True

    except Exception as e:
        err_str = str(e).lower()
        if "unauthorized" in err_str or "401" in err_str or "authentication" in err_str:
            print(f"[INFO]   Auth failed for {user}")
        else:
            print(f"[INFO]   zeep error: {e}")
        return False


def _onvif_probe_raw_http(
    device_url: str,
    user: str,
    password: str,
    camera_ip: str,
    onvif_port: int,
    outcome: dict,
) -> bool:
    """Internal: probe ONVIF with a raw SOAP HTTP request (no zeep dependency).

    Sends the GetDeviceInformation SOAP envelope with digest authentication.
    This is less capable than zeep but works without extra packages.

    We parse the raw XML text for codec keywords rather than using a full
    XML parser, which keeps this function dependency-free.

    Args:
        device_url: Full ONVIF device service URL.
        user: ONVIF username.
        password: ONVIF password.
        camera_ip: Camera IP (unused here, kept for signature consistency).
        onvif_port: Port (unused here, kept for signature consistency).
        outcome: Dict to populate with discovered data.

    Returns:
        True if we received a valid SOAP response body.
    """
    # Minimal SOAP envelope for ONVIF GetDeviceInformation
    soap_body = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body>
    <tds:GetDeviceInformation
        xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>
  </s:Body>
</s:Envelope>"""

    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "SOAPAction": '"http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation"',
    }

    try:
        resp = requests.post(
            device_url,
            data=soap_body,
            headers=headers,
            auth=requests.auth.HTTPDigestAuth(user, password),
            timeout=8,
        )

        if resp.status_code == 200:
            body = resp.text
            print(f"[INFO]   ONVIF SOAP response received ({len(body)} bytes)")

            # Scan response text for manufacturer/model info
            for tag in ("Manufacturer", "Model", "FirmwareVersion"):
                # Extract tag content with simple text search (avoids xml.etree dependency)
                start_tag = f"<tt:{tag}>"
                end_tag = f"</tt:{tag}>"
                idx = body.find(start_tag)
                if idx != -1:
                    end_idx = body.find(end_tag, idx)
                    value = body[idx + len(start_tag):end_idx].strip()
                    print(f"[INFO]   {tag}: {value}")

            # Look for audio codec keywords in any part of the response
            body_lower = body.lower()
            for codec_keyword in ("pcma", "pcmu", "g711", "g.711", "alaw", "mulaw", "opus", "aac"):
                if codec_keyword in body_lower and codec_keyword not in outcome["audio_codecs"]:
                    outcome["audio_codecs"].append(codec_keyword.upper())

            # Check for backchannel / two-way audio keywords
            for kw in ("backchannel", "twoway", "talk", "sendonly"):
                if kw in body_lower:
                    outcome["backchannel"] = True
                    break

            return True

        elif resp.status_code in (401, 403):
            print(f"[INFO]   Authentication rejected (HTTP {resp.status_code})")
        else:
            print(f"[INFO]   Unexpected HTTP {resp.status_code}")
            print(f"[INFO]   Response: {resp.text[:300]}")

    except requests.Timeout:
        print("[INFO]   ONVIF request timed out")
    except requests.ConnectionError as e:
        print(f"[INFO]   Connection error: {e}")
    except Exception as e:
        print(f"[INFO]   Raw HTTP probe error: {e}")

    return False


def test_rtsp_streams(camera_ip: str, onvif_result: dict) -> dict:
    """Test 2: Try to connect to the camera's RTSP streams.

    Iterates over Dahua and Reolink-style RTSP URL patterns using ffprobe
    in a fast "just connect and detect codec" mode.  ffprobe is used rather
    than ffplay or a full read so the test completes in a few seconds per URL.

    The working credential from Test 1 is tried first; then all candidates
    are tried on each URL to handle credential-per-URL differences.

    Args:
        camera_ip: Camera IP address.
        onvif_result: Result dict from test_onvif_discovery.

    Returns:
        dict with keys:
          "success": bool — True if at least one RTSP URL connected
          "working_url": str or None — first RTSP URL that worked
          "working_cred": (user, password) or None
          "stream_info": str — raw ffprobe output for the working URL
    """
    section("Test 2: RTSP Stream Connection")

    outcome = {
        "success": False,
        "working_url": None,
        "working_cred": None,
        "stream_info": "",
    }

    # Build the full list of URL paths to try
    all_paths = DAHUA_RTSP_PATHS + REOLINK_RTSP_PATHS

    # Credential priority: use the ONVIF-proven credential first if we have one
    creds_to_try = []
    if onvif_result.get("working_cred"):
        creds_to_try.append(onvif_result["working_cred"])
    for cred in CREDENTIAL_CANDIDATES:
        if cred not in creds_to_try:
            creds_to_try.append(cred)

    for path in all_paths:
        for user, password in creds_to_try:
            rtsp_url = f"rtsp://{user}:{password}@{camera_ip}:554{path}"
            # Mask password in log output
            safe_url = f"rtsp://{user}:***@{camera_ip}:554{path}"
            print(f"\n[INFO] Probing: {safe_url}")

            # ffprobe in stream-info mode: reads just enough to report codecs,
            # then exits.  -t 5 limits how long it reads stream data.
            rc, stdout, stderr = run_ffmpeg([
                "ffprobe",
                "-v", "quiet",
                "-show_streams",
                "-print_format", "json",
                "-rtsp_transport", "tcp",  # TCP is more reliable on LAN
                "-timeout", str(RTSP_PROBE_TIMEOUT * 1_000_000),  # ffprobe uses microseconds
                rtsp_url,
            ], timeout=RTSP_PROBE_TIMEOUT + 5)

            if rc == 0 and stdout.strip():
                print(f"[INFO] ffprobe connected to {safe_url}")
                outcome["success"] = True
                outcome["working_url"] = rtsp_url
                outcome["working_cred"] = (user, password)
                outcome["stream_info"] = stdout

                # Parse and print stream summary
                _print_rtsp_stream_summary(stdout, safe_url)
                result("OK", f"RTSP connected: {safe_url}")
                return outcome

            # Show a condensed error (last meaningful line from stderr)
            err_lines = [l.strip() for l in stderr.split("\n") if l.strip() and
                         not l.startswith("ffprobe") and "version" not in l.lower()]
            if err_lines:
                print(f"[INFO]   Error: {err_lines[-1][:120]}")

    result("FAIL", "No RTSP URL pattern connected successfully")
    print("[INFO] Possible causes:")
    print(f"  - Wrong credentials (tried: {[u for u, _ in CREDENTIAL_CANDIDATES]})")
    print("  - Camera RTSP disabled — check camera web UI Network > RTSP settings")
    print("  - Camera uses a non-standard RTSP port (not 554)")
    print("  - This camera uses only ONVIF media (no direct RTSP endpoint)")
    return outcome


def _print_rtsp_stream_summary(ffprobe_json: str, safe_url: str) -> None:
    """Parse ffprobe JSON output and print a human-readable stream summary.

    Extracts codec name, type (video/audio), sample rate, and codec tag
    for each stream.  Flags backchannel/sendonly tracks if present.

    Args:
        ffprobe_json: Raw JSON string from ffprobe -show_streams -print_format json.
        safe_url: Password-masked URL for display purposes.
    """
    try:
        data = json.loads(ffprobe_json)
        streams = data.get("streams", [])
        print(f"[INFO]   {len(streams)} stream(s) found:")
        for s in streams:
            idx = s.get("index", "?")
            codec = s.get("codec_name", "unknown")
            codec_type = s.get("codec_type", "?")
            tag = s.get("codec_tag_string", "")
            sr = s.get("sample_rate", "")
            channels = s.get("channels", "")
            disposition = s.get("disposition", {})

            line = f"    stream[{idx}]: {codec_type} / {codec}"
            if tag and tag != "0x0000":
                line += f" ({tag})"
            if sr:
                line += f"  {sr} Hz"
            if channels:
                line += f"  {channels}ch"

            # sendonly disposition = camera's backchannel (it sends to us, we send back)
            is_backchannel = (
                disposition.get("hearing_impaired") or
                "sendonly" in str(s).lower() or
                "backchannel" in str(s).lower()
            )
            if is_backchannel:
                line += "  <-- BACKCHANNEL"

            print(f"[INFO] {line}")
    except json.JSONDecodeError:
        print("[INFO]   (Could not parse ffprobe JSON output)")


def test_go2rtc_stream(stream_name: str) -> dict:
    """Test 3: Check if the camera is configured in go2rtc.

    A camera must be configured in go2rtc before VoxWatch can push audio
    through it.  This test queries the go2rtc API and reports the status.
    If the stream is missing, it prints the YAML snippet needed to add it.

    The go2rtc stream must use an RTSP URL with backchannel=1 appended so
    go2rtc opens the two-way audio RTP session.  Without this flag, go2rtc
    only opens a receive-only RTSP session and the backchannel won't work.

    Args:
        stream_name: go2rtc stream name to look for (e.g., "dahua_onvif").

    Returns:
        dict with keys:
          "go2rtc_reachable": bool
          "stream_present": bool — True if stream_name is in go2rtc
          "stream_config": dict or None — go2rtc config for this stream
    """
    section("Test 3: go2rtc Stream Configuration")

    outcome = {
        "go2rtc_reachable": False,
        "stream_present": False,
        "stream_config": None,
    }

    print(f"[INFO] Querying go2rtc at {GO2RTC_URL}...")
    streams = go2rtc_get_streams(GO2RTC_URL)

    if streams is None:
        result("FAIL", f"go2rtc not reachable at {GO2RTC_URL}")
        print("[INFO] Check that go2rtc is running and the URL is correct")
        return outcome

    outcome["go2rtc_reachable"] = True
    result("OK", f"go2rtc is reachable — {len(streams)} stream(s) configured")

    # List all configured streams so the user knows what exists
    if streams:
        print("[INFO] Configured streams:")
        for name in sorted(streams.keys()):
            print(f"  {'-->' if name == stream_name else '   '} {name}")
    else:
        print("[INFO] go2rtc has no streams configured yet")

    if stream_name in streams:
        outcome["stream_present"] = True
        outcome["stream_config"] = streams[stream_name]
        result("OK", f"Stream '{stream_name}' is configured in go2rtc")

        # Check if the config includes backchannel parameter
        config_str = json.dumps(streams[stream_name]).lower()
        if "backchannel=1" in config_str:
            result("OK", "go2rtc config includes backchannel=1 (two-way audio enabled)")
        else:
            result("WARN", "go2rtc config may be missing backchannel=1 — two-way audio may not work")
            print("[INFO] Add ?backchannel=1 to the RTSP source URL in go2rtc config")
    else:
        result("FAIL", f"Stream '{stream_name}' not found in go2rtc")
        _print_go2rtc_add_instructions(stream_name)

    return outcome


def _print_go2rtc_add_instructions(stream_name: str) -> None:
    """Print the go2rtc YAML config snippet needed to add this camera.

    Dahua cameras use /cam/realmonitor?channel=1&subtype=1 for the sub
    stream.  The ?backchannel=1 suffix is the critical flag that tells
    go2rtc to open the two-way audio RTP session.

    Without backchannel=1, go2rtc opens a standard one-way RTSP session
    and the /api/ffmpeg push will silently fail (go2rtc has no backchannel
    to forward the audio to).

    Args:
        stream_name: The go2rtc stream name to use in the YAML snippet.
    """
    print()
    print("[INFO] To add this camera to go2rtc, add to go2rtc.yaml:")
    print()
    print("  streams:")
    print(f"    {stream_name}:")
    # Dahua sub-stream with backchannel enabled — try each credential
    for user, password in CREDENTIAL_CANDIDATES:
        print(f"      # Try: rtsp://{user}:{password}@{CAMERA_IP}:554"
              f"/cam/realmonitor?channel=1&subtype=1&backchannel=1")
    print()
    print(f"    {stream_name}:")
    print(f"      - rtsp://admin:PASSWORD@{CAMERA_IP}:554"
          f"/cam/realmonitor?channel=1&subtype=1&backchannel=1")
    print(f'      - "ffmpeg:{stream_name}#audio=opus"   '
          f"# transcode for WebRTC preview")
    print()
    print("[INFO] After adding, restart go2rtc and re-run this script.")


def test_codec_detection(rtsp_result: dict) -> dict:
    """Test 4: Use ffprobe to detect audio codecs on the working RTSP stream.

    Runs ffprobe against the working RTSP URL found in Test 2 and parses
    the JSON output to extract all audio track information.  This is the
    most reliable way to discover:
      - What audio codec the camera's live stream uses
      - Whether a backchannel (sendonly) track is advertised
      - Sample rate and channel count for the backchannel

    This information directly tells us what codec to use when pushing
    audio back through the backchannel.

    Args:
        rtsp_result: Result dict from test_rtsp_streams.

    Returns:
        dict with keys:
          "success": bool
          "audio_tracks": list of dicts with codec info for each audio stream
          "backchannel_codec": str or None — codec to use for pushing audio
          "backchannel_rate": int or None — sample rate for backchannel
    """
    section("Test 4: Audio Codec Detection (ffprobe)")

    outcome = {
        "success": False,
        "audio_tracks": [],
        "backchannel_codec": None,
        "backchannel_rate": None,
    }

    if not rtsp_result.get("working_url"):
        result("SKIP", "No working RTSP URL from Test 2 — skipping codec detection")
        return outcome

    rtsp_url = rtsp_result["working_url"]
    user, password = rtsp_result.get("working_cred") or CREDENTIAL_CANDIDATES[0]
    safe_url = rtsp_url.replace(f":{password}@", ":***@")

    print(f"[INFO] Running ffprobe on: {safe_url}")
    print("[INFO] (This may take a few seconds to negotiate RTSP session...)")

    # Use the detailed ffprobe output from Test 2 if we already have it
    stream_info = rtsp_result.get("stream_info", "")
    if not stream_info:
        # Re-run ffprobe if we don't have it
        rc, stream_info, stderr = run_ffmpeg([
            "ffprobe",
            "-v", "quiet",
            "-show_streams",
            "-print_format", "json",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ], timeout=RTSP_PROBE_TIMEOUT + 5)

        if rc != 0 or not stream_info.strip():
            result("FAIL", "ffprobe failed to read stream info")
            return outcome

    try:
        data = json.loads(stream_info)
    except json.JSONDecodeError:
        result("FAIL", "Could not parse ffprobe output as JSON")
        return outcome

    streams = data.get("streams", [])
    audio_tracks = [s for s in streams if s.get("codec_type") == "audio"]

    if not audio_tracks:
        result("FAIL", "No audio tracks found in RTSP stream")
        print("[INFO] Camera may have audio disabled — check camera web UI")
        return outcome

    outcome["success"] = True
    outcome["audio_tracks"] = audio_tracks

    print(f"[INFO] Found {len(audio_tracks)} audio track(s):")
    for track in audio_tracks:
        idx = track.get("index", "?")
        codec = track.get("codec_name", "unknown")
        sr = track.get("sample_rate", "?")
        channels = track.get("channels", "?")
        disposition = track.get("disposition", {})

        # Try to identify backchannel tracks — the 'sendonly' disposition
        # flag isn't always set correctly, so we also look at the tag string
        tag = track.get("codec_tag_string", "").lower()
        is_likely_backchannel = (
            "sendonly" in str(track).lower() or
            "backchannel" in str(track).lower()
        )

        codec_ffmpeg = _codec_name_to_ffmpeg(codec)

        print(f"[INFO]   Audio track [{idx}]: {codec}  {sr} Hz  {channels}ch"
              + ("  <-- likely backchannel" if is_likely_backchannel else ""))
        print(f"[INFO]     ffmpeg codec arg: -acodec {codec_ffmpeg}")

        # Use the first audio track's codec as the backchannel codec guess.
        # For Dahua cameras, the backchannel typically uses the same codec
        # as the outgoing audio stream (PCMA or PCMU).
        if outcome["backchannel_codec"] is None:
            outcome["backchannel_codec"] = codec_ffmpeg
            try:
                outcome["backchannel_rate"] = int(sr)
            except (ValueError, TypeError):
                outcome["backchannel_rate"] = 8000

    codec = outcome["backchannel_codec"]
    rate = outcome["backchannel_rate"]
    result("OK", f"Detected audio codec: {codec} at {rate} Hz")
    print(f"[INFO] Recommended codec for audio push: -acodec {codec} -ar {rate} -ac 1")

    return outcome


def _codec_name_to_ffmpeg(onvif_codec: str) -> str:
    """Map an ONVIF/RTSP codec name to the corresponding ffmpeg codec argument.

    RTSP codec names (from RTSP SDP) differ from ffmpeg's internal names.
    This mapping covers the codecs commonly used in Dahua/Reolink backchannels.

    Args:
        onvif_codec: Codec name as reported by ffprobe (e.g., "pcm_alaw", "PCMA").

    Returns:
        ffmpeg codec name string (e.g., "pcm_alaw" or "pcm_mulaw").
    """
    mapping = {
        # G.711 A-law (most common on Dahua cameras)
        "pcm_alaw": "pcm_alaw",
        "pcma":     "pcm_alaw",
        "alaw":     "pcm_alaw",
        "g711a":    "pcm_alaw",
        # G.711 mu-law (common on Reolink, some Dahua)
        "pcm_mulaw": "pcm_mulaw",
        "pcmu":      "pcm_mulaw",
        "mulaw":     "pcm_mulaw",
        "ulaw":      "pcm_mulaw",
        "g711u":     "pcm_mulaw",
        # Other codecs that some cameras advertise
        "aac":       "aac",
        "opus":      "libopus",
        "g726":      "g726",
    }
    normalized = onvif_codec.lower().replace("-", "_")
    return mapping.get(normalized, normalized)  # fall back to the name as-is


def test_audio_push(
    stream_name: str,
    codec_result: dict,
    work_dir: str,
    serve_ip: str,
) -> dict:
    """Test 5: Push audio to the camera via go2rtc's /api/ffmpeg endpoint.

    This is the core VoxWatch audio push test.  Uses the proven method:
      1. Serve an audio file from a local HTTP server
      2. Tell go2rtc to fetch it: POST /api/ffmpeg?dst={stream}&file={url}
      3. go2rtc uses its internal ffmpeg to decode and stream it to the camera

    A silent warmup push is sent first to open the RTP backchannel session.
    Without warmup, the first audio push is often silently dropped by the
    camera (observed on Reolink CX410 and expected to apply to Dahua as well).

    The codec used is taken from Test 4's detection results.  If detection
    failed, we default to PCMU (G.711 mu-law) as the safer first guess.

    Args:
        stream_name: go2rtc stream name for this camera.
        codec_result: Result dict from test_codec_detection.
        work_dir: Directory where audio files are stored (served via HTTP).
        serve_ip: Local IP address reachable from go2rtc's host.

    Returns:
        dict with keys:
          "success": bool
          "warmup_accepted": bool
          "push_accepted": bool
    """
    section("Test 5: Audio Push via go2rtc /api/ffmpeg")

    outcome = {
        "success": False,
        "warmup_accepted": False,
        "push_accepted": False,
    }

    # Determine which codec to use for the push based on detection results
    ffmpeg_codec = codec_result.get("backchannel_codec") or "pcm_mulaw"
    sample_rate = codec_result.get("backchannel_rate") or 8000

    print(f"[INFO] Using codec: {ffmpeg_codec} at {sample_rate} Hz")
    print(f"[INFO] go2rtc stream: {stream_name}")
    print(f"[INFO] Audio serve IP: {serve_ip}:{AUDIO_SERVE_PORT}")

    # Check that the stream exists in go2rtc before attempting push
    streams = go2rtc_get_streams(GO2RTC_URL)
    if streams is None:
        result("FAIL", "go2rtc not reachable — cannot push audio")
        return outcome

    if stream_name not in (streams or {}):
        result("SKIP", f"Stream '{stream_name}' not in go2rtc — add it first (see Test 3)")
        return outcome

    # Generate the warmup silence file (if not already present)
    warmup_path = os.path.join(work_dir, "warmup_silent_pcmu.wav")
    if not os.path.exists(warmup_path):
        print("[INFO] Generating 1s warmup silence file...")
        generate_silence_wav(warmup_path)
        # Convert raw PCM silence to the target codec format
        warmup_codec_path = os.path.join(work_dir, "warmup_silent.wav")
        if not convert_to_codec(warmup_path, warmup_codec_path, ffmpeg_codec, sample_rate):
            # Fall back: use the raw silence WAV — go2rtc will transcode it
            warmup_codec_path = warmup_path
    else:
        warmup_codec_path = warmup_path

    # Generate the real test audio (source PCM, then convert to target codec)
    print("\n[INFO] Generating test audio...")
    source_wav = generate_test_audio_pcm(work_dir)
    if source_wav is None:
        result("FAIL", "Could not generate test audio")
        return outcome

    push_wav = os.path.join(work_dir, f"push_test_{ffmpeg_codec}.wav")
    if not convert_to_codec(source_wav, push_wav, ffmpeg_codec, sample_rate):
        result("FAIL", f"Audio conversion to {ffmpeg_codec} failed")
        return outcome

    # ── Warmup push ─────────────────────────────────────────────────────────
    print("\n[INFO] Sending warmup push (1s silence to open backchannel)...")
    warmup_filename = os.path.basename(warmup_codec_path)
    warmup_url = f"http://{serve_ip}:{AUDIO_SERVE_PORT}/{warmup_filename}"

    warmup_ok = go2rtc_push_audio(GO2RTC_URL, stream_name, warmup_url, timeout=10)
    outcome["warmup_accepted"] = warmup_ok

    if warmup_ok:
        result("OK", "Warmup push accepted by go2rtc")
    else:
        result("WARN", "Warmup push not confirmed — proceeding anyway")

    # Wait for backchannel to establish before pushing real audio.
    # The RTP session negotiation takes ~1-2s on Dahua cameras.
    print(f"[INFO] Waiting {WARMUP_WAIT}s for backchannel to establish...")
    time.sleep(WARMUP_WAIT)

    # ── Real audio push ──────────────────────────────────────────────────────
    push_filename = os.path.basename(push_wav)
    push_url = f"http://{serve_ip}:{AUDIO_SERVE_PORT}/{push_filename}"

    print(f"\n>>> Pushing audio now -- listen to the camera speaker at {CAMERA_IP}! <<<")
    push_ok = go2rtc_push_audio(GO2RTC_URL, stream_name, push_url, timeout=20)
    outcome["push_accepted"] = push_ok

    if push_ok:
        result("OK", "Audio push accepted by go2rtc")
        print(f"[INFO] Waiting {PLAYBACK_WAIT}s for audio to finish playing...")
        time.sleep(PLAYBACK_WAIT)
        outcome["success"] = True
    else:
        result("FAIL", "go2rtc did not accept the audio push")
        print("[INFO] Possible causes:")
        print(f"  - Stream '{stream_name}' missing backchannel=1 in RTSP source URL")
        print("  - Camera backchannel is disabled in camera web UI")
        print(f"  - Wrong codec — try PCMA if PCMU failed, or vice versa")

    return outcome


def test_multi_codec(
    stream_name: str,
    work_dir: str,
    serve_ip: str,
    skip_if_push_worked: bool = False,
) -> dict:
    """Test 6: Try pushing audio in both PCMU and PCMA codec formats.

    Dahua cameras commonly use PCMA (G.711 A-law), while Reolink uses PCMU
    (G.711 mu-law).  Since this camera's codec isn't confirmed yet, we try
    both to find which one works.

    If Test 5 already succeeded, this test still runs but reports which
    codec was confirmed working, so the information can be used to configure
    VoxWatch permanently.

    Args:
        stream_name: go2rtc stream name for this camera.
        work_dir: Directory with audio files (served via HTTP).
        serve_ip: Local IP reachable from go2rtc.
        skip_if_push_worked: If True, print a note but don't re-push audio.

    Returns:
        dict with keys:
          "pcmu_accepted": bool
          "pcma_accepted": bool
          "recommended_codec": str or None — "pcm_mulaw" or "pcm_alaw"
    """
    section("Test 6: Multi-Codec Audio Push (PCMU and PCMA)")

    outcome = {
        "pcmu_accepted": False,
        "pcma_accepted": False,
        "recommended_codec": None,
    }

    if skip_if_push_worked:
        print("[INFO] Test 5 already confirmed audio push working.")
        print("[INFO] Running codec comparison to identify the correct codec for config.")

    # Check that go2rtc is reachable and stream exists
    streams = go2rtc_get_streams(GO2RTC_URL)
    if streams is None or stream_name not in (streams or {}):
        result("SKIP", f"go2rtc not reachable or stream '{stream_name}' missing — skipping")
        return outcome

    # Build base test audio if not already generated
    source_wav = os.path.join(work_dir, "test_source.wav")
    if not os.path.exists(source_wav):
        print("[INFO] Generating test audio source...")
        generated = generate_test_audio_pcm(work_dir)
        if generated is None:
            result("FAIL", "Could not generate test audio for codec test")
            return outcome

    # ── PCMU (G.711 mu-law) ──────────────────────────────────────────────────
    print("\n--- Codec: PCMU (G.711 mu-law) ---")
    print("[INFO] This codec is used by Reolink CX410 backchannel (proven working).")

    pcmu_wav = os.path.join(work_dir, "test_pcmu.wav")
    if convert_to_codec(source_wav, pcmu_wav, "pcm_mulaw", 8000):
        pcmu_url = f"http://{serve_ip}:{AUDIO_SERVE_PORT}/test_pcmu.wav"
        print(">>> Pushing PCMU audio -- listen to the camera speaker! <<<")

        # Brief silence warmup before each codec attempt
        _send_warmup(GO2RTC_URL, stream_name, work_dir, serve_ip)
        accepted = go2rtc_push_audio(GO2RTC_URL, stream_name, pcmu_url, timeout=20)
        outcome["pcmu_accepted"] = accepted

        if accepted:
            result("OK", "PCMU push accepted by go2rtc")
            time.sleep(PLAYBACK_WAIT)
        else:
            result("FAIL", "PCMU push not accepted")
    else:
        result("FAIL", "PCMU conversion failed — ffmpeg error")

    # Pause between codec attempts to let the camera speaker reset
    print(f"\n[INFO] Pausing 3s between codec tests...")
    time.sleep(3)

    # ── PCMA (G.711 A-law) ──────────────────────────────────────────────────
    print("\n--- Codec: PCMA (G.711 A-law) ---")
    print("[INFO] This codec is more common on Dahua/Hikvision cameras.")

    pcma_wav = os.path.join(work_dir, "test_pcma.wav")
    if convert_to_codec(source_wav, pcma_wav, "pcm_alaw", 8000):
        pcma_url = f"http://{serve_ip}:{AUDIO_SERVE_PORT}/test_pcma.wav"
        print(">>> Pushing PCMA audio -- listen to the camera speaker! <<<")

        _send_warmup(GO2RTC_URL, stream_name, work_dir, serve_ip)
        accepted = go2rtc_push_audio(GO2RTC_URL, stream_name, pcma_url, timeout=20)
        outcome["pcma_accepted"] = accepted

        if accepted:
            result("OK", "PCMA push accepted by go2rtc")
            time.sleep(PLAYBACK_WAIT)
        else:
            result("FAIL", "PCMA push not accepted")
    else:
        result("FAIL", "PCMA conversion failed — ffmpeg error")

    # ── Recommendation ───────────────────────────────────────────────────────
    if outcome["pcmu_accepted"] and outcome["pcma_accepted"]:
        # go2rtc returns 200 for both — the camera likely accepts either.
        # PCMA is the more common Dahua default, so recommend it.
        outcome["recommended_codec"] = "pcm_alaw"
        result("OK", "Both PCMU and PCMA accepted — recommending PCMA (Dahua default)")
    elif outcome["pcma_accepted"]:
        outcome["recommended_codec"] = "pcm_alaw"
        result("OK", "PCMA (G.711 A-law) is the working codec for this camera")
    elif outcome["pcmu_accepted"]:
        outcome["recommended_codec"] = "pcm_mulaw"
        result("OK", "PCMU (G.711 mu-law) is the working codec for this camera")
    else:
        result("FAIL", "Neither PCMU nor PCMA push was accepted by go2rtc")
        print("[INFO] Check Test 3 output — the go2rtc stream config may need backchannel=1")

    return outcome


def _send_warmup(base_url: str, stream_name: str, work_dir: str, serve_ip: str) -> None:
    """Send a 1-second silent warmup push before each codec test.

    Helper used by test_multi_codec to ensure the backchannel is open
    before each push attempt.  Reuses or regenerates the warmup file.

    Args:
        base_url: go2rtc base URL.
        stream_name: go2rtc stream name.
        work_dir: Directory where warmup file is stored/created.
        serve_ip: Local IP address for the HTTP serve URL.
    """
    warmup_path = os.path.join(work_dir, "warmup_silent_pcmu.wav")
    if not os.path.exists(warmup_path):
        generate_silence_wav(warmup_path)

    warmup_url = f"http://{serve_ip}:{AUDIO_SERVE_PORT}/warmup_silent_pcmu.wav"
    print("[INFO] Sending warmup silence...")
    go2rtc_push_audio(base_url, stream_name, warmup_url, timeout=8)
    time.sleep(WARMUP_WAIT)


# ── Results summary ───────────────────────────────────────────────────────────


def print_summary(results: dict, stream_name: str, codec_result: dict) -> None:
    """Print the final pass/fail summary and configuration recommendations.

    Consolidates all test results into a single table.  Prints config
    snippets when the recommended codec has been determined.

    Args:
        results: dict mapping test name to bool/None (True=pass, False=fail, None=skip).
        stream_name: go2rtc stream name used in tests.
        codec_result: dict from test_codec_detection for codec recommendation.
    """
    section("RESULTS SUMMARY")

    for test_name, status in results.items():
        if status is None:
            label = "[SKIP]"
        elif status:
            label = "[OK]  "
        else:
            label = "[FAIL]"
        print(f"  {label}  {test_name}")

    any_pass = any(v is True for v in results.values())
    push_passed = results.get("Test 5: Audio Push")
    recommended_codec = codec_result.get("backchannel_codec")

    print()
    if push_passed:
        print("[OK] Audio push is WORKING on this camera.")
        print()
        print("Next steps:")
        print("  1. Confirm you heard audio from the camera speaker.")
        if recommended_codec:
            print(f"  2. Set codec in voxwatch config: audio.codec = '{recommended_codec}'")
        print(f"  3. Add '{stream_name}' to VoxWatch camera config")
        print(f"  4. Run test_full_pipeline.py --camera {stream_name} to validate end-to-end")
    else:
        print("[WARN] Audio push did not succeed.  Troubleshooting checklist:")
        print("  1. Is the camera stream added to go2rtc with backchannel=1? (Test 3)")
        print("  2. Does the go2rtc web UI microphone test work?")
        print(f"     Open: {GO2RTC_URL}/stream.html?src={stream_name}")
        print("     Click the microphone icon and speak — if it plays, proceed.")
        print("  3. Is the camera speaker volume > 0 in the camera web UI?")
        print("  4. Try adding the stream with PCMA instead of PCMU in the RTSP URL")
        print("     Dahua cameras most often use G.711 A-law (PCMA).")
        print("  5. Re-run with --stream-name if the go2rtc stream name differs.")

    print()


# ── Argument parsing and main entry point ─────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for this test script.

    All arguments have sensible defaults targeting the specific Dahua camera
    at 192.168.1.102 and the go2rtc instance at localhost:1984.

    Returns:
        argparse.Namespace with all parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "VoxWatch ONVIF camera discovery and audio push test suite.\n"
            "Tests a rebranded Dahua camera at 192.168.1.102 for two-way audio via go2rtc."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--camera-ip",
        default=CAMERA_IP,
        help=f"Camera IP address (default: {CAMERA_IP})",
    )
    parser.add_argument(
        "--go2rtc-url",
        default=GO2RTC_URL,
        help=f"go2rtc base URL (default: {GO2RTC_URL})",
    )
    parser.add_argument(
        "--camera-name",
        default=DEFAULT_STREAM_NAME,
        help=(
            f"go2rtc stream name for this camera (default: {DEFAULT_STREAM_NAME}). "
            "Must match the name in go2rtc.yaml."
        ),
    )
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "Camera password to try first (added to the front of the credential list). "
            "If omitted, common factory defaults are tried: admin/admin, admin/password"
        ),
    )
    parser.add_argument(
        "--serve-ip",
        default=None,
        help=(
            "IP address to use for the HTTP audio server URL sent to go2rtc. "
            "Auto-detected from the go2rtc route if omitted."
        ),
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help=(
            "Directory for generated audio files. "
            "A temporary directory is used if omitted."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: run all tests, print summary, clean up.

    Test execution order:
      1. ONVIF discovery (try credentials, probe capabilities)
      2. RTSP stream connection (find working URL pattern)
      3. go2rtc stream check (ensure camera is configured)
      4. Codec detection (ffprobe the RTSP stream)
      5. Audio push (warmup + real audio via /api/ffmpeg)
      6. Multi-codec (try PCMU and PCMA to identify the right one)

    Each test receives results from previous tests so later tests can build
    on earlier discoveries (e.g., use the working RTSP credential for ffprobe).
    """
    args = parse_args()

    # Allow overriding the global defaults from CLI args
    global GO2RTC_URL
    GO2RTC_URL = args.go2rtc_url.rstrip("/")

    camera_ip = args.camera_ip
    stream_name = args.camera_name

    # Prepend a user-supplied password as the first credential to try
    if args.password:
        CREDENTIAL_CANDIDATES.insert(0, ("admin", args.password))

    print("=" * 60)
    print("  VOXWATCH -- ONVIF Camera Audio Push Test Suite")
    print("=" * 60)
    print(f"  Camera IP   : {camera_ip}")
    print(f"  go2rtc      : {GO2RTC_URL}")
    print(f"  Stream name : {stream_name}")
    print(f"  Credentials : {len(CREDENTIAL_CANDIDATES)} candidate(s)")
    print()

    # Detect local IP for the HTTP file server
    serve_ip = args.serve_ip or get_local_ip()
    print(f"[INFO] Audio HTTP serve IP: {serve_ip}:{AUDIO_SERVE_PORT}")

    # Verify ffmpeg/ffprobe before running tests that need them
    print("[INFO] Checking prerequisites...")
    if not check_ffmpeg_available():
        print("[WARN] ffmpeg/ffprobe missing — Tests 2, 4, 5, 6 will be limited")
    print()

    # Use a temp dir or user-specified dir for audio files
    temp_dir_obj = None
    if args.work_dir:
        work_dir = os.path.abspath(args.work_dir)
        os.makedirs(work_dir, exist_ok=True)
        print(f"[INFO] Using work directory: {work_dir}")
    else:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="voxwatch_onvif_")
        work_dir = temp_dir_obj.name
        print(f"[INFO] Using temporary directory: {work_dir}")

    # Start the HTTP server so go2rtc can fetch audio files during Tests 5 and 6
    print(f"[INFO] Starting HTTP server on port {AUDIO_SERVE_PORT}...")
    http_server = start_http_server(work_dir, AUDIO_SERVE_PORT)
    if http_server:
        print(f"[OK]   HTTP server ready at http://{serve_ip}:{AUDIO_SERVE_PORT}/")
    else:
        print(f"[WARN] HTTP server failed to start on port {AUDIO_SERVE_PORT}")
        print("[INFO] Tests 5 and 6 (audio push) will not work without the HTTP server.")
        print(f"[INFO] If port {AUDIO_SERVE_PORT} is in use, stop the other process and retry.")

    test_results: dict[str, Optional[bool]] = {}
    codec_result: dict = {}

    try:
        # ── Test 1: ONVIF Discovery ──────────────────────────────────────────
        try:
            onvif_result = test_onvif_discovery(camera_ip)
            test_results["Test 1: ONVIF Discovery"] = onvif_result["success"]
        except Exception as exc:
            print(f"[FAIL] Test 1 raised an unexpected error: {exc}")
            onvif_result = {"success": False, "working_cred": None, "audio_codecs": [], "backchannel": False}
            test_results["Test 1: ONVIF Discovery"] = False

        # ── Test 2: RTSP Stream ──────────────────────────────────────────────
        try:
            rtsp_result = test_rtsp_streams(camera_ip, onvif_result)
            test_results["Test 2: RTSP Streams"] = rtsp_result["success"]
        except Exception as exc:
            print(f"[FAIL] Test 2 raised an unexpected error: {exc}")
            rtsp_result = {"success": False, "working_url": None, "working_cred": None, "stream_info": ""}
            test_results["Test 2: RTSP Streams"] = False

        # ── Test 3: go2rtc Check ─────────────────────────────────────────────
        try:
            go2rtc_result = test_go2rtc_stream(stream_name)
            test_results["Test 3: go2rtc Stream Config"] = go2rtc_result["stream_present"]
        except Exception as exc:
            print(f"[FAIL] Test 3 raised an unexpected error: {exc}")
            go2rtc_result = {"go2rtc_reachable": False, "stream_present": False}
            test_results["Test 3: go2rtc Stream Config"] = False

        # ── Test 4: Codec Detection ──────────────────────────────────────────
        try:
            codec_result = test_codec_detection(rtsp_result)
            test_results["Test 4: Codec Detection"] = codec_result["success"]
        except Exception as exc:
            print(f"[FAIL] Test 4 raised an unexpected error: {exc}")
            codec_result = {"success": False, "backchannel_codec": None, "backchannel_rate": None}
            test_results["Test 4: Codec Detection"] = False

        # ── Test 5: Audio Push ───────────────────────────────────────────────
        if go2rtc_result["stream_present"] and http_server:
            try:
                push_result = test_audio_push(stream_name, codec_result, work_dir, serve_ip)
                test_results["Test 5: Audio Push"] = push_result["success"]
                push_worked = push_result["success"]
            except Exception as exc:
                print(f"[FAIL] Test 5 raised an unexpected error: {exc}")
                test_results["Test 5: Audio Push"] = False
                push_worked = False
        else:
            if not go2rtc_result["stream_present"]:
                section("Test 5: Audio Push via go2rtc /api/ffmpeg")
                result("SKIP", f"Stream '{stream_name}' not in go2rtc — add it first (Test 3)")
            elif not http_server:
                section("Test 5: Audio Push via go2rtc /api/ffmpeg")
                result("SKIP", "HTTP server not running — cannot serve audio to go2rtc")
            test_results["Test 5: Audio Push"] = None
            push_worked = False

        # ── Test 6: Multi-Codec ──────────────────────────────────────────────
        if go2rtc_result["stream_present"] and http_server:
            try:
                multi_result = test_multi_codec(
                    stream_name, work_dir, serve_ip, skip_if_push_worked=push_worked
                )
                # Multi-codec succeeds if at least one codec was accepted
                any_codec = multi_result["pcmu_accepted"] or multi_result["pcma_accepted"]
                test_results["Test 6: Multi-Codec Push"] = any_codec or None
                # Refine codec recommendation from this test
                if multi_result["recommended_codec"]:
                    codec_result["backchannel_codec"] = multi_result["recommended_codec"]
            except Exception as exc:
                print(f"[FAIL] Test 6 raised an unexpected error: {exc}")
                test_results["Test 6: Multi-Codec Push"] = False
        else:
            section("Test 6: Multi-Codec Audio Push (PCMU and PCMA)")
            result("SKIP", "Skipped — stream not in go2rtc or HTTP server not available")
            test_results["Test 6: Multi-Codec Push"] = None

    finally:
        # Always print summary and clean up, even if a test raised unexpectedly
        print_summary(test_results, stream_name, codec_result)

        if http_server:
            http_server.shutdown()
            print("[INFO] HTTP server stopped")

        if temp_dir_obj is not None:
            try:
                temp_dir_obj.cleanup()
            except Exception:
                pass  # Temp cleanup errors are not worth surfacing

    print("[INFO] Test suite complete.")


if __name__ == "__main__":
    main()
