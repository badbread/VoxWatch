"""voxwatch/ai_vision/__init__.py — Public facade for the ai_vision package.

Re-exports every name that the rest of the codebase imports from
``voxwatch.ai_vision`` so that all existing ``from voxwatch.ai_vision import X``
call sites continue to work without modification.

Confirmed import sites:
    voxwatch/voxwatch_service.py imports:
        DEFAULT_MESSAGES, _get_active_mode, analyze_snapshots, analyze_video,
        check_person_still_present, get_dispatch_initial_message,
        get_last_ai_error, get_stage2_prompt, get_stage3_prompt,
        grab_snapshots, grab_video_clip, close_session (as close_ai_session)

Internal sub-modules:
    prompts.py   — All prompt constants and prompt-building functions.
    snapshots.py — Frigate snapshot/video fetching.
    analysis.py  — AI analysis orchestration and error tracking.
    session.py   — Shared aiohttp ClientSession lifecycle.
    providers/   — Per-provider call implementations.
"""

# ── Session management ─────────────────────────────────────────────────────────
# ── AI analysis orchestration ─────────────────────────────────────────────────
from .analysis import (
    analyze_snapshots,
    analyze_video,
    check_person_still_present,
    get_last_ai_error,
)

# ── Prompt constants and builders ──────────────────────────────────────────────
from .prompts import (
    DEFAULT_MESSAGES,
    DISPATCH_STAGE2_PROMPT,
    DISPATCH_STAGE3_PROMPT,
    PERSONAS,
    RESPONSE_MODES,
    STAGE2_PROMPT,
    STAGE3_PROMPT,
    _get_active_mode,
    get_dispatch_initial_message,
    get_stage2_prompt,
    get_stage3_prompt,
)

# ── Provider internals (available for testing / advanced callers) ──────────────
from .providers import (
    _call_anthropic,
    _call_gemini_images,
    _call_gemini_video,
    _call_ollama,
    _call_openai_compat,
    _dispatch_snapshot_call,
)
from .session import close_session, init_session

# ── Frigate data retrieval ─────────────────────────────────────────────────────
from .snapshots import grab_snapshots, grab_video_clip

__all__ = [
    # Session
    "init_session",
    "close_session",
    # Prompt constants
    "STAGE2_PROMPT",
    "STAGE3_PROMPT",
    "DISPATCH_STAGE2_PROMPT",
    "DISPATCH_STAGE3_PROMPT",
    "RESPONSE_MODES",
    "PERSONAS",
    "DEFAULT_MESSAGES",
    # Prompt builders
    "_get_active_mode",
    "get_dispatch_initial_message",
    "get_stage2_prompt",
    "get_stage3_prompt",
    # Frigate fetching
    "grab_snapshots",
    "grab_video_clip",
    # Analysis
    "analyze_snapshots",
    "analyze_video",
    "check_person_still_present",
    "get_last_ai_error",
    # Provider internals
    "_call_anthropic",
    "_call_gemini_images",
    "_call_gemini_video",
    "_call_ollama",
    "_call_openai_compat",
    "_dispatch_snapshot_call",
]
