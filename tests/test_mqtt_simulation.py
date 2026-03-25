#!/usr/bin/env python3
"""
test_mqtt_simulation.py — VoxWatch MQTT Simulation Test

Simulates a Frigate person detection event so VoxWatch can be tested end-to-end
without a real person walking in front of a camera.  Two things happen together:

  1. A lightweight HTTP server mimics the Frigate API, serving the chosen test
     image at every snapshot/latest endpoint VoxWatch calls during its pipeline.
  2. A realistic Frigate MQTT event is published to ``frigate/events`` so VoxWatch
     picks it up and runs the full pipeline (Stage 1 audio, Stage 2 AI analysis,
     Stage 3 escalation, TTS, audio push to camera speaker).

The fake Frigate server binds to ``0.0.0.0`` so VoxWatch running in Docker can
reach it over the host network.

Prerequisites:
    paho-mqtt >= 2.0.0 (already in requirements.txt)
    A real MQTT broker reachable from this machine
    VoxWatch's config.yaml pointing ``frigate.host`` at this machine's IP and
    ``frigate.port`` at ``--frigate-port`` (see --redirect flag for automation)

Usage:
    # Simplest run — uses default camera and a random test image
    python tests/test_mqtt_simulation.py --mqtt-host 10.1.10.24

    # Named scenario with score override
    python tests/test_mqtt_simulation.py \\
        --scenario car_thief_night \\
        --mqtt-host 10.1.10.24 \\
        --mqtt-port 1883 \\
        --frigate-port 5123 \\
        --score 0.95

    # Use --redirect to have the script patch config.yaml temporarily
    python tests/test_mqtt_simulation.py \\
        --scenario porch_pirate_day \\
        --mqtt-host 10.1.10.24 \\
        --redirect \\
        --config /config/config.yaml

Scenarios (maps to test images in tests/test_images/):
    car_thief_night   — night_car_door.jpg    (person pulling car door handle, IR)
    prowler_night     — night_ir_prowler.jpg  (person in dark clothing near car, IR)
    gate_tester_day   — day_gate_hoodie.jpg   (hoodie + backpack testing gate, color)
    porch_pirate_day  — day_porch_pirate.jpg  (person crouching at door, package, color)
"""

import argparse
import http.server
import json
import os
import random
import re
import shutil
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# paho-mqtt import — fail loudly with a helpful message if missing
# ---------------------------------------------------------------------------

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[FAIL] paho-mqtt is not installed.")
    print("       Run: pip install 'paho-mqtt>=2.0.0'")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maps scenario names to their corresponding test image filenames.
SCENARIO_IMAGE_MAP: dict[str, str] = {
    "car_thief_night": "night_car_door.jpg",
    "prowler_night": "night_ir_prowler.jpg",
    "gate_tester_day": "day_gate_hoodie.jpg",
    "porch_pirate_day": "day_porch_pirate.jpg",
}

# Default test images directory relative to this script's parent.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_IMAGES_DIR = os.path.join(_SCRIPT_DIR, "test_images")

# Status tag constants — match the style used across VoxWatch test scripts.
_TAG_OK = "[OK]"
_TAG_FAIL = "[FAIL]"
_TAG_INFO = "[INFO]"
_TAG_MQTT = "[MQTT]"
_TAG_HTTP = "[HTTP]"
_TAG_WARN = "[WARN]"

# Seconds to wait between the countdown and publishing the MQTT event.
PUBLISH_COUNTDOWN_SECONDS = 3

# MQTT QoS level — mirrors what VoxWatch subscribes with.
MQTT_QOS = 1

# How long (seconds) to wait for the MQTT broker to confirm the publish.
MQTT_PUBLISH_TIMEOUT = 10

# HTTP request log format: method + path + status code.
HTTP_LOG_FORMAT = "{method} {path} — {status}"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SimConfig:
    """All resolved parameters for a single simulation run.

    Attributes:
        camera: Frigate camera name to impersonate (must match VoxWatch config).
        image_path: Absolute path to the JPEG image served as the snapshot.
        scenario: Human-readable scenario label for display purposes.
        mqtt_host: Hostname or IP of the MQTT broker.
        mqtt_port: TCP port of the MQTT broker.
        mqtt_user: MQTT username, or None for anonymous connections.
        mqtt_pass: MQTT password, or None.
        frigate_port: Port for the fake Frigate HTTP API server.
        score: Frigate detection confidence score (0.0–1.0).
        zone: Zone name reported in the event payload.
        keep_alive: Seconds to keep the fake server alive after publishing.
        still_present: If True the /api/events endpoint returns end_time=null.
        redirect: If True patch config.yaml before publishing and restore after.
        config_path: Absolute path to config.yaml (only used with --redirect).
    """

    camera: str
    image_path: str
    scenario: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: Optional[str]
    mqtt_pass: Optional[str]
    frigate_port: int
    score: float
    zone: str
    keep_alive: int
    still_present: bool
    redirect: bool
    config_path: Optional[str]


@dataclass
class RequestRecord:
    """Tracks a single HTTP request received by the fake Frigate server.

    Attributes:
        method: HTTP method (``"GET"``, etc.).
        path: Request path including query string.
        status: HTTP status code returned.
        timestamp: Monotonic timestamp at the moment the request was processed.
    """

    method: str
    path: str
    status: int
    timestamp: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Event ID generation
# ---------------------------------------------------------------------------


def generate_event_id() -> str:
    """Generate a realistic Frigate event ID.

    Frigate uses the format ``{unix_timestamp}.{microseconds}-{random_hex}``,
    for example ``1711324567.123456-abc1def2``.

    Returns:
        A new event ID string based on the current time.
    """
    ts = time.time()
    int_part = int(ts)
    # Six-digit microsecond suffix derived from the fractional seconds.
    micro_part = int((ts - int_part) * 1_000_000)
    # Eight random hex characters for uniqueness across rapid runs.
    rand_hex = "".join(random.choices("0123456789abcdef", k=8))
    return f"{int_part}.{micro_part:06d}-{rand_hex}"


# ---------------------------------------------------------------------------
# MQTT event payload builder
# ---------------------------------------------------------------------------


def build_frigate_event(
    event_id: str,
    camera: str,
    score: float,
    zone: str,
    frame_time: float,
) -> dict:
    """Build a Frigate MQTT event payload that is indistinguishable from a real one.

    Both the ``before`` and ``after`` keys are populated with identical data.
    VoxWatch reads all of its detection metadata from ``after`` (see
    ``_handle_detection`` in voxwatch_service.py).

    Args:
        event_id: Unique Frigate event identifier (see ``generate_event_id``).
        camera: Frigate camera name.
        score: Detection confidence score in the range 0.0–1.0.
        zone: Zone name where the person was detected.
        frame_time: Unix timestamp for the detection frame (current time).

    Returns:
        Dict with ``type``, ``before``, and ``after`` keys, serialisable to
        the JSON payload that Frigate publishes on ``frigate/events``.
    """
    detection_obj = {
        "id": event_id,
        "camera": camera,
        "frame_time": frame_time,
        "snapshot_time": frame_time,
        "label": "person",
        "sub_label": None,
        "top_score": score,
        "score": score,
        # Bounding box [x, y, width, height] — plausible centre-frame person.
        "box": [100, 150, 300, 480],
        "area": 54000,
        "ratio": 0.42,
        # Region covers the full standard 640x480 frame.
        "region": [0, 0, 640, 480],
        "stationary": False,
        "motionless_count": 0,
        "position_changes": 1,
        "current_zones": [zone],
        "entered_zones": [zone],
        "has_clip": False,
        "has_snapshot": True,
        "end_time": None,
    }
    return {
        "type": "new",
        "before": detection_obj,
        # ``after`` is a shallow copy — Frigate typically sends the same data
        # in both keys for ``type=new`` events.
        "after": dict(detection_obj),
    }


# ---------------------------------------------------------------------------
# Fake Frigate HTTP server
# ---------------------------------------------------------------------------


class FakeFrigateHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler that mimics the Frigate NVR REST API.

    VoxWatch makes three types of requests during its pipeline:
      - ``GET /api/events/{event_id}/snapshot.jpg`` — Stage 2/3 primary snapshot.
      - ``GET /api/{camera}/latest.jpg`` — Stage 2/3 polling snapshots.
      - ``GET /api/events?camera={cam}&label=person&limit=5`` — Stage 3 presence check.
      - ``GET /api/config`` — optional; some VoxWatch builds call this on start-up.

    All image requests return the same test JPEG regardless of path parameters.
    The events list endpoint returns a synthetic JSON array whose ``end_time``
    field is controlled by ``SimConfig.still_present``.

    Class-level attributes (set by ``FakeFrigateServer`` before binding):
        _image_bytes: Raw JPEG bytes to return for every image request.
        _sim_config: The active ``SimConfig`` (read-only inside handlers).
        _event_id: The event ID of the MQTT event that was/will be published.
        _request_log: List of ``RequestRecord`` objects appended by each request.
        _lock: Threading lock protecting ``_request_log`` writes.
    """

    # Populated by FakeFrigateServer before the server starts.
    _image_bytes: bytes = b""
    _sim_config: Optional["SimConfig"] = None
    _event_id: str = ""
    _request_log: list = []
    _lock: threading.Lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802 — matches BaseHTTPRequestHandler naming
        """Dispatch GET requests to the appropriate handler method."""
        path = self.path.split("?")[0]  # strip query string for routing
        query = self.path[len(path):]   # keep ?... for logging and inspection

        # Route: /api/events/{event_id}/snapshot.jpg
        if re.match(r"^/api/events/[^/]+/snapshot\.jpg$", path):
            self._serve_image(path + query)
            return

        # Route: /api/{camera_name}/latest.jpg
        if re.match(r"^/api/[^/]+/latest\.jpg$", path):
            self._serve_image(path + query)
            return

        # Route: /api/events?camera=...&label=person&...
        if path == "/api/events":
            self._serve_events_list(path + query)
            return

        # Route: /api/config — return a minimal Frigate config stub.
        if path == "/api/config":
            self._serve_config()
            return

        # Any other path — 404 with a clear diagnostic body.
        self._send_json(404, {"error": "not found", "path": self.path})
        self._record(self.command, self.path, 404)

    # ------------------------------------------------------------------
    # Internal response helpers
    # ------------------------------------------------------------------

    def _serve_image(self, log_path: str) -> None:
        """Send the test JPEG bytes as a ``image/jpeg`` response.

        Args:
            log_path: Full request path (including query string) for logging.
        """
        data = self.__class__._image_bytes
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self._record(self.command, log_path, 200)

    def _serve_events_list(self, log_path: str) -> None:
        """Return a JSON array with one synthetic person event.

        The ``end_time`` field is ``null`` when ``still_present=True`` (person
        is still on camera) or set to the current timestamp when ``False``
        (person has left).  VoxWatch's ``check_person_still_present`` checks
        both cases — it also accepts events that ended within the last 30 s.

        Args:
            log_path: Full request path for logging.
        """
        cfg = self.__class__._sim_config
        event_id = self.__class__._event_id
        now = time.time()

        # Determine end_time based on the --still-present flag.
        if cfg is not None and cfg.still_present:
            end_time = None   # Person is still on camera — active event.
        else:
            # Person left; set end_time to ~5 s ago so it falls within the
            # 30-second recency window VoxWatch uses.
            end_time = now - 5.0

        camera = cfg.camera if cfg else "frontdoor"
        score = cfg.score if cfg else 0.92
        zone = cfg.zone if cfg else "driveway"

        events = [
            {
                "id": event_id,
                "camera": camera,
                "label": "person",
                "sub_label": None,
                "top_score": score,
                "score": score,
                "frame_time": now - 2.0,
                "snapshot_time": now - 2.0,
                "start_time": now - 10.0,
                "end_time": end_time,
                "stationary": False,
                "motionless_count": 0,
                "position_changes": 3,
                "current_zones": [zone],
                "entered_zones": [zone],
                "has_clip": False,
                "has_snapshot": True,
                "box": [100, 150, 300, 480],
                "area": 54000,
                "ratio": 0.42,
                "region": [0, 0, 640, 480],
            }
        ]
        self._send_json(200, events)
        self._record(self.command, log_path, 200)

    def _serve_config(self) -> None:
        """Return a minimal Frigate config JSON so VoxWatch's config probe succeeds."""
        cfg = self.__class__._sim_config
        camera_name = cfg.camera if cfg else "frontdoor"
        config_payload = {
            "cameras": {
                camera_name: {
                    "enabled": True,
                    "ffmpeg": {"inputs": []},
                }
            },
            "version": "0.14.0-fake",
        }
        self._send_json(200, config_payload)
        self._record(self.command, self.path, 200)

    def _send_json(self, status: int, body) -> None:
        """Serialise ``body`` and send it as ``application/json``.

        Args:
            status: HTTP status code.
            body: Any JSON-serialisable Python object.
        """
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self, method: str, path: str, status: int) -> None:
        """Append a ``RequestRecord`` to the shared log and print a status line.

        Args:
            method: HTTP method string.
            path: Request path (may include query string).
            status: HTTP response status code returned.
        """
        record = RequestRecord(method=method, path=path, status=status)
        with self.__class__._lock:
            self.__class__._request_log.append(record)

        # Annotate common paths with a short human-readable note.
        note = ""
        if "/snapshot.jpg" in path:
            note = " (VoxWatch grabbed event snapshot)"
        elif "/latest.jpg" in path:
            note = " (VoxWatch grabbed latest frame)"
        elif "/api/events" in path and "?" in path:
            note = " (VoxWatch checked person presence)"
        elif "/api/config" in path:
            note = " (VoxWatch fetched Frigate config)"

        print(f"{_TAG_HTTP} {method} {path} — {status}{note}", flush=True)

    def log_message(self, format, *args) -> None:  # noqa: A002
        """Suppress the default BaseHTTPRequestHandler stderr logging.

        All request logging is handled by ``_record`` so the terminal output
        stays clean and tagged consistently with the rest of the test script.
        """


class FakeFrigateServer:
    """Manages the lifecycle of the fake Frigate HTTP API server.

    The server runs on a background daemon thread so the main thread can
    proceed to publish the MQTT event and then idle until ``--keep-alive``
    expires.

    Attributes:
        port: TCP port the server binds to.
        _server: The ``http.server.HTTPServer`` instance (set in ``start``).
        _thread: Background thread running ``serve_forever``.
        _request_log: Shared list of ``RequestRecord`` objects.
    """

    def __init__(
        self,
        port: int,
        sim_config: "SimConfig",
        event_id: str,
        image_bytes: bytes,
    ) -> None:
        """Prepare the fake server with all data it needs to serve requests.

        The handler class attributes are populated here before the server
        binds its socket so no request can arrive before the data is ready.

        Args:
            port: TCP port to listen on (bind to 0.0.0.0 for Docker reachability).
            sim_config: Fully resolved simulation configuration.
            event_id: The event ID that will be published via MQTT.
            image_bytes: Raw JPEG bytes for the test image.
        """
        self.port = port
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._request_log: list[RequestRecord] = []

        # Inject shared state into the handler class before binding.
        FakeFrigateHandler._image_bytes = image_bytes
        FakeFrigateHandler._sim_config = sim_config
        FakeFrigateHandler._event_id = event_id
        FakeFrigateHandler._request_log = self._request_log
        FakeFrigateHandler._lock = threading.Lock()

    def start(self) -> None:
        """Bind the socket and start the background serving thread.

        Raises:
            OSError: If the port is already in use.
        """
        self._server = http.server.HTTPServer(("0.0.0.0", self.port), FakeFrigateHandler)
        # Allow rapid re-runs without waiting for TIME_WAIT to expire.
        self._server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="fake-frigate-http",
            daemon=True,
        )
        self._thread.start()
        print(f"{_TAG_OK} Fake Frigate API server started on port {self.port}", flush=True)

    def stop(self) -> None:
        """Shut down the HTTP server and join the serving thread."""
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)

    def request_count(self) -> int:
        """Return total number of requests received since the server started.

        Returns:
            Integer count of all logged requests.
        """
        return len(self._request_log)


# ---------------------------------------------------------------------------
# Config redirect (--redirect flag)
# ---------------------------------------------------------------------------


def patch_config_yaml(
    config_path: str,
    local_ip: str,
    frigate_port: int,
) -> Optional[str]:
    """Temporarily overwrite the ``frigate.host`` and ``frigate.port`` values.

    Uses simple regex substitution rather than a full YAML parse/dump cycle to
    avoid rewriting comments, block styles, or ordering.  A full backup of the
    original file is taken first so ``restore_config_yaml`` can put it back.

    Args:
        config_path: Absolute path to config.yaml.
        local_ip: IP address VoxWatch should contact for fake Frigate API calls.
        frigate_port: Port the fake Frigate server is listening on.

    Returns:
        The original file contents as a string (for use with
        ``restore_config_yaml``), or None if the file could not be read.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            original = fh.read()
    except OSError as exc:
        print(f"{_TAG_WARN} Could not read config.yaml for --redirect: {exc}")
        return None

    # Patch frigate.host — match quoted or unquoted values.
    patched = re.sub(
        r'(^\s*host:\s*)["\']?[^"\'#\n]+["\']?',
        rf'\g<1>"{local_ip}"',
        original,
        flags=re.MULTILINE,
        count=1,  # only replace the first occurrence (under [frigate])
    )

    # Patch frigate.port — match the line that immediately follows the host line.
    patched = re.sub(
        r'(^\s*port:\s*)\d+',
        rf'\g<1>{frigate_port}',
        patched,
        flags=re.MULTILINE,
        count=1,
    )

    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(patched)
        print(
            f"{_TAG_OK} config.yaml patched: frigate.host={local_ip}, "
            f"frigate.port={frigate_port}",
            flush=True,
        )
        return original
    except OSError as exc:
        print(f"{_TAG_WARN} Could not write patched config.yaml: {exc}")
        return None


def restore_config_yaml(config_path: str, original_content: str) -> None:
    """Restore config.yaml to its pre-patch contents.

    Args:
        config_path: Absolute path to config.yaml.
        original_content: The original file text returned by ``patch_config_yaml``.
    """
    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(original_content)
        print(f"{_TAG_OK} config.yaml restored to original.", flush=True)
    except OSError as exc:
        print(f"{_TAG_WARN} Could not restore config.yaml: {exc}", flush=True)
        print(f"{_TAG_INFO} Manually restore frigate.host and frigate.port.", flush=True)


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def get_local_ip() -> str:
    """Detect the machine's primary LAN IP address via a UDP probe.

    Opens a UDP socket towards 8.8.8.8 (no packet is actually sent) and reads
    the local address the OS selected for that route.

    Returns:
        LAN IP address string, e.g. ``"10.1.10.5"``.  Falls back to
        ``"127.0.0.1"`` on any error (Docker containers can't reach loopback,
        so the caller should warn the user).
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def check_port_available(port: int) -> bool:
    """Return True if ``port`` is not already bound on localhost.

    Args:
        port: TCP port number to probe.

    Returns:
        True if the port is free, False if it is already in use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# MQTT publisher
# ---------------------------------------------------------------------------


def publish_event(sim_config: "SimConfig", event_id: str, payload: dict) -> bool:
    """Connect to the MQTT broker and publish the Frigate event payload.

    Uses a synchronous paho-mqtt client with a blocking ``loop_start`` /
    ``loop_stop`` pattern so this function can be called from plain ``main``
    without an asyncio event loop.

    Args:
        sim_config: Simulation configuration (provides broker host/port/auth).
        event_id: Event ID for confirmation logging.
        payload: The Frigate event dict to serialise and publish.

    Returns:
        True if the message was published successfully, False on any error.
    """
    publish_ok = threading.Event()
    connect_ok = threading.Event()
    connect_failed = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        """Handle broker connection result.

        Args:
            client: The paho MQTT client instance.
            userdata: Unused user data.
            flags: Connection flags dict from the broker.
            reason_code: paho ReasonCode (0 = success).
            properties: MQTTv5 properties (unused here).
        """
        # paho v2 passes a ReasonCode object; compare to 0 for success.
        rc = reason_code.value if hasattr(reason_code, "value") else reason_code
        if rc == 0:
            connect_ok.set()
        else:
            print(f"{_TAG_FAIL} MQTT connect refused — reason code {rc}", flush=True)
            connect_failed.set()

    def on_publish(client, userdata, mid, reason_code=None, properties=None):
        """Signal successful publish acknowledgement.

        Args:
            client: The paho MQTT client instance.
            userdata: Unused user data.
            mid: Message ID returned by ``publish()``.
            reason_code: paho v2 ReasonCode (None for QoS 0).
            properties: MQTTv5 properties (unused here).
        """
        publish_ok.set()

    # Build a client ID that is unique per run to avoid collisions on the broker.
    client_id = f"voxwatch-sim-{int(time.time())}"

    try:
        # paho v2.0+ uses CallbackAPIVersion to select the new-style callbacks.
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
        )
    except AttributeError:
        # paho v1.x fallback — older signature without CallbackAPIVersion.
        client = mqtt.Client(client_id=client_id, clean_session=True)  # type: ignore[call-arg]

    if sim_config.mqtt_user:
        client.username_pw_set(sim_config.mqtt_user, sim_config.mqtt_pass)

    client.on_connect = on_connect
    client.on_publish = on_publish

    try:
        client.connect(sim_config.mqtt_host, sim_config.mqtt_port, keepalive=30)
    except OSError as exc:
        print(
            f"{_TAG_FAIL} Cannot connect to MQTT broker at "
            f"{sim_config.mqtt_host}:{sim_config.mqtt_port} — {exc}",
            flush=True,
        )
        return False

    client.loop_start()

    # Wait up to MQTT_PUBLISH_TIMEOUT seconds for the broker to accept us.
    if not connect_ok.wait(timeout=MQTT_PUBLISH_TIMEOUT):
        print(
            f"{_TAG_FAIL} Timed out waiting for MQTT broker at "
            f"{sim_config.mqtt_host}:{sim_config.mqtt_port}",
            flush=True,
        )
        client.loop_stop()
        return False

    print(
        f"{_TAG_OK} Connected to MQTT broker at "
        f"{sim_config.mqtt_host}:{sim_config.mqtt_port}",
        flush=True,
    )

    topic = "frigate/events"
    json_payload = json.dumps(payload)

    result = client.publish(topic, json_payload, qos=MQTT_QOS)

    if not publish_ok.wait(timeout=MQTT_PUBLISH_TIMEOUT):
        print(
            f"{_TAG_FAIL} MQTT publish timed out after {MQTT_PUBLISH_TIMEOUT}s",
            flush=True,
        )
        client.loop_stop()
        client.disconnect()
        return False

    print(
        f"{_TAG_MQTT} Published {topic} — event_id: {event_id}",
        flush=True,
    )

    client.loop_stop()
    client.disconnect()
    return True


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def resolve_image_path(args: argparse.Namespace) -> tuple[str, str]:
    """Determine the image path and scenario label from CLI arguments.

    Priority order:
      1. ``--scenario`` maps to a known image filename.
      2. ``--image`` is used as-is (relative paths resolved from CWD).
      3. A random image from ``tests/test_images/`` is chosen as fallback.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Tuple of ``(absolute_image_path, scenario_label)``.

    Raises:
        SystemExit: If the resolved path does not point to a readable file.
    """
    # Scenario flag takes highest precedence.
    if args.scenario:
        filename = SCENARIO_IMAGE_MAP.get(args.scenario)
        if not filename:
            valid = ", ".join(SCENARIO_IMAGE_MAP.keys())
            print(
                f"{_TAG_FAIL} Unknown scenario '{args.scenario}'. "
                f"Valid options: {valid}",
                flush=True,
            )
            sys.exit(1)
        image_path = os.path.join(TEST_IMAGES_DIR, filename)
        scenario_label = args.scenario
    elif args.image:
        image_path = os.path.abspath(args.image)
        # Derive a human-readable label from the filename without extension.
        scenario_label = os.path.splitext(os.path.basename(image_path))[0]
    else:
        # Pick a random image from the test_images directory.
        jpegs = [
            f for f in os.listdir(TEST_IMAGES_DIR) if f.lower().endswith(".jpg")
        ]
        if not jpegs:
            print(
                f"{_TAG_FAIL} No JPEG files found in {TEST_IMAGES_DIR}. "
                "Provide --image or --scenario.",
                flush=True,
            )
            sys.exit(1)
        chosen = random.choice(jpegs)
        image_path = os.path.join(TEST_IMAGES_DIR, chosen)
        scenario_label = f"random ({os.path.splitext(chosen)[0]})"

    if not os.path.isfile(image_path):
        print(
            f"{_TAG_FAIL} Image not found: {image_path}",
            flush=True,
        )
        sys.exit(1)

    return image_path, scenario_label


def parse_args() -> argparse.Namespace:
    """Parse all CLI arguments for the simulation test.

    Returns:
        Populated ``argparse.Namespace`` with all simulation parameters.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Simulate a Frigate person detection event to test VoxWatch "
            "without a real camera or a person walking by."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Scenarios:\n"
            "  car_thief_night   — night_car_door.jpg  (IR, person at car door)\n"
            "  prowler_night     — night_ir_prowler.jpg (IR, dark clothing near car)\n"
            "  gate_tester_day   — day_gate_hoodie.jpg (color, hoodie + backpack)\n"
            "  porch_pirate_day  — day_porch_pirate.jpg (color, person at package)\n"
            "\n"
            "Examples:\n"
            "  python tests/test_mqtt_simulation.py --mqtt-host 10.1.10.24\n"
            "  python tests/test_mqtt_simulation.py --scenario prowler_night "
            "--mqtt-host 10.1.10.24 --score 0.97\n"
        ),
    )

    # -- Image selection -------------------------------------------------------
    img_group = parser.add_mutually_exclusive_group()
    img_group.add_argument(
        "--scenario",
        metavar="NAME",
        help=(
            "Preset scenario name. One of: "
            + ", ".join(SCENARIO_IMAGE_MAP.keys())
            + ". Mutually exclusive with --image."
        ),
    )
    img_group.add_argument(
        "--image",
        metavar="PATH",
        help=(
            "Path to a JPEG image to serve as the Frigate snapshot. "
            "Mutually exclusive with --scenario. "
            f"(default: random from {TEST_IMAGES_DIR}/)"
        ),
    )

    # -- Camera ---------------------------------------------------------------
    parser.add_argument(
        "--camera",
        default="frontdoor",
        metavar="NAME",
        help=(
            "Frigate camera name to impersonate. Must match a camera defined "
            "in VoxWatch's config.yaml. (default: frontdoor)"
        ),
    )

    # -- MQTT -----------------------------------------------------------------
    parser.add_argument(
        "--mqtt-host",
        default="localhost",
        metavar="HOST",
        help="MQTT broker hostname or IP address. (default: localhost)",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=1883,
        metavar="PORT",
        help="MQTT broker TCP port. (default: 1883)",
    )
    parser.add_argument(
        "--mqtt-user",
        default=None,
        metavar="USER",
        help="MQTT username for brokers that require authentication. (optional)",
    )
    parser.add_argument(
        "--mqtt-pass",
        default=None,
        metavar="PASS",
        help="MQTT password. (optional)",
    )

    # -- Fake Frigate server --------------------------------------------------
    parser.add_argument(
        "--frigate-port",
        type=int,
        default=5123,
        metavar="PORT",
        help=(
            "Port for the fake Frigate HTTP API server. "
            "Must not conflict with the real Frigate (default 5000). "
            "(default: 5123)"
        ),
    )

    # -- Detection parameters -------------------------------------------------
    parser.add_argument(
        "--score",
        type=float,
        default=0.92,
        metavar="SCORE",
        help="Detection confidence score published in the MQTT event. (default: 0.92)",
    )
    parser.add_argument(
        "--zone",
        default="driveway",
        metavar="ZONE",
        help="Detection zone name published in the MQTT event. (default: driveway)",
    )

    # -- Timing ---------------------------------------------------------------
    parser.add_argument(
        "--keep-alive",
        type=int,
        default=120,
        metavar="SECONDS",
        help=(
            "Seconds to keep the fake Frigate server alive after publishing. "
            "VoxWatch needs to fetch snapshots during this window. (default: 120)"
        ),
    )

    # -- Presence simulation --------------------------------------------------
    parser.add_argument(
        "--no-still-present",
        dest="still_present",
        action="store_false",
        help=(
            "Make /api/events return end_time set to ~5s ago instead of null. "
            "VoxWatch will see the person as recently left rather than still there. "
            "(default: person is still present)"
        ),
    )
    parser.set_defaults(still_present=True)

    # -- Config redirect ------------------------------------------------------
    parser.add_argument(
        "--redirect",
        action="store_true",
        help=(
            "Patch frigate.host and frigate.port in config.yaml before publishing "
            "and restore the original values on exit. "
            "Requires --config to point at config.yaml."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "Absolute path to VoxWatch's config.yaml. "
            "Only used when --redirect is set. "
            "(default: /config/config.yaml)"
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Orchestrate the full MQTT simulation test run.

    Execution order:
      1. Parse CLI args and resolve image path / scenario label.
      2. Validate inputs (image readable, port free, score in range).
      3. Generate a realistic Frigate event ID.
      4. Build the MQTT event payload.
      5. Optionally patch config.yaml (``--redirect``).
      6. Start the fake Frigate HTTP API server.
      7. Print setup instructions for manual config.yaml editing if needed.
      8. Connect to MQTT broker and confirm connection.
      9. Countdown then publish the MQTT event.
     10. Idle for ``--keep-alive`` seconds, then stop the fake server.
     11. Restore config.yaml if it was patched.
    """
    args = parse_args()
    image_path, scenario_label = resolve_image_path(args)

    # ── Input validation ────────────────────────────────────────────────────

    if not (0.0 <= args.score <= 1.0):
        print(f"{_TAG_FAIL} --score must be between 0.0 and 1.0 (got {args.score})")
        sys.exit(1)

    if args.frigate_port == 5000:
        print(
            f"{_TAG_WARN} --frigate-port 5000 may conflict with a real Frigate instance. "
            "Use a different port (e.g. 5123).",
            flush=True,
        )

    if not check_port_available(args.frigate_port):
        print(
            f"{_TAG_FAIL} Port {args.frigate_port} is already in use. "
            "Choose a different --frigate-port.",
            flush=True,
        )
        sys.exit(1)

    # Load the JPEG into memory now so the server can start without disk I/O
    # per request.  This also validates the file is readable before we start.
    try:
        with open(image_path, "rb") as fh:
            image_bytes = fh.read()
    except OSError as exc:
        print(f"{_TAG_FAIL} Cannot read image: {exc}", flush=True)
        sys.exit(1)

    image_size_kb = len(image_bytes) // 1024

    # ── Resolve the machine's LAN IP for Docker reachability hints ──────────

    local_ip = get_local_ip()
    if local_ip == "127.0.0.1":
        print(
            f"{_TAG_WARN} Could not auto-detect LAN IP. "
            "VoxWatch in Docker cannot reach 127.0.0.1 — "
            "set frigate.host manually to this machine's IP.",
            flush=True,
        )

    # ── Build SimConfig ─────────────────────────────────────────────────────

    config_path = args.config or "/config/config.yaml"
    sim_config = SimConfig(
        camera=args.camera,
        image_path=image_path,
        scenario=scenario_label,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_user=args.mqtt_user,
        mqtt_pass=args.mqtt_pass,
        frigate_port=args.frigate_port,
        score=args.score,
        zone=args.zone,
        keep_alive=args.keep_alive,
        still_present=args.still_present,
        redirect=args.redirect,
        config_path=config_path,
    )

    # ── Generate event ID and payload ───────────────────────────────────────

    event_id = generate_event_id()
    frame_time = time.time()
    payload = build_frigate_event(
        event_id=event_id,
        camera=sim_config.camera,
        score=sim_config.score,
        zone=sim_config.zone,
        frame_time=frame_time,
    )

    # ── Print header ────────────────────────────────────────────────────────

    print()
    print("=== VoxWatch MQTT Simulation Test ===")
    print()
    print(f"Scenario: {scenario_label}")
    print(f"Camera:   {sim_config.camera}")
    print(f"Image:    {image_path} ({image_size_kb}KB)")
    print(f"MQTT:     {sim_config.mqtt_host}:{sim_config.mqtt_port}")
    print(f"Fake Frigate: 0.0.0.0:{sim_config.frigate_port}")
    print(f"Score:    {sim_config.score:.2f}")
    print(f"Zone:     {sim_config.zone}")
    print(f"Person still present: {sim_config.still_present}")
    print()

    # ── Optional config.yaml redirect ──────────────────────────────────────

    original_config: Optional[str] = None

    if sim_config.redirect:
        if not os.path.isfile(config_path):
            print(
                f"{_TAG_FAIL} --redirect specified but config.yaml not found at: "
                f"{config_path}",
                flush=True,
            )
            print(
                f"{_TAG_INFO} Use --config /path/to/config.yaml to specify the path.",
                flush=True,
            )
            sys.exit(1)
        original_config = patch_config_yaml(config_path, local_ip, sim_config.frigate_port)
        if original_config is None:
            print(
                f"{_TAG_FAIL} Failed to patch config.yaml. "
                "Check file permissions or use manual setup.",
                flush=True,
            )
            sys.exit(1)
        print()

    # ── Register cleanup handler for SIGINT / SIGTERM ──────────────────────

    # Track the fake server and original config so the signal handler can clean up.
    _cleanup_state: dict = {
        "server": None,
        "original_config": original_config,
        "config_path": config_path,
        "redirect": sim_config.redirect,
    }

    def _cleanup(signum=None, frame=None):
        """Handle Ctrl+C and SIGTERM by stopping the server and restoring config.

        Args:
            signum: Signal number (provided by signal.signal, ignored here).
            frame: Current stack frame (provided by signal.signal, ignored here).
        """
        print("\nStopping fake Frigate server...", flush=True)
        server: Optional[FakeFrigateServer] = _cleanup_state.get("server")
        if server:
            server.stop()

        if _cleanup_state["redirect"] and _cleanup_state["original_config"]:
            restore_config_yaml(
                _cleanup_state["config_path"],
                _cleanup_state["original_config"],
            )

        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # ── Start the fake Frigate HTTP server ──────────────────────────────────

    server = FakeFrigateServer(
        port=sim_config.frigate_port,
        sim_config=sim_config,
        event_id=event_id,
        image_bytes=image_bytes,
    )

    try:
        server.start()
    except OSError as exc:
        print(f"{_TAG_FAIL} Could not start fake Frigate server: {exc}", flush=True)
        sys.exit(1)

    _cleanup_state["server"] = server

    # ── Print manual config instructions (if not using --redirect) ──────────

    if not sim_config.redirect:
        print()
        print("-" * 60)
        print("MANUAL SETUP REQUIRED (or use --redirect to automate):")
        print(f"  Point frigate.host in config.yaml to: {local_ip}")
        print(f"  Point frigate.port in config.yaml to: {sim_config.frigate_port}")
        print()
        print("  Example config.yaml snippet:")
        print("    frigate:")
        print(f'      host: "{local_ip}"')
        print(f"      port: {sim_config.frigate_port}")
        print("-" * 60)
        print()

    # ── Connect to MQTT and publish ─────────────────────────────────────────

    # Countdown before publishing — gives the operator a moment to confirm setup.
    print(f"Publishing detection event in {PUBLISH_COUNTDOWN_SECONDS}...", end="", flush=True)
    for i in range(PUBLISH_COUNTDOWN_SECONDS - 1, 0, -1):
        time.sleep(1)
        print(f" {i}...", end="", flush=True)
    time.sleep(1)
    print(" publishing!", flush=True)
    print()

    success = publish_event(sim_config, event_id, payload)
    if not success:
        print(f"{_TAG_FAIL} MQTT publish failed — check broker connectivity.", flush=True)
        server.stop()
        if sim_config.redirect and original_config:
            restore_config_yaml(config_path, original_config)
        sys.exit(1)

    # ── Keep the server alive so VoxWatch can fetch snapshots ───────────────

    print()
    print(f"Waiting for pipeline to complete (keep-alive: {sim_config.keep_alive}s)...")
    print("Press Ctrl+C to stop.")
    print()

    deadline = time.monotonic() + sim_config.keep_alive
    last_count = 0

    while time.monotonic() < deadline:
        time.sleep(1)
        current_count = server.request_count()
        if current_count != last_count:
            # New requests arrived — print a visual separator so the timeline
            # is easy to follow in the terminal output.
            last_count = current_count

    remaining = max(0.0, deadline - time.monotonic())
    if remaining == 0:
        print(
            f"\n{_TAG_INFO} Keep-alive period expired ({sim_config.keep_alive}s). "
            f"Total requests received by fake server: {server.request_count()}",
            flush=True,
        )

    # ── Cleanup ─────────────────────────────────────────────────────────────

    server.stop()

    if sim_config.redirect and original_config:
        restore_config_yaml(config_path, original_config)

    print()
    print("=== Simulation complete ===")
    print(
        f"Event ID: {event_id}\n"
        f"HTTP requests served: {server.request_count()}"
    )


if __name__ == "__main__":
    main()
