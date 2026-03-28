"""
status.py — System Status API Router

Endpoints:
    GET /api/status  — Return a full system status snapshot

Aggregates data from:
  - frigate_client (Frigate NVR health check)
  - go2rtc_client  (go2rtc health check)
  - config_service (camera list from config.yaml)

Returns a single SystemStatus object that the dashboard overview page uses
to render the health tiles, camera cards, and service indicators.
"""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from backend import config as cfg
from backend.models.status_models import (
    CameraStatus,
    FrigateStatus,
    Go2rtcStatus,
    SystemStatus,
    VoxWatchServiceStatus,
)
from backend.services import frigate_client as fc_module
from backend.services import go2rtc_client as g2rtc_module
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.status")

router = APIRouter(prefix="/status", tags=["Status"])


@router.get(
    "",
    response_model=SystemStatus,
    summary="Get full system status",
    description=(
        "Returns a snapshot of the VoxWatch system including: "
        "Frigate NVR health, go2rtc health, and per-camera status from config."
    ),
)
async def get_status() -> SystemStatus:
    """Return aggregated system status from Frigate, go2rtc, and config.

    Probes Frigate and go2rtc concurrently to minimize response latency.
    Falls back gracefully if either service is unreachable.

    Returns:
        SystemStatus with frigate, go2rtc, and cameras fields.
    """
    # Probe Frigate and go2rtc concurrently to minimize response time
    frigate_result, go2rtc_result = await asyncio.gather(
        _probe_frigate(),
        _probe_go2rtc(),
        return_exceptions=True,
    )

    # Handle exceptions from concurrent probes gracefully
    if isinstance(frigate_result, Exception):
        logger.warning("Frigate probe raised: %s", frigate_result)
        frigate_result = FrigateStatus(
            reachable=False, error=str(frigate_result)
        )
    if isinstance(go2rtc_result, Exception):
        logger.warning("go2rtc probe raised: %s", go2rtc_result)
        go2rtc_result = Go2rtcStatus(
            reachable=False, error=str(go2rtc_result)
        )

    # Build cameras list from all visible sources, enriched with last event timing.
    # We merge VoxWatch config cameras with Frigate-known cameras and go2rtc
    # streams so the frontend can list (and test audio on) every camera even
    # if it has not been enrolled in VoxWatch.
    cameras = await _cameras_merged(frigate_result, go2rtc_result)
    last_events = _read_last_events()
    for cam in cameras:
        ev = last_events.get(cam.name)
        if ev:
            cam.last_detection_at = ev.get("timestamp")
            cam.last_latency_ms = ev.get("total_latency_ms")

    voxwatch_status = _read_voxwatch_status()

    return SystemStatus(
        timestamp=datetime.now(tz=UTC),
        frigate=frigate_result,
        go2rtc=go2rtc_result,
        voxwatch=voxwatch_status,
        cameras=cameras,
    )


def _read_voxwatch_status() -> VoxWatchServiceStatus:
    """Read the VoxWatch service status from /data/status.json.

    The VoxWatch container writes this file every few seconds with its
    running state, MQTT connection status, and uptime.  If the file is
    missing or stale (>30s old), we report unreachable.

    Returns:
        VoxWatchServiceStatus populated from the file, or a default
        "unreachable" status on any read error.
    """
    status_path = os.path.join(cfg.DATA_DIR, "status.json")
    try:
        # Check staleness — if the file hasn't been updated in 30s,
        # the VoxWatch service is likely down.
        mtime = os.path.getmtime(status_path)
        age = datetime.now().timestamp() - mtime
        if age > 30:
            return VoxWatchServiceStatus(
                reachable=False,
                error=f"status.json is {int(age)}s stale — VoxWatch may not be running",
            )

        with open(status_path, encoding="utf-8") as fh:
            data = json.load(fh)

        return VoxWatchServiceStatus(
            reachable=True,
            service_running=data.get("service_running", False),
            mqtt_connected=data.get("mqtt_connected", False),
            uptime_seconds=data.get("uptime_seconds"),
            version=data.get("version"),
        )
    except FileNotFoundError:
        return VoxWatchServiceStatus(
            reachable=False,
            error="status.json not found — VoxWatch service may not have started",
        )
    except Exception as exc:
        logger.warning("Failed to read VoxWatch status.json: %s", exc)
        return VoxWatchServiceStatus(
            reachable=False,
            error=str(exc),
        )


async def _probe_frigate() -> FrigateStatus:
    """Probe the Frigate NVR and return its live status.

    Delegates to the module-level client singleton configured at startup.
    Returns a 'not reachable' status if the client isn't initialized.
    """
    if fc_module.frigate_client is None:
        return FrigateStatus(
            reachable=False,
            error="Frigate client not initialized — check config",
        )
    return await fc_module.frigate_client.probe_status()


async def _probe_go2rtc() -> Go2rtcStatus:
    """Probe the go2rtc relay and return its live status.

    Delegates to the module-level client singleton configured at startup.
    Returns a 'not reachable' status if the client isn't initialized.
    """
    if g2rtc_module.go2rtc_client is None:
        return Go2rtcStatus(
            reachable=False,
            error="go2rtc client not initialized — check config",
        )
    return await g2rtc_module.go2rtc_client.probe_status()


def _read_last_events() -> dict[str, dict[str, Any]]:
    """Read events.jsonl and return the last event per camera.

    Reads the file in reverse (last lines first) to find the most recent
    event for each camera without loading the entire file into memory.

    Returns:
        Dict mapping camera name to the last event dict for that camera.
    """
    result: dict[str, dict[str, Any]] = {}
    events_path = cfg.EVENTS_FILE

    if not os.path.exists(events_path):
        return result

    try:
        # Read last 50 lines (enough to cover all cameras)
        with open(events_path, encoding="utf-8") as fh:
            lines = fh.readlines()

        # Walk backwards to find the latest event per camera
        for line in reversed(lines[-100:]):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                camera = event.get("camera", "")
                if camera and camera not in result:
                    result[camera] = event
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        logger.debug("Could not read events file: %s", exc)

    return result


async def _cameras_from_config() -> list[CameraStatus]:
    """Build a basic camera status list from config.yaml.

    Returns:
        List of CameraStatus with name and enabled flag populated from config.
        Returns an empty list if config is missing or unreadable.
    """
    try:
        cfg = await config_service.get_config()
        cameras_cfg = cfg.get("cameras", {})
        return [
            CameraStatus(
                name=name,
                enabled=cam_cfg.get("enabled", True),
            )
            for name, cam_cfg in cameras_cfg.items()
        ]
    except Exception as exc:
        logger.debug("Could not read cameras from config for status: %s", exc)
        return []


async def _cameras_merged(
    frigate_status: FrigateStatus,
    go2rtc_status: Go2rtcStatus,
) -> list[CameraStatus]:
    """Build a unified camera list from all visible sources.

    Merges cameras from three sources in order of priority:
      1. VoxWatch config.yaml       — always included, ``enabled=True``
      2. Frigate camera list        — cameras Frigate knows but VoxWatch hasn't
                                      enrolled are added with ``enabled=False``
      3. go2rtc stream list         — streams in go2rtc that appear in neither
                                      config nor Frigate are also added so that
                                      any camera reachable for audio testing is
                                      visible in the dashboard

    This allows the Audio Test page to show every available camera, not just
    VoxWatch-configured ones. Cameras that appear in multiple sources are
    represented once with ``enabled`` set based on the VoxWatch config.

    Also enriches each camera with backchannel information from go2rtc if the
    go2rtc client is reachable.

    Args:
        frigate_status: Probed Frigate status (used only to check reachability;
            camera names are fetched directly from the Frigate client).
        go2rtc_status: Probed go2rtc status (same pattern — stream names fetched
            from the go2rtc client).

    Returns:
        Deduplicated list of CameraStatus objects sorted by name.
    """
    # --- Source 1: VoxWatch config ---
    config_cameras = await _cameras_from_config()
    # Build a lookup so we can mark config cameras as enabled and avoid dupes
    by_name: dict[str, CameraStatus] = {cam.name: cam for cam in config_cameras}

    # --- Source 2: Frigate cameras ---
    # Add cameras Frigate knows that are not yet in the VoxWatch config.
    if frigate_status.reachable and fc_module.frigate_client is not None:
        try:
            frigate_names = await fc_module.frigate_client.get_cameras()
            if frigate_names:
                for name in frigate_names:
                    if name not in by_name:
                        by_name[name] = CameraStatus(name=name, enabled=False)
        except Exception as exc:
            logger.debug("Could not fetch Frigate camera list for merge: %s", exc)

    # --- Source 3: go2rtc streams ---
    # Add any streams in go2rtc that didn't appear in either previous source.
    # This covers cameras fed into go2rtc by paths other than Frigate (e.g.
    # direct RTSP streams configured manually in go2rtc).
    backchannel_info: dict[str, dict] = {}
    if go2rtc_status.reachable and g2rtc_module.go2rtc_client is not None:
        try:
            streams = await g2rtc_module.go2rtc_client.get_streams()
            if streams:
                for name in streams:
                    if name not in by_name:
                        by_name[name] = CameraStatus(name=name, enabled=False)
            backchannel_info = await g2rtc_module.go2rtc_client.get_backchannel_info()
        except Exception as exc:
            logger.debug("Could not fetch go2rtc stream list for merge: %s", exc)

    # --- Enrich with backchannel data ---
    for cam in by_name.values():
        bc = backchannel_info.get(cam.name)
        if bc is not None:
            cam.has_backchannel = bc.get("has_backchannel", False)
            cam.backchannel_codecs = bc.get("codecs", [])

    return sorted(by_name.values(), key=lambda c: c.name)
