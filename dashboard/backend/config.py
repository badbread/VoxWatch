"""
config.py — Dashboard Environment Configuration

Reads all dashboard-specific settings from environment variables so the
service can be configured without touching files (12-factor style).

These settings control the dashboard backend itself — VoxWatch's own
config.yaml is managed separately via config_service.py.

Environment variables (all optional, defaults shown):
    VOXWATCH_CONFIG_PATH    Path to VoxWatch's config.yaml
                            Default: /config/config.yaml

    DATA_DIR                Directory where VoxWatch writes events.jsonl
                            and logs (informational; not actively read by
                            the dashboard)
                            Default: /data

    DASHBOARD_PORT          TCP port the dashboard backend listens on
                            Default: 33344

    DASHBOARD_HOST          Interface to bind to
                            Default: 0.0.0.0

    STATIC_DIR              Path to the compiled React SPA files to serve
                            Default: ../static (relative to this file)

    LOG_LEVEL               Python logging level for the dashboard backend
                            Default: INFO
"""

import os
import platform
import sys
from pathlib import Path


# ── VoxWatch data paths ───────────────────────────────────────────────────────

# Path to VoxWatch config.yaml — read and written by config_service.py
VOXWATCH_CONFIG_PATH: str = os.environ.get(
    "VOXWATCH_CONFIG_PATH", "/config/config.yaml"
)

# Directory where VoxWatch writes runtime data files (informational)
DATA_DIR: str = os.environ.get("DATA_DIR", "/data")

# Derived data-file paths (informational — reported in /api/system/info)
EVENTS_FILE: str = os.path.join(DATA_DIR, "events.jsonl")
LOG_FILE: str = os.path.join(DATA_DIR, "voxwatch.log")


# ── Dashboard server settings ─────────────────────────────────────────────────

# Port the FastAPI/uvicorn server listens on
DASHBOARD_PORT: int = int(os.environ.get("DASHBOARD_PORT", "33344"))

# Interface to bind — 0.0.0.0 listens on all interfaces (correct for Docker)
DASHBOARD_HOST: str = os.environ.get("DASHBOARD_HOST", "0.0.0.0")


# ── Static files ──────────────────────────────────────────────────────────────

# Path to the compiled React SPA.  The dashboard mounts this directory under /
# so the browser can load index.html, JS bundles, and assets.
# In development this directory won't exist and static serving is skipped.
_backend_dir = Path(__file__).parent          # dashboard/backend/
_default_static = _backend_dir.parent / "static"  # dashboard/static/
STATIC_DIR: str = os.environ.get("STATIC_DIR", str(_default_static))


# ── Logging ───────────────────────────────────────────────────────────────────

# Logging level for the dashboard backend (not the VoxWatch service itself)
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()


# ── System info (populated once at startup) ───────────────────────────────────

SYSTEM_HOSTNAME: str = platform.node()
SYSTEM_PLATFORM: str = platform.platform()
PYTHON_VERSION: str = sys.version.split()[0]
