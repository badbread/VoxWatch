"""telemetry.py — Dashboard telemetry helpers for VoxWatch.

This module owns all I/O that feeds the web dashboard:

  - ``write_status_file``: Atomically writes a JSON snapshot of the service's
    current state to ``/data/status.json`` so the dashboard always reads a
    complete file, never a partial write.
  - ``append_event_log``: Appends one JSON line per detection event to
    ``/data/events.jsonl`` in JSON Lines format for efficient streaming.
  - ``maybe_rotate_events``: Rotates the events file when it exceeds a size
    threshold, keeping one backup to bound disk usage.
  - ``ensure_camera_stats`` / ``record_detection`` / ``record_audio_push``:
    Manage the per-camera in-memory counters that are serialised into
    status.json by ``write_status_file``.

All functions are standalone (no class state) so they are easy to unit-test
and can be called from any part of the service that needs to record telemetry.

Atomic write strategy
---------------------
``write_status_file`` writes to a sibling temp file in the same directory,
then calls ``os.replace()`` to swap it in.  ``os.replace()`` is atomic on
POSIX (the dashboard either reads the old file or the new complete file) and
is best-effort on Windows (where it may fail if the destination is open, but
that edge case is logged rather than crashing).

Event log atomicity
-------------------
``append_event_log`` opens the file in ``"a"`` (append) mode.  On POSIX,
a single ``write()`` call with ``O_APPEND`` is atomic up to PIPE_BUF
(at least 512 bytes, usually 4096 or more), which is always larger than a
single JSON event line.  No explicit locking is needed for this single-writer
scenario.
"""

import contextlib
import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("voxwatch.telemetry")

# How large events.jsonl may grow before it is rotated (bytes).
# Roughly 10,000–20,000 events at typical description lengths.
# Exposed as a public name so callers can reference the default without
# hard-coding the magic number, and so config.py can use the same value as
# the default for the ``logging.events_max_bytes`` config key.
DEFAULT_EVENTS_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB


# ── Per-camera statistics helpers ────────────────────────────────────────────


def ensure_camera_stats(
    camera_stats: dict[str, dict[str, Any]], camera_name: str
) -> None:
    """Lazily initialise the stats bucket for a camera if it does not exist.

    Called before any read or write to ``camera_stats[camera_name]`` so we
    never encounter a KeyError when a camera is seen for the first time.

    The bucket shape is::

        {
            "total_detections": 0,
            "total_audio_pushes": 0,
            "last_detection_at": None,    # ISO 8601 UTC string once set
            "last_audio_push_success": None,  # bool once set
        }

    Args:
        camera_stats: The service's per-camera stats dict, keyed by camera name.
            Mutated in place if the camera is not already present.
        camera_name: The Frigate/go2rtc camera name to initialise.
    """
    if camera_name not in camera_stats:
        camera_stats[camera_name] = {
            "total_detections": 0,
            "total_audio_pushes": 0,
            "last_detection_at": None,
            "last_audio_push_success": None,
        }


def record_detection(
    camera_stats: dict[str, dict[str, Any]], camera_name: str, when: datetime
) -> None:
    """Increment the detection counter and update the last-detection timestamp.

    Called once per qualifying detection event — i.e., after all guards
    (enabled, active hours, cooldown) have passed — so the counter reflects
    events that actually triggered the pipeline, not every raw MQTT message.

    Args:
        camera_stats: Mutable per-camera stats dict (see ``ensure_camera_stats``).
        camera_name: The Frigate/go2rtc camera name that triggered.
        when: The UTC datetime of the detection.  Stored as an ISO 8601
            string (``%Y-%m-%dT%H:%M:%SZ``) in the stats dict.
    """
    ensure_camera_stats(camera_stats, camera_name)
    camera_stats[camera_name]["total_detections"] += 1
    camera_stats[camera_name]["last_detection_at"] = when.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def record_audio_push(
    camera_stats: dict[str, dict[str, Any]], camera_name: str, success: bool
) -> None:
    """Increment the audio-push counter and record whether the last push succeeded.

    Called after each audio push attempt (Stage 2 and optionally Stage 3).
    Only pushes that returned a definitive True/False are counted — stages
    that were skipped entirely (e.g. Stage 3 presence check failed) should
    not call this function.

    Args:
        camera_stats: Mutable per-camera stats dict (see ``ensure_camera_stats``).
        camera_name: The Frigate/go2rtc camera name.
        success: True if go2rtc accepted and played the audio, False otherwise.
    """
    ensure_camera_stats(camera_stats, camera_name)
    camera_stats[camera_name]["total_audio_pushes"] += 1
    camera_stats[camera_name]["last_audio_push_success"] = success


# ── Status file ───────────────────────────────────────────────────────────────


def write_status_file(
    config: dict[str, Any],
    data_dir: str,
    started_at: datetime | None,
    running: bool,
    camera_stats: dict[str, dict[str, Any]],
    cooldowns: dict[str, float],
    active_tasks_count: int,
    mqtt_connected: bool,
    active_hours_active: bool,
    service_version: str,
) -> None:
    """Snapshot the service's current state to ``<data_dir>/status.json`` atomically.

    Writes to a temporary file in the same directory, then calls ``os.replace``
    to swap it in.  The dashboard therefore always reads either the previous
    complete file or the new complete file — never a partial write.

    The output JSON has the following shape::

        {
          "service_running": true,
          "version": "0.2.0",
          "started_at": "2026-03-21T02:15:00Z",
          "mqtt_connected": true,
          "uptime_seconds": 3600,
          "active_hours_active": true,
          "cameras": {
            "frontdoor": {
              "enabled": true,
              "last_detection_at": "2026-03-21T03:42:15Z",
              "cooldown_until": null,
              "total_detections": 12,
              "total_audio_pushes": 11,
              "last_audio_push_success": true
            }
          }
        }

    ``cooldown_until`` is an ISO 8601 UTC string when the camera is currently
    in cooldown, or null if it is ready to fire.

    Args:
        config: Full VoxWatch config dict (used for camera list and cooldown
            duration).
        data_dir: Directory where ``status.json`` is written.
        started_at: UTC datetime when the service started, or None if not yet
            set (uptime will be reported as 0).
        running: True while the service is active; False during shutdown so the
            dashboard can show the service as stopped.
        camera_stats: Per-camera counters dict (see ``ensure_camera_stats``).
        cooldowns: Dict mapping camera_name -> ``time.monotonic()`` timestamp of
            the last trigger, used to compute ``cooldown_until``.
        active_tasks_count: Number of in-flight pipeline asyncio Tasks at the
            time of writing (informational).
        mqtt_connected: True if the paho MQTT client is currently connected.
        active_hours_active: True if the current time falls within the
            configured active-hours window.
        service_version: Version string (e.g. ``"0.2.0"``).
    """
    now = datetime.now(tz=UTC)

    # Compute uptime — guard against started_at not yet being set (belt-and-
    # suspenders; this should always be set before any write is requested).
    if started_at is not None:
        uptime_seconds = int((now - started_at).total_seconds())
        started_at_str = started_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        uptime_seconds = 0
        started_at_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Compute per-camera status blocks from the config + live state.
    conditions = config.get("conditions", {})
    cooldown_seconds = float(conditions.get("cooldown_seconds", 60))
    cameras_cfg = config.get("cameras", {})
    cameras_status: dict[str, dict] = {}

    for cam_name, cam_cfg in cameras_cfg.items():
        stats = camera_stats.get(cam_name, {})

        # Determine cooldown_until: if the camera fired recently, calculate
        # when the cooldown expires and express it as a UTC ISO string.
        cooldown_until: str | None = None
        last_trigger = cooldowns.get(cam_name)
        if last_trigger is not None:
            elapsed = time.monotonic() - last_trigger
            remaining = cooldown_seconds - elapsed
            if remaining > 0:
                expires_at = now + timedelta(seconds=remaining)
                cooldown_until = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        cameras_status[cam_name] = {
            "enabled": bool(cam_cfg.get("enabled", True)),
            "last_detection_at": stats.get("last_detection_at"),
            "cooldown_until": cooldown_until,
            "total_detections": stats.get("total_detections", 0),
            "total_audio_pushes": stats.get("total_audio_pushes", 0),
            "last_audio_push_success": stats.get("last_audio_push_success"),
        }

    payload: dict[str, Any] = {
        "service_running": running,
        "version": service_version,
        "started_at": started_at_str,
        "mqtt_connected": mqtt_connected,
        "uptime_seconds": uptime_seconds,
        "active_hours_active": active_hours_active,
        "cameras": cameras_status,
    }

    status_path = os.path.join(data_dir, "status.json")

    # Atomic write: write to a sibling temp file, then os.replace() it into
    # the final path.  tempfile.NamedTemporaryFile with delete=False lets us
    # control the replacement ourselves.
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=data_dir,
            prefix=".status_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")  # trailing newline for friendlier cat output
            os.replace(tmp_path, status_path)
        except Exception:
            # Clean up the temp file if the write or replace failed.
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception as exc:
        logger.warning("Could not write %s: %s", status_path, exc)


# ── Event log ────────────────────────────────────────────────────────────────


def append_event_log(
    data_dir: str,
    event_dict: dict[str, Any],
    max_bytes: int = DEFAULT_EVENTS_MAX_BYTES,
) -> None:
    """Append a single JSON line to ``<data_dir>/events.jsonl``.

    The file uses the JSON Lines format (one JSON object per line) so the
    dashboard can stream it efficiently, or ``tail -f`` it for real-time
    monitoring.

    A typical line looks like::

        {"timestamp": "2026-03-21T03:42:15Z", "event_id": "abc123",
         "camera": "frontdoor", "score": 0.85, "stage2_description":
         "Person in dark hoodie near garage", "stage2_audio_success": true,
         "stage3_ran": false, "stage3_description": null,
         "stage3_audio_success": null, "total_latency_ms": 12500}

    The append is done with Python's built-in file open in ``"a"`` mode,
    which is atomic for a single ``write()`` call on POSIX because ``O_APPEND``
    writes are atomic up to PIPE_BUF (at least 512 bytes, usually 4 096 or
    65 536).  A single JSON line for one event is always shorter than PIPE_BUF,
    so no explicit file locking is needed for this single-writer scenario.

    Calls ``maybe_rotate_events`` before each append to enforce the size cap.

    Args:
        data_dir: Directory containing ``events.jsonl``.
        event_dict: Fully assembled event dict to serialise as one JSON line.
            No schema validation is performed here; callers are responsible
            for providing the correct keys.
        max_bytes: Rotation threshold forwarded to ``maybe_rotate_events``.
            Callers should pass ``config["logging"]["events_max_bytes"]`` so
            the operator-configured value is honoured.  Defaults to
            ``DEFAULT_EVENTS_MAX_BYTES`` (5 MB) when not supplied.
    """
    events_path = os.path.join(data_dir, "events.jsonl")

    try:
        # Rotate the events file if it exceeds the threshold to prevent
        # unbounded growth.  Old events are not critical — we keep one backup.
        maybe_rotate_events(data_dir, max_bytes=max_bytes)

        # "a" mode: file is created if absent, pointer always seeks to end.
        # The single write() call is atomic on POSIX for payloads < PIPE_BUF.
        with open(events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event_dict) + "\n")

        logger.debug(
            "Event log appended: %s on %s",
            event_dict.get("event_id", "?"),
            event_dict.get("camera", "?"),
        )
    except OSError as exc:
        # Non-fatal — a missed event log entry is better than a crashed pipeline.
        logger.warning("Could not append to %s: %s", events_path, exc)


def maybe_rotate_events(
    data_dir: str, max_bytes: int = DEFAULT_EVENTS_MAX_BYTES
) -> None:
    """Rotate ``events.jsonl`` if it exceeds the size limit.

    Keeps one backup (``events.jsonl.1``) and starts a fresh file.
    This prevents the events log from growing unbounded on systems with
    frequent detections.

    The default rotation threshold is 5 MB — roughly 10,000–20,000 events
    depending on description length.  Callers can override with ``max_bytes``
    for testing or unusual deployments.

    Args:
        data_dir: Directory containing ``events.jsonl``.
        max_bytes: File size threshold in bytes above which rotation occurs.
            Defaults to 5 MB.
    """
    events_path = os.path.join(data_dir, "events.jsonl")
    try:
        if (
            os.path.exists(events_path)
            and os.path.getsize(events_path) > max_bytes
        ):
            backup = events_path + ".1"
            # Remove old backup if it exists, then rotate current file into it.
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(events_path, backup)
            logger.info(
                "Rotated events log (%s -> %s.1)", events_path, events_path
            )
    except OSError as exc:
        logger.warning("Could not rotate events log: %s", exc)
