"""
audio_intro.py — Dispatch Intro Upload and Generation Sub-Router

Handles:
    POST /api/audio/upload-intro    — Upload a custom dispatch channel intro audio file
    POST /api/audio/generate-intro  — Generate (and optionally save) a dispatch channel intro

The upload endpoint accepts WAV/MP3/OGG/FLAC files, validates magic bytes, and
stores the result at /config/audio/dispatch_intro.wav (a named Docker volume
that persists across restarts).

The generate endpoint proxies to the VoxWatch Preview API (port 8892) which has
access to all local TTS providers.  If VoxWatch is unreachable, cloud providers
(ElevenLabs, OpenAI, Cartesia, espeak) are attempted locally.
"""

import logging
import tempfile
import time
from pathlib import Path

import aiohttp
from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.routers._audio_utils import (
    _get_voxwatch_preview_url,
    _resolve_cloud_tts_key,
)
from backend.routers.audio_preview import (
    _synthesize_cartesia,
    _synthesize_elevenlabs,
    _synthesize_espeak,
    _synthesize_openai_tts,
)
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.audio.intro")

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

# Permitted MIME types and magic-byte signatures for uploaded intro audio.
# We validate the file header to reject non-audio content even if the
# browser sends a convincing Content-Type.
_AUDIO_MAGIC: list[tuple[bytes, str]] = [
    (b"RIFF", "WAV"),   # PCM WAV — first 4 bytes
    (b"\xff\xfb", "MP3"),  # MP3 MPEG-1 frame sync
    (b"\xff\xf3", "MP3"),  # MP3 MPEG-2 frame sync
    (b"\xff\xf2", "MP3"),  # MP3 MPEG-2.5 frame sync
    (b"ID3",  "MP3"),   # MP3 with ID3 tag
    (b"OggS", "OGG"),   # Ogg container (Vorbis/Opus)
    (b"fLaC", "FLAC"),  # FLAC
]

# Maximum allowed upload size (10 MB) — plenty for a short intro clip.
_INTRO_UPLOAD_MAX_BYTES = 10 * 1024 * 1024

# Destination path inside the config volume where the custom intro is stored.
# The /config directory is a named Docker volume that persists across restarts.
_INTRO_UPLOAD_DEST = "/config/audio/dispatch_intro.wav"

# Destination for the cached generated intro — matches the path used by
# generate_channel_intro() in radio_dispatch.py (Priority 2).
_CACHED_INTRO_PATH = "/data/audio/dispatch_intro_cached.wav"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_audio_format(header: bytes) -> str | None:
    """Identify the audio format from the first few bytes of a file.

    Checks the file's magic bytes against the known audio signatures.
    Returns the format name string (e.g. "WAV", "MP3") or ``None`` if
    no known signature matches.

    Args:
        header: The first 8 bytes of the file (or as many as are available).

    Returns:
        Format name string on a match, or ``None`` if unrecognised.
    """
    for magic, fmt in _AUDIO_MAGIC:
        if header.startswith(magic):
            return fmt
    return None


# ── Models ────────────────────────────────────────────────────────────────────


class GenerateIntroRequest(BaseModel):
    """Request body for POST /api/audio/generate-intro."""

    text: str = Field(
        description=(
            "Text to synthesise as the channel intro phrase. "
            "Supports {agency} template token which is substituted with the "
            "configured agency name from the current config. "
            "Example: 'Connecting to {agency} dispatch frequency.'"
        ),
        min_length=1,
        max_length=400,
    )
    provider: str | None = Field(
        default=None,
        description=(
            "TTS provider override: 'kokoro', 'elevenlabs', 'openai', 'cartesia', "
            "'piper', 'espeak'. When omitted, the currently configured provider is used."
        ),
    )
    voice: str | None = Field(
        default=None,
        description=(
            "Provider-specific voice identifier. "
            "When omitted the provider's configured default voice is used."
        ),
    )
    speed: float = Field(
        default=1.0,
        description="Playback speed multiplier (0.25 – 4.0).",
        ge=0.25,
        le=4.0,
    )
    save: bool = Field(
        default=False,
        description=(
            "When true, the generated audio is saved to "
            "/data/audio/dispatch_intro_cached.wav so the live dispatch pipeline "
            "reuses it automatically on the next detection event."
        ),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/upload-intro",
    summary="Upload custom dispatch channel intro audio",
    description=(
        "Accepts a WAV or MP3 file and saves it as the custom dispatch channel intro. "
        "The file is stored at /config/audio/dispatch_intro.wav (persists across "
        "container restarts). Once saved, set response_mode.dispatch.intro_audio to "
        "/config/audio/dispatch_intro.wav in config.yaml to activate it. "
        "No VoxWatch restart required — the file is checked at runtime on each event."
    ),
    responses={
        200: {"description": "File accepted and saved successfully"},
        400: {"description": "Not a recognised audio file (bad magic bytes or too large)"},
        500: {"description": "Server-side I/O error when saving the file"},
    },
    status_code=status.HTTP_200_OK,
)
async def upload_intro_audio(file: UploadFile) -> dict:
    """Accept a multipart audio upload and save it as the dispatch channel intro.

    The upload is validated before writing:

    1. **Size check** — file content is read up to ``_INTRO_UPLOAD_MAX_BYTES``
       (10 MB). Files that exceed this limit are rejected with HTTP 400.
    2. **Magic-byte check** — the first 8 bytes are inspected to confirm the
       upload is a recognised audio container (WAV, MP3, OGG, FLAC).  A
       mismatched ``Content-Type`` header alone is not trusted.

    On success the raw upload bytes are written to
    ``/config/audio/dispatch_intro.wav``.  The config volume ensures the
    file survives container restarts.

    To activate the uploaded file:

    * Set ``response_mode.dispatch.intro_audio`` to
      ``/config/audio/dispatch_intro.wav`` in the dashboard.
    * Or update ``config.yaml`` directly and hot-reload.
    * No VoxWatch restart is needed — ``generate_channel_intro`` reads the
      path at runtime on each detection event.

    Args:
        file: FastAPI ``UploadFile`` from the ``multipart/form-data`` body.
              Must contain a valid audio file (WAV or MP3 recommended).

    Returns:
        Dict with ``{"success": True, "path": ..., "size_bytes": ...,
        "format": ...}`` on success.

    Raises:
        HTTPException 400: If the file exceeds the size limit or fails the
            magic-byte check (not a recognised audio format).
        HTTPException 500: If the destination directory cannot be created or
            the file cannot be written.
    """
    # Read the entire upload into memory to validate and write atomically.
    # Limiting to _INTRO_UPLOAD_MAX_BYTES prevents OOM from giant uploads.
    raw_bytes: bytes = await file.read(_INTRO_UPLOAD_MAX_BYTES + 1)
    if len(raw_bytes) > _INTRO_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File too large. Maximum allowed size is "
                f"{_INTRO_UPLOAD_MAX_BYTES // (1024 * 1024)} MB."
            ),
        )

    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Validate magic bytes — do not trust Content-Type alone.
    fmt = _detect_audio_format(raw_bytes[:8])
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Uploaded file does not appear to be a recognised audio format. "
                "Please upload a WAV, MP3, OGG, or FLAC file."
            ),
        )

    # Ensure destination directory exists.
    dest_path = Path(_INTRO_UPLOAD_DEST)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(
            "upload-intro: cannot create destination directory %s: %s",
            dest_path.parent,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Server error: could not create destination directory "
                f"{dest_path.parent}. Check volume mounts."
            ),
        ) from exc

    # Write atomically via a temp file in the same directory, then rename.
    # This prevents a partial write from corrupting an existing good file.
    tmp_dest = dest_path.parent / (dest_path.name + ".tmp")
    try:
        tmp_dest.write_bytes(raw_bytes)
        tmp_dest.rename(dest_path)
    except OSError as exc:
        logger.error("upload-intro: could not write file to %s: %s", dest_path, exc)
        try:
            tmp_dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server error: could not write audio file to {dest_path}.",
        ) from exc

    logger.info(
        "upload-intro: saved %s intro (%d bytes) → %s",
        fmt,
        len(raw_bytes),
        dest_path,
    )

    return {
        "success": True,
        "path": str(dest_path),
        "size_bytes": len(raw_bytes),
        "format": fmt,
        "message": (
            f"Custom intro audio saved ({len(raw_bytes)} bytes). "
            f"Set response_mode.dispatch.intro_audio to {dest_path} to activate it."
        ),
    }


@router.post(
    "/generate-intro",
    summary="Generate and optionally save a dispatch channel intro",
    description=(
        "Synthesises a dispatch intro phrase using the requested TTS provider and voice, "
        "streams the WAV back for in-browser preview, and optionally saves it to "
        "/data/audio/dispatch_intro_cached.wav for reuse by the live dispatch pipeline. "
        "Proxies to the VoxWatch Preview API (port 8892) which has access to all "
        "local TTS providers. Cloud providers (ElevenLabs, OpenAI, Cartesia) are "
        "handled locally so no VoxWatch service connection is required for cloud TTS."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"audio/wav": {}},
            "description": (
                "Raw WAV audio for browser playback. "
                "X-Intro-Saved header is 'true' when save=true succeeded."
            ),
        },
        400: {"description": "Bad request (empty text, invalid provider)"},
        502: {"description": "Remote TTS server or VoxWatch Preview API error"},
        503: {"description": "Local TTS binary unavailable"},
    },
)
async def generate_intro_audio(request: GenerateIntroRequest) -> StreamingResponse:
    """Generate a dispatch channel intro with the specified TTS provider and voice.

    This endpoint proxies to the VoxWatch Preview API (``POST
    /api/preview/generate-intro``) which runs inside the VoxWatch service
    container and has direct access to local TTS providers (Kokoro, Piper,
    espeak).  If the VoxWatch service is unreachable, cloud providers
    (ElevenLabs, OpenAI, Cartesia) are attempted locally using the dashboard's
    own synthesis helpers.

    When ``save=true`` the VoxWatch service writes the generated audio to
    ``/data/audio/dispatch_intro_cached.wav``.  This file is shared between
    the VoxWatch and Dashboard containers via a Docker volume, so the live
    dispatch pipeline (``generate_channel_intro`` Priority 2) picks it up
    automatically on the next detection event — no config change or restart
    needed.

    The ``{agency}`` token in ``text`` is substituted on the VoxWatch side
    using the currently saved agency config.

    Args:
        request: GenerateIntroRequest with text, provider, voice, speed, save.

    Returns:
        StreamingResponse with WAV audio and headers:
        - ``X-Generation-Time``: synthesis latency in milliseconds.
        - ``X-Intro-Saved``: "true" when save=true and the file was written.

    Raises:
        400: If text is empty or provider is unsupported.
        502: If the remote TTS API returned an error.
        503: If the required local TTS binary is not installed.
    """
    # Attempt to proxy to VoxWatch Preview API first (handles all local TTS).
    # _get_voxwatch_preview_url() returns "http://host:port/api/preview" —
    # we derive the generate-intro URL from the same host/port.
    voxwatch_preview_url = await _get_voxwatch_preview_url()
    # Strip the trailing endpoint path and append the generate-intro route.
    voxwatch_base = voxwatch_preview_url.rsplit("/api/", 1)[0]
    voxwatch_intro_url = f"{voxwatch_base}/api/preview/generate-intro"

    payload: dict = {
        "text": request.text,
        "speed": request.speed,
        "save": request.save,
    }
    if request.provider:
        payload["provider"] = request.provider
    if request.voice:
        payload["voice"] = request.voice

    t_start = time.monotonic()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                voxwatch_intro_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30.0),
            ) as resp:
                if resp.status == 200:
                    wav_bytes = await resp.read()
                    elapsed_ms = int((time.monotonic() - t_start) * 1000)
                    saved = resp.headers.get("X-Intro-Saved", "false")
                    logger.info(
                        "generate-intro: VoxWatch proxy returned %d bytes "
                        "in %d ms (saved=%s)",
                        len(wav_bytes),
                        elapsed_ms,
                        saved,
                    )
                    return StreamingResponse(
                        content=iter([wav_bytes]),
                        media_type="audio/wav",
                        headers={
                            "X-Generation-Time": str(elapsed_ms),
                            "X-Intro-Saved": saved,
                        },
                    )
                # Non-200 from VoxWatch — fall through to local synthesis.
                body_text = await resp.text()
                logger.warning(
                    "generate-intro: VoxWatch Preview API returned HTTP %d: %s — "
                    "falling back to local cloud synthesis.",
                    resp.status,
                    body_text[:200],
                )
    except (TimeoutError, aiohttp.ClientConnectorError) as exc:
        logger.info(
            "generate-intro: VoxWatch Preview API unreachable (%s) — "
            "falling back to local cloud synthesis.",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "generate-intro: VoxWatch proxy error: %s — "
            "falling back to local cloud synthesis.",
            exc,
        )

    # ── Local cloud synthesis fallback ───────────────────────────────────────
    # Substitute {agency} from saved config ourselves since VoxWatch is down.
    intro_text = request.text
    try:
        cfg = await config_service.get_raw_config()
        rm = cfg.get("response_mode", cfg.get("persona", {}))
        agency = rm.get("dispatch", {}).get("agency", "").strip()
        intro_text = request.text.format(agency=agency)
    except (KeyError, ValueError, Exception):
        pass  # Use verbatim on any failure.

    provider = (request.provider or "").lower()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if provider == "elevenlabs":
            api_key = await _resolve_cloud_tts_key("elevenlabs_api_key")
            if not api_key:
                raise HTTPException(status_code=400, detail="No ElevenLabs API key configured")
            await _synthesize_elevenlabs(
                message=intro_text,
                api_key=api_key,
                voice_id=request.voice or "pNInz6obpgDQGcFmaJgB",
                model="eleven_flash_v2_5",
                output_path=tmp_path,
            )

        elif provider == "openai":
            api_key = await _resolve_cloud_tts_key("openai_api_key")
            if not api_key:
                raise HTTPException(status_code=400, detail="No OpenAI API key configured")
            await _synthesize_openai_tts(
                message=intro_text,
                api_key=api_key,
                voice=request.voice or "nova",
                model="tts-1",
                speed=request.speed,
                output_path=tmp_path,
            )

        elif provider == "cartesia":
            api_key = await _resolve_cloud_tts_key("cartesia_api_key")
            if not api_key:
                raise HTTPException(status_code=400, detail="No Cartesia API key configured")
            await _synthesize_cartesia(
                message=intro_text,
                api_key=api_key,
                voice_id=request.voice or "",
                output_path=tmp_path,
            )

        elif provider == "espeak":
            wpm = int(min(450, max(80, 175 * request.speed)))
            await _synthesize_espeak(
                message=intro_text,
                speed=wpm,
                pitch=50,
                output_path=tmp_path,
            )

        else:
            # VoxWatch is down and no cloud provider was requested — we cannot
            # serve local TTS providers (Kokoro/Piper) without VoxWatch.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "VoxWatch Preview API is unreachable. "
                    "Local TTS providers (kokoro, piper) require the VoxWatch "
                    "service to be running. Use a cloud provider (elevenlabs, "
                    "openai, cartesia) or start VoxWatch."
                ),
            )

        # Optionally save the generated intro to the shared data volume.
        saved_flag = "false"
        if request.save:
            cached_dir = Path(_CACHED_INTRO_PATH).parent
            try:
                cached_dir.mkdir(parents=True, exist_ok=True)
                import shutil as _shutil
                _shutil.copy2(tmp_path, _CACHED_INTRO_PATH)
                saved_flag = "true"
                logger.info(
                    "generate-intro (local): saved cached intro to %s",
                    _CACHED_INTRO_PATH,
                )
            except OSError as exc:
                logger.warning(
                    "generate-intro (local): could not save to %s: %s — preview OK.",
                    _CACHED_INTRO_PATH,
                    exc,
                )

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        wav_bytes = Path(tmp_path).read_bytes()

        logger.info(
            "generate-intro (local cloud): provider=%s bytes=%d elapsed_ms=%d saved=%s",
            provider,
            len(wav_bytes),
            elapsed_ms,
            saved_flag,
        )

        return StreamingResponse(
            content=iter([wav_bytes]),
            media_type="audio/wav",
            headers={
                "X-Generation-Time": str(elapsed_ms),
                "X-Intro-Saved": saved_flag,
            },
        )

    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
