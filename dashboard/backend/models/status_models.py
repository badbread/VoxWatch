"""
status_models.py — Pydantic Models for VoxWatch System Status

These models represent the live operational state of the external services
(Frigate NVR and go2rtc) as probed by the dashboard, plus per-camera entries
derived from config.yaml.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ── Per-Camera Status ─────────────────────────────────────────────────────────

class CameraStatus(BaseModel):
    """Basic state for a single configured camera.

    Populated from config.yaml. Extended fields (fps, online status) can be
    added in future if Frigate camera probing is wired up.
    """

    name: str = Field(description="Camera name (matches Frigate and go2rtc names)")
    enabled: bool = Field(description="Whether VoxWatch has this camera enabled in config")
    # Frigate-sourced fields
    frigate_online: Optional[bool] = Field(
        default=None,
        description="Whether Frigate reports this camera as online",
    )
    fps: Optional[float] = Field(
        default=None,
        description="Current detection FPS reported by Frigate",
    )
    # go2rtc backchannel fields — determines if two-way audio is possible
    has_backchannel: Optional[bool] = Field(
        default=None,
        description="Whether go2rtc reports a backchannel (sendonly audio) track for this camera",
    )
    backchannel_codecs: Optional[List[str]] = Field(
        default=None,
        description="List of supported backchannel audio codecs (e.g. ['PCMU/8000', 'PCMA/8000'])",
    )
    # Camera identification — populated by POST /api/cameras/{name}/identify
    camera_model: Optional[str] = Field(
        default=None,
        description="Raw model string returned by ONVIF GetDeviceInformation",
    )
    camera_manufacturer: Optional[str] = Field(
        default=None,
        description="Manufacturer name returned by ONVIF or resolved from camera_db",
    )
    speaker_status: Optional[str] = Field(
        default=None,
        description=(
            "Audio output capability of this camera. "
            "One of: 'built_in', 'rca_out', 'none', 'unknown', 'override'. "
            "'built_in' — camera has a built-in loudspeaker (fully compatible). "
            "'rca_out' — camera has an RCA audio output jack but no built-in speaker. "
            "'none' — camera has no audio output (incompatible with VoxWatch). "
            "'unknown' — model not in the compatibility database. "
            "'override' — user confirmed compatibility manually."
        ),
    )
    compatibility_notes: Optional[str] = Field(
        default=None,
        description="Human-readable compatibility notes from camera_db or ONVIF probe",
    )
    # Last detection timing (from events.jsonl)
    last_detection_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of the last detection event on this camera",
    )
    last_latency_ms: Optional[int] = Field(
        default=None,
        description="Total pipeline latency in milliseconds for the last detection",
    )


# ── External Service Status ───────────────────────────────────────────────────

class FrigateStatus(BaseModel):
    """Status of the Frigate NVR service as reported by its API."""

    reachable: bool = Field(description="Whether the dashboard can reach Frigate's API")
    version: Optional[str] = Field(default=None, description="Frigate version string")
    camera_count: Optional[int] = Field(
        default=None,
        description="Number of cameras Frigate knows about",
    )
    uptime_seconds: Optional[int] = Field(
        default=None,
        description="Frigate process uptime in seconds",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if Frigate is not reachable",
    )


class Go2rtcStatus(BaseModel):
    """Status of the go2rtc audio/video relay as reported by its API."""

    reachable: bool = Field(description="Whether the dashboard can reach go2rtc's API")
    version: Optional[str] = Field(default=None, description="go2rtc version string")
    stream_count: Optional[int] = Field(
        default=None,
        description="Number of streams go2rtc currently has configured",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if go2rtc is not reachable",
    )


# ── System-Level Info ─────────────────────────────────────────────────────────

class SystemInfo(BaseModel):
    """Static system information about the host running VoxWatch.

    Populated on startup and cached — not updated at every status poll.
    """

    hostname: Optional[str] = Field(default=None, description="System hostname")
    platform: Optional[str] = Field(default=None, description="OS platform string")
    python_version: Optional[str] = Field(default=None, description="Python version string")
    config_path: Optional[str] = Field(
        default=None,
        description="Path to config.yaml currently in use",
    )
    data_dir: Optional[str] = Field(
        default=None,
        description="Path to the /data directory",
    )
    events_file: Optional[str] = Field(
        default=None,
        description="Path to the events.jsonl file (informational; not actively read)",
    )


# ── Dashboard-Level Aggregated Status ────────────────────────────────────────

class SystemStatus(BaseModel):
    """Complete system status snapshot returned by GET /api/status.

    Aggregates Frigate status, go2rtc status, and per-camera summaries
    from config.yaml into a single response for the dashboard overview.
    """

    timestamp: datetime = Field(description="When this status snapshot was assembled")
    frigate: FrigateStatus = Field(description="Frigate NVR service status")
    go2rtc: Go2rtcStatus = Field(description="go2rtc relay service status")
    cameras: List[CameraStatus] = Field(
        default_factory=list,
        description="List of per-camera status objects derived from config.yaml",
    )


# ── Health Check ──────────────────────────────────────────────────────────────

class HealthStatus(BaseModel):
    """Minimal health check response for GET /api/system/health.

    Used by container orchestrators (Docker healthcheck, Kubernetes probe)
    and load balancers to determine if the dashboard backend is alive.
    """

    status: Literal["ok", "degraded", "error"] = Field(
        description="Overall health: ok = config loaded, degraded = config missing, error = critical"
    )
    dashboard_uptime_seconds: Optional[float] = Field(
        default=None,
        description="Seconds since the dashboard backend process started",
    )
    config_loaded: bool = Field(
        default=False,
        description="Whether a valid config.yaml has been loaded",
    )
