"""
frigate_client.py — Async HTTP Client for the Frigate NVR API

Provides async methods for querying Frigate's REST API endpoints used by
the VoxWatch dashboard.

Frigate API base URL: http://<host>:<port>/api/
Notable endpoints used:
  - GET /api/version              — version string
  - GET /api/stats                — system stats including uptime and camera FPS
  - GET /api/<camera>/latest.jpg  — latest snapshot for a camera
  - GET /api/cameras              — list of configured cameras

This client uses aiohttp for non-blocking HTTP requests so it never blocks
the FastAPI event loop.

Usage:
    client = FrigateClient("localhost", 5000)
    async with client:
        version = await client.get_version()
        snapshot_bytes = await client.get_snapshot("frontdoor")
"""

import logging
from typing import Any

import aiohttp

from backend.models.status_models import FrigateStatus

logger = logging.getLogger("dashboard.frigate_client")

# Timeout for all Frigate API requests (seconds)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=5.0)


class FrigateClient:
    """Async HTTP client for the Frigate NVR API.

    Attributes:
        _base_url:  Frigate API base URL (e.g. 'http://localhost:5000').
        _session:   Shared aiohttp ClientSession (created on first use).
    """

    def __init__(self, host: str = "localhost", port: int = 5000) -> None:
        """Initialize the Frigate client.

        Args:
            host: Frigate hostname or IP address.
            port: Frigate API port (default 5000).
        """
        self._base_url = f"http://{host}:{port}"
        self._session: aiohttp.ClientSession | None = None

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def __aenter__(self) -> "FrigateClient":
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
        """Return the session, creating it lazily if needed.

        Returns:
            Active aiohttp ClientSession.
        """
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT)
        return self._session

    # ── API methods ───────────────────────────────────────────────────────────

    async def get_version(self) -> str | None:
        """Fetch the Frigate version string.

        Returns:
            Version string (e.g. '0.14.0') or None if Frigate is unreachable.
        """
        try:
            session = self._ensure_session()
            async with session.get(f"{self._base_url}/api/version") as resp:
                if resp.status == 200:
                    return (await resp.text()).strip().strip('"')
        except Exception as exc:
            logger.debug("Frigate get_version failed: %s", exc)
        return None

    async def get_stats(self) -> dict[str, Any] | None:
        """Fetch Frigate system stats.

        Returns:
            Stats dict from Frigate's /api/stats endpoint or None on failure.
            Relevant fields: service.uptime, cameras.<name>.detection_fps
        """
        try:
            session = self._ensure_session()
            async with session.get(f"{self._base_url}/api/stats") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as exc:
            logger.debug("Frigate get_stats failed: %s", exc)
        return None

    async def get_cameras(self) -> list[str] | None:
        """Get the list of camera names Frigate knows about.

        Returns:
            List of camera name strings or None on failure.
        """
        try:
            session = self._ensure_session()
            # Frigate's /api/config endpoint returns the full Frigate config
            async with session.get(f"{self._base_url}/api/config") as resp:
                if resp.status == 200:
                    config = await resp.json()
                    cameras = config.get("cameras", {})
                    return list(cameras.keys())
        except Exception as exc:
            logger.debug("Frigate get_cameras failed: %s", exc)
        return None

    async def get_snapshot(self, camera_name: str) -> bytes | None:
        """Fetch the latest snapshot image for a camera.

        Proxies the raw JPEG bytes so the dashboard can stream them to the
        browser without saving to disk.

        Args:
            camera_name: Frigate camera name (must match config).

        Returns:
            Raw JPEG image bytes or None if the request fails.
        """
        try:
            session = self._ensure_session()
            url = f"{self._base_url}/api/{camera_name}/latest.jpg"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.debug(
                    "Frigate snapshot returned %d for camera %s",
                    resp.status,
                    camera_name,
                )
        except Exception as exc:
            logger.debug(
                "Frigate get_snapshot failed for %s: %s", camera_name, exc
            )
        return None

    async def get_camera_config(self, camera_name: str) -> dict[str, Any] | None:
        """Fetch Frigate's configuration block for a single camera.

        Args:
            camera_name: Camera name as configured in Frigate.

        Returns:
            Camera config dict or None on failure.
        """
        try:
            session = self._ensure_session()
            async with session.get(f"{self._base_url}/api/config") as resp:
                if resp.status == 200:
                    cfg = await resp.json()
                    return cfg.get("cameras", {}).get(camera_name)
        except Exception as exc:
            logger.debug(
                "Frigate get_camera_config failed for %s: %s", camera_name, exc
            )
        return None

    async def probe_status(self) -> FrigateStatus:
        """Check Frigate reachability and gather status in one call.

        Returns:
            FrigateStatus populated from version and stats endpoints.
        """
        version = await self.get_version()
        if version is None:
            return FrigateStatus(
                reachable=False,
                error="Frigate API is not reachable — check host/port in config",
            )

        stats = await self.get_stats()
        cameras = await self.get_cameras()

        uptime: int | None = None
        if stats:
            uptime = stats.get("service", {}).get("uptime")

        return FrigateStatus(
            reachable=True,
            version=version,
            camera_count=len(cameras) if cameras is not None else None,
            uptime_seconds=uptime,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
# Reconfigured in main.py after config is loaded.

frigate_client: FrigateClient | None = None
