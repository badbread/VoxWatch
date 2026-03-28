"""
audio.py — Audio API Router (Main)

Endpoints registered directly here:
    POST /api/audio/test        — Trigger a test audio push to a camera via go2rtc
    POST /api/audio/announce    — Play a TTS announcement on a camera speaker

Sub-routers mounted from domain modules (no URL changes):
    audio_preview   → POST /api/audio/preview
    audio_tts_test  → POST /api/audio/test-tts-provider
    audio_piper     → GET  /api/audio/piper-voices
                       DELETE /api/audio/piper-voices/{model_name}
    audio_intro     → POST /api/audio/upload-intro
                       POST /api/audio/generate-intro

The test endpoint is intended for setup verification: it pushes a short test
tone or a canned message to a camera's speaker so the user can confirm the
audio path works without triggering a real detection event.

The announce endpoint is a purpose-built TTS announcement endpoint for Home
Assistant automations and external integrations.  It proxies the request to the
VoxWatch service's preview API (port 8892) which has access to the full
AudioPipeline.

Security:
    The camera_name field in the request body is validated against a strict
    allowlist pattern before use.  This prevents SSRF attacks where a crafted
    camera name could direct go2rtc to fetch audio from or push audio to an
    unintended internal host.  See the _validate_camera_name helper for details.
"""

import asyncio
import logging
import re
import time
from collections import defaultdict

import aiohttp
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.routers.audio_intro import router as intro_router
from backend.routers.audio_piper import router as piper_router
from backend.routers.audio_preview import router as preview_router
from backend.routers.audio_tts_test import router as tts_test_router
from backend.services import go2rtc_client as g2rtc_module
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.audio")

router = APIRouter(prefix="/audio", tags=["Audio"])

# ── Mount sub-routers ─────────────────────────────────────────────────────────
# Each sub-router carries no prefix of its own; the parent "/audio" prefix
# applies.  URL paths are identical to the original monolithic audio.py.

router.include_router(preview_router)
router.include_router(tts_test_router)
router.include_router(piper_router)
router.include_router(intro_router)

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Simple in-memory rate limiter for the audio test endpoint.
# Prevents abuse (intentional or accidental) — pushing audio to camera speakers
# too frequently is annoying and could mask real deterrent events.
#
# Limit: 5 pushes per camera per 60 seconds.

_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 60.0  # seconds
_push_timestamps: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(camera_name: str) -> None:
    """Enforce per-camera rate limit on audio test pushes.

    Tracks timestamps of recent pushes per camera and rejects requests
    that exceed the limit within the time window.

    Args:
        camera_name: Camera to check rate limit for.

    Raises:
        HTTPException 429: If rate limit exceeded.
    """
    now = time.monotonic()
    timestamps = _push_timestamps[camera_name]

    # Prune old entries outside the window
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


# ── Input validation ──────────────────────────────────────────────────────────
# Camera names must consist only of alphanumeric characters, underscores, and
# hyphens.  This is the same pattern enforced in cameras.py.
#
# Security rationale: request.camera_name is used to look up a go2rtc stream
# and construct URLs.  An unrestricted name (e.g. "cam/../admin" or
# "cam?inject=1") could be exploited to redirect go2rtc's internal HTTP client
# to unintended destinations (SSRF).
_CAMERA_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_camera_name(camera_name: str) -> None:
    """Raise HTTP 400 if *camera_name* contains characters outside the safe set.

    Security rationale: camera names are interpolated into URLs sent to the
    go2rtc API.  Without validation a malicious caller could inject extra path
    segments or query parameters, turning this endpoint into an SSRF vector
    against internal services reachable from the VoxWatch container.

    Args:
        camera_name: The camera name string to validate.

    Raises:
        HTTPException 400: If the name contains any disallowed characters.
    """
    if not _CAMERA_NAME_RE.match(camera_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid camera name {camera_name!r}. "
                "Camera names may only contain letters, digits, underscores, "
                "and hyphens (pattern: ^[a-zA-Z0-9_-]+$)."
            ),
        )


# ── Request/response models ───────────────────────────────────────────────────


class TestAudioRequest(BaseModel):
    """Request body for POST /api/audio/test."""

    camera_name: str = Field(
        description=(
            "Camera name to push test audio to (must match go2rtc stream name). "
            "Allowed characters: letters, digits, underscores, hyphens."
        )
    )
    message: str = Field(
        default="This is a VoxWatch audio system test.",
        description="Message text to synthesize and push (kept short for testing)",
        max_length=200,
    )
    audio_server_url: str | None = Field(
        default=None,
        description=(
            "Base URL of the VoxWatch audio HTTP server "
            "(e.g. 'http://192.168.1.10:8891'). "
            "Used to construct the audio source URL for go2rtc. "
            "If not provided, uses a pre-generated test tone."
        ),
    )


class TestAudioResponse(BaseModel):
    """Response from POST /api/audio/test."""

    success: bool = Field(description="Whether go2rtc accepted the push request")
    camera: str = Field(description="Camera the test was sent to")
    stream_name: str = Field(description="go2rtc stream name used")
    message: str = Field(description="Human-readable status message")


class AnnounceRequest(BaseModel):
    """Request body for POST /api/audio/announce."""

    camera: str = Field(
        description=(
            "Target camera name to play the announcement on. "
            "Must match a go2rtc stream name."
        )
    )
    message: str = Field(
        description="Text to synthesise and play on the camera speaker.",
        max_length=1000,
    )
    voice: str | None = Field(
        default=None,
        description="TTS voice override. Uses configured default when omitted.",
    )
    provider: str | None = Field(
        default=None,
        description="TTS provider override (kokoro, piper, elevenlabs, etc.).",
    )
    speed: float | None = Field(
        default=None,
        description="Playback speed multiplier (0.25–4.0).",
        ge=0.25,
        le=4.0,
    )
    tone: str | None = Field(
        default=None,
        description="Attention tone to prepend: 'short', 'long', 'siren', or 'none'.",
    )


class AnnounceResponse(BaseModel):
    """Response from POST /api/audio/announce."""

    success: bool = Field(description="Whether the announcement was played")
    camera: str = Field(description="Camera the announcement was sent to")
    duration_ms: int | None = Field(
        default=None,
        description="Total processing time in milliseconds",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the announcement failed",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/test",
    response_model=TestAudioResponse,
    summary="Trigger test audio push",
    description=(
        "Pushes a test audio stream to a camera speaker via go2rtc. "
        "Used to verify the audio pipeline is working without needing a real detection. "
        "Requires go2rtc to be reachable and the stream to be configured."
    ),
    status_code=status.HTTP_200_OK,
)
async def test_audio_push(request: TestAudioRequest) -> TestAudioResponse:
    """Trigger a test audio push to a camera via go2rtc.

    Looks up the camera's go2rtc stream name from config.yaml first, then
    falls back to querying go2rtc directly if the camera is not in VoxWatch
    config. This allows testing audio on any camera visible in go2rtc, not
    just cameras configured in VoxWatch.

    Note: This endpoint only sends the push request to go2rtc. Actual TTS
    generation requires the VoxWatch audio pipeline to be running. For a
    basic connectivity test, the audio_server_url can point to any accessible
    audio file.

    Args:
        request: TestAudioRequest with camera name, message, and optional URL.
                 camera_name is validated before use to prevent SSRF.

    Returns:
        TestAudioResponse indicating success or failure.

    Raises:
        400: If request.camera_name contains disallowed characters.
        404: If the camera is not found in config.yaml or go2rtc streams.
        503: If go2rtc is not reachable.
    """
    # Validate camera name and enforce rate limit before doing any real work.
    # go2rtc stream names (derived from camera names) are interpolated into
    # the /api/ffmpeg?dst=<name> query parameter — an unvalidated name could
    # inject additional query parameters or path segments.
    _validate_camera_name(request.camera_name)
    _check_rate_limit(request.camera_name)

    # Look up the go2rtc stream name.  Try VoxWatch config first (which may
    # map a Frigate camera name to a different go2rtc stream name), then fall
    # back to probing go2rtc directly so unconfigured cameras can still be
    # tested.
    stream_name = await _get_stream_name(request.camera_name)
    if stream_name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Camera {request.camera_name!r} not found in config.yaml or "
                "in the go2rtc stream list. "
                "Ensure the stream name matches the Frigate camera name."
            ),
        )

    if g2rtc_module.go2rtc_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="go2rtc client not initialized. Check go2rtc config in config.yaml.",
        )

    # Determine the audio source URL for go2rtc.
    # The VoxWatch container serves audio files on port 8891 (audio_push.serve_port).
    # We use the cached Stage 1 audio for testing since it's always available.
    cfg = await config_service.get_config()
    go2rtc_host = cfg.get("go2rtc", {}).get("host", "localhost")
    serve_port = cfg.get("audio_push", {}).get("serve_port", 8891)
    audio_url = f"http://{go2rtc_host}:{serve_port}/stage1_cached.wav"

    logger.info(
        "Test audio push: camera=%s stream=%s url=%s",
        request.camera_name,
        stream_name,
        audio_url,
    )

    # Warmup push — first push after idle establishes backchannel but
    # audio may not play. Send a short warmup file first.
    warmup_url = f"http://{go2rtc_host}:{serve_port}/warmup_silent.wav"
    await g2rtc_module.go2rtc_client.push_audio(stream_name, warmup_url)

    await asyncio.sleep(2.0)

    # Real audio push
    success = await g2rtc_module.go2rtc_client.push_audio(stream_name, audio_url)

    return TestAudioResponse(
        success=success,
        camera=request.camera_name,
        stream_name=stream_name,
        message=(
            "Test audio push sent to go2rtc successfully. "
            "Check camera speaker in 1-3 seconds."
            if success
            else "go2rtc rejected the push request. Check stream name and go2rtc logs."
        ),
    )


@router.post(
    "/announce",
    response_model=AnnounceResponse,
    summary="Play a TTS announcement on a camera speaker",
    description=(
        "Synthesises text-to-speech and plays it on a camera speaker via go2rtc. "
        "Designed for Home Assistant automations and external integrations. "
        "Supports custom voice, provider, speed, and attention tone settings."
    ),
    status_code=status.HTTP_200_OK,
)
async def announce(request: AnnounceRequest) -> AnnounceResponse:
    """Play a TTS announcement on a camera speaker.

    Proxies the request to the VoxWatch service's preview API which has
    access to the full AudioPipeline for TTS generation, codec conversion,
    and go2rtc push.

    Args:
        request: AnnounceRequest with camera, message, and optional overrides.

    Returns:
        AnnounceResponse with success status and timing.
    """
    _validate_camera_name(request.camera)

    # Build the payload for the VoxWatch announce API.
    payload: dict = {
        "camera": request.camera,
        "message": request.message,
    }
    if request.voice is not None:
        payload["voice"] = request.voice
    if request.provider is not None:
        payload["provider"] = request.provider
    if request.speed is not None:
        payload["speed"] = request.speed
    if request.tone is not None:
        payload["tone"] = request.tone

    # Resolve the VoxWatch service preview API URL.
    # Uses 127.0.0.1 because the Preview API binds to localhost only (security).
    cfg = await config_service.get_config()
    preview_port = cfg.get("preview_api_port", 8892)
    announce_url = f"http://127.0.0.1:{preview_port}/api/announce"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                announce_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                result = await resp.json()

                if resp.status == 200 and result.get("success"):
                    return AnnounceResponse(
                        success=True,
                        camera=request.camera,
                        duration_ms=result.get("duration_ms"),
                    )
                else:
                    error_msg = result.get("error", f"VoxWatch API returned HTTP {resp.status}")
                    logger.error(
                        "Announce failed for camera %s: %s",
                        request.camera,
                        error_msg,
                    )
                    return AnnounceResponse(
                        success=False,
                        camera=request.camera,
                        error=error_msg,
                    )
    except aiohttp.ClientError as exc:
        logger.error("Announce: VoxWatch service unreachable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "VoxWatch service is not reachable. "
                "Ensure the VoxWatch container is running."
            ),
        ) from exc


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_stream_name(camera_name: str) -> str | None:
    """Resolve the go2rtc stream name for a camera.

    Resolution order:
      1. VoxWatch config.yaml — the ``go2rtc_stream`` key under the camera
         block, which may differ from the camera name (e.g. if the Frigate
         camera name is "frontdoor" but the go2rtc stream is "frontdoor_hd").
      2. go2rtc streams API — if the camera is not in VoxWatch config (or its
         go2rtc_stream is blank), query go2rtc directly and accept the camera
         name as-is if a matching stream exists.

    Accepting unconfigured cameras allows the test endpoint to verify audio
    on any camera that go2rtc knows about, not just those enrolled in
    VoxWatch.  The go2rtc stream name for Frigate cameras typically matches
    the Frigate camera name verbatim.

    Args:
        camera_name: Camera / stream name to look up.

    Returns:
        Resolved go2rtc stream name string, or None if not found anywhere.
    """
    # --- Step 1: check VoxWatch config ---
    try:
        cfg = await config_service.get_config()
        cam = cfg.get("cameras", {}).get(camera_name, {})
        configured_stream = cam.get("go2rtc_stream") or None
        if configured_stream:
            logger.debug(
                "Resolved stream for %s from config: %s",
                camera_name,
                configured_stream,
            )
            return configured_stream
    except Exception as exc:
        logger.warning("Could not read config for stream lookup of %s: %s", camera_name, exc)

    # --- Step 2: probe go2rtc streams directly ---
    # If the camera is not in VoxWatch config (or has no go2rtc_stream set),
    # check whether go2rtc has a stream whose name matches the camera name.
    # This is the common case for Frigate-managed cameras: Frigate feeds
    # a stream into go2rtc under the same name as the Frigate camera.
    if g2rtc_module.go2rtc_client is not None:
        try:
            streams = await g2rtc_module.go2rtc_client.get_streams()
            if streams and camera_name in streams:
                logger.debug(
                    "Resolved stream for %s directly from go2rtc stream list",
                    camera_name,
                )
                return camera_name
            elif streams is not None:
                logger.debug(
                    "Camera %s not found in go2rtc streams (available: %s)",
                    camera_name,
                    ", ".join(streams.keys()) if streams else "none",
                )
        except Exception as exc:
            logger.warning("go2rtc stream lookup failed for %s: %s", camera_name, exc)

    return None
