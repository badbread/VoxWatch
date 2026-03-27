"""voxwatch_service.py — Main Orchestration Service for VoxWatch

This is the entry point that ties together every subsystem:
  - Loads and validates configuration from config.yaml
  - Connects to an MQTT broker and subscribes to Frigate person detection events
  - Enforces per-camera cooldowns and active-hours windows
  - Orchestrates the smart-escalation deterrent pipeline:

      Detection       — MQTT event received; all guards pass.
      Initial Response (0 s) — Mode-specific pre-cached message plays instantly.
                                AI analysis starts concurrently in background.
      Escalation      (6 s)  — If person still present: AI description inserted
                                into the mode's escalation template and played.
      Resolution      (opt.) — If person leaves: brief "area clear" message.

The pipeline is designed so Initial Response plays while AI analysis runs in
the background — AI latency is hidden behind the initial audio playback.

Usage (Docker / direct):
    python -m voxwatch.voxwatch_service
    python -m voxwatch.voxwatch_service --config /config/config.yaml

Prerequisites:
    pip install paho-mqtt astral aiohttp
    ffmpeg on PATH
    piper or espeak-ng for TTS
    go2rtc running and accessible

Signal handling:
    SIGTERM / SIGINT will trigger a graceful shutdown:
      - MQTT client disconnects cleanly
      - Audio HTTP server is stopped
      - In-flight pipeline tasks are awaited briefly before cancellation
"""

import argparse
import asyncio
import contextlib
import json
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

import paho.mqtt.client as mqtt

from voxwatch.ai_vision import (
    DEFAULT_MESSAGES,
    _get_active_mode,
    analyze_snapshots,
    analyze_video,
    check_person_still_present,
    get_dispatch_initial_message,
    get_stage2_prompt,
    get_stage3_prompt,
    grab_snapshots,
    grab_video_clip,
)
from voxwatch.ai_vision import (
    close_session as close_ai_session,
)
from voxwatch.audio_pipeline import AudioPipeline
from voxwatch.conditions import (
    check_cooldown,
    is_active_hours,
)
from voxwatch.config import load_config_or_none, reload_config
from voxwatch.modes import (
    build_ai_vars,
    get_mode_template,
)
from voxwatch.modes import (
    get_active_mode as get_active_mode_obj,
)
from voxwatch.modes.mode import VoiceConfig
from voxwatch.radio_dispatch import (
    DISPATCH_MODES,
    compose_dispatch_audio,
    segment_dispatch_message,
)
from voxwatch.mqtt_publisher import VoxWatchPublisher
from voxwatch.telemetry import (
    append_event_log,
    ensure_camera_stats,
    record_audio_push,
    record_detection,
    write_status_file,
)

logger = logging.getLogger("voxwatch.service")

# How long (seconds) to wait for in-flight pipeline tasks when shutting down
# gracefully. Keeps shutdown snappy while still letting near-complete work land.
SHUTDOWN_DRAIN_TIMEOUT = 10.0

# Directory where the dashboard reads status and event data.
# Matches the Docker volume mount: -v /host/data:/data
DATA_DIR = "/data"

# How often the background task refreshes /data/status.json (seconds).
STATUS_WRITE_INTERVAL = 5

# Service version — keep in sync with pyproject.toml / __version__.
SERVICE_VERSION = "0.2.0"


def _try_parse_phrase_list(ai_description: str | None) -> list[str]:
    """Attempt to parse an AI description string as a JSON array of phrases.

    Used by ``_run_escalation`` and ``_handle_detection`` to detect when the AI
    returned a structured list of short phrases (intended for the natural cadence
    system) rather than a plain sentence.

    Delegates to ``voxwatch.speech.natural_cadence.parse_ai_response`` but is
    intentionally non-fatal: any import error or parse failure returns an empty
    list so the caller can fall back to flat-string TTS without crashing.

    A result of ``[single_item]`` where the single item equals the original
    input string is treated as a failed parse (i.e., the AI did not return a
    multi-phrase array) and an empty list is returned instead.

    Args:
        ai_description: Raw AI output string, or None.

    Returns:
        A list of phrase strings if the input looks like a JSON array with
        more than one element, otherwise an empty list.
    """
    if not ai_description:
        return []
    try:
        from voxwatch.speech.natural_cadence import parse_ai_response
        phrases = parse_ai_response(ai_description)
        # Only use the cadence path when the AI actually returned multiple
        # phrases.  A single-phrase result means the AI responded as plain text
        # and the standard generate_and_push path handles it correctly.
        if len(phrases) > 1:
            return phrases
        return []
    except Exception:
        return []


class VoxWatchService:
    """Main orchestration class for the VoxWatch deterrent system.

    Lifecycle:
        1. Instantiate with a loaded config dict.
        2. Await ``start()`` — initialises subsystems and runs the event loop
           forever until ``stop()`` is called.
        3. Await ``stop()`` from a signal handler to clean up gracefully.

    MQTT threading note:
        paho-mqtt fires callbacks on its own background thread.  All callbacks
        immediately hand work off to the asyncio event loop via
        ``loop.call_soon_threadsafe`` so the rest of the class is fully async
        and thread-safe.

    Attributes:
        config: The full VoxWatch config dict (already validated).
        _config_path: Absolute path to the config.yaml file.  Stored so the
            hot-reload watcher knows which file to monitor.
        _config_lock: asyncio Lock that must be held when swapping ``self.config``
            to prevent detection handlers from reading a half-written config.
        _audio: AudioPipeline instance managing TTS, conversion, and HTTP push.
        _loop: The running asyncio event loop (set in ``start()``).
        _mqtt_client: The paho MQTT client instance.
        _cooldowns: Maps camera_name -> monotonic timestamp of last trigger (float).
        _running: Set to False when ``stop()`` is called to exit the main loop.
        _active_tasks: Set of in-flight asyncio Tasks (used for graceful drain).
        _started_at: UTC datetime when the service was started (set in ``start()``).
        _status_task: The background asyncio Task that writes status.json periodically.
        _config_watch_task: The background asyncio Task that polls config mtime and
            triggers hot-reloads when the file changes.
        _camera_stats: Per-camera counters for detections and audio pushes, keyed by
            camera name.  Each entry is a dict with the keys ``total_detections``,
            ``total_audio_pushes``, ``last_detection_at``, and
            ``last_audio_push_success``.
    """

    def __init__(self, config: dict, config_path: str = "/config/config.yaml") -> None:
        """Initialise the service with a validated config dict.

        Args:
            config: Fully resolved config dict from ``voxwatch.config.load_config``.
            config_path: Absolute path to the config.yaml file.  Used by the
                hot-reload watcher to detect file changes.
        """
        self.config = config
        self._config_path = config_path
        # Protects self.config swaps — detection handlers and the watcher both
        # access config concurrently, so we need mutual exclusion.
        self._config_lock: asyncio.Lock = asyncio.Lock()
        self._audio = AudioPipeline(config)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt_client: mqtt.Client | None = None
        self._publisher: VoxWatchPublisher | None = None
        # camera_name -> UNIX monotonic timestamp of last successful trigger
        self._cooldowns: dict[str, float] = {}
        self._running = False
        # Track live pipeline tasks so we can drain them on shutdown
        self._active_tasks: set[asyncio.Task] = set()

        # ── Dashboard telemetry state ──────────────────────────────────────
        # Set to a real datetime in start() once the event loop is running.
        self._started_at: datetime | None = None
        # Background asyncio Task that writes /data/status.json every N seconds.
        self._status_task: asyncio.Task | None = None
        # Background asyncio Task that polls config mtime and triggers hot-reloads.
        self._config_watch_task: asyncio.Task | None = None
        # Per-camera counters, populated lazily when the first detection arrives.
        # Structure per camera:
        #   {
        #     "total_detections": int,       # events that passed all guards
        #     "total_audio_pushes": int,      # audio pushes that returned True
        #     "last_detection_at": str|None,  # ISO 8601 UTC string
        #     "last_audio_push_success": bool|None,
        #   }
        self._camera_stats: dict[str, dict[str, Any]] = {}

        # Preview API — started in start(), stopped in the shutdown sequence.
        # Typed as Optional[Any] to avoid a circular import at module level;
        # the actual type is PreviewAPI from voxwatch.preview_api.
        self._preview_api: Any | None = None

    # ── Public lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise all subsystems and run the service until stopped.

        Execution order:
          1. Capture the running event loop (needed for MQTT->asyncio bridge).
          2. Initialise the AudioPipeline (starts HTTP server, pre-caches Stage 1).
          3. Connect to the MQTT broker and subscribe to Frigate events.
          4. Spin in an async idle loop until ``_running`` is cleared by ``stop()``.
        """
        self._loop = asyncio.get_running_loop()
        self._running = True
        # Record the exact moment the service became operational.  Used by the
        # status writer to compute uptime and stamp the status payload.
        self._started_at = datetime.now(tz=UTC)

        # Ensure the shared data directory exists before writing any files.
        os.makedirs(DATA_DIR, exist_ok=True)

        # Initialise audio subsystem first — if TTS/ffmpeg are broken we want
        # to know before we start receiving events.
        logger.info("Initialising audio pipeline...")
        await self._audio.initialize()

        # Start the lightweight preview API.  Non-fatal: if the port is already
        # in use or the bind fails for any reason, the main service continues.
        # The API must start AFTER the audio pipeline is initialised because
        # preview requests call self._audio.generate_tts() immediately.
        try:
            from voxwatch.preview_api import PreviewAPI
            preview_port = self.config.get("preview_api_port", 8892)
            self._preview_api = PreviewAPI(self._audio, self.config)
            await self._preview_api.start(port=preview_port)
        except Exception as exc:
            logger.warning(
                "Preview API startup failed (%s) — preview functionality unavailable.",
                exc,
            )
            self._preview_api = None

        # Connect to MQTT and start the paho network loop in its own thread.
        logger.info("Connecting to MQTT broker...")
        try:
            await self._connect_mqtt()
        except RuntimeError as exc:
            logger.error("Fatal MQTT error: %s", exc)
            self._running = False
            self._audio.shutdown()
            return

        # Initialize the MQTT event publisher for Home Assistant integration.
        publish_cfg = self.config.get("mqtt_publish", {})
        if publish_cfg.get("enabled", True) and self._mqtt_client:
            self._publisher = VoxWatchPublisher(self._mqtt_client, publish_cfg)
            self._publisher.publish_online()
        else:
            self._publisher = None
            logger.info("MQTT event publishing is disabled.")

        # Start the background task that periodically writes /data/status.json.
        # Named tasks show up more clearly in asyncio debug output.
        self._status_task = asyncio.create_task(
            self._write_status_loop(),
            name="status_writer",
        )
        logger.info(
            "Status writer started (writing to %s/status.json every %ds).",
            DATA_DIR,
            STATUS_WRITE_INTERVAL,
        )

        # Start the config hot-reload watcher.  It polls the config file's mtime
        # every 10 seconds and reinitialises only the components that changed.
        self._config_watch_task = asyncio.create_task(
            self._config_watch_loop(),
            name="config_watcher",
        )
        logger.info(
            "Config watcher started (polling '%s' every 10s for changes).",
            self._config_path,
        )

        logger.info("VoxWatch service running. Waiting for Frigate events...")

        # Keep the coroutine alive; stop() will flip _running to False.
        while self._running:
            await asyncio.sleep(1)

        # Give in-flight pipeline tasks a moment to finish before we tear down
        # the audio subsystem (otherwise audio files can vanish mid-push).
        if self._active_tasks:
            logger.info(
                "Draining %d in-flight task(s) (max %.0fs)...",
                len(self._active_tasks),
                SHUTDOWN_DRAIN_TIMEOUT,
            )
            await asyncio.wait(
                self._active_tasks,
                timeout=SHUTDOWN_DRAIN_TIMEOUT,
            )

        # Stop the config watcher first so no reload can race with shutdown.
        if self._config_watch_task and not self._config_watch_task.done():
            self._config_watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._config_watch_task

        # Stop the status writer and do one final write so the dashboard shows
        # service_running: false rather than stale data.
        if self._status_task and not self._status_task.done():
            self._status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._status_task
        self._write_status_file()
        logger.info("Final status.json written.")

        # Close the shared aiohttp session used by ai_vision.
        await close_ai_session()

        # Stop the preview API before the audio pipeline so no in-flight
        # preview requests can call generate_tts() after the pipeline shuts down.
        if self._preview_api is not None:
            await self._preview_api.stop()

        # Clean up the audio HTTP server thread.
        self._audio.shutdown()
        logger.info("VoxWatch service stopped cleanly.")

    async def stop(self) -> None:
        """Signal the service to shut down gracefully.

        Safe to call from a signal handler (via ``loop.call_soon_threadsafe``).
        Sets the ``_running`` flag which causes ``start()``'s idle loop to exit.
        Also disconnects the MQTT client so no further events arrive.

        The ``_status_task`` background writer is cancelled and a final
        status.json is written inside ``start()`` after this flag is detected,
        so there is nothing extra to do here — clearing ``_running`` is enough.
        """
        logger.info("Shutdown requested — stopping VoxWatch service...")
        self._running = False

        # Publish offline status before disconnecting.
        if self._publisher:
            try:
                self._publisher.publish_offline()
            except Exception:
                pass

        if self._mqtt_client:
            # loop_stop() ends the paho background thread; disconnect() sends
            # a clean DISCONNECT packet to the broker.
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            logger.info("MQTT client disconnected.")

    # ── MQTT connection ───────────────────────────────────────────────────────

    async def _connect_mqtt(self) -> None:
        """Create the paho MQTT client, register callbacks, and connect.

        The paho client runs its network loop in a background thread
        (``loop_start()``).  All callbacks are bridged into the asyncio event
        loop via ``call_soon_threadsafe`` so the rest of the service stays
        single-threaded from asyncio's perspective.

        Raises:
            RuntimeError: If the broker is unreachable (host/port refused).
        """
        frigate_cfg = self.config["frigate"]
        mqtt_host = frigate_cfg.get("mqtt_host", "localhost")
        mqtt_port = frigate_cfg.get("mqtt_port", 1883)
        topic = frigate_cfg.get("mqtt_topic", "frigate/events")

        # Store the topic BEFORE connecting — on_connect fires on the paho
        # thread and needs this attribute to subscribe.
        self._mqtt_topic = topic

        # Resolve publish config early — used for announce topic and LWT setup.
        publish_cfg = self.config.get("mqtt_publish", {})

        # Announce topic — HA and external services can publish here to trigger
        # TTS announcements on camera speakers.
        announce_prefix = publish_cfg.get("topic_prefix", "voxwatch").rstrip("/")
        self._mqtt_announce_topic = f"{announce_prefix}/announce"

        # Use a clean client ID so reconnects don't collide with a stale session.
        # paho-mqtt v2.0+ uses CallbackAPIVersion; v1.x uses clean_session.
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id="voxwatch",
                clean_session=True,
            )
        except (AttributeError, TypeError):
            # paho-mqtt < 2.0 fallback
            client = mqtt.Client(client_id="voxwatch", clean_session=True)

        # Set MQTT credentials if configured
        mqtt_user = frigate_cfg.get("mqtt_user")
        mqtt_password = frigate_cfg.get("mqtt_password")
        if mqtt_user:
            client.username_pw_set(mqtt_user, mqtt_password)

        # Wire up callbacks — these run on paho's thread, not asyncio's.
        client.on_connect = self._on_mqtt_connect
        client.on_disconnect = self._on_mqtt_disconnect
        client.on_message = self._on_mqtt_message

        # Configure MQTT Last Will and Testament for online/offline status.
        # If VoxWatch disconnects unexpectedly, the broker publishes "offline".
        if publish_cfg.get("enabled", True):
            lwt_prefix = publish_cfg.get("topic_prefix", "voxwatch").rstrip("/")
            client.will_set(
                f"{lwt_prefix}/status", "offline", qos=1, retain=True
            )

        try:
            client.connect(mqtt_host, mqtt_port, keepalive=60)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot connect to MQTT broker at {mqtt_host}:{mqtt_port} — {exc}"
            ) from exc

        # Start paho's background network thread; it will call on_connect once
        # the TCP handshake completes.
        client.loop_start()
        self._mqtt_client = client

        # Give the broker a moment to acknowledge the connection before we
        # declare startup complete.  This is a short poll — on_connect sets
        # the subscription, but we don't want to block forever here.
        for _ in range(20):
            await asyncio.sleep(0.25)
            if client.is_connected():
                break

        if not client.is_connected():
            logger.warning(
                "MQTT broker not yet connected — will retry in background."
            )

    def _on_mqtt_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ) -> None:
        """Called by paho when the broker connection is established.

        Subscribes to the Frigate events topic.  This callback runs on the
        paho background thread — no asyncio calls here.

        Args:
            client: The paho MQTT client.
            userdata: User data passed to the client (unused).
            flags: Connection flags from the broker.
            reason_code: paho-mqtt v2 ReasonCode (0 = success).
            properties: MQTT v5 properties (unused).
        """
        # paho v2 ReasonCode: check .is_failure or compare to 0 via .value
        failed = False
        if reason_code is not None:
            if hasattr(reason_code, 'is_failure'):
                failed = reason_code.is_failure
            elif hasattr(reason_code, 'value'):
                failed = reason_code.value != 0
            else:
                failed = bool(reason_code)

        if not failed:
            logger.info(
                "Connected to MQTT broker. Subscribing to '%s'.",
                self._mqtt_topic,
            )
            client.subscribe(self._mqtt_topic, qos=1)

            # Subscribe to the announce topic for HA-triggered TTS announcements.
            if hasattr(self, '_mqtt_announce_topic') and self._mqtt_announce_topic:
                client.subscribe(self._mqtt_announce_topic, qos=1)
                logger.info(
                    "Subscribed to announce topic '%s'.",
                    self._mqtt_announce_topic,
                )
        else:
            logger.error("MQTT connect failed: %s", reason_code)

    def _on_mqtt_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        flags=None,
        reason_code=None,
        properties=None,
    ) -> None:
        """Called by paho when the broker connection is lost.

        paho will automatically attempt reconnection when ``loop_start()`` is
        active.  We just log the event here.

        Args:
            client: The paho MQTT client.
            userdata: User data passed to the client (unused).
            flags: Disconnect flags (paho v2).
            reason_code: paho-mqtt v2 ReasonCode (0 = clean, non-zero = drop).
            properties: MQTT v5 properties (unused).
        """
        # paho v2 ReasonCode: check .is_failure or compare via .value
        failed = False
        if reason_code is not None:
            if hasattr(reason_code, 'is_failure'):
                failed = reason_code.is_failure
            elif hasattr(reason_code, 'value'):
                failed = reason_code.value != 0
            else:
                failed = bool(reason_code)

        if failed:
            logger.warning("MQTT connection lost (%s) — will reconnect.", reason_code)
        else:
            logger.info("MQTT disconnected cleanly.")

    def _on_mqtt_message(
        self,
        client: mqtt.Client,
        userdata,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Called by paho on the background thread when a message arrives.

        This method intentionally does as little work as possible on paho's
        thread.  It decodes the JSON payload and schedules the real async
        handler on the event loop via ``call_soon_threadsafe``.

        Malformed messages are logged and discarded — we never want an
        unexpected payload to crash the background thread.

        Args:
            client: The paho MQTT client.
            userdata: User data passed to the client (unused).
            msg: The received MQTT message (topic + payload bytes).
        """
        try:
            payload_str = msg.payload.decode("utf-8")
            event_data = json.loads(payload_str)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Malformed MQTT message on %s: %s", msg.topic, exc)
            return

        if self._loop is None:
            # Shouldn't happen, but guard defensively.
            return

        # Route announce messages to the announce handler instead of detection.
        if (
            hasattr(self, '_mqtt_announce_topic')
            and msg.topic == self._mqtt_announce_topic
        ):
            self._loop.call_soon_threadsafe(
                self._schedule_announce, event_data
            )
            return

        # Hand off to the asyncio event loop — this is the thread boundary.
        # asyncio.create_task cannot be called directly from another thread;
        # call_soon_threadsafe schedules a coroutine creation safely.
        self._loop.call_soon_threadsafe(
            self._schedule_detection, event_data
        )

    def _schedule_detection(self, event_data: dict) -> None:
        """Create an asyncio Task for ``_handle_detection`` from the event loop thread.

        This is the glue called by ``call_soon_threadsafe``.  It runs on the
        event loop thread so it is safe to create Tasks here.

        Args:
            event_data: Decoded Frigate event dict.
        """
        task = asyncio.create_task(self._handle_detection(event_data))
        # Track the task so graceful shutdown can drain it.
        self._active_tasks.add(task)
        # Auto-remove from the tracking set when the task completes.
        task.add_done_callback(self._active_tasks.discard)

    # ── MQTT Announce handler ────────────────────────────────────────────────

    def _schedule_announce(self, event_data: dict) -> None:
        """Create an asyncio Task for ``_handle_announce`` from the event loop thread.

        Called by ``call_soon_threadsafe`` when a message arrives on the
        announce topic. Same thread-boundary pattern as ``_schedule_detection``.

        Args:
            event_data: Decoded JSON payload from the announce MQTT message.
        """
        task = asyncio.create_task(self._handle_announce(event_data))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def _handle_announce(self, event_data: dict) -> None:
        """Handle an MQTT announce request — synthesise TTS and push to camera.

        Expected payload::

            {
                "camera": "front_door",
                "message": "Package delivered at front door",
                "voice": "af_heart",       // optional
                "provider": "kokoro",      // optional
                "speed": 1.0,              // optional
                "tone": "none"             // optional: short, long, siren, none
            }

        Delegates to the preview API's announce handler if available, otherwise
        runs the pipeline directly.

        Args:
            event_data: Decoded JSON dict from the MQTT announce message.
        """
        camera = str(event_data.get("camera", "")).strip()
        message = str(event_data.get("message", "")).strip()

        if not camera or not message:
            logger.warning(
                "MQTT announce: missing 'camera' or 'message' field, ignoring. "
                "Payload keys: %s",
                list(event_data.keys()),
            )
            return

        if len(message) > 1000:
            logger.warning(
                "MQTT announce: message too long (%d chars, max 1000), truncating.",
                len(message),
            )
            message = message[:1000]

        logger.info(
            "MQTT announce: camera=%s message_len=%d",
            camera,
            len(message),
        )

        # If the preview API is running, delegate to its announce handler
        # which has the full TTS→convert→tone→push pipeline.
        if self._preview_api is not None:
            import aiohttp
            try:
                preview_port = self.config.get("preview_api_port", 8892)
                url = f"http://127.0.0.1:{preview_port}/api/announce"
                payload = {
                    "camera": camera,
                    "message": message,
                }
                # Pass through optional fields.
                for key in ("voice", "provider", "speed", "tone"):
                    if key in event_data:
                        payload[key] = event_data[key]

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        result = await resp.json()
                        if resp.status == 200 and result.get("success"):
                            logger.info(
                                "MQTT announce: success camera=%s duration_ms=%s",
                                camera,
                                result.get("duration_ms"),
                            )
                        else:
                            logger.error(
                                "MQTT announce: failed camera=%s error=%s",
                                camera,
                                result.get("error", f"HTTP {resp.status}"),
                            )
            except Exception as exc:
                logger.error(
                    "MQTT announce: request to preview API failed: %s", exc
                )
        else:
            logger.warning(
                "MQTT announce: preview API not available, cannot process announce for camera=%s",
                camera,
            )

    # ── Pipeline orchestration ────────────────────────────────────────────────

    async def _handle_detection(self, event_data: dict) -> None:
        """Main deterrent pipeline — called for every qualifying MQTT event.

        This is the heart of VoxWatch.  The flow is:

          1. Filter: only ``type=new``, ``label=person``, score >= min_score.
          2. Guard: camera enabled, active hours, per-camera cooldown.
          3. Mark cooldown immediately (before any awaits) so a second rapid
             detection on the same camera doesn't race through the gate.
          4. Launch Stage 1 audio and Stage 2 AI prep concurrently.
          5. Wait for Stage 1 to finish (it plays to the speaker in real time).
          6. Play Stage 2 audio with the AI-generated description.
          7. Optionally run Stage 3 if person is still present.

        Args:
            event_data: Decoded Frigate MQTT event dict with ``type``,
                        ``before``, and ``after`` keys.
        """
        # ── Guard 1: event type and label ──────────────────────────────────
        # Frigate emits "new", "update", and "end" events.  We only act on
        # "new" to avoid retriggering on motion updates for the same person.
        event_type = event_data.get("type", "")
        if event_type != "new":
            return

        after = event_data.get("after", {})
        label = after.get("label", "")
        if label != "person":
            return

        score = float(after.get("score", 0.0))
        camera_name = after.get("camera", "")
        event_id = after.get("id", "unknown")
        # frame_time is available if needed for future features (e.g. fetching
        # the exact detection frame from Frigate rather than the latest snapshot).
        _frame_time = after.get("frame_time", 0.0)

        conditions = self.config.get("conditions", {})
        min_score = float(conditions.get("min_score", 0.7))

        if score < min_score:
            logger.debug(
                "Event %s on %s: score %.2f < min_score %.2f",
                event_id,
                camera_name,
                score,
                min_score,
            )
            return

        # ── Guard 2: camera enabled ────────────────────────────────────────
        cameras = self.config.get("cameras", {})
        camera_cfg = cameras.get(camera_name)
        if not camera_cfg:
            logger.debug(
                "Event %s: camera '%s' not in config.", event_id, camera_name
            )
            return
        if not camera_cfg.get("enabled", True):
            logger.debug(
                "Event %s: camera '%s' is disabled.", event_id, camera_name
            )
            return

        # ── Guard 3: active hours ─────────────────────────────────────────
        if not is_active_hours(self.config, logger):
            logger.info(
                "Event %s on %s: outside active hours.", event_id, camera_name
            )
            return

        # ── Guard 4: cooldown ─────────────────────────────────────────────
        cooldown_seconds = float(conditions.get("cooldown_seconds", 60))
        if not check_cooldown(self._cooldowns, camera_name, cooldown_seconds, logger):
            logger.info(
                "Event %s on %s: camera in cooldown.", event_id, camera_name
            )
            return

        # Cooldown is now marked — subsequent events for this camera will be
        # skipped until cooldown_seconds has elapsed.
        camera_stream = camera_cfg.get("go2rtc_stream", camera_name)

        logger.info(
            "Handling detection: event=%s camera=%s score=%.2f",
            event_id,
            camera_name,
            score,
        )

        # ── Telemetry: record the detection and start the latency clock ────
        # _pipeline_start_ts is a monotonic clock value used at the end of this
        # method to compute total_latency_ms for the event log.  We use
        # time.monotonic() (not time.time()) for latency because it is
        # not affected by clock adjustments.
        _pipeline_start_ts = time.monotonic()
        detection_utc = datetime.now(tz=UTC)
        record_detection(self._camera_stats, camera_name, detection_utc)

        # Initialise result accumulators for the event log entry.  These are
        # filled in as each stage completes and passed to append_event_log at
        # the bottom of this method.
        _initial_audio_success: bool | None = None
        _escalation_description: str | None = None
        _escalation_audio_success: bool | None = None
        _escalation_ran: bool = False

        # ── Initial Response + AI prep (concurrent) ───────────────────────
        # The new smart-escalation pipeline:
        #
        #   1. Backchannel warmup (silent push to establish go2rtc connection).
        #   2. Initial Response — plays the mode's pre-cached message instantly
        #      (0 s delay).  This is intentionally short: 1 sentence, mode-
        #      specific, no AI required.
        #   3. AI analysis runs concurrently during step 2 so its latency is
        #      hidden behind the audio playback.
        #   4. Escalation — fires after `pipeline.escalation.delay` seconds IF
        #      the person is still present.  The AI description is inserted into
        #      the mode's escalation template.
        #   5. Resolution — optional, plays when person leaves.

        stage2_cfg = self.config.get("stage2", {})
        snapshot_count = stage2_cfg.get("snapshot_count", 3)
        snapshot_interval_ms = stage2_cfg.get("snapshot_interval_ms", 1000)

        pipeline_cfg = self.config.get("pipeline", {})
        initial_cfg = pipeline_cfg.get("initial_response", {})
        escalation_cfg = pipeline_cfg.get("escalation", {})
        resolution_cfg = pipeline_cfg.get("resolution", {})

        initial_enabled: bool = initial_cfg.get("enabled", True)
        escalation_enabled: bool = escalation_cfg.get("enabled", True)
        escalation_delay: float = float(escalation_cfg.get("delay", 6))

        # Resolve the active response mode once so we don't re-read config
        # in every helper call.  Use the new mode loader which respects
        # per-camera overrides; keep the legacy mode_name string for the
        # parts of the pipeline that have not been migrated yet.
        mode_name, _ = _get_active_mode(self.config)
        # Per-camera override: if this camera has a mode override configured
        # under response_modes.camera_overrides, the mode object reflects it.
        _active_mode_obj = get_active_mode_obj(self.config, camera_name)
        # Re-resolve mode_name from the mode object so it agrees with the
        # per-camera override (e.g. camera_overrides.backyard_cam = homeowner).
        mode_name = _active_mode_obj.id

        logger.info(
            "Pipeline start: event=%s camera=%s mode=%s",
            event_id, camera_stream, mode_name,
        )

        # ── MQTT: publish detection_started ────────────────────────────────
        vw_event_id = ""
        if self._publisher:
            frigate_host = self.config.get("frigate", {}).get("host", "localhost")
            frigate_port = self.config.get("frigate", {}).get("port", 5000)
            snapshot_url = f"http://{frigate_host}:{frigate_port}/api/events/{event_id}/snapshot.jpg"
            vw_event_id = self._publisher.publish_detection_started(
                camera=camera_name,
                mode=mode_name,
                frigate_event_id=event_id,
                snapshot_url=snapshot_url,
            )

        # ── Step A: Backchannel warmup ─────────────────────────────────────
        # Runs concurrently with everything else — goal is for the go2rtc
        # backchannel to be warm before Initial Response TTS is ready.
        warmup_task = asyncio.create_task(
            self._audio.warmup_backchannel(camera_stream),
            name=f"warmup_{event_id}",
        )

        # ── Step B: AI analysis (concurrent with warmup) ──────────────────
        # Start grabbing snapshots and running AI immediately.  By the time
        # Initial Response audio plays and the escalation delay elapses, the
        # AI result should already be available.
        ai_prep_task = asyncio.create_task(
            self._stage2_ai_prep(
                event_id, camera_name, snapshot_count, snapshot_interval_ms,
            ),
            name=f"ai_prep_{event_id}",
        )

        # ── Step C: Initial Response ───────────────────────────────────────
        # Wait only for the backchannel warmup, then play the mode's instant
        # pre-cached message.  We do NOT wait for AI here.
        await warmup_task

        if initial_enabled:
            initial_push_ok = await self._play_initial_response(
                camera_stream, mode_name, _active_mode_obj.voice,
            )
            _initial_audio_success = initial_push_ok
            record_audio_push(self._camera_stats, camera_name, initial_push_ok)
            logger.info("Initial Response: complete (pushed=%s).", initial_push_ok)

            # ── MQTT: publish stage 1 ──────────────────────────────────────
            if self._publisher:
                self._publisher.publish_stage(
                    vw_event_id=vw_event_id,
                    camera=camera_name,
                    stage=1,
                    mode=mode_name,
                    audio_pushed=_initial_audio_success,
                    frigate_event_id=event_id,
                )

        # ── Step D: Escalation delay ───────────────────────────────────────
        # Wait the configured delay while AI analysis finishes in background.
        # asyncio.sleep yields control so other events can be processed.
        if escalation_enabled:
            logger.info(
                "Escalation: waiting %.0fs before escalation check...",
                escalation_delay,
            )
            await asyncio.sleep(escalation_delay)

            # ── Step E: Escalation ─────────────────────────────────────────
            _escalation_ran = True
            ai_description: str | None = await ai_prep_task
            _escalation_description = ai_description

            s_esc_description, s_esc_push_ok = await self._run_escalation(
                event_id, camera_name, camera_stream, mode_name, ai_description,
                _active_mode_obj.voice,
            )
            # Use the more detailed description if the escalation stage got one
            if s_esc_description:
                _escalation_description = s_esc_description
            _escalation_audio_success = s_esc_push_ok
            if s_esc_push_ok:
                record_audio_push(self._camera_stats, camera_name, s_esc_push_ok)

            # ── MQTT: publish stage 2 ──────────────────────────────────────
            if self._publisher and _escalation_ran:
                self._publisher.publish_stage(
                    vw_event_id=vw_event_id,
                    camera=camera_name,
                    stage=2,
                    mode=mode_name,
                    audio_pushed=_escalation_audio_success,
                    ai_analysis={"description": _escalation_description} if _escalation_description else None,
                    frigate_event_id=event_id,
                )
        else:
            # Escalation disabled — still drain the AI task to avoid orphaned tasks.
            ai_prep_task.cancel()
            logger.info("Escalation: disabled in config — done.")

        # ── Step F: Resolution (optional) ─────────────────────────────────
        # Resolution is off by default (most deployments don't need it).
        if resolution_cfg.get("enabled", False):
            await self._play_resolution(camera_stream, resolution_cfg)

        # ── Event log ─────────────────────────────────────────────────────
        total_latency_ms = int((time.monotonic() - _pipeline_start_ts) * 1000)

        # ── MQTT: publish detection_ended ──────────────────────────────────
        if self._publisher:
            stages_completed = 1  # stage 1 always fires
            if _escalation_ran:
                stages_completed = 2
            reason = "all_stages_completed"
            if not _escalation_ran and _escalation_description is None:
                reason = "person_left"
            self._publisher.publish_ended(
                vw_event_id=vw_event_id,
                camera=camera_name,
                reason=reason,
                stages_completed=stages_completed,
                total_duration_seconds=total_latency_ms / 1000.0,
                mode=mode_name,
                frigate_event_id=event_id,
            )

        event_entry: dict[str, Any] = {
            "timestamp": detection_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event_id": event_id,
            "camera": camera_name,
            "score": round(score, 4),
            "response_mode": mode_name,
            "initial_audio_success": _initial_audio_success,
            "escalation_ran": _escalation_ran,
            "escalation_description": _escalation_description,
            "escalation_audio_success": _escalation_audio_success,
            # Legacy keys retained for dashboard / log consumers that read
            # the old field names (stage2_* / stage3_*).
            "stage2_description": _escalation_description,
            "stage2_audio_success": _initial_audio_success,
            "stage3_ran": _escalation_ran,
            "stage3_description": _escalation_description,
            "stage3_audio_success": _escalation_audio_success,
            "total_latency_ms": total_latency_ms,
        }
        # Pass the operator-configured rotation threshold so the events file is
        # rotated according to config rather than always using the module default.
        events_max_bytes = self.config.get("logging", {}).get(
            "events_max_bytes", None
        )
        append_event_log(
            DATA_DIR,
            event_entry,
            **({"max_bytes": events_max_bytes} if events_max_bytes is not None else {}),
        )

    # ── Pipeline stage helpers ────────────────────────────────────────────────

    async def _play_initial_response(
        self,
        camera_stream: str,
        mode_name: str,
        voice_config: "VoiceConfig | None" = None,
    ) -> bool:
        """Play the mode's instant Initial Response message (0 s delay, 1 sentence).

        The Initial Response fires immediately after backchannel warmup.  It
        uses the pre-defined ``DEFAULT_MESSAGES[mode_name]["initial"]`` string so
        no AI call is needed — latency is bounded by TTS generation time only.

        Dispatch modes (``police_dispatch`` etc.) use the same short canned text
        rather than the full segmented radio path, keeping Initial Response fast.
        The segmented radio treatment is reserved for the Escalation stage where
        the AI's structured JSON is available.

        When a dispatch mode is active and ``response_mode.dispatch.address``
        is configured (via the dashboard Dispatch Settings panel), the Initial
        Response message is address-aware (e.g. "All units, 10-97 at 123 Main
        Street. Subject detected.") instead of the generic static default.
        ``get_dispatch_initial_message()`` handles address and agency resolution.

        Args:
            camera_stream: go2rtc stream name for the target camera.
            mode_name: Active response mode name (e.g. ``"private_security"``).
            voice_config: Optional per-persona voice overrides forwarded from
                the active ResponseMode.

        Returns:
            True if the audio push succeeded, False otherwise.
        """
        from voxwatch.radio_dispatch import DISPATCH_MODES  # noqa: PLC0415

        if mode_name in DISPATCH_MODES:
            # For dispatch modes: build an address/agency-aware canned message
            # rather than the plain static default.  The full segmented radio
            # treatment (with AI-driven suspect description) fires in Escalation.
            initial_text = get_dispatch_initial_message(self.config)
        else:
            # Try the new mode system first: get the stage1 template.
            # The camera_name is embedded in mode_name already (resolved above),
            # so look up the mode object and pull its stage1 template.
            try:
                mode_obj = get_active_mode_obj(self.config)
                if mode_obj.id == mode_name:
                    # Build minimal ai_vars — no AI result available yet at stage1.
                    _vars = build_ai_vars(self.config, camera_name="")
                    initial_text = get_mode_template(mode_obj, "stage1", _vars, index=0)
                else:
                    raise LookupError("mode_name mismatch")
            except Exception:
                # Graceful fallback to the old DEFAULT_MESSAGES dict.
                mode_defaults = DEFAULT_MESSAGES.get(mode_name, DEFAULT_MESSAGES["standard"])
                initial_text = mode_defaults.get(
                    "initial",
                    DEFAULT_MESSAGES["standard"]["initial"],
                )

        logger.info(
            "Initial Response [%s]: '%s'", mode_name, initial_text
        )
        return await self._audio.generate_and_push(
            camera_stream, initial_text, "stage2", voice_config
        )

    async def _run_escalation(
        self,
        event_id: str,
        camera_name: str,
        camera_stream: str,
        mode_name: str,
        ai_description: str | None,
        voice_config: "VoiceConfig | None" = None,
    ) -> tuple[str | None, bool]:
        """Run the Escalation stage if the person is still present.

        The Escalation stage is the primary deterrent response.  It:
          1. Checks whether the person is still present via Frigate API.
          2. If present: inserts the AI description into the mode's escalation
             template and plays it.  Dispatch modes use the full segmented radio
             path with the AI's structured JSON.
          3. If absent: logs and returns without playing anything.

        This method replaces the old ``_run_stage3``.  The old method is kept as
        a thin alias for backward compatibility with any external callers.

        Args:
            event_id: Frigate event ID.
            camera_name: Name of the triggering camera.
            camera_stream: go2rtc stream name for audio output.
            mode_name: Active response mode name.
            ai_description: AI-generated description string from ``_stage2_ai_prep``,
                or None if the AI call failed.  For dispatch modes this should be
                a JSON string; for other modes it is a plain sentence.
            voice_config: Optional per-persona voice overrides forwarded from
                the active ResponseMode.  Passed through to every TTS call so
                the correct voice is used for each persona.

        Returns:
            A 2-tuple of (description_used, push_success).
            ``description_used`` is the text that was inserted into the audio
            (may be the mode default if AI failed), or None if escalation was
            skipped.  ``push_success`` is True if the audio push succeeded.
        """
        stage3_cfg = self.config.get("stage3", {})

        # ── Presence check ─────────────────────────────────────────────────
        # Only fire if person is confirmed still present (configurable).
        escalation_cfg = self.config.get("pipeline", {}).get("escalation", {})
        condition: str = escalation_cfg.get("condition", "person_still_present")
        if condition == "person_still_present" and stage3_cfg.get(
            "person_still_present_check", True
        ):
            logger.info(
                "Escalation: checking if person still present on %s...", camera_name
            )
            try:
                still_present = await check_person_still_present(
                    self.config, camera_name,
                )
            except Exception as exc:
                logger.error(
                    "Escalation: presence check error: %s — skipping.", exc
                )
                return None, False

            if not still_present:
                logger.info(
                    "Escalation: person no longer present on %s — skipping.", camera_name
                )
                return None, False

            logger.info("Escalation: person confirmed still present.")

        # ── If AI description missing, run a fresh behavioral analysis ────
        # When the initial AI prep timed out or returned None, attempt a new
        # video/snapshot analysis now that the escalation delay has elapsed.
        if not ai_description and stage3_cfg.get("enabled", True):
            logger.info("Escalation: no initial AI description — running behavioral analysis.")
            _, ai_description = await self._run_stage3_analysis(event_id, camera_name)

        # ── Build and play the escalation message ─────────────────────────
        if self._is_dispatch_mode():
            push_ok = await self._play_dispatch_escalation(
                camera_stream, ai_description
            )
            return ai_description, push_ok

        # Standard/non-dispatch mode: use AI description directly if present,
        # otherwise render the mode's stage3 fallback template with AI vars.
        if ai_description:
            # AI returned something — use it directly (may be a plain sentence
            # or a JSON phrase array from the natural cadence system).
            escalation_message = ai_description
        else:
            # AI failed — build variable-substituted fallback from mode template.
            logger.warning(
                "Escalation [%s]: no AI description — using mode fallback template.",
                mode_name,
            )
            try:
                mode_obj = get_active_mode_obj(self.config, camera_name)
                ai_vars = build_ai_vars(self.config, camera_name=camera_name)
                escalation_message = get_mode_template(mode_obj, "stage3", ai_vars)
            except Exception:
                # Ultimate fallback to old DEFAULT_MESSAGES.
                mode_defaults = DEFAULT_MESSAGES.get(mode_name, DEFAULT_MESSAGES["standard"])
                escalation_message = mode_defaults.get(
                    "escalation",
                    DEFAULT_MESSAGES["standard"]["escalation"],
                )

        logger.info(
            "Escalation [%s]: playing on %s — '%s...'",
            mode_name, camera_stream, escalation_message[:80],
        )

        # ── Natural cadence path ───────────────────────────────────────────
        # When the AI returned a JSON array of short phrases AND natural cadence
        # is enabled, use generate_natural_tts for a more human-sounding result.
        # The template phrase(s) are prepended so the mode's framing is always
        # present regardless of what the AI returned.
        cadence_enabled: bool = (
            self.config.get("speech", {})
            .get("natural_cadence", {})
            .get("enabled", True)
        )
        ai_phrases = _try_parse_phrase_list(ai_description)

        if cadence_enabled and ai_phrases:
            # Build the full phrase list: template phrase + AI phrases.
            # The escalation_message may itself be a single short sentence, so
            # we prepend it as the first element.
            full_phrases = [escalation_message] + ai_phrases
            import os as _os
            cadence_path = _os.path.join(
                self._audio._serve_dir, "escalation_cadence_tts.wav"
            )
            converted_path = _os.path.join(
                self._audio._serve_dir, "escalation_cadence_ready.wav"
            )
            try:
                cadence_ok = await self._audio.generate_natural_tts(
                    full_phrases, cadence_path, voice_config
                )
                if cadence_ok:
                    conv_ok = await self._audio.convert_audio(cadence_path, converted_path)
                    if conv_ok:
                        tone_name = self._audio._get_stage_tone("stage3_tone")
                        audio_to_push = await self._audio.prepend_tone(
                            converted_path, tone_name
                        )
                        push_ok = await self._audio.push_audio(camera_stream, audio_to_push)
                        # Cleanup temp files.
                        for _p in [cadence_path, converted_path]:
                            with contextlib.suppress(OSError):
                                _os.remove(_p)
                        if audio_to_push not in (cadence_path, converted_path):
                            with contextlib.suppress(OSError):
                                _os.remove(audio_to_push)
                        return ai_description, push_ok
                logger.warning(
                    "Escalation [%s]: natural cadence failed — falling back to flat TTS",
                    mode_name,
                )
            except Exception as cadence_exc:
                logger.warning(
                    "Escalation [%s]: natural cadence raised %s — falling back to flat TTS",
                    mode_name,
                    cadence_exc,
                )

        # Flat-string fallback (natural cadence disabled, no phrases, or error).
        push_ok = await self._audio.generate_and_push(
            camera_stream, escalation_message, "stage3", voice_config
        )
        return ai_description, push_ok

    async def _run_stage3_analysis(
        self,
        event_id: str,
        camera_name: str,
    ) -> tuple[str | None, str | None]:
        """Run behavioral video/snapshot analysis for the Escalation stage.

        Attempts to grab a video clip from Frigate and analyze it.  Falls back
        to snapshots if the clip is unavailable or the provider does not support
        video.  Returns both the raw AI text and a display label.

        This extracts the pure analysis logic that was previously embedded in
        ``_run_stage3``, so it can be called independently of audio playback.

        Args:
            event_id: Frigate event ID.
            camera_name: Name of the triggering camera.

        Returns:
            A 2-tuple of (stage_label, ai_description).  ``stage_label`` is
            ``"video"`` or ``"snapshot"`` for logging.  ``ai_description`` is
            the raw AI output string, or None if all attempts failed.
        """
        stage3_cfg = self.config.get("stage3", {})
        clip_seconds = stage3_cfg.get("video_clip_seconds", 5)

        s3_prompt = get_stage3_prompt(self.config, camera_name=camera_name)
        scene_ctx = self._get_scene_context(camera_name)
        if scene_ctx:
            s3_prompt = f"Scene context: {scene_ctx}\n\n{s3_prompt}"

        # Try video clip first
        try:
            video_clip = await grab_video_clip(self.config, event_id, clip_seconds)
        except Exception as exc:
            logger.warning("Escalation analysis: video clip failed: %s — trying snapshots.", exc)
            video_clip = None

        if video_clip:
            try:
                desc = await analyze_video(video_clip, s3_prompt, self.config)
                if desc:
                    logger.info(
                        "Escalation analysis: video result: %s", desc[:120]
                    )
                    return "video", desc
            except Exception as exc:
                logger.error("Escalation analysis: video analysis error: %s", exc, exc_info=True)

        # Snapshot fallback
        if stage3_cfg.get("fallback_to_snapshots", True):
            fallback_count = stage3_cfg.get("fallback_snapshot_count", 5)
            logger.info(
                "Escalation analysis: falling back to %d snapshots.", fallback_count
            )
            try:
                fallback_snaps = await grab_snapshots(
                    self.config, event_id, camera_name, fallback_count, 500,
                )
                if fallback_snaps:
                    desc = await analyze_snapshots(fallback_snaps, s3_prompt, self.config)
                    if desc:
                        logger.info(
                            "Escalation analysis: snapshot result: %s", desc[:120]
                        )
                        return "snapshot", desc
            except Exception as exc:
                logger.error(
                    "Escalation analysis: snapshot fallback error: %s", exc, exc_info=True
                )

        return None, None

    async def _play_initial_response_dispatch(
        self,
        camera_stream: str,
    ) -> bool:
        """Play a short canned dispatch alert as the Initial Response.

        Dispatch modes (``police_dispatch``) use this instead of
        ``_play_initial_response`` so the Initial Response remains a single
        short line rather than the full segmented radio treatment.  The full
        dispatch audio is reserved for the Escalation stage.

        Args:
            camera_stream: go2rtc stream name.

        Returns:
            True if the push succeeded, False otherwise.
        """
        canned = "All units... be advised. Subject detected."
        logger.info("Initial Response [dispatch]: '%s'", canned)
        return await self._audio.generate_and_push(camera_stream, canned, "stage2")

    async def _play_dispatch_escalation(
        self,
        camera_stream: str,
        ai_output: str | None,
    ) -> bool:
        """Play segmented dispatch audio for the Escalation stage.

        Wraps the existing ``_play_dispatch_stage2`` and ``_play_dispatch_stage3``
        logic into a single unified method.  The AI output is treated as a Stage 3
        behavioral update if it contains movement/behavior JSON; otherwise it is
        handled as a Stage 2 appearance description.

        For simplicity, this always routes through the Stage 3 (behavioral)
        dispatch path during escalation because by the time escalation fires,
        the person has been present for several seconds and behavioral context
        is more useful than appearance alone.

        Fallback: if ``ai_output`` is None, uses a canned escalation alert.

        Args:
            camera_stream: go2rtc stream name.
            ai_output: Raw AI output string (JSON for dispatch modes).

        Returns:
            True if audio was pushed successfully, False otherwise.
        """
        if not ai_output:
            fallback = (
                "Dispatch update. Suspect remains on scene. "
                "Advise... immediate departure."
            )
            logger.warning("Escalation dispatch: no AI output — using canned escalation.")
            return await self._audio.generate_and_push(camera_stream, fallback, "stage3")

        # Try Stage 3 (behavior) schema first; if the JSON parses as Stage 2
        # (suspect_count, description, location) it will fall through gracefully.
        segments = segment_dispatch_message(ai_output, stage="stage3", config=self.config)
        logger.info(
            "Escalation dispatch: %d segment(s) from AI output.", len(segments)
        )

        output_path = os.path.join(self._audio._serve_dir, "escalation_dispatch_ready.wav")
        composed = await compose_dispatch_audio(
            segments=segments,
            output_path=output_path,
            audio_pipeline=self._audio,
            config=self.config,
            stage_label="escalation",
        )

        if composed and os.path.exists(composed):
            ok = await self._audio.push_audio(camera_stream, composed)
            with contextlib.suppress(OSError):
                os.remove(composed)
            return ok

        logger.warning("Escalation dispatch: composition failed — falling back to plain TTS.")
        return await self._audio.generate_and_push(
            camera_stream,
            " ".join(segments) if segments else "Dispatch update. Suspect remains on scene.",
            "stage3",
        )

    async def _play_resolution(
        self,
        camera_stream: str,
        resolution_cfg: dict,
    ) -> bool:
        """Play the Resolution message when the person has left (optional).

        Resolution is disabled by default (``pipeline.resolution.enabled: false``)
        because most deployments don't need it.  When enabled, it plays a short
        neutral "area clear" message to close out the deterrent sequence.

        Args:
            camera_stream: go2rtc stream name.
            resolution_cfg: The ``pipeline.resolution`` config sub-dict.

        Returns:
            True if the push succeeded, False otherwise.
        """
        message: str = resolution_cfg.get("message", "Area clear.")
        logger.info("Resolution: playing '%s' on %s.", message, camera_stream)
        return await self._audio.generate_and_push(camera_stream, message, "stage3")

    async def _stage2_ai_prep(
        self,
        event_id: str,
        camera_name: str,
        snapshot_count: int,
        snapshot_interval_ms: int,
    ) -> str | None:
        """Grab snapshots and return an AI description of the person's appearance.

        Runs concurrently with Initial Response audio playback to hide AI latency.
        If anything goes wrong (network error, AI timeout, etc.) we return None
        so the caller can fall back gracefully rather than crashing the pipeline.

        For dispatch modes the prompt asks the AI to return a JSON object;
        for all other response modes a single plain-text sentence is returned.

        Args:
            event_id: Frigate event ID (used to fetch the correct snapshot).
            camera_name: Name of the camera that triggered the event.
            snapshot_count: How many snapshot frames to grab for the AI.
            snapshot_interval_ms: Milliseconds between additional snapshots.

        Returns:
            AI-generated description string, or None if the analysis failed.
        """
        try:
            snapshots = await grab_snapshots(
                self.config, event_id, camera_name, snapshot_count, snapshot_interval_ms,
            )
            if not snapshots:
                logger.warning(
                    "AI prep: no snapshots returned for event %s.", event_id
                )
                return None

            # Build the prompt.  get_stage2_prompt() reads the active response
            # mode from config and applies the appropriate modifier.  Passing
            # camera_name enables per-camera override resolution so cameras
            # configured with different modes get the right prompt.
            prompt = get_stage2_prompt(self.config, camera_name=camera_name)
            scene_ctx = self._get_scene_context(camera_name)
            if scene_ctx:
                prompt = f"Scene context: {scene_ctx}\n\n{prompt}"

            description = await analyze_snapshots(snapshots, prompt, self.config)
            logger.info(
                "AI prep: description: %s",
                description[:120] if description else "(none)",
            )
            return description

        except Exception as exc:
            logger.error("AI prep error: %s", exc, exc_info=True)
            return None

    async def _run_stage3(
        self,
        event_id: str,
        camera_name: str,
        camera_stream: str,
    ) -> tuple[str | None, bool]:
        """Backward-compatibility alias for ``_run_escalation``.

        .. deprecated::
            The smart-escalation pipeline now calls ``_run_escalation`` directly.
            This method is retained so any external test code or tooling that
            calls ``_run_stage3`` continues to work without modification.

        Args:
            event_id: Frigate event ID.
            camera_name: Name of the triggering camera.
            camera_stream: go2rtc stream name for audio output.

        Returns:
            A 2-tuple of (ai_description, push_success).
        """
        mode_name, _ = _get_active_mode(self.config)
        return await self._run_escalation(
            event_id=event_id,
            camera_name=camera_name,
            camera_stream=camera_stream,
            mode_name=mode_name,
            ai_description=None,  # will trigger fresh behavioral analysis
        )

    # ── Dashboard output — status file ────────────────────────────────────────

    async def _write_status_loop(self) -> None:
        """Background coroutine: write /data/status.json every STATUS_WRITE_INTERVAL seconds.

        Runs as an asyncio Task started in ``start()`` and cancelled in the
        shutdown sequence.  Uses ``asyncio.sleep`` so it yields control between
        writes and never blocks the event loop.

        The loop swallows all exceptions except CancelledError so a transient
        filesystem error (e.g. disk full for one second) does not kill the task.
        """
        while True:
            try:
                self._write_status_file()
            except asyncio.CancelledError:
                # Re-raise so the Task is properly marked as cancelled.
                raise
            except Exception as exc:
                # Log but continue — a missed write is better than a dead task.
                logger.warning("Status file write failed: %s", exc)

            await asyncio.sleep(STATUS_WRITE_INTERVAL)

    def _write_status_file(self) -> None:
        """Write the current service state to /data/status.json via telemetry module.

        Delegates all serialisation and atomic-write logic to
        ``telemetry.write_status_file``, passing the service's live state as
        arguments so the telemetry module remains stateless and testable.
        """
        mqtt_connected = bool(
            self._mqtt_client and self._mqtt_client.is_connected()
        )
        write_status_file(
            config=self.config,
            data_dir=DATA_DIR,
            started_at=self._started_at,
            running=self._running,
            camera_stats=self._camera_stats,
            cooldowns=self._cooldowns,
            active_tasks_count=len(self._active_tasks),
            mqtt_connected=mqtt_connected,
            active_hours_active=is_active_hours(self.config, logger),
            service_version=SERVICE_VERSION,
        )

    # ── Config hot-reload ────────────────────────────────────────────────────

    # How often (seconds) to poll the config file's modification time.
    _CONFIG_POLL_INTERVAL: int = 10

    @staticmethod
    def _hash_file(path: str) -> str:
        """Compute a fast MD5 hash of a file's contents.

        Used instead of os.path.getmtime() because NFS/SMB bind mounts
        (common in Docker on NAS devices like Synology) do not reliably
        propagate mtime changes to the container.  Reading the file and
        hashing it is slightly more expensive but always correct.

        Args:
            path: Absolute path to the file to hash.

        Returns:
            Hex digest string, or empty string on read failure.
        """
        import hashlib
        try:
            with open(path, "rb") as fh:
                return hashlib.md5(fh.read()).hexdigest()
        except OSError:
            return ""

    async def _config_watch_loop(self) -> None:
        """Poll the config file for changes and trigger a hot-reload.

        Runs as a background asyncio Task for the lifetime of the service.
        Uses content hashing (MD5) instead of mtime because NFS/SMB bind
        mounts do not reliably propagate mtime changes to Docker containers.

        Errors reading the file are swallowed and retried on the next poll
        cycle.  Only the reload itself can log a warning; the watcher always
        continues running.
        """
        last_hash = self._hash_file(self._config_path)
        if not last_hash:
            logger.warning(
                "Config watcher: cannot read '%s' — "
                "hot-reload disabled for this session",
                self._config_path,
            )
            return

        logger.info(
            "Config watcher started (polling '%s' every %ds for changes).",
            self._config_path,
            self._CONFIG_POLL_INTERVAL,
        )

        while self._running:
            await asyncio.sleep(self._CONFIG_POLL_INTERVAL)
            current_hash = self._hash_file(self._config_path)
            if not current_hash:
                continue

            if current_hash != last_hash:
                last_hash = current_hash
                logger.info(
                    "Config file changed (content hash updated) — attempting hot-reload..."
                )
                await self._reload_config()

    async def _reload_config(self) -> None:
        """Re-read the config file and reinitialise only the changed components.

        Compares the new config against the current one section by section.
        Only components whose configuration actually differs are touched, so a
        change to ``conditions`` does not bounce the TTS provider, for example.

        Reinitialisation order:
          1. TTS (blocks: initialises provider and regenerates Stage 1 audio).
          2. Stage 1 message text (if TTS unchanged but message wording changed).
          3. AI, persona, conditions, cameras (in-place config swap, no I/O).

        The config swap is protected by ``_config_lock`` so detection handlers
        reading ``self.config`` always see a consistent snapshot.

        On any validation error the old config is kept and a warning is logged;
        the service never crashes due to a bad hot-reload.
        """
        # ── Load and validate new config ─────────────────────────────────
        try:
            new_config = reload_config(self._config_path)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning(
                "Config hot-reload skipped — new config is invalid: %s", exc
            )
            return
        except Exception as exc:
            logger.warning(
                "Config hot-reload skipped — unexpected error loading config: %s", exc
            )
            return

        old_config = self.config

        # ── Diff each section we care about ──────────────────────────────
        tts_changed = new_config.get("tts") != old_config.get("tts")
        stage1_msg_changed = (
            not tts_changed
            and new_config.get("messages", {}).get("stage1")
            != old_config.get("messages", {}).get("stage1")
        )
        ai_changed = new_config.get("ai") != old_config.get("ai")
        # Detect response_mode changes.  Also check the legacy "persona" key so
        # configs that have not been migrated still trigger a reload summary.
        persona_changed = (
            new_config.get("response_mode") != old_config.get("response_mode")
            or new_config.get("persona") != old_config.get("persona")
        )
        conditions_changed = new_config.get("conditions") != old_config.get("conditions")
        frigate_changed = new_config.get("frigate") != old_config.get("frigate")

        old_cameras = set(old_config.get("cameras", {}).keys())
        new_cameras = set(new_config.get("cameras", {}).keys())
        cameras_changed = new_config.get("cameras") != old_config.get("cameras")

        # Build a human-readable summary of what actually changed.
        changed_parts: list[str] = []
        if tts_changed:
            changed_parts.append(
                f"TTS provider changed to '{new_config.get('tts', {}).get('provider', '?')}'"
            )
        if stage1_msg_changed:
            changed_parts.append("Stage 1 message text changed")
        if ai_changed:
            changed_parts.append(
                f"AI primary provider changed to "
                f"'{new_config.get('ai', {}).get('primary', {}).get('provider', '?')}'"
            )
        if persona_changed:
            # Report the active mode name from whichever key is present.
            new_mode_name, _ = _get_active_mode(new_config)
            changed_parts.append(f"response_mode changed to '{new_mode_name}'")
        if conditions_changed:
            changed_parts.append("conditions changed")
        if cameras_changed:
            added = new_cameras - old_cameras
            removed = old_cameras - new_cameras
            if added:
                changed_parts.append(f"cameras added: {sorted(added)}")
            if removed:
                changed_parts.append(f"cameras removed: {sorted(removed)}")
            if not added and not removed:
                changed_parts.append("camera settings changed")
        if frigate_changed:
            changed_parts.append("Frigate/MQTT connection settings changed")

        if not changed_parts:
            logger.debug("Config file changed but no monitored sections differ — no action taken.")
            return

        logger.info("Config reloaded: %s", ", ".join(changed_parts))

        # ── Reinitialise TTS (async, must happen outside the lock) ───────
        # reload_tts() swaps self._audio.config internally and regenerates
        # the Stage 1 cached audio.  We do this before swapping self.config
        # so the audio pipeline is ready before detection handlers can read
        # the new config.
        if tts_changed:
            try:
                await self._audio.reload_tts(new_config)
            except Exception as exc:
                logger.warning(
                    "TTS reload failed (%s) — keeping old TTS config.  "
                    "Other config changes will still be applied.",
                    exc,
                )
                # Patch the new config to keep the old TTS section so the
                # atomic swap below doesn't change TTS settings on self.config.
                new_config["tts"] = old_config["tts"]
                new_config["messages"]["stage1"] = old_config["messages"]["stage1"]
        elif stage1_msg_changed:
            # TTS provider unchanged, only the message wording changed.
            try:
                await self._audio.recache_stage1(new_config)
            except Exception as exc:
                logger.warning(
                    "Stage 1 re-cache failed (%s) — old audio will be used.", exc
                )

        # ── Reconnect MQTT if credentials/host changed ────────────────────
        if frigate_changed and self._mqtt_client:
            try:
                logger.info("MQTT settings changed — reconnecting with new credentials...")
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
                self._mqtt_client = None
            except Exception as exc:
                logger.warning("Error disconnecting old MQTT client: %s", exc)

        # Do the atomic config swap FIRST so _connect_mqtt reads new creds

        # ── Atomic config swap ───────────────────────────────────────────
        # Hold the lock only for the dict assignment — we don't hold it during
        # the TTS I/O above because that could block detection handlers for
        # many seconds while models load.
        async with self._config_lock:
            self.config = new_config

        # Reconnect MQTT after config swap so _connect_mqtt reads new settings
        if frigate_changed:
            try:
                await self._connect_mqtt()
                if self._mqtt_client and self._mqtt_client.is_connected():
                    logger.info("MQTT reconnected successfully with updated settings.")
                else:
                    logger.warning("MQTT reconnect initiated — waiting for broker response.")
            except Exception as exc:
                logger.warning("MQTT reconnection failed: %s — will retry in background.", exc)

        # Reinitialize MQTT publisher if publish settings changed.
        mqtt_pub_changed = new_config.get("mqtt_publish") != old_config.get("mqtt_publish")
        if mqtt_pub_changed:
            publish_cfg = new_config.get("mqtt_publish", {})
            if publish_cfg.get("enabled", True) and self._mqtt_client:
                self._publisher = VoxWatchPublisher(self._mqtt_client, publish_cfg)
                logger.info("MQTT publisher reinitialized with updated settings.")
            else:
                self._publisher = None
                logger.info("MQTT event publishing disabled.")

        # Propagate the new config to the preview API so subsequent preview
        # requests use the updated dispatch address, agency, callsign, etc.
        if self._preview_api is not None:
            self._preview_api.update_config(new_config)

        logger.info("Hot-reload complete.")

    # ── Dispatch persona audio helpers ────────────────────────────────────────

    async def _play_dispatch_stage2(
        self,
        camera_stream: str,
        ai_output: str | None,
    ) -> bool:
        """Generate and push segmented dispatch audio for Stage 2.

        Called instead of the standard ``generate_and_push`` flow when a
        dispatch-style persona is active.  Segments the AI's structured JSON
        output into scanner-style speech chunks, composes them with radio
        static effects, and pushes the result.

        Fallback behaviour:
          - If ``ai_output`` is None or empty, a canned dispatch alert is used
            so the deterrent always plays something.
          - If ``compose_dispatch_audio`` fails entirely (returns None), the
            method falls back to plain ``generate_and_push`` with the raw
            ai_output text so the pipeline never goes silent.

        Args:
            camera_stream: go2rtc stream name for the target camera.
            ai_output: Raw AI response string (expected to be JSON for dispatch
                personas).  May be None if the AI call failed.

        Returns:
            True if audio was successfully pushed, False otherwise.
        """
        fallback_text = (
            "All units... 10-97. Unidentified subject on scene. "
            "Nearest unit, respond... code three."
        )

        if not ai_output:
            logger.warning(
                "Stage 2 dispatch: no AI output — using canned dispatch alert."
            )
            return await self._audio.generate_and_push(
                camera_stream, fallback_text, "stage2"
            )

        segments = segment_dispatch_message(ai_output, stage="stage2", config=self.config)
        logger.info(
            "Stage 2 dispatch: %d segment(s) generated from AI output.", len(segments)
        )

        output_path = os.path.join(self._audio._serve_dir, "stage2_dispatch_ready.wav")
        composed = await compose_dispatch_audio(
            segments=segments,
            output_path=output_path,
            audio_pipeline=self._audio,
            config=self.config,
            stage_label="stage2",
        )

        if composed and os.path.exists(composed):
            logger.info("Stage 2 dispatch: pushing composed audio to %s...", camera_stream)
            ok = await self._audio.push_audio(camera_stream, composed)
            # Clean up the composed file after push
            with contextlib.suppress(OSError):
                os.remove(composed)
            return ok

        # Composition failed entirely — fall back to plain TTS with the raw text
        logger.warning(
            "Stage 2 dispatch: composition failed — falling back to plain TTS."
        )
        plain_text = " ".join(segments) if segments else fallback_text
        return await self._audio.generate_and_push(
            camera_stream, plain_text, "stage2"
        )

    async def _play_dispatch_stage3(
        self,
        camera_stream: str,
        ai_output: str | None,
    ) -> bool:
        """Generate and push segmented dispatch audio for Stage 3.

        Equivalent to ``_play_dispatch_stage2`` but uses the Stage 3 JSON
        schema (behavior + movement) and assembles an escalation-update message
        rather than an initial contact message.

        Fallback behaviour mirrors ``_play_dispatch_stage2``: canned escalation
        text if no AI output, plain TTS if composition fails.

        Args:
            camera_stream: go2rtc stream name for the target camera.
            ai_output: Raw AI response string (expected to be JSON for dispatch
                personas).  May be None if the AI call failed.

        Returns:
            True if audio was successfully pushed, False otherwise.
        """
        fallback_text = (
            "Dispatch update. Suspect still on scene. "
            "This is now a ten thirty-one, crime in progress. Requesting backup."
        )

        if not ai_output:
            logger.warning(
                "Stage 3 dispatch: no AI output — using canned escalation alert."
            )
            return await self._audio.generate_and_push(
                camera_stream, fallback_text, "stage3"
            )

        segments = segment_dispatch_message(ai_output, stage="stage3", config=self.config)
        logger.info(
            "Stage 3 dispatch: %d segment(s) generated from AI output.", len(segments)
        )

        output_path = os.path.join(self._audio._serve_dir, "stage3_dispatch_ready.wav")
        composed = await compose_dispatch_audio(
            segments=segments,
            output_path=output_path,
            audio_pipeline=self._audio,
            config=self.config,
            stage_label="stage3",
        )

        if composed and os.path.exists(composed):
            logger.info("Stage 3 dispatch: pushing composed audio to %s...", camera_stream)
            ok = await self._audio.push_audio(camera_stream, composed)
            with contextlib.suppress(OSError):
                os.remove(composed)
            return ok

        logger.warning(
            "Stage 3 dispatch: composition failed — falling back to plain TTS."
        )
        plain_text = " ".join(segments) if segments else fallback_text
        return await self._audio.generate_and_push(
            camera_stream, plain_text, "stage3"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_dispatch_mode(self) -> bool:
        """Return True if the currently active response mode uses the dispatch pipeline.

        Checks the active response mode name (from ``config["response_mode"]["name"]``
        or the legacy ``config["persona"]["name"]``) against the canonical set of
        dispatch-style mode names defined in
        ``voxwatch.radio_dispatch.DISPATCH_MODES``.

        Dispatch modes route through a different audio path than standard modes:
        the AI is asked to return structured JSON instead of a free-text sentence,
        and the output is segmented and composed with radio static effects by the
        ``radio_dispatch`` module.

        This method is intentionally cheap — it reads a config value that is
        already loaded in memory — so it is safe to call multiple times per
        detection event.

        Returns:
            True if the active mode name is in ``DISPATCH_MODES``,
            False for all standard modes (including ``"standard"``,
            ``"mafioso"``, ``"private_security"``, ``"custom"``, etc.).
        """
        mode_name, _ = _get_active_mode(self.config)
        return mode_name in DISPATCH_MODES

    def _is_dispatch_persona(self) -> bool:
        """Backward-compatibility alias for ``_is_dispatch_mode``.

        .. deprecated::
            Use ``_is_dispatch_mode()`` instead.  This alias is retained so any
            test code or tooling that calls the old method name continues to work.

        Returns:
            Same value as ``_is_dispatch_mode()``.
        """
        return self._is_dispatch_mode()

    def _get_scene_context(self, camera_name: str) -> str | None:
        """Get the scene context string for a camera from config.

        Scene context gives the AI spatial awareness so it can reference
        landmarks in the camera's field of view (e.g. "person near the
        kitchen window" instead of "person near a window").

        Args:
            camera_name: Camera name matching the cameras config section.

        Returns:
            Scene context string, or None if not configured.
        """
        cameras = self.config.get("cameras", {})
        cam_cfg = cameras.get(camera_name, {})
        ctx = cam_cfg.get("scene_context")
        if ctx and isinstance(ctx, str) and ctx.strip():
            return ctx.strip()
        return None

    def _ensure_camera_stats(self, camera_name: str) -> None:
        """Lazily initialise the stats bucket for a camera if it does not exist.

        Thin wrapper around ``telemetry.ensure_camera_stats`` kept for
        backwards compatibility with any callers that reference it as a method.

        Args:
            camera_name: The Frigate/go2rtc camera name.
        """
        ensure_camera_stats(self._camera_stats, camera_name)


# ── Logging setup ─────────────────────────────────────────────────────────────


def setup_logging(
    level_str: str,
    log_file: str | None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure root and voxwatch loggers with console and rotating file output.

    All voxwatch modules use ``logging.getLogger("voxwatch.*")`` so this
    single configuration covers the whole service.

    Rotation prevents unbounded disk growth — default is 10 MB per file
    with 5 backups (50 MB total max).  These values are configurable in
    config.yaml under ``logging.max_bytes`` and ``logging.backup_count``.

    Args:
        level_str: Log level string ("DEBUG", "INFO", "WARNING", "ERROR").
        log_file: Absolute path to a log file, or None for console-only output.
        max_bytes: Maximum size of each log file before rotation (default 10 MB).
        backup_count: Number of rotated backup files to keep (default 5).
    """
    level = getattr(logging, level_str.upper(), logging.INFO)

    # Consistent format used by all handlers — timestamp, logger name, level, message.
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any pre-existing handlers to prevent duplicate log lines
    # (e.g. basicConfig auto-added a StreamHandler before we got here).
    root_logger.handlers.clear()

    # Console handler — always present so Docker logs work out of the box.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler — rotating to prevent unbounded disk growth.
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            logger.info(
                "Logging to file: %s (max %d MB, %d backups)",
                log_file,
                max_bytes // (1024 * 1024),
                backup_count,
            )
        except OSError as exc:
            logger.warning(
                "Could not open log file %s: %s — logging to console only.",
                log_file,
                exc,
            )


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the VoxWatch service.

    Parses command-line arguments, configures logging, loads config, and
    runs the async event loop.  Registers SIGTERM/SIGINT handlers for
    graceful shutdown so Docker stop/restart works cleanly.

    Example:
        python -m voxwatch.voxwatch_service
        python -m voxwatch.voxwatch_service --config /config/config.yaml
    """
    parser = argparse.ArgumentParser(
        description="VoxWatch — AI-powered security audio deterrent system."
    )
    parser.add_argument(
        "--config",
        default="/config/config.yaml",
        help="Path to config.yaml (default: /config/config.yaml)",
    )
    args = parser.parse_args()

    # Bootstrap minimal logging before the config is loaded so any early
    # errors are visible rather than silently swallowed.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    # Attempt to load config — if it doesn't exist yet, wait for the setup
    # wizard to write it.  This lets the container start cleanly before
    # config.yaml has been created via the first-run web wizard.
    config = load_config_or_none(args.config)
    if config is None:
        logger.info(
            "config.yaml not found at %s — waiting for setup. "
            "Open the VoxWatch Dashboard at http://your-host:33344 to complete first-run setup.",
            args.config,
        )
        while config is None:
            time.sleep(5)
            config = load_config_or_none(args.config)
        logger.info("config.yaml detected — starting VoxWatch service.")

    # Re-configure logging with values from the loaded config.
    # Rotation settings prevent unbounded disk growth — configurable in config.yaml.
    log_cfg = config.get("logging", {})
    setup_logging(
        level_str=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file"),
        max_bytes=log_cfg.get("max_bytes", 10 * 1024 * 1024),
        backup_count=log_cfg.get("backup_count", 5),
    )

    logger.info("Starting VoxWatch v%s", _get_version())
    logger.info("Config: %s", args.config)

    # Create the service instance.  Pass config_path so the hot-reload watcher
    # knows which file to monitor for changes.
    service = VoxWatchService(config, config_path=args.config)

    # Get (or create) the event loop before registering signal handlers,
    # because the handlers need a reference to the loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(sig_name: str) -> None:
        """Schedule graceful shutdown on the event loop when a signal arrives.

        This function is called from the signal handler installed below.
        We schedule ``service.stop()`` as a coroutine on the loop because
        signal handlers must not block or call asyncio directly.

        Args:
            sig_name: Human-readable signal name for logging.
        """
        logger.info("Received %s — initiating graceful shutdown...", sig_name)
        # create_task is safe here because this runs on the event loop thread
        # (asyncio signal handlers are delivered on the loop thread).
        loop.create_task(service.stop())

    # Register POSIX signal handlers.  On Windows, only SIGINT (Ctrl-C) is
    # reliably supported; SIGTERM is a no-op on win32 but harmless to register.
    for sig, name in [(signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")]:
        try:
            loop.add_signal_handler(sig, _handle_signal, name)
        except (NotImplementedError, AttributeError):
            # Windows does not support loop.add_signal_handler — fall back to
            # the standard signal module which handles SIGINT (Ctrl-C) only.
            signal.signal(sig, lambda s, f, n=name: _handle_signal(n))

    try:
        loop.run_until_complete(service.start())
    except KeyboardInterrupt:
        # Ctrl-C on platforms where the signal handler fallback isn't used.
        logger.info("KeyboardInterrupt received — shutting down...")
        loop.run_until_complete(service.stop())
    finally:
        # Cancel any remaining tasks and close the loop cleanly.
        pending = asyncio.all_tasks(loop)
        if pending:
            logger.debug("Cancelling %d pending task(s)...", len(pending))
            for task in pending:
                task.cancel()
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        loop.close()
        logger.info("Event loop closed. Goodbye.")


def _get_version() -> str:
    """Return the VoxWatch package version string.

    Returns:
        Version string from ``voxwatch.__version__``, or "unknown" on failure.
    """
    try:
        from voxwatch import __version__
        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    main()
