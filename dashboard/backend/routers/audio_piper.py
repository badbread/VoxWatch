"""
audio_piper.py — Piper Voice Model Management Sub-Router

Handles:
    GET    /api/audio/piper-voices                  — List installed and available Piper models
    DELETE /api/audio/piper-voices/{model_name}     — Delete a downloaded Piper model

Two directories are scanned for installed .onnx model files:
    /usr/share/piper-voices/  — baked into the Docker image ("builtin")
    /data/piper-voices/       — auto-downloaded at runtime ("downloaded")

Results are merged with a known voice list so the frontend can display
friendly labels and descriptions even for voices that are not yet installed.
Any .onnx files found on disk that are not in the known list are also returned
so manually-added models are visible.

The DELETE endpoint only removes files from the downloaded cache directory.
Builtin voices cannot be deleted (they live in the image layer).  The delete
operation is proxied to the VoxWatch Preview API because the dashboard
container mounts /data as read-only.
"""

import logging
import re
from pathlib import Path

import aiohttp
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.config import DATA_DIR
from backend.routers._audio_utils import _get_voxwatch_preview_url

logger = logging.getLogger("dashboard.router.audio.piper")

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

#: Friendly label and description for every known Piper voice.
#: Voices absent from this dict are still surfaced if the .onnx exists on disk.
_PIPER_VOICE_INFO: dict[str, tuple[str, str]] = {
    "en_US-lessac-medium": ("Lessac (Medium)", "Clear American male. Balanced quality and speed."),
    "en_US-lessac-high": ("Lessac (High)", "Same voice, higher quality. Slower to generate."),
    "en_US-lessac-low": ("Lessac (Low)", "Same voice, fastest generation. Lower quality."),
    "en_US-ryan-medium": ("Ryan (Medium)", "Deep American male. Authoritative tone."),
    "en_US-ryan-high": ("Ryan (High)", "Same voice, higher quality. Good for security warnings."),
    "en_US-amy-medium": ("Amy (Medium)", "American female. Clear and professional."),
    "en_US-arctic-medium": ("Arctic (Medium)", "Neutral American. Clean and steady."),
    "en_GB-alan-medium": ("Alan (Medium)", "British male. Formal tone."),
    "en_GB-jenny_dioco-medium": ("Jenny (Medium)", "British female. Warm and clear."),
    "en_GB-cori-medium": ("Cori (Medium)", "British female. Professional newsreader style."),
    "hal9000": ("HAL 9000", "Calm, monotone AI voice."),
}

#: Directory containing voices baked into the Docker image (read-only).
_PIPER_BUILTIN_DIR = Path("/usr/share/piper-voices")

#: Regex reused from _CAMERA_NAME_RE — model names follow the same safe-name rules.
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_model_name(model_name: str) -> None:
    """Raise HTTP 400 if *model_name* contains characters outside the safe set.

    Model names are interpolated into filesystem paths.  Without validation a
    crafted name (e.g. ``../../etc/passwd``) could escape the voice directory
    and delete arbitrary files on the host.

    Args:
        model_name: The Piper model name string to validate.

    Raises:
        HTTPException 400: If the name contains any disallowed characters.
    """
    if not _MODEL_NAME_RE.match(model_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid model name {model_name!r}. "
                "Model names may only contain letters, digits, underscores, "
                "and hyphens (pattern: ^[a-zA-Z0-9_-]+$)."
            ),
        )


def _scan_onnx_dir(directory: Path, source: str) -> dict[str, dict]:
    """Scan *directory* for .onnx files and return a dict keyed by model name.

    The model name is the filename stem with the ``.onnx`` suffix stripped
    (e.g. ``en_US-lessac-medium.onnx`` -> ``en_US-lessac-medium``).

    Args:
        directory: Filesystem path to scan.  May not exist; returns empty dict.
        source: Source tag to attach to each entry ("builtin" or "downloaded").

    Returns:
        Dict mapping model name to a partial voice info dict with keys
        ``installed``, ``size_mb``, and ``source``.
    """
    found: dict[str, dict] = {}
    if not directory.exists():
        return found

    for onnx_path in directory.glob("*.onnx"):
        model_name = onnx_path.name[: -len(".onnx")]
        try:
            size_bytes = onnx_path.stat().st_size
            size_mb = round(size_bytes / (1024 * 1024), 1)
        except OSError:
            size_mb = None
        found[model_name] = {
            "installed": True,
            "size_mb": size_mb,
            "source": source,
        }

    return found


# ── Models ────────────────────────────────────────────────────────────────────


class PiperVoiceInfo(BaseModel):
    """Details for a single Piper TTS voice model."""

    id: str = Field(description="Model identifier used with --model flag (e.g. 'en_US-lessac-medium').")
    label: str = Field(description="Human-readable voice name (e.g. 'Lessac (Medium)').")
    desc: str = Field(description="Short description of the voice character and quality.")
    installed: bool = Field(description="True if the .onnx file is present on disk.")
    size_mb: float | None = Field(
        default=None,
        description="File size of the .onnx model in megabytes. Null if not installed.",
    )
    source: str = Field(
        description=(
            "Where the model lives: 'builtin' (in Docker image), "
            "'downloaded' (auto-cached in /data/piper-voices/), "
            "or 'available' (known but not yet installed)."
        )
    )


class PiperVoiceListResponse(BaseModel):
    """Response from GET /api/audio/piper-voices."""

    voices: list[PiperVoiceInfo] = Field(
        description="All known and/or installed Piper voice models."
    )
    builtin_dir: str = Field(
        description="Path scanned for builtin voices (baked into Docker image).",
    )
    downloaded_dir: str = Field(
        description="Path scanned for downloaded voices (runtime cache).",
    )


class DeletePiperVoiceResponse(BaseModel):
    """Response from DELETE /api/audio/piper-voices/{model_name}."""

    ok: bool = Field(description="True if the model was successfully deleted.")
    message: str = Field(description="Human-readable result or error description.")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/piper-voices",
    response_model=PiperVoiceListResponse,
    summary="List installed and available Piper TTS voice models",
    description=(
        "Scans two directories for installed .onnx model files: "
        "/usr/share/piper-voices/ (builtin, baked into Docker image) and "
        "/data/piper-voices/ (downloaded at runtime). "
        "Results are merged with a known voice list so friendly labels are "
        "always available. Unknown .onnx files found on disk are also included."
    ),
    status_code=status.HTTP_200_OK,
)
async def list_piper_voices() -> PiperVoiceListResponse:
    """Enumerate installed and available Piper TTS voice models.

    Scans two voice directories and merges the results with the known voice
    list so the frontend can display friendly labels even for voices that are
    not yet downloaded.  Any .onnx files found on disk that are not in the
    known list are appended at the end so manually-added models are visible.

    The function is non-blocking: filesystem I/O is light (directory listing
    only) so it runs synchronously in the async handler without threadpool
    offloading.

    Returns:
        PiperVoiceListResponse with a list of PiperVoiceInfo entries and the
        two directory paths that were scanned.
    """
    downloaded_dir = Path(DATA_DIR) / "piper-voices"

    # Scan both directories.  Missing directories produce empty dicts without
    # raising an error — they simply mean no voices of that source are present.
    builtin_models = _scan_onnx_dir(_PIPER_BUILTIN_DIR, "builtin")
    downloaded_models = _scan_onnx_dir(downloaded_dir, "downloaded")

    # Merge: builtin takes precedence if the same model exists in both locations.
    all_installed: dict[str, dict] = {**downloaded_models, **builtin_models}

    voices: list[PiperVoiceInfo] = []

    # First pass: walk the known voice list to preserve canonical ordering and
    # attach labels/descriptions to installed models.
    for model_id, (label, desc) in _PIPER_VOICE_INFO.items():
        if model_id in all_installed:
            entry = all_installed[model_id]
            voices.append(
                PiperVoiceInfo(
                    id=model_id,
                    label=label,
                    desc=desc,
                    installed=True,
                    size_mb=entry["size_mb"],
                    source=entry["source"],
                )
            )
        else:
            # Known but not installed — shown as "available" for future download.
            voices.append(
                PiperVoiceInfo(
                    id=model_id,
                    label=label,
                    desc=desc,
                    installed=False,
                    size_mb=None,
                    source="available",
                )
            )

    # Second pass: surface any .onnx files that are not in the known list.
    # These are user-added models; we fabricate a label from the filename.
    known_ids = set(_PIPER_VOICE_INFO.keys())
    for model_id, entry in all_installed.items():
        if model_id not in known_ids:
            voices.append(
                PiperVoiceInfo(
                    id=model_id,
                    label=model_id,  # no better label available
                    desc="Custom model — not in the known voice list.",
                    installed=True,
                    size_mb=entry["size_mb"],
                    source=entry["source"],
                )
            )

    logger.debug(
        "piper-voices: scanned builtin=%d downloaded=%d total=%d",
        len(builtin_models),
        len(downloaded_models),
        len(voices),
    )

    return PiperVoiceListResponse(
        voices=voices,
        builtin_dir=str(_PIPER_BUILTIN_DIR),
        downloaded_dir=str(downloaded_dir),
    )


@router.delete(
    "/piper-voices/{model_name}",
    response_model=DeletePiperVoiceResponse,
    summary="Delete a downloaded Piper TTS voice model",
    description=(
        "Removes a downloaded voice model from /data/piper-voices/. "
        "Both the .onnx model file and its .onnx.json config file are deleted. "
        "Builtin voices (in /usr/share/piper-voices/) cannot be deleted — "
        "those are baked into the Docker image. "
        "Returns 403 if the model is builtin, 404 if not found in the downloaded cache."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "model_name contains disallowed characters"},
        403: {"description": "Model is a builtin voice and cannot be deleted"},
        404: {"description": "Model not found in the downloaded voice cache"},
    },
)
async def delete_piper_voice(model_name: str) -> DeletePiperVoiceResponse:
    """Delete a downloaded Piper TTS voice model.

    Proxies the delete request to the VoxWatch Preview API because the
    dashboard container mounts /data as read-only.  The VoxWatch container
    has read-write access and handles the actual file deletion.

    Args:
        model_name: Piper model identifier (e.g. "en_US-ryan-high").
                    Must match ^[a-zA-Z0-9_-]+$.

    Returns:
        DeletePiperVoiceResponse with ok=True and a confirmation message.

    Raises:
        400: If model_name contains characters outside the safe set.
        403: If the model is a builtin voice.
        404: If the model is not found in the download cache.
    """
    _validate_model_name(model_name)

    # Proxy to VoxWatch Preview API which has read-write /data access.
    voxwatch_url = await _get_voxwatch_preview_url()
    # Replace /api/preview with /api/piper-voices/{model_name}
    base_url = voxwatch_url.rsplit("/api/preview", 1)[0]
    delete_url = f"{base_url}/api/piper-voices/{model_name}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                delete_url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise HTTPException(
                        status_code=resp.status,
                        detail=data.get("message", "Delete failed"),
                    )
                return DeletePiperVoiceResponse(
                    ok=data.get("ok", True),
                    message=data.get("message", "Voice deleted."),
                )
    except aiohttp.ClientConnectorError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VoxWatch service unreachable — cannot delete voice model.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_piper_voice: proxy error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
