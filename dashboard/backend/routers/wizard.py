"""
wizard.py — Camera Setup Wizard API Router

Endpoints:
    POST /api/wizard/detect       — Probe a camera's go2rtc stream and return
                                    backchannel capabilities, codecs, and Frigate stats.
    POST /api/wizard/test-audio   — Generate and push a test tone to a camera to
                                    verify the backchannel audio path.
    GET  /api/wizard/serve/{filename} — Serve wizard-generated WAV files to go2rtc.
    POST /api/wizard/save         — Persist a camera configuration to config.yaml.

Intended use:
    The wizard guides the operator through adding a new camera to VoxWatch.
    The flow is: detect -> test-audio (optional, repeat) -> save.

Security:
    Camera names are validated against a strict allowlist before any downstream
    calls are made.  Served filenames are validated against a regex that only
    allows safe characters, preventing directory traversal through the serve
    endpoint.  See _validate_camera_name and the serve endpoint for details.

Temp file management:
    Test tone WAV files are written to WIZARD_TEMP_DIR (/tmp/voxwatch-wizard/).
    The directory is created at module import time.  Files older than
    WIZARD_FILE_TTL_SECONDS (3600 s) are deleted during each /test-audio call
    to prevent unbounded disk growth.
"""

import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import config as dashboard_cfg
from backend.services import frigate_client as fc_module
from backend.services import go2rtc_client as g2rtc_module
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.wizard")

router = APIRouter(prefix="/wizard", tags=["Wizard"])

# ── Codec mappings ────────────────────────────────────────────────────────────
# go2rtc exposes RTSP codec names in the stream media strings.  ffmpeg uses
# different names for the same formats.  These dicts provide bidirectional
# translation used by the detect endpoint (RTSP -> ffmpeg for the response)
# and potentially by the VoxWatch audio pipeline.

RTSP_TO_FFMPEG: dict[str, str] = {
    "PCMU": "pcm_mulaw",   # G.711 µ-law, 8 kHz — most common camera codec
    "PCMA": "pcm_alaw",    # G.711 A-law, 8 kHz — European / Hikvision cameras
}

FFMPEG_TO_RTSP: dict[str, str] = {v: k for k, v in RTSP_TO_FFMPEG.items()}

# ── Temp directory for wizard-generated audio files ───────────────────────────
# Files are served back to go2rtc from this directory via GET /serve/{filename}.
# The directory is created here so the path is always valid before any endpoint
# tries to write to it.

WIZARD_TEMP_DIR: str = "/tmp/voxwatch-wizard"
WIZARD_FILE_TTL_SECONDS: int = 3600  # Delete files older than 1 hour

os.makedirs(WIZARD_TEMP_DIR, exist_ok=True)
logger.debug("Wizard temp directory ready: %s", WIZARD_TEMP_DIR)

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Replicates the same in-memory rate limiting used in audio.py.
# The test-audio endpoint drives actual speaker output; limiting it prevents
# the wizard from being accidentally (or intentionally) used as a noise source.
#
# Limit: 5 test pushes per camera per 60 seconds.

_RATE_LIMIT_MAX: int = 5
_RATE_LIMIT_WINDOW: float = 60.0  # seconds
_push_timestamps: dict[str, list[float]] = defaultdict(list)

# ── Filename validation for the serve endpoint ────────────────────────────────
# Only allow filenames that consist of safe characters and end in .wav.
# This prevents directory traversal attacks where a crafted filename like
# "../../etc/passwd" could escape WIZARD_TEMP_DIR.

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+\.wav$")

# ── Camera name validation (mirrors audio.py) ─────────────────────────────────
# Camera names are interpolated into go2rtc API query parameters and
# dashboard URLs.  Restrict to the safe set to block SSRF.

_CAMERA_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_camera_name(camera_name: str) -> None:
    """Raise HTTP 400 if *camera_name* contains characters outside the safe set.

    Security rationale: camera names are interpolated into URLs sent to the
    go2rtc API (as the ``dst`` query parameter) and used to construct snapshot
    URLs returned in API responses.  An unvalidated name could inject extra
    path segments or query parameters, turning the wizard into an SSRF vector.

    Args:
        camera_name: The camera name string submitted by the caller.

    Raises:
        HTTPException 400: If the name contains any disallowed characters or
                           is empty.
    """
    if not camera_name or not _CAMERA_NAME_RE.match(camera_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid camera name {camera_name!r}. "
                "Camera names may only contain letters, digits, underscores, "
                "and hyphens (pattern: ^[a-zA-Z0-9_-]+$)."
            ),
        )


def _check_rate_limit(camera_name: str) -> None:
    """Enforce per-camera rate limit on wizard test-audio pushes.

    Tracks monotonic timestamps of recent pushes per camera and rejects
    requests that exceed ``_RATE_LIMIT_MAX`` within ``_RATE_LIMIT_WINDOW``
    seconds.  The timestamp list is pruned on every call so memory usage is
    bounded by the window size.

    Args:
        camera_name: The camera identifier whose push history to check.

    Raises:
        HTTPException 429: If the rate limit for this camera is exceeded.
    """
    now = time.monotonic()
    timestamps = _push_timestamps[camera_name]

    # Remove entries that have aged out of the window.
    _push_timestamps[camera_name] = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    timestamps = _push_timestamps[camera_name]

    if len(timestamps) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded for camera '{camera_name}'. "
                f"Maximum {_RATE_LIMIT_MAX} test pushes per {int(_RATE_LIMIT_WINDOW)}s."
            ),
        )

    timestamps.append(now)


def _cleanup_old_wizard_files() -> None:
    """Delete WAV files in WIZARD_TEMP_DIR that are older than WIZARD_FILE_TTL_SECONDS.

    Called at the start of each /test-audio request so stale files are
    collected without a background task.  Errors are logged and swallowed —
    a cleanup failure must not block the test-audio response.
    """
    now = time.time()
    try:
        for entry in os.scandir(WIZARD_TEMP_DIR):
            if not entry.name.endswith(".wav"):
                continue
            try:
                age = now - entry.stat().st_mtime
                if age > WIZARD_FILE_TTL_SECONDS:
                    os.unlink(entry.path)
                    logger.debug("Cleaned up old wizard file: %s (age %.0fs)", entry.name, age)
            except OSError as exc:
                logger.warning("Failed to remove wizard file %s: %s", entry.path, exc)
    except OSError as exc:
        logger.warning("Failed to scan wizard temp dir %s: %s", WIZARD_TEMP_DIR, exc)


async def _run_ffmpeg(*args: str) -> tuple[int, str, str]:
    """Run an ffmpeg command as a subprocess and return its exit status and output.

    Uses asyncio.create_subprocess_exec rather than subprocess.run so the
    FastAPI event loop is not blocked while ffmpeg encodes audio.

    Args:
        *args: Command-line arguments for ffmpeg (do NOT include the "ffmpeg"
               binary name itself — it is prepended automatically).

    Returns:
        A 3-tuple of (return_code, stdout_text, stderr_text).
        stdout and stderr are decoded as UTF-8 with errors replaced.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return_code = proc.returncode if proc.returncode is not None else -1
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    return return_code, stdout_text, stderr_text


# ── Request / response models ─────────────────────────────────────────────────

class DetectRequest(BaseModel):
    """Request body for POST /api/wizard/detect."""

    camera_name: str = Field(
        description=(
            "Camera name to probe.  Must match the stream name in go2rtc. "
            "Allowed characters: letters, digits, underscores, hyphens."
        )
    )


class DetectResponse(BaseModel):
    """Response from POST /api/wizard/detect.

    Attributes:
        camera_name:       The camera name that was probed.
        stream_name:       The resolved go2rtc stream name (may differ from camera_name
                           if the VoxWatch config maps them separately).
        has_backchannel:   True if go2rtc reports at least one sendonly audio track,
                           meaning the camera supports receiving audio.
        codecs:            List of RTSP codec strings reported in the backchannel media
                           description (e.g. ["PCMU/8000", "PCMA/8000"]).
        recommended_codec: The ffmpeg codec name recommended for this camera, derived
                           by translating the first detected RTSP codec via RTSP_TO_FFMPEG.
                           None if no recognised codec is found.
        frigate_online:    Whether Frigate considers this camera online.  None if
                           Frigate is unreachable or the camera is not in Frigate.
        fps:               Detection FPS reported by Frigate for this camera, or None.
        snapshot_url:      Relative URL path for a live snapshot of this camera
                           (proxied through the dashboard API).  Always set when
                           the camera name is known, regardless of Frigate status.
    """

    camera_name: str
    stream_name: str
    has_backchannel: bool
    codecs: list[str]
    recommended_codec: str | None
    frigate_online: bool | None
    fps: float | None
    snapshot_url: str | None


class TestAudioRequest(BaseModel):
    """Request body for POST /api/wizard/test-audio."""

    camera_name: str = Field(
        description=(
            "Camera name to push the test tone to (must match go2rtc stream name). "
            "Allowed characters: letters, digits, underscores, hyphens."
        )
    )
    stream_name: str = Field(
        description=(
            "go2rtc stream name to push audio to.  Typically the same as camera_name "
            "unless the VoxWatch config maps them differently.  Returned by /detect."
        )
    )
    codec: str = Field(
        default="pcm_mulaw",
        description=(
            "ffmpeg audio codec to encode the test tone with.  Must match the "
            "codec supported by the camera's backchannel (returned by /detect). "
            "Supported values: 'pcm_mulaw' (G.711 µ-law), 'pcm_alaw' (G.711 A-law)."
        ),
    )
    warmup_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=10.0,
        description=(
            "Seconds to wait after the warmup silence push before sending the real "
            "test tone.  The backchannel requires a brief warmup push on first use; "
            "audio played during that window is often silently discarded by the camera. "
            "Range: 0.0–10.0 s."
        ),
    )
    sample_rate: int = Field(
        default=8000,
        description=(
            "Audio sample rate in Hz.  Should match the camera's backchannel codec "
            "declaration (typically 8000 for PCMU/PCMA).  Common values: 8000, 16000."
        ),
    )


class TestAudioResponse(BaseModel):
    """Response from POST /api/wizard/test-audio."""

    success: bool = Field(description="True if go2rtc accepted the test tone push.")
    message: str = Field(description="Human-readable result message.")
    response_time_ms: int = Field(
        description="Wall-clock time for the entire test-audio operation in milliseconds."
    )


class SaveRequest(BaseModel):
    """Request body for POST /api/wizard/save."""

    camera_name: str = Field(
        description=(
            "Camera name to add or update in config.yaml.  Used as the key under "
            "the top-level 'cameras:' block.  Must be a valid camera name."
        )
    )
    go2rtc_stream: str = Field(
        description=(
            "go2rtc stream name for this camera.  Stored as 'go2rtc_stream' in the "
            "camera config block.  Typically matches camera_name."
        )
    )
    audio_codec: str | None = Field(
        default=None,
        description=(
            "ffmpeg codec string for the camera's backchannel (e.g. 'pcm_mulaw'). "
            "Stored as 'audio_codec'.  None means use the VoxWatch service default."
        ),
    )
    sample_rate: int | None = Field(
        default=None,
        description="Audio sample rate in Hz (e.g. 8000).  None uses service default.",
    )
    channels: int | None = Field(
        default=None,
        description="Audio channel count (1 = mono, 2 = stereo).  None uses service default.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this camera should be actively monitored by VoxWatch.",
    )
    scene_context: str = Field(
        default="",
        description=(
            "Optional free-text description of the scene visible by this camera "
            "(e.g. 'front driveway facing street').  Used as context in AI prompts."
        ),
    )


class SaveResponse(BaseModel):
    """Response from POST /api/wizard/save."""

    success: bool = Field(description="True if the config was saved successfully.")
    message: str = Field(description="Human-readable result message.")


# ── Endpoint 1: detect ────────────────────────────────────────────────────────

@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Detect camera capabilities",
    description=(
        "Probes a camera's go2rtc stream and Frigate integration to discover "
        "backchannel support, supported audio codecs, and live camera stats. "
        "Use this as the first step in the camera setup wizard."
    ),
    status_code=status.HTTP_200_OK,
)
async def detect_camera(request: DetectRequest) -> DetectResponse:
    """Detect backchannel capabilities and Frigate stats for a camera.

    Queries go2rtc for stream info and inspects producer media strings to find
    'sendonly' audio tracks indicating RTSP backchannel support.  Concurrently
    queries Frigate for camera FPS and online status.

    The codec list is extracted from go2rtc's media description strings, which
    look like "audio, sendonly, PCMU/8000, PCMA/8000".  Each codec entry is
    translated to its ffmpeg name via ``RTSP_TO_FFMPEG``.  The first recognised
    codec becomes ``recommended_codec``.

    Args:
        request: DetectRequest containing the camera name to probe.
                 The name is validated before any downstream calls.

    Returns:
        DetectResponse with backchannel info, codecs, and Frigate stats.

    Raises:
        HTTPException 400: If the camera name contains disallowed characters.
        HTTPException 404: If go2rtc has no stream matching the camera name.
        HTTPException 503: If go2rtc is not reachable.
    """
    _validate_camera_name(request.camera_name)

    if g2rtc_module.go2rtc_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "go2rtc client is not initialized. "
                "Check go2rtc host/port in config.yaml."
            ),
        )

    # ── Resolve stream name from config, fall back to camera_name ─────────────
    # Some users configure a go2rtc_stream that differs from the Frigate camera
    # name.  Honour that mapping if present; otherwise use the camera name
    # directly (which is how Frigate-managed streams are typically named).
    stream_name: str = request.camera_name
    try:
        cfg = await config_service.get_config()
        cam_cfg = cfg.get("cameras", {}).get(request.camera_name, {})
        configured_stream = cam_cfg.get("go2rtc_stream") or None
        if configured_stream:
            stream_name = configured_stream
            logger.debug(
                "Wizard detect: resolved stream name from config: %s -> %s",
                request.camera_name,
                stream_name,
            )
    except Exception as exc:
        logger.warning(
            "Wizard detect: could not read config for stream lookup of %s: %s",
            request.camera_name,
            exc,
        )

    # ── Query go2rtc for backchannel info ──────────────────────────────────────
    # get_backchannel_info() fetches all streams in one call and parses each
    # stream's producer medias for sendonly audio tracks.
    try:
        backchannel_map = await g2rtc_module.go2rtc_client.get_backchannel_info()
    except Exception as exc:
        logger.error("Wizard detect: go2rtc backchannel query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"go2rtc is not reachable: {exc}",
        ) from exc

    if backchannel_map is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="go2rtc returned no stream data.  Verify it is running and reachable.",
        )

    if stream_name not in backchannel_map:
        # Stream doesn't exist in go2rtc at all.
        available = ", ".join(backchannel_map.keys()) if backchannel_map else "none"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Stream '{stream_name}' not found in go2rtc "
                f"(available: {available}). "
                "Verify the camera is streaming and the name matches."
            ),
        )

    stream_info = backchannel_map[stream_name]
    has_backchannel: bool = stream_info.get("has_backchannel", False)
    raw_codecs: list[str] = stream_info.get("codecs", [])  # e.g. ["PCMU/8000", "PCMA/8000"]

    # Translate RTSP codec names (e.g. "PCMU/8000") to ffmpeg names ("pcm_mulaw").
    # The RTSP codec string includes the sample rate as a suffix after "/".
    # We strip the suffix before looking up the base codec name.
    ffmpeg_codecs: list[str] = []
    for rtsp_codec in raw_codecs:
        base = rtsp_codec.split("/")[0].upper()  # "PCMU/8000" -> "PCMU"
        ffmpeg_name = RTSP_TO_FFMPEG.get(base)
        if ffmpeg_name and ffmpeg_name not in ffmpeg_codecs:
            ffmpeg_codecs.append(ffmpeg_name)

    recommended_codec: str | None = ffmpeg_codecs[0] if ffmpeg_codecs else None

    # ── Query Frigate for camera stats ────────────────────────────────────────
    # These are best-effort; Frigate being unreachable should not block the wizard.
    frigate_online: bool | None = None
    fps: float | None = None

    if fc_module.frigate_client is not None:
        try:
            stats = await fc_module.frigate_client.get_stats()
            if stats:
                cam_stats = stats.get("cameras", {}).get(request.camera_name, {})
                if cam_stats:
                    # Frigate reports detection_fps; capture_fps is also available.
                    fps_val = cam_stats.get("detection_fps") or cam_stats.get("capture_fps")
                    if fps_val is not None:
                        fps = float(fps_val)
                    # A camera is considered online if Frigate has stats for it
                    # and is actively sending frames (capture_fps > 0).
                    capture_fps = cam_stats.get("capture_fps", 0)
                    frigate_online = float(capture_fps) > 0
        except Exception as exc:
            logger.debug(
                "Wizard detect: Frigate stats query failed for %s: %s",
                request.camera_name,
                exc,
            )

    snapshot_url: str = f"/api/cameras/{request.camera_name}/snapshot"

    logger.info(
        "Wizard detect: camera=%s stream=%s backchannel=%s codecs=%s recommended=%s",
        request.camera_name,
        stream_name,
        has_backchannel,
        ffmpeg_codecs,
        recommended_codec,
    )

    return DetectResponse(
        camera_name=request.camera_name,
        stream_name=stream_name,
        has_backchannel=has_backchannel,
        codecs=ffmpeg_codecs,
        recommended_codec=recommended_codec,
        frigate_online=frigate_online,
        fps=fps,
        snapshot_url=snapshot_url,
    )


# ── Endpoint 2: test-audio ────────────────────────────────────────────────────

@router.post(
    "/test-audio",
    response_model=TestAudioResponse,
    summary="Push a test tone to a camera",
    description=(
        "Generates a short test tone via ffmpeg and pushes it to the camera "
        "backchannel through go2rtc.  Sends a warmup silence first (required by "
        "some cameras to establish the backchannel before audio is played). "
        "Rate limited to 5 calls per camera per 60 seconds."
    ),
    status_code=status.HTTP_200_OK,
)
async def test_audio_push(request: TestAudioRequest) -> TestAudioResponse:
    """Generate a test tone and push it to a camera via go2rtc.

    Workflow:
      1. Validate camera name and enforce rate limit.
      2. Clean up old wizard WAV files (TTL-based housekeeping).
      3. Generate a 1.5 s 800 Hz sine wave with ffmpeg using the requested codec.
      4. Generate a 0.1 s silence warmup file with the same codec.
      5. Derive the serve URL where go2rtc will fetch the file
         (http://<go2rtc_host>:<dashboard_port>/api/wizard/serve/<filename>).
      6. Push the warmup file to prime the backchannel.
      7. Wait warmup_delay seconds.
      8. Push the test tone.

    The test tone and warmup file are written to WIZARD_TEMP_DIR and served
    back to go2rtc by the GET /api/wizard/serve/{filename} endpoint in this
    same router.

    Args:
        request: TestAudioRequest with camera, stream name, codec, and timing.

    Returns:
        TestAudioResponse with success flag, message, and total wall-clock time.

    Raises:
        HTTPException 400: If the camera name or codec is invalid.
        HTTPException 429: If the rate limit for this camera is exceeded.
        HTTPException 500: If ffmpeg fails to generate the test tone.
        HTTPException 503: If go2rtc is not reachable or not initialised.
    """
    operation_start = time.monotonic()

    _validate_camera_name(request.camera_name)
    _check_rate_limit(request.camera_name)

    # Validate codec is a known safe value to prevent ffmpeg command injection.
    # We only allow the two standard codecs; anything else is rejected.
    allowed_codecs = set(RTSP_TO_FFMPEG.values())  # {"pcm_mulaw", "pcm_alaw"}
    if request.codec not in allowed_codecs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported codec {request.codec!r}. "
                f"Allowed values: {sorted(allowed_codecs)}."
            ),
        )

    if g2rtc_module.go2rtc_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "go2rtc client is not initialized. "
                "Check go2rtc host/port in config.yaml."
            ),
        )

    # ── Housekeeping: remove expired wizard files ──────────────────────────────
    _cleanup_old_wizard_files()

    # ── Generate unique filenames scoped to this camera + timestamp ───────────
    ts = int(time.time())
    safe_cam = request.camera_name.replace("-", "_")
    tone_filename = f"wizard_{safe_cam}_{ts}_tone.wav"
    warmup_filename = f"wizard_{safe_cam}_{ts}_warmup.wav"
    tone_path = os.path.join(WIZARD_TEMP_DIR, tone_filename)
    warmup_path = os.path.join(WIZARD_TEMP_DIR, warmup_filename)

    # ── Generate 1.5 s 800 Hz test tone via ffmpeg ────────────────────────────
    # -y              : overwrite output without prompting
    # -f lavfi        : use the lavfi virtual device for the sine source
    # -i "sine=..."   : 800 Hz sine wave, 1.5 s duration
    # -acodec {codec} : encode with the camera's backchannel codec
    # -ar {rate}      : sample rate to match the backchannel declaration
    # -ac 1           : mono (cameras always use mono backchannel)
    logger.debug(
        "Wizard test-audio: generating tone %s (codec=%s rate=%d)",
        tone_path,
        request.codec,
        request.sample_rate,
    )
    rc, _, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=800:duration=1.5",
        "-acodec", request.codec,
        "-ar", str(request.sample_rate),
        "-ac", "1",
        tone_path,
    )
    if rc != 0:
        logger.error(
            "Wizard test-audio: ffmpeg tone generation failed (rc=%d): %s",
            rc,
            stderr[-500:],
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"ffmpeg failed to generate test tone (exit code {rc}). "
                "Ensure ffmpeg is installed and the codec is supported."
            ),
        )

    # ── Generate 0.1 s warmup silence via ffmpeg ──────────────────────────────
    # anullsrc produces digital silence.  The warmup push establishes the
    # backchannel connection; some cameras drop audio during the first push.
    logger.debug("Wizard test-audio: generating warmup silence %s", warmup_path)
    rc_warmup, _, stderr_warmup = await _run_ffmpeg(
        "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={request.sample_rate}:cl=mono",
        "-t", "0.1",
        "-acodec", request.codec,
        warmup_path,
    )
    if rc_warmup != 0:
        logger.warning(
            "Wizard test-audio: ffmpeg warmup generation failed (rc=%d): %s",
            rc_warmup,
            stderr_warmup[-300:],
        )
        # A missing warmup file is non-fatal — we can still try the real push.

    # ── Construct serve URLs for go2rtc to fetch ──────────────────────────────
    # go2rtc needs a URL it can reach from inside the Docker network.
    # We use the go2rtc host (which is on the same network as the dashboard)
    # and the dashboard's own listen port.
    try:
        cfg_data = await config_service.get_raw_config()
        go2rtc_host: str = cfg_data.get("go2rtc", {}).get("host", "localhost")
    except Exception as exc:
        logger.warning(
            "Wizard test-audio: could not read config for URL construction: %s", exc
        )
        go2rtc_host = "localhost"

    dashboard_port: int = dashboard_cfg.DASHBOARD_PORT
    base_url = f"http://{go2rtc_host}:{dashboard_port}/api/wizard/serve"
    tone_url = f"{base_url}/{tone_filename}"
    warmup_url = f"{base_url}/{warmup_filename}"

    logger.info(
        "Wizard test-audio: camera=%s stream=%s codec=%s tone_url=%s",
        request.camera_name,
        request.stream_name,
        request.codec,
        tone_url,
    )

    # ── Warmup push ────────────────────────────────────────────────────────────
    # Send the silence first to establish the backchannel.  Ignore the result —
    # the warmup succeeding is nice-to-have, not critical.
    if os.path.isfile(warmup_path):
        try:
            await g2rtc_module.go2rtc_client.push_audio(request.stream_name, warmup_url)
            logger.debug("Wizard test-audio: warmup push sent")
        except Exception as exc:
            logger.warning("Wizard test-audio: warmup push failed (non-fatal): %s", exc)

    # ── Wait for the backchannel to become ready ───────────────────────────────
    if request.warmup_delay > 0:
        await asyncio.sleep(request.warmup_delay)

    # ── Real test tone push ────────────────────────────────────────────────────
    success = False
    try:
        success = await g2rtc_module.go2rtc_client.push_audio(request.stream_name, tone_url)
    except Exception as exc:
        logger.error(
            "Wizard test-audio: test tone push failed for %s: %s",
            request.stream_name,
            exc,
        )

    elapsed_ms = int((time.monotonic() - operation_start) * 1000)

    if success:
        message = (
            "Test tone pushed successfully. "
            "Listen for an 800 Hz beep from the camera speaker in 1–3 seconds."
        )
    else:
        message = (
            "go2rtc rejected the push request. "
            "Verify the stream name is correct and the camera supports backchannel audio."
        )

    logger.info(
        "Wizard test-audio: camera=%s success=%s elapsed_ms=%d",
        request.camera_name,
        success,
        elapsed_ms,
    )

    return TestAudioResponse(
        success=success,
        message=message,
        response_time_ms=elapsed_ms,
    )


# ── Endpoint 3: serve ─────────────────────────────────────────────────────────

@router.get(
    "/serve/{filename}",
    summary="Serve a wizard-generated WAV file",
    description=(
        "Serves a WAV file from the wizard temp directory so go2rtc can fetch it "
        "as the audio source for a backchannel push.  Only .wav files with "
        "safe filenames are served.  This endpoint is called by go2rtc internally; "
        "it is not intended for direct browser use."
    ),
    response_class=FileResponse,
)
async def serve_wizard_file(filename: str) -> FileResponse:
    """Serve a wizard-generated WAV file to go2rtc.

    Security measures:
      - Filename is validated against ``_SAFE_FILENAME_RE`` which only allows
        alphanumeric characters, underscores, hyphens, and dots, and enforces
        a .wav extension.  This blocks directory traversal sequences like
        "../../../etc/passwd".
      - The resolved absolute path is checked with ``Path.is_relative_to()``
        to confirm it stays within WIZARD_TEMP_DIR, providing a second layer
        of defence against bypasses.
      - Only regular files are served (symlinks are not followed to external
        paths thanks to the relative_to check).

    Args:
        filename: WAV filename to serve.  Must match ``_SAFE_FILENAME_RE``.

    Returns:
        FileResponse with Content-Type audio/wav and cache-control headers
        that prevent the file from being cached (files are ephemeral).

    Raises:
        HTTPException 400: If the filename contains disallowed characters or
                           does not end in .wav.
        HTTPException 404: If the file does not exist in the wizard temp dir.
    """
    # ── Security: validate filename before touching the filesystem ─────────────
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid filename {filename!r}. "
                "Only .wav files with alphanumeric names are permitted "
                "(pattern: ^[a-zA-Z0-9_.-]+\\.wav$)."
            ),
        )

    # ── Security: confirm resolved path stays inside the temp directory ────────
    # Path.resolve() collapses any ".." components before we do the boundary check.
    candidate = Path(WIZARD_TEMP_DIR) / filename
    try:
        resolved = candidate.resolve()
        resolved.relative_to(Path(WIZARD_TEMP_DIR).resolve())
    except ValueError:
        # Resolved path escapes the temp directory — treat as 404 to avoid
        # disclosing filesystem layout details.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wizard audio file '{filename}' not found or has expired.",
        )

    logger.debug("Wizard serve: %s", filename)

    return FileResponse(
        path=str(resolved),
        media_type="audio/wav",
        headers={
            # Prevent proxies or browsers from caching ephemeral wizard files.
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


# ── Endpoint 4: save ──────────────────────────────────────────────────────────

@router.post(
    "/save",
    response_model=SaveResponse,
    summary="Save camera configuration",
    description=(
        "Adds or updates a camera entry in config.yaml.  All fields provided by "
        "the wizard are written; fields omitted from the request (None values) "
        "are not written to the config so VoxWatch falls back to its built-in "
        "defaults for those settings.  Existing camera entries are fully replaced."
    ),
    status_code=status.HTTP_200_OK,
)
async def save_camera_config(request: SaveRequest) -> SaveResponse:
    """Persist wizard-collected camera settings to config.yaml.

    Reads the current raw config (preserving all existing cameras and settings),
    upserts the camera block under ``cameras.<camera_name>``, then atomically
    saves the merged config via config_service.save_config().

    The camera block written to config.yaml contains:
      - ``go2rtc_stream``:  always set (required for audio push)
      - ``enabled``:        always set
      - ``scene_context``:  always set (may be empty string)
      - ``audio_codec``:    only written if not None
      - ``sample_rate``:    only written if not None
      - ``channels``:       only written if not None

    Args:
        request: SaveRequest with camera name and all wizard-collected settings.

    Returns:
        SaveResponse indicating success or failure with a descriptive message.

    Raises:
        HTTPException 400: If the camera name contains disallowed characters.
        HTTPException 500: If the config cannot be read or written.
    """
    _validate_camera_name(request.camera_name)

    # ── Read current config ────────────────────────────────────────────────────
    # Use get_raw_config() to get unmasked values so save_config() does not
    # attempt to merge masked placeholders with the incoming camera data.
    try:
        current_config = await config_service.get_raw_config()
    except FileNotFoundError:
        # config.yaml doesn't exist yet — start with a minimal skeleton.
        # The user is in initial setup, so an empty config is acceptable.
        logger.warning(
            "Wizard save: config.yaml not found; creating a new config skeleton "
            "for camera %s",
            request.camera_name,
        )
        current_config = {}
    except Exception as exc:
        logger.error("Wizard save: failed to read config: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read current config: {exc}",
        ) from exc

    # ── Build the camera config block ─────────────────────────────────────────
    # Always-present fields: these are what the wizard primarily collects.
    camera_block: dict = {
        "go2rtc_stream": request.go2rtc_stream,
        "enabled": request.enabled,
        "scene_context": request.scene_context,
    }

    # Optional fields: only write if the wizard collected a value.
    # Omitting them lets VoxWatch use its built-in defaults (e.g. service-wide
    # default codec), which is better than writing wrong/None values.
    if request.audio_codec is not None:
        camera_block["audio_codec"] = request.audio_codec
    if request.sample_rate is not None:
        camera_block["sample_rate"] = request.sample_rate
    if request.channels is not None:
        camera_block["channels"] = request.channels

    # ── Upsert camera entry ────────────────────────────────────────────────────
    if "cameras" not in current_config or not isinstance(current_config.get("cameras"), dict):
        current_config["cameras"] = {}

    current_config["cameras"][request.camera_name] = camera_block

    logger.info(
        "Wizard save: upserting camera %s with block %s",
        request.camera_name,
        camera_block,
    )

    # ── Persist to config.yaml ─────────────────────────────────────────────────
    try:
        await config_service.save_config(current_config)
    except Exception as exc:
        logger.error(
            "Wizard save: config_service.save_config failed for %s: %s",
            request.camera_name,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save config: {exc}",
        ) from exc

    return SaveResponse(
        success=True,
        message=(
            f"Camera '{request.camera_name}' saved to config.yaml. "
            "Restart VoxWatch to apply changes."
        ),
    )
