"""snapshots.py — Frigate snapshot and video-clip fetching for VoxWatch.

Public API:
    grab_snapshots(config, event_id, camera_name, count, interval_ms) -> list[bytes]
    grab_video_clip(config, event_id, duration_seconds) -> bytes | None

Internal helpers:
    _fetch_image(session, url, label, timeout) -> bytes | None
    _frigate_base_url(config) -> str
"""

import asyncio
import logging

import aiohttp

from .session import _get_session

logger = logging.getLogger("voxwatch.ai_vision")


def _frigate_base_url(config: dict) -> str:
    """Build the Frigate API base URL from the config dict.

    Reads ``config["frigate"]["host"]`` and ``config["frigate"].get("port", 5000)``
    and assembles them into an ``http://host:port`` string.

    This helper centralises the URL construction that previously appeared as
    three identical inline blocks across ``grab_snapshots``, ``grab_video_clip``,
    and ``check_person_still_present``. Any future change to the scheme or
    path prefix only needs to happen here.

    Args:
        config: Full VoxWatch config dict (must contain a ``frigate`` section
            with at least a ``host`` key).

    Returns:
        Base URL string, e.g. ``"http://192.168.1.10:5000"``.
    """
    frigate_cfg = config["frigate"]
    host = frigate_cfg["host"]
    port = frigate_cfg.get("port", 5000)
    return f"http://{host}:{port}"


async def _fetch_image(
    session: aiohttp.ClientSession,
    url: str,
    label: str = "image",
    timeout: aiohttp.ClientTimeout | None = None,
) -> bytes | None:
    """Fetch a JPEG image from a URL using an existing aiohttp session.

    Intended for internal use only.  A per-request ``timeout`` may be supplied
    to override the session default for this individual call.

    Args:
        session: Active aiohttp.ClientSession to reuse.
        url: Full URL to fetch.
        label: Human-readable description for log messages.
        timeout: Optional per-request timeout.  If None, the session's default
            timeout is used.

    Returns:
        Raw image bytes, or None if the fetch failed.
    """
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.read()
                logger.debug("Fetched %s: %d bytes", label, len(data))
                return data
            else:
                logger.warning("HTTP %d fetching %s from %s", resp.status, label, url)
                return None
    except TimeoutError:
        logger.warning("Timed out fetching %s from %s", label, url)
        return None
    except aiohttp.ClientError as exc:
        logger.warning("Network error fetching %s: %s", label, exc)
        return None


async def grab_snapshots(
    config: dict,
    event_id: str,
    camera_name: str,
    count: int,
    interval_ms: int,
) -> list[bytes]:
    """Fetch a series of JPEG snapshots from Frigate for an event.

    The first snapshot is pulled from the event's canonical snapshot endpoint,
    which is the best still Frigate has captured for that event.  Subsequent
    snapshots are pulled from the camera's "latest" endpoint at ``interval_ms``
    milliseconds apart so we capture the person at different moments.

    Uses the module-level shared aiohttp session (see ``_get_session``).
    A per-call ``aiohttp.ClientTimeout`` is set on each individual request
    rather than on the session itself, so this function does not interfere with
    timeouts used by concurrent calls on the same session.

    Args:
        config: Full VoxWatch config dict.
        event_id: Frigate event ID string (e.g. "1716400000.123456-abc123").
        camera_name: Frigate camera name (e.g. "frontdoor").
        count: Total number of snapshots to collect.
        interval_ms: Milliseconds to wait between each additional snapshot.

    Returns:
        List of raw JPEG bytes.  May be shorter than ``count`` if any
        individual fetch fails — the caller should handle an empty list
        gracefully.
    """
    base_url = _frigate_base_url(config)

    # AI timeout drives how long we wait per image fetch.
    # Use the longer of the two provider timeouts so we don't bail early.
    ai_timeout = max(
        config.get("ai", {}).get("primary", {}).get("timeout_seconds", 5),
        config.get("ai", {}).get("fallback", {}).get("timeout_seconds", 8),
    )
    http_timeout = aiohttp.ClientTimeout(total=ai_timeout)

    images: list[bytes] = []

    session = await _get_session()

    # --- First snapshot: event snapshot endpoint ---
    # Frigate stores the highest-quality still for the event here.
    event_url = f"{base_url}/api/events/{event_id}/snapshot.jpg"
    snapshot = await _fetch_image(session, event_url, label="event snapshot",
                                  timeout=http_timeout)
    if snapshot:
        images.append(snapshot)
    else:
        logger.warning("Could not fetch event snapshot for %s", event_id)

    # --- Additional snapshots: camera latest endpoint ---
    # We poll the live camera feed to capture the person in motion.
    latest_url = f"{base_url}/api/{camera_name}/latest.jpg"
    for i in range(1, count):
        # Wait before each additional fetch so frames are meaningfully different.
        await asyncio.sleep(interval_ms / 1000.0)
        frame = await _fetch_image(session, latest_url,
                                   label=f"latest frame {i}/{count - 1}",
                                   timeout=http_timeout)
        if frame:
            images.append(frame)

    logger.info("Grabbed %d/%d snapshots for event %s", len(images), count, event_id)
    return images


async def grab_video_clip(
    config: dict,
    event_id: str,
    duration_seconds: int,
) -> bytes | None:
    """Download an MP4 video clip from Frigate for a specific event.

    Frigate generates a clip for an event once sufficient footage has been
    buffered.  If the clip is not yet available (HTTP 404) or the download
    fails, we return None and the caller should fall back to snapshots.

    Uses the module-level shared aiohttp session (see ``_get_session``).

    Args:
        config: Full VoxWatch config dict.
        event_id: Frigate event ID string.
        duration_seconds: Expected clip length (used only for logging context;
            Frigate controls the actual clip duration based on its own config).

    Returns:
        Raw MP4 bytes, or None if the clip could not be fetched.
    """
    clip_url = f"{_frigate_base_url(config)}/api/events/{event_id}/clip.mp4"

    # Video clips can be several megabytes — allow more time than for images.
    timeout_seconds = config.get("stage3", {}).get("video_clip_seconds", 5) + 10
    http_timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    logger.info("Fetching video clip for event %s (%ds expected)", event_id, duration_seconds)

    try:
        session = await _get_session()
        async with session.get(clip_url, timeout=http_timeout) as resp:
            if resp.status == 200:
                data = await resp.read()
                logger.info("Video clip fetched: %d bytes", len(data))
                return data
            elif resp.status == 404:
                # Clip not yet generated — this is normal for very recent events.
                logger.warning("Video clip not ready yet (HTTP 404) for event %s",
                               event_id)
                return None
            else:
                logger.error("Unexpected HTTP %d fetching clip for event %s",
                             resp.status, event_id)
                return None
    except TimeoutError:
        logger.error("Timed out fetching video clip for event %s (timeout=%ds)",
                     event_id, timeout_seconds)
        return None
    except aiohttp.ClientError as exc:
        logger.error("Network error fetching video clip: %s", exc)
        return None
