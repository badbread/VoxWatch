"""
services/__init__.py — VoxWatch Dashboard Services Package

This package contains the backend service layer that handles all I/O:
reading/writing config, querying Frigate and go2rtc.

Modules:
    config_service  — Read/write/validate config.yaml with secret masking
    frigate_client  — aiohttp-based async HTTP client for the Frigate NVR API
    go2rtc_client   — aiohttp-based async HTTP client for the go2rtc API
"""
