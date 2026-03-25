"""
go2rtc_client.py — Async HTTP Client for the go2rtc API

Provides async methods for querying go2rtc's REST API used by the VoxWatch
dashboard.

go2rtc API base URL: http://<host>:<api_port>/api/
Notable endpoints:
  - GET /api/streams              — list all configured streams and their state
  - GET /api/streams?src=<name>   — get a specific stream
  - POST /api/streams?dst=<name>&src=<url> — push audio to a stream (used by VoxWatch)

The dashboard uses this client to:
  - Show stream health / connection count on the cameras page
  - Trigger test audio pushes from the /api/audio/test endpoint

Usage:
    client = Go2rtcClient("localhost", 1984)
    async with client:
        streams = await client.get_streams()
        status = await client.probe_status()
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from backend.models.status_models import Go2rtcStatus

logger = logging.getLogger("dashboard.go2rtc_client")

# Timeout for all go2rtc API requests (seconds)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=5.0)


class Go2rtcClient:
    """Async HTTP client for the go2rtc relay API.

    Attributes:
        _base_url:  go2rtc API base URL (e.g. 'http://localhost:1984').
        _session:   Shared aiohttp ClientSession (created lazily).
    """

    def __init__(self, host: str = "localhost", api_port: int = 1984) -> None:
        """Initialize the go2rtc client.

        Args:
            host:     go2rtc hostname or IP address.
            api_port: go2rtc HTTP API port (default 1984).
        """
        self._base_url = f"http://{host}:{api_port}"
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def __aenter__(self) -> "Go2rtcClient":
        """Create the aiohttp session."""
        self._session = aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT)
        return self

    async def __aexit__(self, *_) -> None:
        """Close the aiohttp session."""
        await self.close()

    async def close(self) -> None:
        """Close the shared aiohttp session if it is open."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the session, creating it lazily if needed."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT)
        return self._session

    # ── API methods ───────────────────────────────────────────────────────────

    async def get_streams(self) -> Optional[Dict[str, Any]]:
        """Fetch the list of all configured streams from go2rtc.

        Returns:
            Dict mapping stream name -> stream info dict, or None on failure.
            Each stream entry includes 'producers' and 'consumers' lists.
        """
        try:
            session = self._ensure_session()
            async with session.get(f"{self._base_url}/api/streams") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as exc:
            logger.debug("go2rtc get_streams failed: %s", exc)
        return None

    async def get_stream(self, stream_name: str) -> Optional[Dict[str, Any]]:
        """Fetch details for a specific stream.

        Args:
            stream_name: Stream name as configured in go2rtc.

        Returns:
            Stream info dict or None if the stream doesn't exist or request fails.
        """
        try:
            session = self._ensure_session()
            url = f"{self._base_url}/api/streams"
            async with session.get(url, params={"src": stream_name}) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as exc:
            logger.debug("go2rtc get_stream(%s) failed: %s", stream_name, exc)
        return None

    async def get_backchannel_info(self) -> Dict[str, Dict[str, Any]]:
        """Check which streams have backchannel (two-way audio) support.

        Inspects each stream's producer medias for 'sendonly' tracks, which
        indicate the camera supports receiving audio via RTSP backchannel.

        Returns:
            Dict mapping stream name to backchannel info:
            {
                "frontdoor": {"has_backchannel": True, "codecs": ["PCMU/8000"]},
                "driveway": {"has_backchannel": False, "codecs": []},
            }
        """
        result: Dict[str, Dict[str, Any]] = {}
        streams = await self.get_streams()
        if not streams:
            return result

        for name, info in streams.items():
            codecs: List[str] = []
            producers = info.get("producers", [])
            if isinstance(producers, list):
                for p in producers:
                    for media in p.get("medias", []):
                        if "sendonly" in media:
                            # Parse codecs from media string like:
                            # "audio, sendonly, PCMU/8000, PCMA/8000"
                            parts = [x.strip() for x in media.split(",")]
                            # Skip "audio" and "sendonly", keep codec entries
                            codecs.extend(
                                p for p in parts
                                if p not in ("audio", "sendonly") and "/" in p
                            )
            result[name] = {
                "has_backchannel": len(codecs) > 0,
                "codecs": codecs,
            }

        return result

    async def get_version(self) -> Optional[str]:
        """Fetch the go2rtc version string.

        go2rtc doesn't expose a dedicated /version endpoint, but its root
        page or /api/config may include version info. We try /api/config first.

        Returns:
            Version string or None if unavailable.
        """
        try:
            session = self._ensure_session()
            async with session.get(f"{self._base_url}/api") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # go2rtc /api returns {"version": "1.9.10", ...}
                    version = data.get("version")
                    if version:
                        return str(version)
                # Fall back to Server header
                server_header = resp.headers.get("Server", "")
                if "go2rtc" in server_header:
                    parts = server_header.split("/")
                    if len(parts) == 2:
                        return parts[1]
                return "unknown"
        except Exception as exc:
            logger.debug("go2rtc get_version failed: %s", exc)
        return None

    async def push_audio(self, stream_name: str, audio_url: str) -> bool:
        """Push an audio file to a camera stream via go2rtc's /api/ffmpeg endpoint.

        Uses the same endpoint as go2rtc's web UI "Play audio" feature.
        The /api/ffmpeg endpoint handles backchannel negotiation internally,
        unlike /api/streams which does not route audio to the backchannel.

        Note: the backchannel requires a "warmup" push on first use. This
        method sends a single push — if it fails, retry after a moment.

        Args:
            stream_name: go2rtc stream name (must match camera's go2rtc config).
            audio_url:   Fully-qualified URL to the audio file (must be reachable
                         by go2rtc — typically a VoxWatch audio server URL).

        Returns:
            True if go2rtc accepted the push request, False otherwise.
        """
        try:
            session = self._ensure_session()
            async with session.post(
                f"{self._base_url}/api/ffmpeg",
                params={"dst": stream_name, "file": audio_url},
            ) as resp:
                success = resp.status in (200, 201)
                if not success:
                    body = await resp.text()
                    logger.warning(
                        "go2rtc push_audio returned %d for stream %s: %s",
                        resp.status,
                        stream_name,
                        body[:200],
                    )
                return success
        except Exception as exc:
            logger.error(
                "go2rtc push_audio failed for stream %s: %s", stream_name, exc
            )
        return False

    async def probe_status(self) -> Go2rtcStatus:
        """Check go2rtc reachability and gather status in one call.

        Returns:
            Go2rtcStatus populated from streams and version endpoints.
        """
        streams = await self.get_streams()
        if streams is None:
            return Go2rtcStatus(
                reachable=False,
                error="go2rtc API is not reachable — check host/port in config",
            )

        version = await self.get_version()
        stream_count = len(streams) if isinstance(streams, dict) else None

        return Go2rtcStatus(
            reachable=True,
            version=version,
            stream_count=stream_count,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
# Reconfigured in main.py after config is loaded.

go2rtc_client: Optional[Go2rtcClient] = None
