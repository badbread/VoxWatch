"""
setup.py — First-Run Setup API Router

Endpoints:
    GET  /api/setup/status          — Check whether config.yaml exists and which
                                      sections are populated (no auth required).
    POST /api/setup/probe           — Probe Frigate, go2rtc, and MQTT at the
                                      addresses provided by the user; returns all
                                      discovered cameras, streams, and backchannel
                                      info needed to populate the wizard form.
    POST /api/setup/generate-config — Write a new config.yaml from the validated
                                      wizard form data.  Atomic write; refuses if
                                      config already exists.

All three endpoints are intentionally unauthenticated because, by definition,
no DASHBOARD_API_KEY has been configured yet during first-run.  Once config.yaml
exists the user should configure a key and the setup endpoints become read-only
(probe and generate-config refuse with 409 Conflict when config already exists).

Probe concurrency:
    /probe runs Frigate, go2rtc, and MQTT probes concurrently via asyncio.gather
    so the combined probe latency is bounded by the slowest individual probe
    rather than their sum.

Config generation:
    /generate-config builds a minimal but complete config.yaml from the wizard
    form values and writes it atomically using tempfile + os.replace.  The
    VoxWatch service polling loop in voxwatch_service.py will detect the new
    file within 5 seconds and start up automatically.
"""

import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend import config as dashboard_cfg

logger = logging.getLogger("dashboard.router.setup")

router = APIRouter(prefix="/setup", tags=["Setup"])

# ── Input validation ──────────────────────────────────────────────────────────
# Frigate hostnames are placed into aiohttp URLs.  Restrict to safe hostname
# characters to prevent SSRF via crafted host strings like "localhost/evil#".

_HOST_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

# Ports to probe on Frigate in order.  Frigate uses 5000 by default but some
# deployments expose it on 5001 (HA add-on) or 8971 (reverse-proxied).
_FRIGATE_PROBE_PORTS = [5000, 5001, 8971]

# Timeout for each individual probe connection (seconds)
_PROBE_TIMEOUT_SECONDS = 5.0

# MQTT connection timeout for synchronous paho probe (seconds)
_MQTT_PROBE_TIMEOUT_SECONDS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_host(host: str, field_name: str = "host") -> None:
    """Raise HTTP 400 if *host* contains characters outside the safe hostname set.

    Security rationale: the host is interpolated directly into aiohttp request
    URLs.  An unvalidated host like 'evil.com/inject?x=' would allow SSRF by
    injecting extra path components into the URL sent to internal services.
    Restricting to ^[a-zA-Z0-9._-]+$ eliminates slashes, colons, and all other
    characters that could modify the URL structure.

    Args:
        host:       Hostname or IP string submitted by the caller.
        field_name: Field name to include in the error message.

    Raises:
        HTTPException 400: If the host contains any disallowed characters or is
                           empty.
    """
    if not host or not _HOST_RE.match(host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid {field_name} {host!r}. "
                "Host must contain only letters, digits, dots, hyphens, and "
                "underscores (pattern: ^[a-zA-Z0-9._-]+$). "
                "Do not include http://, port numbers, or path components here."
            ),
        )


def _config_exists() -> bool:
    """Return True if config.yaml already exists at the configured path."""
    return Path(dashboard_cfg.VOXWATCH_CONFIG_PATH).exists()


# ── Pydantic models ───────────────────────────────────────────────────────────


class SetupStatus(BaseModel):
    """Response model for GET /api/setup/status.

    Attributes:
        config_exists:       True when config.yaml is present on disk.
        setup_complete:      True when config.yaml exists and all mandatory
                             sections (frigate, go2rtc, cameras) are present.
        frigate_configured:  True when the frigate section is present and host
                             is non-empty.
        mqtt_configured:     True when mqtt_host is set in the frigate section.
        ai_configured:       True when ai.primary.api_key is set (non-empty,
                             non-placeholder).
        cameras_configured:  True when at least one camera entry is defined.
        frigate_host_env:    Value of the FRIGATE_HOST environment variable, if
                             set.  Pre-fills the wizard host field.
    """

    config_exists: bool = Field(
        description="True when config.yaml is present on disk."
    )
    setup_complete: bool = Field(
        description="True when config.yaml exists and all mandatory sections are populated."
    )
    frigate_configured: bool = Field(
        description="True when the frigate section is present with a non-empty host."
    )
    mqtt_configured: bool = Field(
        description="True when mqtt_host is set in the frigate section."
    )
    ai_configured: bool = Field(
        description="True when ai.primary.api_key is set and not an unresolved ${TOKEN}."
    )
    cameras_configured: bool = Field(
        description="True when at least one camera entry is defined."
    )
    frigate_host_env: Optional[str] = Field(
        default=None,
        description="Value of the FRIGATE_HOST env var for wizard pre-fill, or null.",
    )


class ProbeRequest(BaseModel):
    """Request body for POST /api/setup/probe.

    Attributes:
        frigate_host:    Hostname or IP of the Frigate NVR (required).
        frigate_port:    Frigate API port — tried first.  Additional ports
                         5001 and 8971 are also tried automatically.
        go2rtc_host:     go2rtc hostname.  Defaults to frigate_host when null.
        go2rtc_port:     go2rtc API port.
        mqtt_host:       MQTT broker hostname.  Defaults to frigate_host when null.
        mqtt_port:       MQTT broker port.
        mqtt_user:       MQTT username (optional).
        mqtt_password:   MQTT password (optional).
    """

    frigate_host: str = Field(
        description=(
            "Hostname or IP of the Frigate NVR. "
            "Letters, digits, dots, hyphens, and underscores only — no http://"
        )
    )
    frigate_port: int = Field(
        default=5000,
        description="Frigate API port to try first (default 5000). Also probes 5001 and 8971.",
    )
    go2rtc_host: Optional[str] = Field(
        default=None,
        description="go2rtc hostname.  Defaults to frigate_host when null.",
    )
    go2rtc_port: int = Field(
        default=1984,
        description="go2rtc API port (default 1984).",
    )
    mqtt_host: Optional[str] = Field(
        default=None,
        description="MQTT broker hostname.  Defaults to frigate_host when null.",
    )
    mqtt_port: int = Field(
        default=1883,
        description="MQTT broker port (default 1883).",
    )
    mqtt_user: str = Field(
        default="",
        description="MQTT username (leave blank if no auth).",
    )
    mqtt_password: str = Field(
        default="",
        description="MQTT password (leave blank if no auth).",
    )


class ProbeResult(BaseModel):
    """Response model for POST /api/setup/probe.

    Attributes:
        frigate_reachable:  True when any Frigate port responded successfully.
        frigate_version:    Frigate version string, or null if unreachable.
        frigate_cameras:    Camera names found in the Frigate config, or empty.
        go2rtc_reachable:   True when go2rtc responded successfully.
        go2rtc_version:     go2rtc version string, or null if unreachable.
        go2rtc_streams:     Stream names returned by go2rtc /api/streams.
        backchannel_info:   Per-stream backchannel capability dict keyed by
                            stream name.  Each value has has_backchannel (bool)
                            and codecs (list of RTSP codec strings).
        mqtt_reachable:     True when the MQTT broker accepted a connection.
        mqtt_host_detected: MQTT host extracted from Frigate's /api/config,
                            or null when Frigate is unreachable or MQTT is not
                            configured in Frigate.
        mqtt_port_detected: MQTT port extracted from Frigate's /api/config,
                            or null when not available.
        errors:             List of non-fatal error messages from individual
                            probe steps that did not prevent other probes.
        probe_duration_ms:  Total wall-clock time for all probes in milliseconds.
    """

    frigate_reachable: bool = Field(
        description="True when Frigate responded on any probed port."
    )
    frigate_version: Optional[str] = Field(
        default=None,
        description="Frigate version string (e.g. '0.14.1'), or null.",
    )
    frigate_cameras: List[str] = Field(
        default_factory=list,
        description="Camera names returned by the Frigate /api/config endpoint.",
    )
    go2rtc_reachable: bool = Field(
        description="True when go2rtc /api responded with HTTP 200."
    )
    go2rtc_version: Optional[str] = Field(
        default=None,
        description="go2rtc version string (e.g. '1.9.10'), or null.",
    )
    go2rtc_streams: List[str] = Field(
        default_factory=list,
        description="Stream names returned by go2rtc /api/streams.",
    )
    backchannel_info: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-stream backchannel capabilities.  "
            "Keys are stream names; values are {has_backchannel, codecs}."
        ),
    )
    mqtt_reachable: bool = Field(
        description="True when the MQTT broker accepted a TCP connection."
    )
    mqtt_host_detected: Optional[str] = Field(
        default=None,
        description=(
            "MQTT host extracted from Frigate's /api/config mqtt.host field. "
            "Null when Frigate is unreachable or mqtt.host is not set."
        ),
    )
    mqtt_port_detected: Optional[int] = Field(
        default=None,
        description=(
            "MQTT port extracted from Frigate's /api/config mqtt.port field. "
            "Null when Frigate is unreachable or mqtt.port is not set."
        ),
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Non-fatal error messages from individual probe steps.",
    )
    probe_duration_ms: int = Field(
        description="Total wall-clock duration of all concurrent probes in milliseconds."
    )


class CameraSetupEntry(BaseModel):
    """Per-camera configuration submitted via the setup wizard.

    Attributes:
        enabled:         Whether this camera is active in VoxWatch.
        go2rtc_stream:   The go2rtc stream name to use for audio push.
        audio_codec:     ffmpeg codec name for audio (e.g. 'pcm_mulaw').
        scene_context:   Optional free-text description of the camera scene
                         used to tune AI prompts (e.g. 'front driveway').
    """

    enabled: bool = Field(
        default=True,
        description="Whether this camera is active in VoxWatch.",
    )
    go2rtc_stream: str = Field(
        description="go2rtc stream name used for audio push to this camera.",
    )
    audio_codec: str = Field(
        default="pcm_mulaw",
        description="ffmpeg codec name for audio output (e.g. 'pcm_mulaw', 'pcm_alaw').",
    )
    scene_context: str = Field(
        default="",
        description="Free-text scene description for AI prompt tuning (optional).",
    )


class GenerateConfigRequest(BaseModel):
    """Request body for POST /api/setup/generate-config.

    All settings required to produce a functional first-run config.yaml.

    Frigate / MQTT:
        frigate_host:    Hostname of the Frigate NVR.
        frigate_port:    Frigate API port (default 5000).
        mqtt_host:       MQTT broker hostname (defaults to frigate_host).
        mqtt_port:       MQTT broker port (default 1883).
        mqtt_user:       MQTT username (optional).
        mqtt_password:   MQTT password (optional).

    go2rtc:
        go2rtc_host:     go2rtc hostname (defaults to frigate_host).
        go2rtc_port:     go2rtc API port (default 1984).

    AI:
        ai_provider:     Primary AI provider (e.g. 'gemini', 'openai').
        ai_model:        Model name (e.g. 'gemini-2.5-flash').
        ai_api_key:      API key for the primary provider.

    TTS:
        tts_engine:      TTS engine name (e.g. 'piper', 'kokoro', 'openai').
        tts_voice:       Voice identifier (engine-specific; optional).
        tts_api_key:     API key for cloud TTS engines (optional).
        tts_host:        Host URL for self-hosted TTS engines like kokoro (optional).

    Pipeline:
        response_mode:   Deterrent response mode (e.g. 'private_security').

    Cameras:
        cameras:         Dict mapping camera name -> CameraSetupEntry.
    """

    # ── Frigate / MQTT ────────────────────────────────────────────────────────
    frigate_host: str = Field(
        description="Hostname or IP of the Frigate NVR (no http://)."
    )
    frigate_port: int = Field(
        default=5000,
        description="Frigate API port (default 5000).",
    )
    mqtt_host: Optional[str] = Field(
        default=None,
        description="MQTT broker hostname.  Defaults to frigate_host when null.",
    )
    mqtt_port: int = Field(
        default=1883,
        description="MQTT broker port (default 1883).",
    )
    mqtt_user: str = Field(
        default="",
        description="MQTT username (leave blank if none).",
    )
    mqtt_password: str = Field(
        default="",
        description="MQTT password (leave blank if none).",
    )

    # ── go2rtc ────────────────────────────────────────────────────────────────
    go2rtc_host: Optional[str] = Field(
        default=None,
        description="go2rtc hostname.  Defaults to frigate_host when null.",
    )
    go2rtc_port: int = Field(
        default=1984,
        description="go2rtc API port (default 1984).",
    )

    # ── AI provider ───────────────────────────────────────────────────────────
    ai_provider: str = Field(
        default="gemini",
        description="Primary AI vision provider (gemini, openai, ollama, etc.).",
    )
    ai_model: str = Field(
        default="gemini-2.5-flash",
        description="Model name for the primary AI provider.",
    )
    ai_api_key: str = Field(
        default="",
        description="API key for the primary AI provider (leave blank for ollama).",
    )

    # ── TTS ───────────────────────────────────────────────────────────────────
    tts_engine: str = Field(
        default="piper",
        description="TTS engine name (piper, kokoro, espeak, openai, elevenlabs, etc.).",
    )
    tts_voice: str = Field(
        default="",
        description="Voice identifier.  Meaning depends on the engine (optional).",
    )
    tts_api_key: str = Field(
        default="",
        description="API key for cloud TTS engines (leave blank for local engines).",
    )
    tts_host: str = Field(
        default="",
        description="Host URL for self-hosted TTS engines like kokoro (optional).",
    )

    # ── Pipeline ──────────────────────────────────────────────────────────────
    response_mode: str = Field(
        default="private_security",
        description=(
            "Deterrent response mode.  Valid values: private_security, "
            "police_dispatch, security_firm, custom."
        ),
    )

    # ── Cameras ───────────────────────────────────────────────────────────────
    cameras: Dict[str, CameraSetupEntry] = Field(
        default_factory=dict,
        description="Camera definitions keyed by camera name.",
    )


# ── Probe helpers ─────────────────────────────────────────────────────────────

async def _probe_frigate(
    session: aiohttp.ClientSession,
    host: str,
    ports: List[int],
    errors: List[str],
) -> tuple[bool, Optional[str], List[str], Optional[str], Optional[int]]:
    """Try each port in *ports* and return (reachable, version, cameras, mqtt_host, mqtt_port).

    Iterates through the port list and returns on the first successful
    connection.  Non-fatal errors are appended to *errors*.

    Also reads Frigate's /api/config to extract the mqtt.host and mqtt.port
    fields so the wizard can pre-fill MQTT settings using Frigate's own
    configuration rather than assuming co-location.

    Args:
        session: Shared aiohttp session (caller owns lifecycle).
        host:    Frigate hostname or IP.
        ports:   Port numbers to attempt, in order.
        errors:  Mutable list to append non-fatal error strings to.

    Returns:
        5-tuple of (reachable, version_string_or_None, camera_name_list,
                    mqtt_host_or_None, mqtt_port_or_None).
    """
    timeout = aiohttp.ClientTimeout(total=_PROBE_TIMEOUT_SECONDS)
    for port in ports:
        base_url = f"http://{host}:{port}"
        try:
            # Probe version first — fast and lightweight
            async with session.get(
                f"{base_url}/api/version", timeout=timeout
            ) as resp:
                if resp.status != 200:
                    errors.append(
                        f"Frigate port {port}: version endpoint returned HTTP {resp.status}"
                    )
                    continue
                version = (await resp.text()).strip().strip('"')

            # Probe cameras and MQTT settings from the Frigate config
            cameras: List[str] = []
            mqtt_host_detected: Optional[str] = None
            mqtt_port_detected: Optional[int] = None
            try:
                async with session.get(
                    f"{base_url}/api/config", timeout=timeout
                ) as cfg_resp:
                    if cfg_resp.status == 200:
                        cfg_data = await cfg_resp.json()
                        cameras = list(cfg_data.get("cameras", {}).keys())
                        # Extract Frigate's MQTT config so the wizard can
                        # pre-fill accurate values instead of assuming the
                        # MQTT broker is co-located with Frigate.
                        mqtt_cfg = cfg_data.get("mqtt", {})
                        if isinstance(mqtt_cfg, dict):
                            raw_host = mqtt_cfg.get("host")
                            raw_port = mqtt_cfg.get("port")
                            if isinstance(raw_host, str) and raw_host:
                                mqtt_host_detected = raw_host
                            if isinstance(raw_port, int) and raw_port > 0:
                                mqtt_port_detected = raw_port
            except Exception as cam_exc:
                errors.append(f"Frigate config probe failed: {cam_exc}")

            return True, version, cameras, mqtt_host_detected, mqtt_port_detected

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            errors.append(f"Frigate port {port}: {exc}")

    return False, None, [], None, None


async def _probe_go2rtc(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    errors: List[str],
) -> tuple[bool, Optional[str], List[str], Dict[str, Any]]:
    """Probe go2rtc and return (reachable, version, stream_names, backchannel_info).

    Args:
        session:  Shared aiohttp session (caller owns lifecycle).
        host:     go2rtc hostname or IP.
        port:     go2rtc API port.
        errors:   Mutable list to append non-fatal error strings to.

    Returns:
        4-tuple of (reachable, version_or_None, stream_list, backchannel_dict).
    """
    timeout = aiohttp.ClientTimeout(total=_PROBE_TIMEOUT_SECONDS)
    base_url = f"http://{host}:{port}"

    try:
        # GET /api returns version info
        async with session.get(f"{base_url}/api", timeout=timeout) as resp:
            if resp.status != 200:
                errors.append(
                    f"go2rtc /api returned HTTP {resp.status}"
                )
                return False, None, [], {}
            api_data = await resp.json()
            version: Optional[str] = api_data.get("version")

        # GET /api/streams for stream list and backchannel info
        streams: List[str] = []
        backchannel_info: Dict[str, Any] = {}

        try:
            async with session.get(
                f"{base_url}/api/streams", timeout=timeout
            ) as s_resp:
                if s_resp.status == 200:
                    streams_data: Dict[str, Any] = await s_resp.json()
                    streams = list(streams_data.keys())

                    # Parse backchannel info from each stream's producer medias.
                    # A 'sendonly' track in the RTSP media description means the
                    # camera accepts audio — i.e. backchannel is available.
                    for stream_name, info in streams_data.items():
                        codecs: List[str] = []
                        producers = info.get("producers", [])
                        if isinstance(producers, list):
                            for producer in producers:
                                for media in producer.get("medias", []):
                                    if "sendonly" in media:
                                        # Media string format:
                                        # "audio, sendonly, PCMU/8000, PCMA/8000"
                                        parts = [
                                            p.strip() for p in media.split(",")
                                        ]
                                        # Collect codec entries (contain "/" like "PCMU/8000")
                                        codecs.extend(
                                            p for p in parts
                                            if p not in ("audio", "sendonly")
                                            and "/" in p
                                        )
                        backchannel_info[stream_name] = {
                            "has_backchannel": len(codecs) > 0,
                            "codecs": codecs,
                        }
        except Exception as s_exc:
            errors.append(f"go2rtc streams probe failed: {s_exc}")

        return True, version, streams, backchannel_info

    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        errors.append(f"go2rtc probe failed: {exc}")
        return False, None, [], {}


def _probe_mqtt_sync(
    host: str,
    port: int,
    username: str,
    password: str,
) -> bool:
    """Synchronously probe an MQTT broker with a short timeout.

    Uses paho-mqtt's synchronous connect to test TCP reachability and (if
    credentials are provided) authentication.  Intended to be called via
    ``asyncio.to_thread`` to avoid blocking the event loop.

    Args:
        host:     MQTT broker hostname or IP.
        port:     MQTT broker port.
        username: MQTT username (empty string for anonymous).
        password: MQTT password (empty string for anonymous).

    Returns:
        True if the broker accepted the connection, False otherwise.
    """
    try:
        import paho.mqtt.client as mqtt

        try:
            client = mqtt.Client()
        except TypeError:
            # paho-mqtt v2 requires CallbackAPIVersion
            from paho.mqtt.enums import CallbackAPIVersion
            client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2
            )

        if username:
            client.username_pw_set(username, password)

        # connect() raises on TCP failure; timeout controls socket-level wait
        client.connect(host, port, keepalive=_MQTT_PROBE_TIMEOUT_SECONDS)
        client.disconnect()
        return True

    except Exception as exc:
        logger.debug("MQTT probe failed for %s:%d — %s", host, port, exc)
        return False


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=SetupStatus,
    summary="Get first-run setup status",
    description=(
        "Returns whether config.yaml exists and which sections are populated. "
        "Used by the wizard to decide which steps to show. "
        "No authentication required — safe to call before any key is configured."
    ),
)
async def get_setup_status() -> SetupStatus:
    """Return first-run setup status based on presence and content of config.yaml.

    Reads config.yaml if it exists and inspects the top-level sections to
    determine what has been configured.  Returns FRIGATE_HOST from the
    environment so the wizard can pre-fill the host field.

    Returns:
        SetupStatus with per-section flags and optional FRIGATE_HOST env value.
    """
    config_path = Path(dashboard_cfg.VOXWATCH_CONFIG_PATH)
    exists = config_path.exists()

    # Default all flags to False — populated below if the file can be read.
    frigate_configured = False
    mqtt_configured = False
    ai_configured = False
    cameras_configured = False

    if exists:
        try:
            with config_path.open("r", encoding="utf-8") as fh:
                raw: Dict[str, Any] = yaml.safe_load(fh) or {}

            frigate_cfg = raw.get("frigate", {})
            if isinstance(frigate_cfg, dict) and frigate_cfg.get("host"):
                frigate_configured = True
            if isinstance(frigate_cfg, dict) and frigate_cfg.get("mqtt_host"):
                mqtt_configured = True

            ai_cfg = raw.get("ai", {})
            if isinstance(ai_cfg, dict):
                primary_key = ai_cfg.get("primary", {}).get("api_key", "")
                # Consider configured if non-empty and not an unresolved ${TOKEN}
                if (
                    isinstance(primary_key, str)
                    and primary_key
                    and not primary_key.startswith("${")
                ):
                    ai_configured = True

            cameras_cfg = raw.get("cameras", {})
            if isinstance(cameras_cfg, dict) and cameras_cfg:
                cameras_configured = True

        except Exception as exc:
            # Unparseable config is not fatal for status — just report exists=True.
            logger.warning("Could not parse config.yaml for status check: %s", exc)

    # All mandatory sections must be present for setup_complete to be True.
    setup_complete = exists and frigate_configured and cameras_configured

    # Read FRIGATE_HOST env var for wizard pre-fill — common in Docker Compose
    # deployments where the same value is shared between containers.
    frigate_host_env: Optional[str] = os.environ.get("FRIGATE_HOST") or None

    return SetupStatus(
        config_exists=exists,
        setup_complete=setup_complete,
        frigate_configured=frigate_configured,
        mqtt_configured=mqtt_configured,
        ai_configured=ai_configured,
        cameras_configured=cameras_configured,
        frigate_host_env=frigate_host_env,
    )


@router.post(
    "/probe",
    response_model=ProbeResult,
    summary="Probe Frigate, go2rtc, and MQTT",
    description=(
        "Concurrently probes all three services at the addresses provided. "
        "Returns discovered cameras, streams, and per-stream backchannel support. "
        "Returns 409 Conflict if config.yaml already exists (setup already complete). "
        "No authentication required."
    ),
)
async def probe_services(req: ProbeRequest) -> ProbeResult:
    """Probe Frigate, go2rtc, and MQTT concurrently and return everything discovered.

    All three probes run simultaneously via asyncio.gather so the total latency
    is bounded by the slowest individual service, not their sum.

    Frigate is tried on the provided port and automatically falls back to
    ports 5001 and 8971 if the primary port fails.

    Args:
        req: Probe addresses and optional MQTT credentials.

    Returns:
        ProbeResult with reachability, version, and discovery data for each service.

    Raises:
        HTTPException 409: If config.yaml already exists (setup is not needed).
        HTTPException 400: If any host value fails the safety regex.
    """
    if _config_exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "config.yaml already exists at "
                f"{dashboard_cfg.VOXWATCH_CONFIG_PATH}. "
                "Setup is already complete. Use the config editor to make changes."
            ),
        )

    # Validate all host inputs before making any outbound connections.
    _validate_host(req.frigate_host, "frigate_host")

    # Resolve defaults: go2rtc and MQTT share the Frigate host when not set.
    go2rtc_host = req.go2rtc_host or req.frigate_host
    mqtt_host = req.mqtt_host or req.frigate_host

    _validate_host(go2rtc_host, "go2rtc_host")
    _validate_host(mqtt_host, "mqtt_host")

    errors: List[str] = []
    probe_start = time.monotonic()

    # Build the Frigate port probe list: requested port first, then fallbacks.
    frigate_ports = [req.frigate_port] + [
        p for p in _FRIGATE_PROBE_PORTS if p != req.frigate_port
    ]

    # Create a temporary aiohttp session scoped to this probe request.
    # Using a dedicated session here (rather than the module singleton) ensures
    # first-run probes don't interfere with normal dashboard operations.
    async with aiohttp.ClientSession() as session:
        # Run all three probes concurrently.  asyncio.gather collects results
        # even when individual coroutines raise — we use return_exceptions=False
        # because each probe handles its own exceptions internally and returns
        # a safe default rather than raising.
        (
            frigate_result,
            go2rtc_result,
            mqtt_result,
        ) = await asyncio.gather(
            _probe_frigate(session, req.frigate_host, frigate_ports, errors),
            _probe_go2rtc(session, go2rtc_host, req.go2rtc_port, errors),
            asyncio.to_thread(
                _probe_mqtt_sync,
                mqtt_host,
                req.mqtt_port,
                req.mqtt_user,
                req.mqtt_password,
            ),
        )

    probe_duration_ms = int((time.monotonic() - probe_start) * 1000)

    frigate_reachable, frigate_version, frigate_cameras, mqtt_host_detected, mqtt_port_detected = frigate_result
    go2rtc_reachable, go2rtc_version, go2rtc_streams, backchannel_info = go2rtc_result
    mqtt_reachable: bool = bool(mqtt_result)

    return ProbeResult(
        frigate_reachable=frigate_reachable,
        frigate_version=frigate_version,
        frigate_cameras=frigate_cameras,
        go2rtc_reachable=go2rtc_reachable,
        go2rtc_version=go2rtc_version,
        go2rtc_streams=go2rtc_streams,
        backchannel_info=backchannel_info,
        mqtt_reachable=mqtt_reachable,
        mqtt_host_detected=mqtt_host_detected,
        mqtt_port_detected=mqtt_port_detected,
        errors=errors,
        probe_duration_ms=probe_duration_ms,
    )


@router.post(
    "/generate-config",
    status_code=status.HTTP_201_CREATED,
    summary="Generate and write initial config.yaml",
    description=(
        "Builds a complete config.yaml from the wizard form data and writes it "
        "atomically.  The VoxWatch service detects the new file within ~5 seconds "
        "and starts automatically.  Returns 409 Conflict if config already exists. "
        "No authentication required."
    ),
)
async def generate_config(req: GenerateConfigRequest) -> Dict[str, str]:
    """Build and atomically write config.yaml from wizard form data.

    Constructs a minimal but fully functional config dict, serialises it to
    YAML, and writes it using tempfile + os.replace for atomicity.  The
    VoxWatch service's polling loop detects the file within 5 seconds.

    Args:
        req: All settings collected by the setup wizard.

    Returns:
        Dict with a single 'message' key confirming success and the config path.

    Raises:
        HTTPException 409: If config.yaml already exists.
        HTTPException 400: If any host value fails the safety regex.
        HTTPException 500: If the file cannot be written to disk.
    """
    if _config_exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "config.yaml already exists at "
                f"{dashboard_cfg.VOXWATCH_CONFIG_PATH}. "
                "Setup is already complete. Use the config editor to make changes."
            ),
        )

    # Validate host inputs before building the config.
    _validate_host(req.frigate_host, "frigate_host")

    go2rtc_host = req.go2rtc_host or req.frigate_host
    mqtt_host = req.mqtt_host or req.frigate_host

    _validate_host(go2rtc_host, "go2rtc_host")
    _validate_host(mqtt_host, "mqtt_host")

    # ── Build the config dict ─────────────────────────────────────────────────

    # Frigate section — includes MQTT connection details because VoxWatch reads
    # MQTT settings from the frigate block (matching Frigate's own conventions).
    frigate_section: Dict[str, Any] = {
        "host": req.frigate_host,
        "port": req.frigate_port,
        "mqtt_host": mqtt_host,
        "mqtt_port": req.mqtt_port,
    }
    if req.mqtt_user:
        frigate_section["mqtt_user"] = req.mqtt_user
    if req.mqtt_password:
        frigate_section["mqtt_password"] = req.mqtt_password

    # go2rtc section
    go2rtc_section: Dict[str, Any] = {
        "host": go2rtc_host,
        "api_port": req.go2rtc_port,
    }

    # Cameras section — one entry per camera supplied by the wizard.
    cameras_section: Dict[str, Any] = {}
    for cam_name, cam in req.cameras.items():
        cam_entry: Dict[str, Any] = {
            "enabled": cam.enabled,
            "go2rtc_stream": cam.go2rtc_stream,
            "audio_codec": cam.audio_codec,
        }
        if cam.scene_context:
            cam_entry["scene_context"] = cam.scene_context
        cameras_section[cam_name] = cam_entry

    # AI section — primary provider only.  Fallback left to defaults from
    # _apply_defaults() when the service loads the file.
    ai_section: Dict[str, Any] = {
        "primary": {
            "provider": req.ai_provider,
            "model": req.ai_model,
        }
    }
    if req.ai_api_key:
        ai_section["primary"]["api_key"] = req.ai_api_key

    # TTS section — build sub-dict for the selected engine only.
    tts_section: Dict[str, Any] = {
        "engine": req.tts_engine,
        "provider": req.tts_engine,  # both keys for compatibility
    }
    # Per-engine voice/key/host fields — only written when non-empty so the
    # config stays minimal and the service applies its own defaults for the rest.
    if req.tts_engine == "piper" and req.tts_voice:
        tts_section["piper"] = {"model": req.tts_voice}
    elif req.tts_engine == "kokoro":
        kokoro_cfg: Dict[str, Any] = {}
        if req.tts_voice:
            kokoro_cfg["voice"] = req.tts_voice
        if req.tts_host:
            kokoro_cfg["host"] = req.tts_host
        if kokoro_cfg:
            tts_section["kokoro"] = kokoro_cfg
    elif req.tts_engine == "espeak" and req.tts_voice:
        tts_section["espeak"] = {"voice": req.tts_voice}
    elif req.tts_engine in ("elevenlabs", "openai", "cartesia"):
        cloud_tts: Dict[str, Any] = {}
        if req.tts_api_key:
            cloud_tts["api_key"] = req.tts_api_key
        if req.tts_voice:
            cloud_tts["voice"] = req.tts_voice
        if cloud_tts:
            tts_section[req.tts_engine] = cloud_tts

    # Response mode section
    response_mode_section: Dict[str, Any] = {"name": req.response_mode}

    # Assemble the final config dict.  Key order follows the logical reading
    # order that human contributors will expect (infrastructure first, then
    # AI / TTS settings, then cameras).
    config: Dict[str, Any] = {
        "frigate": frigate_section,
        "go2rtc": go2rtc_section,
        "cameras": cameras_section,
        "ai": ai_section,
        "tts": tts_section,
        "response_mode": response_mode_section,
    }

    # ── Atomic write ──────────────────────────────────────────────────────────
    # Write to a temp file alongside config.yaml then rename into place.
    # os.replace is atomic on POSIX and best-effort on Windows (win32file
    # semantics), meaning a crash mid-write cannot leave a truncated config.
    yaml_text = yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

    config_path = Path(dashboard_cfg.VOXWATCH_CONFIG_PATH)
    config_dir = config_path.parent
    try:
        config_dir.mkdir(parents=True, exist_ok=True)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir),
            prefix=".setup_config_",
            suffix=".yaml.tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(yaml_text)
            os.replace(tmp_path, str(config_path))
        except Exception:
            # Remove the temp file if anything goes wrong to avoid orphan files.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    except OSError as exc:
        logger.error("Failed to write config.yaml during setup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write config.yaml: {exc}",
        ) from exc

    logger.info(
        "First-run setup complete — config.yaml written to %s "
        "with %d camera(s). VoxWatch service will start within 5 seconds.",
        config_path,
        len(cameras_section),
    )

    return {
        "message": (
            f"config.yaml written to {config_path}. "
            "VoxWatch will start automatically within a few seconds."
        )
    }
