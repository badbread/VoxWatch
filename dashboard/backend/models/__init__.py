"""
models/__init__.py — VoxWatch Dashboard Pydantic Models Package

Re-exports all model classes for convenient top-level imports:

    from backend.models import VoxWatchConfig, CameraStatus, SystemStatus

Models are split into two modules:
  - config_models.py  — Full VoxWatch config tree (mirrors config.yaml exactly)
  - status_models.py  — Live service and camera status structures
"""

from .config_models import (
    FrigateConfig,
    Go2rtcConfig,
    CameraConfig,
    ActiveHoursConfig,
    ConditionsConfig,
    AiProviderConfig,
    AiConfig,
    Stage2Config,
    Stage3Config,
    TtsConfig,
    AudioConfig,
    AudioPushConfig,
    MessagesConfig,
    LoggingConfig,
    VoxWatchConfig,
    ConfigValidationResult,
)

from .status_models import (
    CameraStatus,
    SystemStatus,
    FrigateStatus,
    Go2rtcStatus,
    SystemInfo,
    HealthStatus,
)

__all__ = [
    # Config models
    "FrigateConfig",
    "Go2rtcConfig",
    "CameraConfig",
    "ActiveHoursConfig",
    "ConditionsConfig",
    "AiProviderConfig",
    "AiConfig",
    "Stage2Config",
    "Stage3Config",
    "TtsConfig",
    "AudioConfig",
    "AudioPushConfig",
    "MessagesConfig",
    "LoggingConfig",
    "VoxWatchConfig",
    "ConfigValidationResult",
    # Status models
    "CameraStatus",
    "SystemStatus",
    "FrigateStatus",
    "Go2rtcStatus",
    "SystemInfo",
    "HealthStatus",
]
