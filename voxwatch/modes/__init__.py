"""
voxwatch.modes — Response Mode System

Exports the public API for loading, resolving, and rendering VoxWatch
response modes.  All other modules should import from here rather than
directly from ``loader`` or ``mode`` sub-modules.

Quick usage::

    from voxwatch.modes import (
        load_modes,
        get_active_mode,
        get_mode_prompt,
        get_mode_template,
        build_ai_vars,
        extract_ai_vars_from_dispatch_json,
        ResponseMode,
    )

    # At service startup: load all mode definitions
    modes = load_modes(config)

    # On each detection: resolve the active mode (respects per-camera overrides)
    mode = get_active_mode(config, camera_name="frontdoor")

    # Build AI variables from detection data
    ai_vars = build_ai_vars(config, camera_name="frontdoor")

    # Get the AI prompt for stage2
    prompt = get_mode_prompt(mode, "stage2", ai_vars)

    # Get a fallback template if AI fails
    fallback = get_mode_template(mode, "stage2", ai_vars)
"""

from voxwatch.modes.loader import (
    build_ai_vars,
    extract_ai_vars_from_dispatch_json,
    get_active_mode,
    get_mode_prompt,
    get_mode_template,
    load_modes,
)
from voxwatch.modes.mode import (
    BehaviorConfig,
    ResponseMode,
    StageConfig,
    ToneConfig,
    VoiceConfig,
)

__all__ = [
    # Loader functions
    "load_modes",
    "get_active_mode",
    "get_mode_prompt",
    "get_mode_template",
    "build_ai_vars",
    "extract_ai_vars_from_dispatch_json",
    # Dataclasses
    "ResponseMode",
    "StageConfig",
    "ToneConfig",
    "VoiceConfig",
    "BehaviorConfig",
]
