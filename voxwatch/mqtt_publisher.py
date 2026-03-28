"""
mqtt_publisher.py — VoxWatch MQTT Event Publisher.

Publishes structured JSON events to MQTT so Home Assistant (and any other
MQTT subscriber) can trigger automations based on VoxWatch activity.

VoxWatch already subscribes to Frigate events via MQTT.  This module adds
the PUBLISHING side so VoxWatch becomes a first-class participant in the
MQTT ecosystem.

Topic structure (all under a configurable prefix, default ``voxwatch/``)::

    voxwatch/events/detection  — person detected, VoxWatch is responding
    voxwatch/events/stage      — a pipeline stage has fired (1, 2, or 3)
    voxwatch/events/ended      — detection ended (person left / completed)
    voxwatch/events/error      — something went wrong (TTS fail, AI timeout)
    voxwatch/status            — service status (online/offline via LWT)
    voxwatch/announce          — SUBSCRIBE: play TTS on a camera speaker (HA integration)

Usage::

    publisher = VoxWatchPublisher(mqtt_client, config.get("mqtt_publish", {}))
    publisher.publish_online()

    publisher.publish_detection_started(
        event_id="vw_1711338420_driveway",
        camera="driveway",
        mode="police_dispatch",
        frigate_event_id="abc123",
        snapshot_url="http://frigate:5000/api/events/abc123/snapshot.jpg",
    )

All publish calls are fire-and-forget — failures are logged but never block
the detection pipeline.  The publisher reuses the existing paho MQTT client
connection (no second broker connection).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger("voxwatch.mqtt_publisher")


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DetectionEvent:
    """Published when VoxWatch begins responding to a person detection."""

    event: str = "detection_started"
    event_id: str = ""
    timestamp: str = ""
    camera: str = ""
    frigate_event_id: str = ""
    mode: str = ""
    snapshot_url: str = ""


@dataclass
class StageEvent:
    """Published when a pipeline stage fires (1 = initial, 2 = escalation, 3 = behavioral)."""

    event: str = "stage_triggered"
    event_id: str = ""
    timestamp: str = ""
    camera: str = ""
    stage: int = 0
    total_stages: int = 3
    mode: str = ""
    audio_pushed: bool = False
    ai_analysis: dict | None = None
    message_text: str | None = None
    person_still_present: bool = True
    frigate_event_id: str = ""


@dataclass
class EndedEvent:
    """Published when a detection event concludes."""

    event: str = "detection_ended"
    event_id: str = ""
    timestamp: str = ""
    camera: str = ""
    reason: str = ""
    stages_completed: int = 0
    total_duration_seconds: float = 0.0
    mode: str = ""
    frigate_event_id: str = ""


@dataclass
class ErrorEvent:
    """Published when something goes wrong during a detection response."""

    event: str = "error"
    event_id: str = ""
    timestamp: str = ""
    camera: str = ""
    stage: int = 0
    error_type: str = ""
    error_message: str = ""
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _make_vw_event_id(camera: str) -> str:
    """Generate a unique VoxWatch event ID from camera name and timestamp."""
    return f"vw_{int(time.time())}_{camera}"


class VoxWatchPublisher:
    """Publishes VoxWatch detection events to MQTT.

    Reuses the same paho MQTT client that VoxWatch already uses for
    subscribing to Frigate events.  Does NOT create a second connection.

    All publish methods are synchronous and safe to call from the asyncio
    event loop (paho's ``publish()`` is thread-safe and non-blocking for
    QoS 0).  Every call is wrapped in try/except so publishing failures
    never disrupt the detection pipeline.

    Args:
        mqtt_client: Connected paho MQTT client instance.
        publish_config: The ``mqtt_publish`` section from VoxWatch config.
            Expected keys: ``topic_prefix``, ``include_ai_analysis``,
            ``include_snapshot_url``.
    """

    def __init__(
        self,
        mqtt_client: mqtt.Client,
        publish_config: dict[str, Any],
    ) -> None:
        self._client = mqtt_client
        self._prefix = publish_config.get("topic_prefix", "voxwatch").rstrip("/")
        self._include_ai = publish_config.get("include_ai_analysis", True)
        self._include_snapshot = publish_config.get("include_snapshot_url", True)

    # ── Public API ────────────────────────────────────────────────────────

    def publish_online(self) -> None:
        """Publish retained 'online' status.  Call on startup."""
        self._publish(f"{self._prefix}/status", "online", retain=True)
        logger.info("Published MQTT status: online (topic=%s/status)", self._prefix)

    def publish_offline(self) -> None:
        """Publish retained 'offline' status.  Call on graceful shutdown."""
        self._publish(f"{self._prefix}/status", "offline", retain=True)
        logger.info("Published MQTT status: offline (topic=%s/status)", self._prefix)

    def publish_detection_started(
        self,
        *,
        camera: str,
        mode: str,
        frigate_event_id: str,
        snapshot_url: str = "",
        vw_event_id: str = "",
    ) -> str:
        """Publish detection_started event.  Returns the VoxWatch event ID.

        Args:
            camera: Frigate camera name.
            mode: Active response mode name.
            frigate_event_id: Frigate's unique event ID.
            snapshot_url: URL to the Frigate snapshot image.
            vw_event_id: Pre-generated VW event ID (auto-generated if empty).

        Returns:
            The VoxWatch event ID used (for passing to subsequent stage events).
        """
        if not vw_event_id:
            vw_event_id = _make_vw_event_id(camera)

        event = DetectionEvent(
            event_id=vw_event_id,
            timestamp=_now_iso(),
            camera=camera,
            frigate_event_id=frigate_event_id,
            mode=mode,
            snapshot_url=snapshot_url if self._include_snapshot else "",
        )
        self._publish(f"{self._prefix}/events/detection", event)
        logger.info(
            "MQTT published: detection_started camera=%s mode=%s event_id=%s",
            camera, mode, vw_event_id,
        )
        return vw_event_id

    def publish_stage(
        self,
        *,
        vw_event_id: str,
        camera: str,
        stage: int,
        mode: str,
        audio_pushed: bool = False,
        ai_analysis: dict | None = None,
        message_text: str | None = None,
        person_still_present: bool = True,
        frigate_event_id: str = "",
        total_stages: int = 3,
    ) -> None:
        """Publish stage_triggered event.

        Args:
            vw_event_id: VoxWatch event ID from publish_detection_started.
            camera: Frigate camera name.
            stage: Stage number (1, 2, or 3).
            mode: Active response mode name.
            audio_pushed: Whether audio was successfully pushed to the camera.
            ai_analysis: Dict with clothing_description, location_on_property, etc.
            message_text: The text that was spoken (if available).
            person_still_present: Whether the person is still detected.
            frigate_event_id: Frigate's unique event ID.
            total_stages: Total number of stages configured.
        """
        event = StageEvent(
            event_id=vw_event_id,
            timestamp=_now_iso(),
            camera=camera,
            stage=stage,
            total_stages=total_stages,
            mode=mode,
            audio_pushed=audio_pushed,
            ai_analysis=ai_analysis if self._include_ai else None,
            message_text=message_text,
            person_still_present=person_still_present,
            frigate_event_id=frigate_event_id,
        )
        self._publish(f"{self._prefix}/events/stage", event)
        logger.info(
            "MQTT published: stage_triggered camera=%s stage=%d pushed=%s",
            camera, stage, audio_pushed,
        )

    def publish_ended(
        self,
        *,
        vw_event_id: str,
        camera: str,
        reason: str,
        stages_completed: int,
        total_duration_seconds: float,
        mode: str,
        frigate_event_id: str = "",
    ) -> None:
        """Publish detection_ended event.

        Args:
            vw_event_id: VoxWatch event ID from publish_detection_started.
            camera: Frigate camera name.
            reason: Why the detection ended (person_left, all_stages_completed, etc.).
            stages_completed: Number of stages that actually fired.
            total_duration_seconds: Total pipeline duration in seconds.
            mode: Active response mode name.
            frigate_event_id: Frigate's unique event ID.
        """
        event = EndedEvent(
            event_id=vw_event_id,
            timestamp=_now_iso(),
            camera=camera,
            reason=reason,
            stages_completed=stages_completed,
            total_duration_seconds=round(total_duration_seconds, 2),
            mode=mode,
            frigate_event_id=frigate_event_id,
        )
        self._publish(f"{self._prefix}/events/ended", event)
        logger.info(
            "MQTT published: detection_ended camera=%s reason=%s stages=%d duration=%.1fs",
            camera, reason, stages_completed, total_duration_seconds,
        )

    def publish_error(
        self,
        *,
        vw_event_id: str = "",
        camera: str = "",
        stage: int = 0,
        error_type: str = "",
        error_message: str = "",
        fallback_used: bool = False,
    ) -> None:
        """Publish error event.

        Args:
            vw_event_id: VoxWatch event ID (may be empty for startup errors).
            camera: Frigate camera name.
            stage: Stage that failed (0 if not stage-specific).
            error_type: Category of error (tts_failure, ai_timeout, etc.).
            error_message: Human-readable error description.
            fallback_used: Whether a fallback was successfully used.
        """
        event = ErrorEvent(
            event_id=vw_event_id,
            timestamp=_now_iso(),
            camera=camera,
            stage=stage,
            error_type=error_type,
            error_message=error_message,
            fallback_used=fallback_used,
        )
        self._publish(f"{self._prefix}/events/error", event)
        logger.warning(
            "MQTT published: error camera=%s stage=%d type=%s msg=%s",
            camera, stage, error_type, error_message,
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        """Serialize and publish a message.  Never raises.

        Args:
            topic: Full MQTT topic string.
            payload: A dataclass instance (serialized to JSON) or a plain string.
            retain: Whether the message should be retained by the broker.
        """
        try:
            if isinstance(payload, str):
                data = payload
            else:
                data = json.dumps(asdict(payload), default=str)
            self._client.publish(topic, data, qos=0, retain=retain)
        except Exception as exc:
            logger.error("MQTT publish failed on %s: %s", topic, exc)
