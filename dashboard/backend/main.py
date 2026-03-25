"""
main.py — VoxWatch Dashboard FastAPI Application Entry Point

This module creates the FastAPI app, configures middleware, registers all
API routers, mounts the React SPA static files, and manages the lifespan
of the aiohttp client connections.

Architecture overview:
  - FastAPI app with a lifespan context manager handles startup/shutdown
  - CORS origins are configured via CORS_ORIGINS env var (default: open in dev)
  - All API endpoints are prefixed with /api
  - Static files from ../static/ serve the compiled React SPA (production)
  - Background services started in lifespan:
      * aiohttp clients for Frigate and go2rtc

Running directly:
    python -m backend.main
    uvicorn backend.main:app --host 0.0.0.0 --port 33344 --reload

Environment variables:
    VOXWATCH_CONFIG_PATH  — Path to config.yaml (default: /config/config.yaml)
    DATA_DIR              — Data directory (default: /data)
    DASHBOARD_PORT        — Server port (default: 33344)
    DASHBOARD_HOST        — Bind address (default: 0.0.0.0)
    STATIC_DIR            — React SPA directory (default: ../static)
    LOG_LEVEL             — Log level (default: INFO)
    DASHBOARD_API_KEY     — Bearer token required for all /api/* routes.
                            If unset, authentication is skipped (dev mode).
    CORS_ORIGINS          — Comma-separated list of allowed CORS origins.
                            Defaults to ["*"] (open) when unset.
                            Example: "https://dash.example.com,https://admin.example.com"
    ENABLE_DOCS           — Set to "false" (case-insensitive) to disable the
                            interactive OpenAPI docs (/api/docs, /api/redoc) and
                            the OpenAPI schema endpoint (/api/openapi.json).
                            Defaults to "true" for development convenience.
                            Always set to "false" in production deployments.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiohttp
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from backend import config as cfg
from backend.routers import (
    audio,
    cameras,
    config_editor,
    status,
    system,
    wizard,
)
from backend.services import frigate_client as fc_module
from backend.services import go2rtc_client as g2rtc_module
from backend.services.config_service import config_service

# ── Logging setup ─────────────────────────────────────────────────────────────
# Configure logging before anything else so all modules log correctly.

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dashboard.main")


# ── API key authentication ────────────────────────────────────────────────────
# Read the API key from the environment at module load time.
# If DASHBOARD_API_KEY is not set, authentication is disabled so the dashboard
# is still accessible during local development without any configuration.
#
# Security note: the key is intentionally read once here rather than on every
# request to avoid repeated os.environ lookups and to make the "no auth"
# decision explicit and visible at startup.

_API_KEY: Optional[str] = os.environ.get("DASHBOARD_API_KEY") or None

# HTTPBearer extracts the token from the "Authorization: Bearer <token>" header.
# auto_error=False means it returns None instead of raising 403 when the header
# is absent — we handle the missing-header case ourselves so we can return a
# more informative 401 (Unauthorized) with a WWW-Authenticate header.
_bearer_scheme = HTTPBearer(auto_error=False)


def _require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> None:
    """FastAPI dependency that enforces Bearer token authentication on /api/* routes.

    Behaviour:
      - If DASHBOARD_API_KEY env var is NOT set: auth is skipped entirely (dev
        mode). A one-time warning is logged at startup but requests pass through.
      - If DASHBOARD_API_KEY IS set: the request must carry an
        ``Authorization: Bearer <key>`` header whose token matches the configured
        key exactly (constant-time comparison to resist timing attacks).

    Args:
        credentials: Injected by FastAPI from the Authorization header, or None
                     if the header is absent.

    Raises:
        HTTPException 401: If auth is enabled and the header is missing or the
                           token does not match.
    """
    # Dev mode — no key configured, pass all requests through.
    if _API_KEY is None:
        return

    # Security: use hmac.compare_digest for constant-time string comparison.
    # A plain == comparison leaks timing information about how many characters
    # matched, which could be exploited to brute-force the key one character at a time.
    import hmac

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Authorization: Bearer <api-key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_matches = hmac.compare_digest(
        credentials.credentials.encode("utf-8"),
        _API_KEY.encode("utf-8"),
    )
    if not token_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── CORS configuration ────────────────────────────────────────────────────────
# CORS_ORIGINS is a comma-separated list of allowed origins.
# Defaults to ["*"] (open) for development convenience.
#
# Security note: allow_credentials=True cannot be combined with allow_origins=["*"]
# — browsers reject such responses. We therefore only enable credentials when the
# operator has explicitly configured specific origins.

_cors_origins_raw: str = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_origins_raw:
    # Specific origins configured — split and strip whitespace around each one.
    _cors_origins: list[str] = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    # Only allow credentials (cookies, Authorization headers) when origins are
    # restricted. Sending credentials with wildcard origins is rejected by browsers
    # per the CORS spec (and is a security risk regardless).
    _cors_allow_credentials: bool = True
else:
    # No origins configured — open wildcard mode for development.
    _cors_origins = ["*"]
    # Must be False with wildcard origins; browsers enforce this.
    _cors_allow_credentials = False


# ── Lifespan context manager ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the lifecycle of aiohttp clients for Frigate and go2rtc.

    Startup sequence:
      1. Log auth/CORS posture warnings for operators
      2. Load VoxWatch config.yaml to get connection settings
      3. Create aiohttp clients for Frigate and go2rtc

    Shutdown sequence (reverse order):
      4. Close aiohttp clients

    All services are started/stopped even if config.yaml is missing so the
    dashboard can still serve the UI and show a configuration error.
    """
    logger.info("VoxWatch Dashboard starting up")

    # ── 0. Security posture warnings ─────────────────────────────────────────
    # Log a clear warning if authentication is disabled so operators running in
    # production notice immediately in the container logs.
    if _API_KEY is None:
        logger.warning(
            "SECURITY WARNING: DASHBOARD_API_KEY is not set. "
            "The /api/* endpoints are accessible without authentication. "
            "Set DASHBOARD_API_KEY in the environment for production deployments."
        )
    else:
        logger.info("API key authentication enabled for all /api/* routes.")

    if _cors_origins == ["*"]:
        logger.warning(
            "SECURITY WARNING: CORS_ORIGINS is not set. "
            "All origins are permitted (wildcard). "
            "Set CORS_ORIGINS to a comma-separated list of allowed origins for "
            "production deployments (e.g. 'https://dash.example.com')."
        )
    else:
        logger.info("CORS restricted to origins: %s", _cors_origins)

    if _docs_enabled:
        logger.warning(
            "SECURITY WARNING: OpenAPI docs are enabled (ENABLE_DOCS=true). "
            "The API schema is publicly accessible at /api/openapi.json. "
            "Set ENABLE_DOCS=false in production to suppress the docs endpoints."
        )
    else:
        logger.info("OpenAPI docs disabled (ENABLE_DOCS=false).")

    # ── 1. Load config ────────────────────────────────────────────────────────
    voxwatch_config = {}
    try:
        voxwatch_config = await config_service.get_config()
        logger.info(
            "Loaded config from %s — cameras: %s",
            cfg.VOXWATCH_CONFIG_PATH,
            list(voxwatch_config.get("cameras", {}).keys()),
        )
    except FileNotFoundError:
        logger.warning(
            "config.yaml not found at %s — dashboard will run in config-only mode",
            cfg.VOXWATCH_CONFIG_PATH,
        )
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)

    # ── 2. Create aiohttp clients ─────────────────────────────────────────────
    frigate_cfg = voxwatch_config.get("frigate", {})
    go2rtc_cfg = voxwatch_config.get("go2rtc", {})

    fc_module.frigate_client = fc_module.FrigateClient(
        host=frigate_cfg.get("host", "localhost"),
        port=int(frigate_cfg.get("port", 5000)),
    )
    # Eagerly create the session (lazy creation also works but this surfaces
    # connection errors at startup instead of on first request)
    fc_module.frigate_client._session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5.0)
    )

    g2rtc_module.go2rtc_client = g2rtc_module.Go2rtcClient(
        host=go2rtc_cfg.get("host", "localhost"),
        api_port=int(go2rtc_cfg.get("api_port", 1984)),
    )
    g2rtc_module.go2rtc_client._session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5.0)
    )

    logger.info(
        "Frigate client: %s:%s | go2rtc client: %s:%s",
        frigate_cfg.get("host", "localhost"),
        frigate_cfg.get("port", 5000),
        go2rtc_cfg.get("host", "localhost"),
        go2rtc_cfg.get("api_port", 1984),
    )

    logger.info(
        "VoxWatch Dashboard ready — listening on http://%s:%d",
        cfg.DASHBOARD_HOST,
        cfg.DASHBOARD_PORT,
    )

    # ── Hand control to FastAPI ───────────────────────────────────────────────
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("VoxWatch Dashboard shutting down")

    # Close aiohttp sessions
    if fc_module.frigate_client:
        await fc_module.frigate_client.close()
    if g2rtc_module.go2rtc_client:
        await g2rtc_module.go2rtc_client.close()

    logger.info("VoxWatch Dashboard shutdown complete")


# ── OpenAPI docs toggle ───────────────────────────────────────────────────────
# ENABLE_DOCS defaults to "true" so the interactive Swagger UI and ReDoc pages
# are available during development without any configuration.
#
# Security note: the OpenAPI schema and UI expose the full API surface —
# endpoint paths, parameter names, and response shapes — to anyone who can reach
# the server.  In production this information should not be publicly accessible.
# Set ENABLE_DOCS=false in the Docker environment to suppress all three URLs:
#   /api/docs         — Swagger UI
#   /api/redoc        — ReDoc UI
#   /api/openapi.json — raw OpenAPI schema used by both UIs
#
# When docs are disabled, FastAPI returns 404 for all three URLs; the API
# itself continues to function normally.

_enable_docs_raw: str = os.environ.get("ENABLE_DOCS", "true").strip().lower()
# Treat any value other than an explicit falsy word as "enabled" so the default
# is always safe for development (nothing breaks if the variable is unset).
_docs_enabled: bool = _enable_docs_raw not in ("false", "0", "no", "off")

if _docs_enabled:
    _docs_url: Optional[str] = "/api/docs"
    _redoc_url: Optional[str] = "/api/redoc"
    _openapi_url: Optional[str] = "/api/openapi.json"
else:
    # Setting these to None tells FastAPI not to register the routes at all.
    _docs_url = None
    _redoc_url = None
    _openapi_url = None


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="VoxWatch Dashboard API",
    description=(
        "REST API backend for the VoxWatch AI security deterrent dashboard. "
        "Provides configuration management, camera status, "
        "audio push controls, and system health monitoring."
    ),
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    lifespan=lifespan,
)


# ── Middleware ────────────────────────────────────────────────────────────────

# CORS middleware uses the origins and credentials policy derived above.
# See _cors_origins and _cors_allow_credentials at the top of this file for
# the logic that determines these values from the CORS_ORIGINS env var.
#
# Security note: this middleware is NOT used to enforce authentication — it only
# controls which browser origins may read the responses.  API key enforcement is
# handled separately via the _require_api_key dependency on each router.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # allow_credentials must be False when allow_origins=["*"].
    # It is True only when specific origins are configured (set above).
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API Routers ───────────────────────────────────────────────────────────────

# Each router is registered under /api to keep API and static routes separate.
# The _require_api_key dependency is added here — at include_router() time —
# rather than as global middleware.  This ensures that static file serving
# (the React SPA) is never subject to the API key check: only /api/* routes
# require authentication.  If the key is not configured, _require_api_key is
# a no-op (see its docstring).
api_prefix = "/api"
api_auth = Depends(_require_api_key)

app.include_router(config_editor.router, prefix=api_prefix, dependencies=[api_auth])
app.include_router(status.router, prefix=api_prefix, dependencies=[api_auth])
app.include_router(cameras.router, prefix=api_prefix, dependencies=[api_auth])
app.include_router(audio.router, prefix=api_prefix, dependencies=[api_auth])
app.include_router(system.router, prefix=api_prefix, dependencies=[api_auth])
app.include_router(wizard.router, prefix=api_prefix, dependencies=[api_auth])


# ── Static files (React SPA) ──────────────────────────────────────────────────
# Mounted AFTER API routers so /api/* routes take priority over the catch-all SPA handler.
# No authentication dependency is added here — the SPA assets are public HTML/JS/CSS
# and must be loadable by the browser before it can present a login prompt.

_static_dir = Path(cfg.STATIC_DIR).resolve()
if _static_dir.exists() and _static_dir.is_dir():
    from fastapi.responses import FileResponse

    # Serve static assets (JS, CSS, images) from the Vite build output
    app.mount(
        "/assets",
        StaticFiles(directory=str(_static_dir / "assets")),
        name="static-assets",
    )
    # Serve other static files (favicon, branding) at root level
    app.mount(
        "/branding",
        StaticFiles(directory=str(_static_dir / "branding")),
        name="static-branding",
    )

    # SPA catch-all: any route not matching /api/* or a static file
    # serves index.html so React Router handles client-side navigation.
    # This fixes page refresh on routes like /cameras, /config, etc.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve the React SPA index.html for all non-API routes.

        Security note: path traversal is prevented by calling .resolve() and
        checking that the resolved path remains within _static_dir before
        serving any file.  Without this check a crafted path like
        '../../etc/passwd' could escape the static directory.
        """
        # Resolve the candidate path to its absolute, canonical form.
        # Path.resolve() collapses ".." components, symlinks, etc.
        candidate = (_static_dir / full_path).resolve()

        # Security: reject any path that resolves outside the static directory.
        # str(candidate).startswith(str(_static_dir)) is not used here because
        # it can be fooled by directory names that are prefixes of each other
        # (e.g. /static-dir vs /static-dir-evil).  is_relative_to() is exact.
        try:
            candidate.relative_to(_static_dir)
        except ValueError:
            # Path escapes the static root — return 404 rather than an error
            # that might leak information about the filesystem layout.
            return FileResponse(str(_static_dir / "index.html"), status_code=404)

        # Serve the file if it exists and is a regular file within the static dir.
        if candidate.is_file():
            return FileResponse(str(candidate))

        # Otherwise serve index.html for client-side routing (React Router).
        return FileResponse(str(_static_dir / "index.html"))

    logger.info("Serving React SPA from %s", _static_dir)
else:
    logger.info(
        "Static directory %s not found — running in API-only mode "
        "(React SPA not served)",
        _static_dir,
    )
    # Add a root redirect to the API docs in development
    from fastapi.responses import RedirectResponse

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        """Redirect root to API docs when no static files are present."""
        return RedirectResponse(url="/api/docs")


# ── Direct execution ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=cfg.DASHBOARD_HOST,
        port=cfg.DASHBOARD_PORT,
        reload=False,
        log_level=cfg.LOG_LEVEL.lower(),
        # access_log produces one line per request — useful for debugging
        access_log=True,
    )
