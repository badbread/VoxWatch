"""
routers/__init__.py — VoxWatch Dashboard API Routers Package

Each module in this package is a FastAPI APIRouter covering one area of the API:

    config_editor  — GET/PUT /api/config, POST /api/config/validate
    status         — GET /api/status
    cameras        — GET /api/cameras, /api/cameras/{name},
                        /api/cameras/{name}/snapshot
    audio          — POST /api/audio/test
    system         — GET /api/system/health, /api/system/info,
                        /api/system/frigate, /api/system/go2rtc

All routers are registered under the /api prefix in main.py.
"""
