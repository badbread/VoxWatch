"""analysis.py — AI analysis orchestration for VoxWatch.

Public API:
    analyze_snapshots(images, prompt, config) -> str
    analyze_video(video_bytes, prompt, config, fallback_images) -> str
    check_person_still_present(config, camera_name) -> bool
    get_last_ai_error() -> str

Internal state:
    _last_ai_error: str  — populated on provider failure, cleared on success.

This module is the orchestration layer that calls provider implementations
from the ``providers`` sub-package and handles primary/fallback routing,
error recording, and the Frigate person-presence check.
"""

import logging
import time as _time

import aiohttp

from .providers import _dispatch_snapshot_call
from .providers.gemini import _call_gemini_video
from .session import _get_session
from .snapshots import _frigate_base_url

logger = logging.getLogger("voxwatch.ai_vision")

# ── Last AI analysis error ─────────────────────────────────────────────────────
# Populated when the primary and fallback providers both fail and a generic
# description is returned instead.  Read by the service layer to publish MQTT
# error events.  Reset to "" on every successful analysis so callers can
# distinguish transient failures from persistent ones.
_last_ai_error: str = ""


def get_last_ai_error() -> str:
    """Return the last AI analysis error, or empty string if last analysis succeeded.

    The error string is set whenever both the primary and fallback AI providers
    fail (or when Frigate returns no snapshots).  It is cleared to an empty
    string on any successful AI analysis.

    Intended for use by the service layer to publish structured MQTT error
    events without changing the return type of ``analyze_snapshots``.

    Returns:
        A human-readable error string describing the failure, or ``""`` if the
        most recent analysis completed without error.
    """
    return _last_ai_error


async def analyze_snapshots(
    images: list[bytes],
    prompt: str,
    config: dict,
) -> str:
    """Analyse a list of JPEG snapshots with AI and return a text description.

    Tries the primary provider first, then falls back to the fallback provider
    if the primary fails or is not configured.  All providers are supported for
    snapshot analysis; Ollama is single-image only (uses the last frame).

    Provider routing reads ``config["ai"]["primary"]["provider"]`` and
    ``config["ai"]["fallback"]["provider"]``.  Supported values: ``gemini``,
    ``openai``, ``grok``, ``anthropic``, ``ollama``, ``custom``.

    Args:
        images: List of raw JPEG bytes.  Must contain at least one image.
        prompt: Instruction for the AI (e.g. STAGE2_PROMPT or STAGE3_PROMPT).
        config: Full VoxWatch config dict.

    Returns:
        AI-generated description string.  Returns a safe default message if
        all providers fail so the pipeline can continue.
    """
    global _last_ai_error

    if not images:
        logger.warning("analyze_snapshots called with no images")
        # Record the no-snapshot condition so the service layer can emit an MQTT
        # error event.  The camera_name is not available here, so keep the message
        # generic; callers that know the camera name should set _last_ai_error
        # directly after a failed grab_snapshots call returns an empty list.
        _last_ai_error = "No snapshots available from Frigate — image fetch returned empty list"
        return "A person was detected but could not be described."

    ai_cfg = config.get("ai", {})

    # Track per-role errors so we can compose a combined error string when both fail.
    primary_provider: str = ""
    primary_error: str = ""
    fallback_provider: str = ""
    fallback_error: str = ""

    # Try primary provider, then fall back.
    for role in ("primary", "fallback"):
        provider_cfg = ai_cfg.get(role, {})
        if not provider_cfg:
            continue

        provider: str = provider_cfg.get("provider", "gemini")
        api_key: str = provider_cfg.get("api_key", "")
        model: str = provider_cfg.get("model", "")
        timeout: int = provider_cfg.get("timeout_seconds", 8)

        # Skip providers whose API key is a bare placeholder (unresolved env var).
        if provider != "ollama" and (not api_key or api_key.startswith("${")):
            logger.warning(
                "%s provider %r has no valid API key — skipping", role, provider
            )
            continue

        try:
            result = await _dispatch_snapshot_call(
                images, prompt, provider, provider_cfg, api_key, model, timeout
            )
            logger.info("%s provider %r snapshot analysis succeeded", role, provider)
            # Clear any previous error — this analysis succeeded.
            _last_ai_error = ""
            return result
        except Exception as exc:
            exc_str = str(exc)
            if role == "primary":
                primary_provider = provider
                primary_error = exc_str
                logger.warning(
                    "Primary provider %r snapshot analysis failed: %s — trying fallback",
                    provider, exc,
                )
            else:
                fallback_provider = provider
                fallback_error = exc_str
                logger.error(
                    "Fallback provider %r snapshot analysis also failed: %s",
                    provider, exc,
                )

    # Both providers failed (or were not configured) — record the combined error.
    if primary_provider and fallback_provider:
        _last_ai_error = (
            f"Primary ({primary_provider}): {primary_error}; "
            f"Fallback ({fallback_provider}): {fallback_error}"
        )
    elif primary_provider:
        _last_ai_error = f"Primary ({primary_provider}): {primary_error}"
    elif fallback_provider:
        _last_ai_error = f"Fallback ({fallback_provider}): {fallback_error}"
    else:
        _last_ai_error = "No AI providers configured or all have invalid API keys"

    return "A person was detected on camera."


async def analyze_video(
    video_bytes: bytes,
    prompt: str,
    config: dict,
    fallback_images: list[bytes] | None = None,
) -> str:
    """Analyse an MP4 video clip with AI and return a text description.

    Only Gemini natively supports video analysis.  All other providers
    (OpenAI, Grok, Anthropic, Ollama, custom) do not accept video and will
    automatically trigger a fallback to snapshot analysis when they are
    configured as the primary provider.

    Provider selection:
      1. If primary provider is ``gemini``: upload the video to the Gemini
         Files API and analyse it directly.
      2. If primary provider is anything else, or if Gemini video fails:
         fall back to ``analyze_snapshots`` using ``fallback_images`` (if
         ``stage3.fallback_to_snapshots`` is enabled in config).
      3. If no snapshot fallback is available: return a safe default string.

    Args:
        video_bytes: Raw MP4 bytes from ``grab_video_clip``.
        prompt: Instruction for the AI (e.g. STAGE3_PROMPT).
        config: Full VoxWatch config dict.
        fallback_images: Optional list of JPEG bytes to use when the primary
            provider does not support video, or when Gemini video fails.

    Returns:
        AI-generated description string.
    """
    primary_cfg = config.get("ai", {}).get("primary", {})
    provider: str = primary_cfg.get("provider", "gemini")

    # Only Gemini supports direct video analysis.  For every other provider
    # we skip straight to snapshot fallback and log an informational note so
    # users understand why the video is not being analysed directly.
    _VIDEO_CAPABLE_PROVIDERS = {"gemini"}

    if provider not in _VIDEO_CAPABLE_PROVIDERS:
        logger.info(
            "Primary provider %r does not support video analysis — "
            "using snapshot fallback for Stage 3",
            provider,
        )
    else:
        # --- Primary: Gemini video upload ---
        api_key: str = primary_cfg.get("api_key", "")
        if api_key and not api_key.startswith("${"):
            try:
                result = await _call_gemini_video(video_bytes, prompt, config)
                logger.info("Gemini video analysis succeeded")
                return result
            except Exception as exc:
                logger.warning(
                    "Gemini video analysis failed: %s — falling back to snapshots", exc
                )
        else:
            logger.warning(
                "Gemini API key not configured — skipping video analysis"
            )

    # --- Fallback: snapshot analysis ---
    # All non-video-capable providers and any Gemini failure end up here.
    stage3_cfg = config.get("stage3", {})
    if stage3_cfg.get("fallback_to_snapshots", True) and fallback_images:
        logger.info("Falling back to snapshot analysis for Stage 3")
        return await analyze_snapshots(fallback_images, prompt, config)

    # --- Last resort: no snapshots available ---
    logger.warning("No fallback images available for Stage 3 analysis")
    return "The person's actions could not be fully analysed."


async def check_person_still_present(config: dict, camera_name: str) -> bool:
    """Query Frigate to determine whether a person is currently detected on a camera.

    Calls the Frigate current events API, which returns the set of active
    (ongoing, not yet ended) events.  We check whether any of them are for
    the target camera and have the label "person".

    This is used before Stage 3 to avoid wasting time on AI analysis and
    TTS generation if the intruder has already left.

    Uses the module-level shared aiohttp session (see ``_get_session``).

    Args:
        config: Full VoxWatch config dict.
        camera_name: Frigate camera name (e.g. "frontdoor").

    Returns:
        True if Frigate reports an active person detection on that camera.
        Returns False on any error so the pipeline can continue safely.
    """
    base = _frigate_base_url(config)

    # Frigate 0.17 closes events quickly (16-66s) and reopens new ones.
    # The end_time is ALWAYS set within seconds even if the person is still
    # standing there. So checking for end_time=None is unreliable.
    #
    # Strategy: check if any person event ended within the last 30 seconds
    # OR is still active. If yes, the person is likely still there.
    # This catches both rapid event cycling and genuinely active events.
    events_url = (
        f"{base}/api/events"
        f"?camera={camera_name}&label=person&limit=5"
    )

    # Short timeout — this check is on the critical latency path.
    http_timeout = aiohttp.ClientTimeout(total=5)

    try:
        session = await _get_session()
        now = _time.time()

        async with session.get(events_url, timeout=http_timeout) as resp:
            if resp.status != 200:
                logger.warning("Frigate events API returned HTTP %d for camera %s",
                               resp.status, camera_name)
                # Default to True (assume present) so Stage 3 still fires.
                # False negatives are worse than false positives here.
                return True

            events = await resp.json()

            for e in events:
                if e.get("label") != "person":
                    continue

                end_time = e.get("end_time")

                # Still active (no end_time) — person definitely there
                if end_time is None:
                    logger.info("Person still present on %s (active event %s)",
                                camera_name, str(e.get("id", "?"))[:12])
                    return True

                # Event ended recently — person likely still there.
                # Frigate cycles events rapidly, so a 30s recency window
                # accounts for the gap between event close and next event open.
                seconds_ago = now - end_time
                if seconds_ago < 30:
                    logger.info(
                        "Person likely still present on %s (event ended %.1fs ago)",
                        camera_name, seconds_ago,
                    )
                    return True

            logger.info("No recent person events on %s — person likely left",
                        camera_name)
            return False

    except TimeoutError:
        logger.warning("Timed out checking person presence on %s", camera_name)
        return False
    except aiohttp.ClientError as exc:
        logger.warning("Network error checking person presence: %s", exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error in check_person_still_present: %s", exc)
        return False
