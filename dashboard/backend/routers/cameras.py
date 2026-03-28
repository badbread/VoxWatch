"""
cameras.py — Camera Management API Router

Endpoints:
    GET  /api/cameras                      — List all configured cameras with status
    GET  /api/cameras/{name}               — Single camera details + Frigate stats
    GET  /api/cameras/{name}/snapshot      — Live snapshot image (proxied from Frigate)
    POST /api/cameras/{name}/identify      — ONVIF probe + compatibility lookup

Camera data is sourced from two places:
  1. config.yaml — enabled flag, go2rtc_stream name
  2. Frigate API (via frigate_client) — FPS, online status, snapshot images

The snapshot endpoint proxies the raw JPEG bytes from Frigate so the browser
doesn't need CORS exceptions or direct Frigate access.

Security:
    Camera names are validated against a strict allowlist pattern before use.
    This prevents SSRF attacks where a crafted camera name could be used to
    construct a malicious URL that go2rtc or Frigate would then fetch — for
    example, a name like "../../admin" or "host.internal/secret" could redirect
    internal HTTP requests to unintended destinations.
"""

import base64
import hashlib
import logging
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

import aiohttp
from fastapi import APIRouter, HTTPException, Response, status

from backend.camera_db import match_camera_model
from backend.models.status_models import CameraStatus
from backend.services import frigate_client as fc_module
from backend.services import go2rtc_client as g2rtc_module
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.cameras")

router = APIRouter(prefix="/cameras", tags=["Cameras"])

# ── Input validation ──────────────────────────────────────────────────────────
# Camera names must consist only of alphanumeric characters, underscores, and
# hyphens.  This pattern is intentionally narrow:
#   - Prevents path traversal sequences (e.g. "../", "%2F")
#   - Prevents URL injection into Frigate/go2rtc API calls (e.g. "cam?admin=1")
#   - Prevents shell metacharacters if names are ever used in subprocesses
#
# Typical real-world camera names ("frontdoor", "backyard_cam", "garage-01")
# all satisfy this pattern.
_CAMERA_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_camera_name(camera_name: str) -> None:
    """Raise HTTP 400 if *camera_name* contains characters outside the safe set.

    Security rationale: camera names appear in URLs constructed for Frigate and
    go2rtc API calls.  An unrestricted name could be used to inject path
    segments or query parameters, turning this endpoint into an SSRF vector.

    Args:
        camera_name: The camera name string provided by the API caller.

    Raises:
        HTTPException 400: If the name contains any disallowed characters.
    """
    if not _CAMERA_NAME_RE.match(camera_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid camera name {camera_name!r}. "
                "Camera names may only contain letters, digits, underscores, "
                "and hyphens (pattern: ^[a-zA-Z0-9_-]+$)."
            ),
        )


@router.get(
    "",
    response_model=list[CameraStatus],
    summary="List all cameras",
    description=(
        "Returns the list of cameras configured in config.yaml, "
        "enriched with live status from Frigate."
    ),
)
async def list_cameras() -> list[CameraStatus]:
    """Return ALL cameras from Frigate, enriched with VoxWatch config status.

    Discovers cameras from the Frigate API (so every camera in the system
    is visible), then marks which ones are enabled in VoxWatch's config.yaml.
    Cameras not in VoxWatch config are shown as enabled=False.

    Returns:
        List of CameraStatus objects, one per Frigate camera.
    """
    voxwatch_cameras = await _get_cameras_config()
    result: list[CameraStatus] = []

    # Fetch Frigate stats and go2rtc backchannel info concurrently
    import asyncio
    frigate_cameras: dict[str, Any] = {}
    backchannel_info: dict[str, Any] = {}

    async def _fetch_frigate() -> None:
        nonlocal frigate_cameras
        if fc_module.frigate_client:
            try:
                stats = await fc_module.frigate_client.get_stats()
                if stats:
                    frigate_cameras = stats.get("cameras", {})
            except Exception as exc:
                logger.debug("Could not fetch Frigate cameras: %s", exc)

    async def _fetch_backchannel() -> None:
        nonlocal backchannel_info
        if g2rtc_module.go2rtc_client:
            try:
                backchannel_info = await g2rtc_module.go2rtc_client.get_backchannel_info()
            except Exception as exc:
                logger.debug("Could not fetch go2rtc backchannel info: %s", exc)

    await asyncio.gather(_fetch_frigate(), _fetch_backchannel())

    # ── Cross-reference camera DB for backchannel cameras ─────────────────
    # go2rtc reports backchannel support based on RTSP stream capabilities,
    # but some cameras (e.g. Dahua IPC-T54IR-AS) have an RCA audio *jack*
    # without a built-in speaker.  The camera_db knows which models actually
    # have speakers.  We do parallel ONVIF probes for cameras that go2rtc
    # says have backchannel, then override has_backchannel=False for cameras
    # whose model is in the DB but lacks a built-in speaker.
    from backend.camera_db import SPEAKER_BUILTIN

    # Identify cameras needing a DB cross-reference (backchannel detected)
    bc_cameras = [
        name for name, bc in backchannel_info.items()
        if bc and bc.get("has_backchannel")
    ]

    # Results from ONVIF probe + camera_db lookup, keyed by camera name
    speaker_overrides: dict[str, dict[str, Any]] = {}

    async def _identify_speaker(cam_name: str) -> None:
        """ONVIF-probe a camera and cross-reference the camera DB.

        If the camera model is known and lacks a built-in speaker, store
        an override entry so has_backchannel can be set to False.
        """
        try:
            cam_ip, rtsp_creds = await _resolve_camera_ip(cam_name)
            if not cam_ip:
                return
            onvif_result = await _probe_onvif(cam_ip, rtsp_creds)
            if not onvif_result:
                return
            model = onvif_result.get("model", "")
            db_entry = match_camera_model(model) if model else None
            if not db_entry:
                return
            speaker_overrides[cam_name] = {
                "camera_model": model,
                "camera_manufacturer": db_entry.get("manufacturer"),
                "speaker_status": db_entry.get("speaker_type", "unknown"),
                "compatibility_notes": db_entry.get("notes"),
                "no_builtin_speaker": db_entry.get("speaker_type") != SPEAKER_BUILTIN,
            }
        except Exception:
            pass  # best-effort — don't block the camera list

    if bc_cameras:
        await asyncio.gather(
            *[_identify_speaker(name) for name in bc_cameras],
            return_exceptions=True,
        )

    # Build a merged set of all camera names
    all_names = set(frigate_cameras.keys()) | set(voxwatch_cameras.keys())

    for name in sorted(all_names):
        vox_cfg = voxwatch_cameras.get(name, {})
        is_voxwatch_enabled = name in voxwatch_cameras and vox_cfg.get("enabled", True)

        cam_status = CameraStatus(
            name=name,
            enabled=is_voxwatch_enabled,
        )

        # Enrich with Frigate FPS and online status
        if name in frigate_cameras:
            cam_data = frigate_cameras[name]
            fps = cam_data.get("detection_fps")
            camera_fps = cam_data.get("camera_fps", cam_data.get("capture_fps", 0))
            online = camera_fps is not None and float(camera_fps) > 0
            cam_status = cam_status.model_copy(
                update={
                    "frigate_online": online,
                    "fps": float(fps) if fps is not None else None,
                }
            )

        # Enrich with go2rtc backchannel (two-way audio) capability
        bc = backchannel_info.get(name, {})
        has_bc = bc.get("has_backchannel", False) if bc else False
        bc_codecs = bc.get("codecs") or None

        # Apply camera DB override: if the model is known and has no
        # built-in speaker, mark backchannel as unavailable and populate
        # speaker_status so the frontend can show the correct state.
        override = speaker_overrides.get(name)
        extra_fields: dict[str, Any] = {}
        if override:
            extra_fields["camera_model"] = override["camera_model"]
            extra_fields["camera_manufacturer"] = override["camera_manufacturer"]
            extra_fields["speaker_status"] = override["speaker_status"]
            extra_fields["compatibility_notes"] = override["compatibility_notes"]
            if override["no_builtin_speaker"]:
                has_bc = False

        cam_status = cam_status.model_copy(
            update={
                "has_backchannel": has_bc,
                "backchannel_codecs": bc_codecs,
                **extra_fields,
            }
        )

        result.append(cam_status)

    return result


@router.get(
    "/{camera_name}",
    response_model=CameraStatus,
    summary="Get single camera status",
    description=(
        "Returns status for a single camera including Frigate FPS and online state."
    ),
)
async def get_camera(camera_name: str) -> CameraStatus:
    """Return status for a specific camera.

    Args:
        camera_name: Camera name (must match config.yaml and Frigate config).
                     Validated against ^[a-zA-Z0-9_-]+$ to prevent SSRF.

    Returns:
        CameraStatus for the requested camera.

    Raises:
        400: If camera_name contains disallowed characters.
        404: If the camera name is not in config.yaml.
    """
    # Validate name before using it in any downstream API URL.
    _validate_camera_name(camera_name)

    voxwatch_cameras = await _get_cameras_config()
    vox_cfg = voxwatch_cameras.get(camera_name, {})
    is_voxwatch_enabled = camera_name in voxwatch_cameras and vox_cfg.get("enabled", True)

    cam_status = CameraStatus(
        name=camera_name,
        enabled=is_voxwatch_enabled,
    )

    # Enrich with Frigate data
    if fc_module.frigate_client:
        cam_status = await _enrich_with_frigate(cam_status)

    return cam_status


@router.get(
    "/{camera_name}/snapshot",
    summary="Get latest camera snapshot",
    description=(
        "Proxies the latest JPEG snapshot for a camera from Frigate. "
        "Returns raw image bytes with Content-Type: image/jpeg."
    ),
    responses={
        200: {"content": {"image/jpeg": {}}},
        400: {"description": "Invalid camera name"},
        404: {"description": "Camera not found or Frigate unavailable"},
        503: {"description": "Frigate snapshot unavailable"},
    },
)
async def get_snapshot(camera_name: str) -> Response:
    """Proxy a live snapshot image from Frigate.

    Fetches the latest JPEG from Frigate's /api/<camera>/latest.jpg and
    returns the raw bytes so the browser can display it without CORS issues.

    Args:
        camera_name: Camera name (must match Frigate camera name).
                     Validated against ^[a-zA-Z0-9_-]+$ to prevent SSRF.

    Returns:
        JPEG image response.

    Raises:
        400: If camera_name contains disallowed characters.
        404: If the camera is not in config or Frigate client is unavailable.
        503: If Frigate cannot provide a snapshot.
    """
    # Validate name before constructing the Frigate URL.
    # Without this check an attacker could pass a name like
    # "frontdoor/../../admin" which would resolve to an unintended Frigate path.
    _validate_camera_name(camera_name)

    if fc_module.frigate_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Frigate client not initialized. Check config.yaml frigate section.",
        )

    image_bytes = await fc_module.frigate_client.get_snapshot(camera_name)
    if image_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not retrieve snapshot for camera {camera_name!r} from Frigate. "
                   "Check that Frigate is running and the camera is online.",
        )

    return Response(content=image_bytes, media_type="image/jpeg")


@router.post(
    "/{camera_name}/identify",
    summary="Identify camera model and check VoxWatch compatibility",
    description=(
        "Probes the camera via ONVIF GetDeviceInformation to retrieve its "
        "manufacturer and model string, then cross-references that model against "
        "the VoxWatch compatibility database to determine speaker capability."
    ),
    response_model=dict[str, Any],
)
async def identify_camera(camera_name: str) -> dict[str, Any]:
    """Attempt ONVIF identification and compatibility lookup for a camera.

    Steps:
        1. Resolve the camera's RTSP URL from go2rtc stream data.
        2. Extract the IP address from the URL.
        3. Try ONVIF ``GetDeviceInformation`` against that IP using a set of
           common credentials drawn from the RTSP URL and well-known defaults.
        4. Cross-reference the returned model string against ``KNOWN_CAMERAS``.
        5. Return a structured result with identification and compatibility info.

    Args:
        camera_name: Camera name, validated against ``^[a-zA-Z0-9_-]+$``.

    Returns:
        Dict with keys:
            - ``identified`` (bool) — whether ONVIF probe succeeded.
            - ``manufacturer`` (str | None) — manufacturer from ONVIF.
            - ``model`` (str | None) — raw model string from ONVIF.
            - ``firmware`` (str | None) — firmware version from ONVIF.
            - ``camera_ip`` (str | None) — resolved IP used for the probe.
            - ``compatibility`` (dict | None) — entry from the VoxWatch
              camera database, or ``None`` if model is unknown.
            - ``speaker_status`` (str) — one of ``"built_in"``, ``"rca_out"``,
              ``"none"``, ``"unknown"``.
            - ``error`` (str | None) — human-readable error if probe failed.

    Raises:
        400: If ``camera_name`` contains disallowed characters.
        404: If go2rtc has no stream configured for this camera.
    """
    _validate_camera_name(camera_name)

    # ── Step 1: resolve RTSP URL from go2rtc ─────────────────────────────────
    camera_ip, rtsp_credentials = await _resolve_camera_ip(camera_name)

    if camera_ip is None:
        return {
            "identified": False,
            "manufacturer": None,
            "model": None,
            "firmware": None,
            "camera_ip": None,
            "compatibility": None,
            "speaker_status": "unknown",
            "error": (
                f"Could not resolve an IP address for camera '{camera_name}'. "
                "Ensure go2rtc has an RTSP stream configured for this camera."
            ),
        }

    # ── Step 2: ONVIF probe ───────────────────────────────────────────────────
    onvif_result = await _probe_onvif(camera_ip, rtsp_credentials)

    if onvif_result is None:
        return {
            "identified": False,
            "manufacturer": None,
            "model": None,
            "firmware": None,
            "camera_ip": camera_ip,
            "compatibility": None,
            "speaker_status": "unknown",
            "error": (
                f"ONVIF probe failed for {camera_ip}. "
                "The camera may not support ONVIF, or the credentials are incorrect. "
                "Check that the camera is reachable and ONVIF is enabled."
            ),
        }

    manufacturer = onvif_result.get("manufacturer")
    model = onvif_result.get("model")
    firmware = onvif_result.get("firmware_version")

    # ── Step 3: compatibility lookup ──────────────────────────────────────────
    compatibility = match_camera_model(model) if model else None

    if compatibility:
        speaker_status = compatibility.get("speaker_type", "unknown")
        # Normalise: if has_speaker is True and speaker_type missing, treat as built_in
        if compatibility.get("has_speaker") and speaker_status not in (
            "built_in", "rca_out", "none"
        ):
            speaker_status = "built_in"
    else:
        speaker_status = "unknown"

    logger.info(
        "Identified camera '%s' at %s: %s %s (speaker_status=%s)",
        camera_name,
        camera_ip,
        manufacturer,
        model,
        speaker_status,
    )

    return {
        "identified": True,
        "manufacturer": manufacturer,
        "model": model,
        "firmware": firmware,
        "camera_ip": camera_ip,
        "compatibility": compatibility,
        "speaker_status": speaker_status,
        "error": None,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_cameras_config() -> dict[str, Any]:
    """Read the cameras section from config.yaml.

    Returns:
        Dict of camera_name -> camera config dict.
        Returns an empty dict if config is missing or unreadable.
    """
    try:
        cfg = await config_service.get_config()
        return cfg.get("cameras", {})
    except Exception as exc:
        logger.warning("Could not read cameras from config: %s", exc)
        return {}


async def _enrich_with_frigate(cam_status: CameraStatus) -> CameraStatus:
    """Add Frigate-sourced FPS and online status to a CameraStatus.

    Queries Frigate's /api/stats endpoint for the camera's detection FPS.
    Does not raise on failure — returns the original status unchanged.

    Args:
        cam_status: CameraStatus to enrich.

    Returns:
        Enriched CameraStatus (or original if Frigate is unreachable).
    """
    if fc_module.frigate_client is None:
        return cam_status

    try:
        stats = await fc_module.frigate_client.get_stats()
        if stats:
            cam_stats = stats.get("cameras", {}).get(cam_status.name, {})
            fps = cam_stats.get("detection_fps")
            camera_fps = cam_stats.get("camera_fps", cam_stats.get("capture_fps", 0))
            # Camera is considered online if Frigate is reporting any FPS for it
            online = camera_fps is not None and float(camera_fps) > 0

            # Return a new instance with the Frigate fields filled in
            return cam_status.model_copy(
                update={
                    "frigate_online": online,
                    "fps": float(fps) if fps is not None else None,
                }
            )
    except Exception as exc:
        logger.debug("Frigate enrichment failed for %s: %s", cam_status.name, exc)

    return cam_status


# ── ONVIF identification helpers ──────────────────────────────────────────────

# Credential pairs to try during ONVIF probing, in priority order.
# The RTSP-URL credentials are prepended at runtime if present.
_FALLBACK_CREDENTIALS: list[tuple[str, str]] = [
    ("admin", "admin"),
    ("admin", ""),
    ("admin", "password"),
    ("admin", "12345"),
]

# Per-camera ONVIF request timeout (seconds).
_ONVIF_TIMEOUT = aiohttp.ClientTimeout(total=4.0)

async def _resolve_camera_ip(
    camera_name: str,
) -> tuple[str | None, tuple[str, str] | None]:
    """Extract the IP address and credentials from a camera's RTSP URL in go2rtc.

    Looks up the go2rtc stream for *camera_name*, finds the first RTSP producer
    URL, and parses the host and any embedded credentials.

    Args:
        camera_name: go2rtc stream name for the camera.

    Returns:
        Tuple of ``(ip_address, (username, password))`` where either element
        may be ``None`` if resolution fails or no credentials are embedded.
    """
    if g2rtc_module.go2rtc_client is None:
        return None, None

    try:
        streams = await g2rtc_module.go2rtc_client.get_streams()
        if not streams:
            return None, None

        stream = streams.get(camera_name)
        if not stream:
            return None, None

        # Walk producers looking for an RTSP source URL
        for producer in stream.get("producers", []):
            url_str = producer.get("url", "")
            if not url_str.lower().startswith("rtsp"):
                continue

            parsed = urllib.parse.urlparse(url_str)
            ip = parsed.hostname
            credentials: tuple[str, str] | None = None
            if parsed.username:
                credentials = (
                    urllib.parse.unquote(parsed.username),
                    urllib.parse.unquote(parsed.password or ""),
                )
            return ip, credentials

    except Exception as exc:
        logger.debug("_resolve_camera_ip failed for %s: %s", camera_name, exc)

    return None, None


async def _probe_onvif(
    camera_ip: str,
    rtsp_credentials: tuple[str, str] | None,
) -> dict[str, str | None] | None:
    """Send an ONVIF GetDeviceInformation SOAP request to the camera.

    Tries multiple credential pairs so that cameras whose passwords differ from
    the defaults are still identified.  The credentials embedded in the RTSP URL
    are tried first because they are the most likely to be correct.

    ONVIF WS-Security UsernameToken is used for authentication.  We implement a
    minimal subset — enough to authenticate against Dahua, Reolink, and most
    other mainstream cameras — without pulling in the full zeep SOAP stack.

    Args:
        camera_ip: Camera IP address to probe.
        rtsp_credentials: Optional ``(username, password)`` tuple extracted from
            the RTSP URL.  Tried before the fallback credential list.

    Returns:
        Dict with ``"manufacturer"``, ``"model"``, ``"firmware_version"`` keys
        (string values, may be ``None``), or ``None`` if all attempts fail.
    """
    # Build the ordered credential list
    credential_list: list[tuple[str, str]] = []
    if rtsp_credentials:
        credential_list.append(rtsp_credentials)
    for cred in _FALLBACK_CREDENTIALS:
        if cred not in credential_list:
            credential_list.append(cred)

    onvif_url = f"http://{camera_ip}/onvif/device_service"

    async with aiohttp.ClientSession(timeout=_ONVIF_TIMEOUT) as session:
        for username, password in credential_list:
            soap_body = _build_onvif_soap(username, password)
            try:
                async with session.post(
                    onvif_url,
                    data=soap_body,
                    headers={
                        "Content-Type": "application/soap+xml; charset=utf-8",
                        "SOAPAction": (
                            '"http://www.onvif.org/ver10/device/wsdl'
                            '/GetDeviceInformation"'
                        ),
                    },
                ) as resp:
                    if resp.status not in (200, 400):
                        # 401/403 means wrong auth — try next credential
                        continue

                    text = await resp.text()
                    result = _parse_device_info_response(text)
                    if result:
                        return result

            except aiohttp.ClientConnectorError:
                # Camera unreachable — no point trying other credentials
                logger.debug("ONVIF probe: %s is unreachable", camera_ip)
                return None
            except Exception as exc:
                logger.debug(
                    "ONVIF probe error for %s (user=%s): %s",
                    camera_ip,
                    username,
                    exc,
                )

    return None


def _build_onvif_soap(username: str, password: str) -> str:
    """Build a WS-Security signed SOAP envelope for GetDeviceInformation.

    Implements the ONVIF WS-Security UsernameToken profile using a nonce,
    UTC timestamp, and a SHA-1 password digest.  This is the authentication
    scheme used by the majority of IP cameras (Dahua, Reolink, Hikvision, etc.).

    Digest formula (per WS-Security spec):
        PasswordDigest = Base64(SHA-1(Nonce + Created + Password))

    Args:
        username: ONVIF username (typically "admin").
        password: ONVIF password in plaintext.

    Returns:
        Complete SOAP envelope string ready to POST as the request body.
    """
    nonce_bytes = os.urandom(16)
    nonce_b64 = base64.b64encode(nonce_bytes).decode()
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # SHA-1(nonce_raw + created_bytes + password_bytes)
    digest_input = nonce_bytes + created.encode("utf-8") + password.encode("utf-8")
    digest = base64.b64encode(hashlib.sha1(digest_input).digest()).decode()  # nosec B324

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
    xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
    xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
  <s:Header>
    <wsse:Security>
      <wsse:UsernameToken>
        <wsse:Username>{username}</wsse:Username>
        <wsse:Password
          Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
        >{digest}</wsse:Password>
        <wsse:Nonce
          EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
        >{nonce_b64}</wsse:Nonce>
        <wsu:Created>{created}</wsu:Created>
      </wsse:UsernameToken>
    </wsse:Security>
  </s:Header>
  <s:Body>
    <tds:GetDeviceInformation/>
  </s:Body>
</s:Envelope>"""


def _parse_device_info_response(soap_text: str) -> dict[str, str | None] | None:
    """Extract device information fields from an ONVIF SOAP response.

    Parses ``GetDeviceInformationResponse`` elements from the SOAP body.
    Handles both SOAP 1.1 and SOAP 1.2 envelope namespaces.

    Args:
        soap_text: Raw XML string returned by the camera's ONVIF endpoint.

    Returns:
        Dict with ``"manufacturer"``, ``"model"``, ``"firmware_version"`` keys,
        or ``None`` if the response could not be parsed or contains a SOAP fault.
    """
    try:
        root = ET.fromstring(soap_text)
    except ET.ParseError as exc:
        logger.debug("ONVIF response XML parse error: %s", exc)
        return None

    # Reject SOAP faults immediately — wrong credentials return a fault
    fault_tags = [
        "{http://www.w3.org/2003/05/soap-envelope}Fault",
        "{http://schemas.xmlsoap.org/soap/envelope/}Fault",
    ]
    for fault_tag in fault_tags:
        if root.find(f".//{fault_tag}") is not None:
            return None

    # ONVIF GetDeviceInformationResponse namespace
    ns = "http://www.onvif.org/ver10/device/wsdl"

    def _text(tag: str) -> str | None:
        """Return stripped text for the first matching element, or None."""
        el = root.find(f".//{{{ns}}}{tag}")
        return el.text.strip() if el is not None and el.text else None

    manufacturer = _text("Manufacturer")
    model = _text("Model")
    firmware = _text("FirmwareVersion")

    # Must have at least a manufacturer or model to be useful
    if manufacturer is None and model is None:
        return None

    return {
        "manufacturer": manufacturer,
        "model": model,
        "firmware_version": firmware,
    }
