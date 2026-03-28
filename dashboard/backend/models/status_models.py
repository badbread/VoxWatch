"""
status_models.py — Pydantic Models for VoxWatch System Status

These models represent the live operational state of the external services
(Frigate NVR and go2rtc) as probed by the dashboard, plus per-camera entries
derived from config.yaml.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    frigate_online: bool | None = Field(
        default=None,
        description="Whether Frigate reports this camera as online",
    )
    fps: float | None = Field(
        default=None,
        description="Current detection FPS reported by Frigate",
    )
    # go2rtc backchannel fields — determines if two-way audio is possible
    has_backchannel: bool | None = Field(
        default=None,
        description="Whether go2rtc reports a backchannel (sendonly audio) track for this camera",
    )
    backchannel_codecs: list[str] | None = Field(
        default=None,
        description="List of supported backchannel audio codecs (e.g. ['PCMU/8000', 'PCMA/8000'])",
    )
    # Camera identification — populated by POST /api/cameras/{name}/identify
    camera_model: str | None = Field(
        default=None,
        description="Raw model string returned by ONVIF GetDeviceInformation",
    )
    camera_manufacturer: str | None = Field(
        default=None,
        description="Manufacturer name returned by ONVIF or resolved from camera_db",
    )
    speaker_status: str | None = Field(
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
    compatibility_notes: str | None = Field(
        default=None,
        description="Human-readable compatibility notes from camera_db or ONVIF probe",
    )
    # Last detection timing (from events.jsonl)
    last_detection_at: str | None = Field(
        default=None,
        description="ISO timestamp of the last detection event on this camera",
    )
    last_latency_ms: int | None = Field(
        default=None,
        description="Total pipeline latency in milliseconds for the last detection",
    )


# ── Detection Event ───────────────────────────────────────────────────────────

class DetectionEvent(BaseModel):
    """Full details of a single detection event from events.jsonl.

    Fields map directly to keys written by ``append_event_log`` in
    ``voxwatch_service.py``.  Optional fields are ``None`` when absent so
    that older events (recorded before enriched logging was added) can still
    be parsed without errors.
    """

    timestamp: str = Field(description="ISO 8601 timestamp of detection")
    event_id: str = Field(default="", description="Frigate event ID")
    camera: str = Field(description="Camera name")
    score: float = Field(default=0.0, description="Detection confidence score (0-1)")
    response_mode: str = Field(default="standard", description="Response mode/persona used")
    tts_message: str | None = Field(default=None, description="Initial TTS message spoken")
    escalation_ran: bool = Field(default=False, description="Whether escalation stage fired")
    escalation_description: str | None = Field(
        default=None, description="AI-generated person description"
    )
    escalation_message: str | None = Field(
        default=None, description="Escalation TTS message"
    )
    initial_audio_success: bool | None = Field(
        default=None, description="Whether initial audio pushed successfully"
    )
    escalation_audio_success: bool | None = Field(
        default=None, description="Whether escalation audio pushed"
    )
    tts_provider: str | None = Field(default=None, description="TTS provider that generated audio")
    tts_voice: str | None = Field(default=None, description="TTS voice used")
    ai_provider: str | None = Field(default=None, description="AI vision provider used")
    total_latency_ms: int | None = Field(
        default=None, description="Total pipeline latency in ms"
    )


# ── External Service Status ───────────────────────────────────────────────────

class FrigateStatus(BaseModel):
    """Status of the Frigate NVR service as reported by its API."""

    reachable: bool = Field(description="Whether the dashboard can reach Frigate's API")
    version: str | None = Field(default=None, description="Frigate version string")
    camera_count: int | None = Field(
        default=None,
        description="Number of cameras Frigate knows about",
    )
    uptime_seconds: int | None = Field(
        default=None,
        description="Frigate process uptime in seconds",
    )
    error: str | None = Field(
        default=None,
        description="Error message if Frigate is not reachable",
    )


class Go2rtcStatus(BaseModel):
    """Status of the go2rtc audio/video relay as reported by its API."""

    reachable: bool = Field(description="Whether the dashboard can reach go2rtc's API")
    version: str | None = Field(default=None, description="go2rtc version string")
    stream_count: int | None = Field(
        default=None,
        description="Number of streams go2rtc currently has configured",
    )
    error: str | None = Field(
        default=None,
        description="Error message if go2rtc is not reachable",
    )


# ── System-Level Info ─────────────────────────────────────────────────────────

class SystemInfo(BaseModel):
    """Static system information about the host running VoxWatch.

    Populated on startup and cached — not updated at every status poll.
    """

    hostname: str | None = Field(default=None, description="System hostname")
    platform: str | None = Field(default=None, description="OS platform string")
    python_version: str | None = Field(default=None, description="Python version string")
    config_path: str | None = Field(
        default=None,
        description="Path to config.yaml currently in use",
    )
    data_dir: str | None = Field(
        default=None,
        description="Path to the /data directory",
    )
    events_file: str | None = Field(
        default=None,
        description="Path to the events.jsonl file (informational; not actively read)",
    )


# ── Dashboard-Level Aggregated Status ────────────────────────────────────────

class VoxWatchServiceStatus(BaseModel):
    """Live status of the VoxWatch detection service.

    Read from /data/status.json which the VoxWatch container writes every
    few seconds.  Gives the dashboard visibility into whether the service
    is running, MQTT is connected, and the TTS provider is healthy.
    """

    reachable: bool = Field(
        default=False,
        description="True if status.json was readable and recently updated",
    )
    service_running: bool = Field(default=False, description="Whether the VoxWatch service loop is active")
    mqtt_connected: bool = Field(default=False, description="Whether MQTT is connected to the broker")
    uptime_seconds: float | None = Field(default=None, description="Service uptime in seconds")
    version: str | None = Field(default=None, description="VoxWatch service version string")
    error: str | None = Field(default=None, description="Error message if status.json could not be read")


class SystemStatus(BaseModel):
    """Complete system status snapshot returned by GET /api/status.

    Aggregates Frigate status, go2rtc status, VoxWatch service status,
    and per-camera summaries from config.yaml into a single response
    for the dashboard overview.
    """

    timestamp: datetime = Field(description="When this status snapshot was assembled")
    frigate: FrigateStatus = Field(description="Frigate NVR service status")
    go2rtc: Go2rtcStatus = Field(description="go2rtc relay service status")
    voxwatch: VoxWatchServiceStatus = Field(
        default_factory=VoxWatchServiceStatus,
        description="VoxWatch detection service status (from status.json)",
    )
    cameras: list[CameraStatus] = Field(
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
    dashboard_uptime_seconds: float | None = Field(
        default=None,
        description="Seconds since the dashboard backend process started",
    )
    config_loaded: bool = Field(
        default=False,
        description="Whether a valid config.yaml has been loaded",
    )
