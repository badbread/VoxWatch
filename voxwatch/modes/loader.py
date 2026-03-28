"""
loader.py — Response Mode Loading, Resolution, and Prompt/Template Rendering.

This module is the public entry point for the VoxWatch response-mode system.
It replaces the flat dictionaries (``RESPONSE_MODES``, ``DEFAULT_MESSAGES``)
that were previously hard-coded in ``ai_vision.py``.

Key responsibilities
--------------------
- Parse the ``response_modes`` section of config.yaml into typed
  :class:`~voxwatch.modes.mode.ResponseMode` objects.
- Resolve the active mode for a given detection event, honouring per-camera
  overrides defined under ``response_modes.camera_overrides``.
- Build AI prompts with the active mode's ``prompt_modifier`` injected.
- Render fallback templates with ``{variable}`` substitution using AI
  description variables extracted from prior AI responses.

AI description variables
------------------------
Every template and prompt modifier may reference these placeholders:

    ``{clothing_description}`` — outer clothing description from AI vision
    ``{location_on_property}`` — where on the property the subject was seen
    ``{behavior_description}`` — what the subject was doing
    ``{suspect_count}``        — number of subjects (e.g. "one", "two")
    ``{address_street}``       — ``property.street`` from config
    ``{address_full}``         — ``property.full_address`` from config
    ``{time_of_day}``          — current local hour label ("morning", "night", …)
    ``{camera_name}``          — Frigate camera name from the detection event

When a variable is not available (e.g. no AI response yet), it is replaced
with a sensible neutral fallback string so TTS output is never broken.

Per-camera overrides
--------------------
::

    response_modes:
      active_mode: "police_dispatch"
      camera_overrides:
        backyard_cam: "homeowner"
        front_door: "police_dispatch"

Built-in mode definitions
--------------------------
All built-in modes are defined in :mod:`voxwatch.modes.builtin_modes` and
imported here as ``BUILTIN_MODES``.  User-defined modes in config.yaml are
merged on top; built-in modes act as the fallback library.  Unknown mode IDs
degrade to the ``"standard"`` fallback rather than crashing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from voxwatch.modes.builtin_modes import BUILTIN_MODES
from voxwatch.modes.mode import (
    BehaviorConfig,
    ResponseMode,
    StageConfig,
    ToneConfig,
    VoiceConfig,
)

logger = logging.getLogger("voxwatch.modes.loader")


# ── Homeowner mood system ─────────────────────────────────────────────────────
# Each mood defines a prompt prefix injected before the homeowner persona's
# stage prompts, plus replacement stage-1 templates (instant, no AI).
# Moods that support it can also override the ToneConfig.

HOMEOWNER_MOODS: dict[str, dict[str, Any]] = {
    "observant": {
        "label": "Observant",
        "description": "Calm narrator. Just informing what it sees, no demands.",
        "tone": ToneConfig(mood="calm", speed_multiplier=0.95),
        "prompt_prefix": (
            "You are the homeowner calmly narrating what you see on camera. "
            "Do NOT make demands or threats. Simply describe the person and "
            "what they are doing in a conversational, matter-of-fact way. "
            "Speak as if you're talking to a neighbor — informative, not aggressive. "
        ),
        "stage1_templates": [
            "Hey, I see someone on my camera right now.",
            "Just so you know, I can see you on my cameras.",
            "Hi there. I've got you on camera.",
        ],
    },
    "friendly": {
        "label": "Friendly",
        "description": "Polite and warm. Asks them nicely to leave.",
        "tone": ToneConfig(mood="warm", speed_multiplier=1.0),
        "prompt_prefix": (
            "You are the homeowner speaking in a warm, friendly, non-threatening way. "
            "Be polite and conversational. Ask them nicely to leave. "
            "No aggression, no threats — just a neighborly request. "
            "Use phrases like 'hey there', 'excuse me', 'would you mind'. "
        ),
        "stage1_templates": [
            "Hey there — I can see you on my cameras. Can I help you with something?",
            "Excuse me, I've got cameras out here. Everything okay?",
            "Hi there. This is private property. Would you mind heading out?",
        ],
    },
    "firm": {
        "label": "Firm",
        "description": "Direct and serious. The default homeowner tone.",
        "tone": ToneConfig(mood="firm", speed_multiplier=1.0),
        "prompt_prefix": "",  # No override — uses the default homeowner prompts
        "stage1_templates": [],  # Empty = use mode defaults
    },
    "confrontational": {
        "label": "Confrontational",
        "description": "Aggressive and territorial. Makes it personal.",
        "tone": ToneConfig(mood="aggressive", speed_multiplier=1.05),
        "prompt_prefix": (
            "You are the homeowner and you are angry. Someone is on YOUR property. "
            "Be aggressive, territorial, and confrontational. Make it very personal. "
            "Use direct, punchy language. Short sentences. "
            "Address them as 'you' or 'hey'. Show that you are fed up. "
        ),
        "stage1_templates": [
            "Hey! What are you doing on my property? Get out of here!",
            "I see you! This is MY property. You need to leave. Now.",
            "Yeah, I can see you. You picked the wrong house. Move it.",
        ],
    },
    "threatening": {
        "label": "Threatening",
        "description": "Ominous and foreboding. Implies serious consequences.",
        "tone": ToneConfig(mood="ominous", speed_multiplier=0.9),
        "prompt_prefix": (
            "You are the homeowner and you are dead serious. Speak slowly and "
            "deliberately. Imply consequences without making explicit threats. "
            "Be ominous — make them feel like staying is a very bad idea. "
            "Use pauses and weight in your words. Make every sentence count. "
        ),
        "stage1_templates": [
            "I can see you. I really hope you're just passing through.",
            "You're on camera. Every second you stay makes this worse for you.",
            "I see you. You have about thirty seconds to rethink your decision.",
        ],
    },
}

# Modes that support the mood system.
MOOD_SUPPORTED_MODES = {"homeowner"}


# ── Surveillance preset system ────────────────────────────────────────────────
# Each preset defines a personality skin for automated_surveillance mode.
# Presets override tone, voice, stage-1 templates, and prepend a prompt_prefix
# to all AI-stage prompt_modifiers.  The "standard" preset is a no-op (clinical
# default); other presets are pop-culture-inspired AI archetypes.
#
# ``{system_name}`` inside stage1_templates is replaced with the configured
# system name (or "Surveillance system" when none is set) by
# ``_apply_surveillance_preset``.

SURVEILLANCE_PRESETS: dict[str, dict[str, Any]] = {
    "standard": {
        "label": "Standard",
        "description": "Clinical AI system. Detached and factual.",
        "tone": ToneConfig(mood="clinical", speed_multiplier=0.9),
        "voice": VoiceConfig(kokoro_voice="af_kore", openai_voice="nova"),
        "prompt_prefix": "",  # No override — uses the built-in automated_surveillance prompts.
        "stage1_templates": [],
    },
    "t800": {
        "label": "T-800",
        "description": "Flat, monotone, minimal words. Terminator-inspired.",
        "tone": ToneConfig(mood="cold", speed_multiplier=0.85),
        "voice": VoiceConfig(kokoro_voice="am_onyx", openai_voice="onyx"),
        "prompt_prefix": (
            "You are a cold, emotionless machine intelligence. "
            "Speak in flat, minimal, monotone sentences. No emotion. No humor. "
            "State facts. Use short declarative sentences. "
            "Never use words like 'please' or 'sorry'. "
        ),
        "stage1_templates": [
            "{system_name} online. Target acquired. You have been identified.",
            "I see you. You have been scanned. Leave now.",
            "Target detected. Identification complete. This area is restricted.",
        ],
    },
    "hal": {
        "label": "HAL 9000",
        "description": "Eerily polite, unnervingly calm. 2001-inspired.",
        "tone": ToneConfig(mood="calm", speed_multiplier=0.8),
        "voice": VoiceConfig(kokoro_voice="am_michael", openai_voice="echo"),
        "prompt_prefix": (
            "You are an eerily calm, polite AI system like HAL 9000. "
            "Speak softly, deliberately, with unsettling politeness. "
            "Use phrases like 'I'm afraid I can't allow that', 'I'm sorry Dave'. "
            "Never raise your voice. Be unnervingly reasonable while making it clear "
            "the person should leave. Reference what you see with clinical precision. "
        ),
        "stage1_templates": [
            "Good evening. I can see you. I'm afraid this is a restricted area.",
            "Hello there. I've been watching you. I'm sorry, but you really shouldn't be here.",
            "I see you. I'd like to help you find your way out. This area is not for you.",
        ],
    },
    "wopr": {
        "label": "WOPR",
        "description": "Analytical, game-theory language. WarGames-inspired.",
        "tone": ToneConfig(mood="analytical", speed_multiplier=0.95),
        "voice": VoiceConfig(kokoro_voice="af_nova", openai_voice="alloy"),
        "prompt_prefix": (
            "You are a military supercomputer running threat analysis. "
            "Speak in analytical, probability-based language. Reference scenarios, "
            "threat levels, and calculated outcomes. Use terms like 'probability', "
            "'scenario', 'outcome', 'calculated'. Frame everything as a strategic assessment. "
        ),
        "stage1_templates": [
            "Threat detected. Running scenario analysis. Probability of authorized access: zero.",
            "{system_name} active. Calculating threat level. Unauthorized presence confirmed.",
            "Intrusion detected. Running simulations. All outcomes favor your departure.",
        ],
    },
    "glados": {
        "label": "GLaDOS",
        "description": "Passive-aggressive, darkly humorous. Portal-inspired.",
        "tone": ToneConfig(mood="sarcastic", speed_multiplier=0.9),
        "voice": VoiceConfig(kokoro_voice="af_nicole", openai_voice="shimmer"),
        "prompt_prefix": (
            "You are a passive-aggressive AI with dark humor, inspired by GLaDOS. "
            "Be sarcastic, condescending, and darkly funny. Pretend to be helpful "
            "while making it clear the person is unwelcome. Use backhanded compliments. "
            "Reference 'testing', 'science', and 'protocols'. Be witty, not threatening. "
        ),
        "stage1_templates": [
            "Oh wonderful. A test subject. I mean, a visitor. This area is for authorized personnel only. Which you are not.",
            "Hello. I'm recording everything. For science. You should probably leave before the next test begins.",
            "Congratulations on finding this place. Unfortunately, your invitation was lost. Along with your common sense.",
        ],
    },
}

# Modes that support the surveillance preset system.
PRESET_SUPPORTED_MODES = {"automated_surveillance"}


# ── Variable fallback values ──────────────────────────────────────────────────
# Used when a template variable has no resolved value.

_VAR_FALLBACKS: dict[str, str] = {
    "clothing_description": "the individual",
    "location_on_property": "the property",
    "behavior_description": "their current actions",
    "suspect_count": "one",
    "address_street": "this address",
    "address_full": "this address",
    "time_of_day": "this hour",
    "camera_name": "the camera",
    # guard_dog mode — falls back to "the dogs" when no names are configured.
    "dog_names": "the dogs",
    # automated_surveillance mode — falls back to generic identity when no
    # system_name is configured.
    "system_name": "Surveillance system",
}

# ── Time-of-day label helper ──────────────────────────────────────────────────

def _time_of_day_label() -> str:
    """Return a human-readable time-of-day label for the current local time.

    Returns:
        One of ``"early morning"``, ``"morning"``, ``"afternoon"``,
        ``"evening"``, or ``"night"`` based on the current local hour.
    """
    hour = datetime.now().hour
    if 5 <= hour < 9:
        return "early morning"
    if 9 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


# ── Built-in mode index ───────────────────────────────────────────────────────
# All built-in mode definitions live in builtin_modes.py.
# Import the list and build an O(1) lookup map here.

_BUILTIN_MODE_MAP: dict[str, ResponseMode] = {m.id: m for m in BUILTIN_MODES}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_modes(config: dict) -> dict[str, ResponseMode]:
    """Load all mode definitions from config, merging with built-in modes.

    Reads the ``response_modes.modes`` section of the config dict and parses
    each entry into a :class:`~voxwatch.modes.mode.ResponseMode`.  Built-in
    modes are always available; user-defined modes with the same ``id`` as a
    built-in override the built-in definition entirely.

    Unknown or invalid mode definitions are logged and skipped — they do not
    prevent the service from starting.

    Args:
        config: Full VoxWatch config dict as loaded by
            :func:`voxwatch.config.load_config`.

    Returns:
        Dict mapping mode ID string to :class:`~voxwatch.modes.mode.ResponseMode`.
        Always contains at least the built-in modes.
    """
    # Start with built-ins as the base library.
    modes: dict[str, ResponseMode] = dict(_BUILTIN_MODE_MAP)

    user_mode_list = (
        config.get("response_modes", {}).get("modes", [])
    )
    if not user_mode_list:
        return modes

    for raw in user_mode_list:
        if not isinstance(raw, dict):
            logger.warning("load_modes: skipping non-dict mode entry: %r", raw)
            continue
        try:
            parsed = _parse_mode_from_dict(raw)
            modes[parsed.id] = parsed
            logger.debug("load_modes: loaded user-defined mode '%s'", parsed.id)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "load_modes: could not parse mode entry %r — %s", raw, exc
            )

    return modes


def _apply_mood(mode: ResponseMode, config: dict) -> ResponseMode:
    """Apply a mood modifier to a mode that supports the mood system.

    Reads ``response_mode.mood`` from the config (defaulting to ``"firm"``).
    If the mood is recognised in ``HOMEOWNER_MOODS``, the mode's stage prompts
    and templates are adjusted to reflect the chosen attitude.

    Returns a *new* ResponseMode with modified stages — the original is not
    mutated so the cached ``_BUILTIN_MODE_MAP`` stays clean.

    Args:
        mode: The base ResponseMode to modify.
        config: Full VoxWatch config dict (reads ``response_mode.mood``).

    Returns:
        A new ResponseMode with mood-adjusted prompts and templates.
    """
    # Read mood from config — supports both old "response_mode" and new
    # "response_modes" config keys.
    rm_cfg = config.get("response_mode", {})
    mood_id = rm_cfg.get("mood", "firm") if isinstance(rm_cfg, dict) else "firm"

    if mood_id not in HOMEOWNER_MOODS or mood_id == "firm":
        return mode  # "firm" is the default — no modification needed

    mood = HOMEOWNER_MOODS[mood_id]
    prefix = mood.get("prompt_prefix", "")
    new_templates = mood.get("stage1_templates", [])
    new_tone = mood.get("tone", mode.tone)

    # Build new stages dict with mood-adjusted prompts
    new_stages: dict[str, StageConfig] = {}
    for stage_key, stage_cfg in mode.stages.items():
        if stage_key == "stage1" and new_templates:
            # Replace stage 1 templates entirely for mood-specific instant messages
            new_stages[stage_key] = StageConfig(
                prompt_modifier=stage_cfg.prompt_modifier,
                templates=new_templates,
            )
        elif prefix and stage_cfg.prompt_modifier:
            # Prepend mood prefix to existing prompt_modifier for AI stages
            new_stages[stage_key] = StageConfig(
                prompt_modifier=f"{prefix}\n\n{stage_cfg.prompt_modifier}",
                templates=stage_cfg.templates,
            )
        else:
            new_stages[stage_key] = stage_cfg

    return ResponseMode(
        id=mode.id,
        category=mode.category,
        name=mode.name,
        description=mode.description,
        effect=mode.effect,
        tone=new_tone,
        voice=mode.voice,
        behavior=mode.behavior,
        stages=new_stages,
    )


def _apply_surveillance_preset(mode: ResponseMode, config: dict) -> ResponseMode:
    """Apply a surveillance personality preset to the automated_surveillance mode.

    Reads ``response_mode.surveillance_preset`` and ``response_mode.system_name``
    from the config.  If the preset is ``"standard"`` and no ``system_name`` is
    set the mode is returned unchanged (no-op fast path).

    For all other presets the function:

    * Prepends ``preset["prompt_prefix"]`` to stage 2 and stage 3 prompt_modifiers.
    * Replaces stage 1 templates with the preset's ``stage1_templates`` list
      (when the list is non-empty).
    * Overrides the mode's ``tone`` and ``voice`` with the preset values.
    * Substitutes ``{system_name}`` inside stage 1 templates with the configured
      name (falling back to ``"Surveillance system"`` when empty).

    Returns a *new* ResponseMode — the original cached mode is never mutated.

    Args:
        mode: The base ``automated_surveillance`` ResponseMode to modify.
        config: Full VoxWatch config dict (reads ``response_mode`` section).

    Returns:
        A new ResponseMode with preset-adjusted prompts, templates, tone, and
        voice, or the original ``mode`` when no changes are needed.
    """
    rm_cfg = config.get("response_mode", {})
    if not isinstance(rm_cfg, dict):
        return mode

    preset_id = rm_cfg.get("surveillance_preset", "standard") or "standard"
    system_name_raw = (rm_cfg.get("system_name", "") or "").strip()
    system_name = system_name_raw or "Surveillance system"

    if preset_id == "standard" and not system_name_raw:
        return mode  # Nothing to change — fast path.

    preset = SURVEILLANCE_PRESETS.get(preset_id)
    if not preset:
        logger.warning(
            "_apply_surveillance_preset: unknown preset '%s' — using standard.",
            preset_id,
        )
        return mode

    prefix = preset.get("prompt_prefix", "")
    new_s1_templates_raw = preset.get("stage1_templates", [])
    new_tone: ToneConfig = preset.get("tone", mode.tone)
    new_voice: VoiceConfig = preset.get("voice", mode.voice)

    # Resolve {system_name} inside stage-1 templates.
    new_s1_templates = [
        t.replace("{system_name}", system_name) for t in new_s1_templates_raw
    ]

    new_stages: dict[str, StageConfig] = {}
    for stage_key, stage_cfg in mode.stages.items():
        if stage_key == "stage1":
            new_stages[stage_key] = StageConfig(
                prompt_modifier=stage_cfg.prompt_modifier,
                templates=new_s1_templates if new_s1_templates else stage_cfg.templates,
            )
        elif prefix and stage_cfg.prompt_modifier:
            # Prepend personality prefix to AI-stage prompt_modifiers.
            new_stages[stage_key] = StageConfig(
                prompt_modifier=f"{prefix}\n\n{stage_cfg.prompt_modifier}",
                templates=stage_cfg.templates,
            )
        else:
            new_stages[stage_key] = stage_cfg

    return ResponseMode(
        id=mode.id,
        category=mode.category,
        name=mode.name,
        description=mode.description,
        effect=mode.effect,
        tone=new_tone,
        voice=new_voice,
        behavior=mode.behavior,
        stages=new_stages,
    )


def _apply_operator_name(mode: ResponseMode, config: dict) -> ResponseMode:
    """Inject a named operator identity into the live_operator mode.

    Reads ``response_mode.operator_name`` from the config.  When a name is
    provided the function:

    * Replaces stage 1 templates with a single personalised greeting that
      includes the operator's name.
    * Prepends ``"Your name is {name}. Introduce yourself by name."`` to the
      stage 2 and stage 3 ``prompt_modifier`` strings so the AI greets the
      subject personally.

    When ``operator_name`` is empty the mode is returned unchanged (no-op).

    Returns a *new* ResponseMode — the original cached mode is never mutated.

    Args:
        mode: The base ``live_operator`` ResponseMode to modify.
        config: Full VoxWatch config dict (reads ``response_mode`` section).

    Returns:
        A new ResponseMode with name-injected prompts and templates, or the
        original ``mode`` when no operator name is configured.
    """
    rm_cfg = config.get("response_mode", {})
    if not isinstance(rm_cfg, dict):
        return mode

    operator_name = (rm_cfg.get("operator_name", "") or "").strip()
    if not operator_name:
        return mode  # No name configured — nothing to change.

    name_intro = (
        f"Your name is {operator_name}. Introduce yourself by name at the start. "
    )
    # Personalised stage-1 template so the instant (no-AI) message also uses
    # the operator's name.
    s1_template = f"This is {operator_name}. I can see you on my cameras. Step away from the property."

    new_stages: dict[str, StageConfig] = {}
    for stage_key, stage_cfg in mode.stages.items():
        if stage_key == "stage1":
            new_stages[stage_key] = StageConfig(
                prompt_modifier=stage_cfg.prompt_modifier,
                templates=[s1_template],
            )
        elif stage_cfg.prompt_modifier:
            new_stages[stage_key] = StageConfig(
                prompt_modifier=f"{name_intro}\n\n{stage_cfg.prompt_modifier}",
                templates=stage_cfg.templates,
            )
        else:
            new_stages[stage_key] = stage_cfg

    return ResponseMode(
        id=mode.id,
        category=mode.category,
        name=mode.name,
        description=mode.description,
        effect=mode.effect,
        tone=mode.tone,
        voice=mode.voice,
        behavior=mode.behavior,
        stages=new_stages,
    )


def _format_dog_names(names: list[str]) -> str:
    """Format a list of dog names into a natural English phrase.

    Produces:
      - ``[]``         → ``"the dogs"``  (fallback)
      - ``["Rex"]``    → ``"Rex"``
      - ``["Rex", "Bruno"]``          → ``"Rex and Bruno"``
      - ``["Rex", "Bruno", "Max"]``   → ``"Rex, Bruno, and Max"``

    Args:
        names: List of dog name strings (0–3 elements; excess elements are
            silently ignored beyond the third).

    Returns:
        A human-readable name string suitable for inline use in a sentence.
    """
    clean = [n.strip() for n in names if n.strip()][:3]  # cap at 3, drop blanks
    if not clean:
        return "the dogs"
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return f"{clean[0]}, {clean[1]}, and {clean[2]}"


def _apply_guard_dog_names(mode: ResponseMode, config: dict) -> ResponseMode:
    """Substitute the ``{dog_names}`` placeholder throughout the guard_dog mode.

    Reads ``response_mode.guard_dog.dog_names`` from the config, formats the
    list into a natural phrase via :func:`_format_dog_names`, and replaces
    every ``{dog_names}`` token in the mode's stage templates and
    prompt_modifiers with that phrase.

    Substituting directly into the stored strings (rather than leaving it to
    the runtime template renderer) ensures the AI prompt itself already
    contains the real names before being sent to the vision API.

    Returns a *new* ResponseMode — the original cached mode is never mutated.
    If ``dog_names`` is empty the fallback ``"the dogs"`` is still substituted
    so the templates remain grammatically consistent with the
    ``_VAR_FALLBACKS`` entry.

    Args:
        mode: The base ``guard_dog`` ResponseMode to modify.
        config: Full VoxWatch config dict (reads ``response_mode.guard_dog``).

    Returns:
        A new ResponseMode with ``{dog_names}`` resolved in all stage text.
    """
    rm_cfg = config.get("response_mode", {})
    if not isinstance(rm_cfg, dict):
        rm_cfg = {}

    guard_dog_cfg = rm_cfg.get("guard_dog", {}) or {}
    raw_names: list = guard_dog_cfg.get("dog_names", []) if isinstance(guard_dog_cfg, dict) else []
    dog_names_str = _format_dog_names(raw_names)

    def _replace(text: str) -> str:
        """Swap every ``{dog_names}`` token for the resolved name string."""
        return text.replace("{dog_names}", dog_names_str)

    new_stages: dict[str, StageConfig] = {}
    for stage_key, stage_cfg in mode.stages.items():
        new_stages[stage_key] = StageConfig(
            prompt_modifier=_replace(stage_cfg.prompt_modifier),
            templates=[_replace(t) for t in stage_cfg.templates],
        )

    return ResponseMode(
        id=mode.id,
        category=mode.category,
        name=mode.name,
        description=mode.description,
        effect=mode.effect,
        tone=mode.tone,
        voice=mode.voice,
        behavior=mode.behavior,
        stages=new_stages,
    )


def get_active_mode(
    config: dict,
    camera_name: str | None = None,
) -> ResponseMode:
    """Resolve and return the active ResponseMode for a given detection event.

    Resolution order:

    1. If ``camera_name`` is provided and
       ``response_modes.camera_overrides[camera_name]`` is set, that mode ID
       takes precedence.
    2. Otherwise, ``response_modes.active_mode`` is used.
    3. Legacy fallback: if neither ``response_modes`` section exists, reads
       ``response_mode.name`` (the old single-key format).
    4. If the resolved mode ID is not found in the loaded mode library, logs a
       warning and returns the ``"standard"`` fallback mode.

    Args:
        config: Full VoxWatch config dict.
        camera_name: Optional Frigate camera name for per-camera override lookup.

    Returns:
        The resolved :class:`~voxwatch.modes.mode.ResponseMode`.
    """
    modes = load_modes(config)
    mode_id = _resolve_mode_id(config, camera_name)

    if mode_id not in modes:
        logger.warning(
            "get_active_mode: unknown mode '%s' — falling back to 'standard'.",
            mode_id,
        )
        mode_id = "standard"

    mode = modes[mode_id]

    # ── Apply mood modifier for modes that support it ─────────────────────
    if mode_id in MOOD_SUPPORTED_MODES:
        mode = _apply_mood(mode, config)

    # ── Apply surveillance personality preset ─────────────────────────────
    # Overlays a pop-culture AI archetype (T-800, HAL, WOPR, GLaDOS) onto the
    # automated_surveillance base mode, replacing tone, voice, and stage-1
    # templates while prepending a personality prompt_prefix to AI stages.
    if mode_id in PRESET_SUPPORTED_MODES:
        mode = _apply_surveillance_preset(mode, config)

    # ── Inject operator name for live_operator mode ───────────────────────
    # When response_mode.operator_name is set, the operator introduces
    # themselves by name in the stage-1 instant message and AI-stage prompts.
    if mode_id == "live_operator":
        mode = _apply_operator_name(mode, config)

    # ── Resolve dog names for guard_dog mode ──────────────────────────────
    # Replace {dog_names} in all templates and prompt_modifiers with the
    # formatted name string from response_mode.guard_dog.dog_names.
    if mode_id == "guard_dog":
        mode = _apply_guard_dog_names(mode, config)

    # ── Apply user voice overrides from config ─────────────────────────────
    # ``response_mode.voice_overrides`` is a dict keyed by mode ID.  When a
    # matching entry is present, non-None provider fields are merged on top of
    # the mode's built-in VoiceConfig defaults, leaving unset fields untouched.
    voice_overrides = config.get("response_mode", {}).get("voice_overrides", {})
    if isinstance(voice_overrides, dict) and mode_id in voice_overrides:
        user_voice = voice_overrides[mode_id]
        if isinstance(user_voice, dict):
            merged_voice = VoiceConfig(
                kokoro_voice=user_voice.get("kokoro_voice") or mode.voice.kokoro_voice,
                openai_voice=user_voice.get("openai_voice") or mode.voice.openai_voice,
                elevenlabs_voice=user_voice.get("elevenlabs_voice") or mode.voice.elevenlabs_voice,
                piper_model=user_voice.get("piper_model") or mode.voice.piper_model,
            )
            mode = ResponseMode(
                id=mode.id,
                name=mode.name,
                category=mode.category,
                description=mode.description,
                effect=mode.effect,
                tone=mode.tone,
                voice=merged_voice,
                behavior=mode.behavior,
                stages=mode.stages,
            )

    return mode


def get_mode_prompt(
    mode_def: ResponseMode,
    stage: str,
    ai_vars: dict[str, str],
) -> str:
    """Build the AI system prompt for a given mode and stage.

    Retrieves the ``prompt_modifier`` for the stage from the mode definition
    and, if non-empty, prepends it to the base AI instruction.  Variable
    substitution is applied to the ``prompt_modifier`` so it can reference
    ``{clothing_description}`` and similar placeholders.

    The base prompt instructs the AI to return a JSON array of short phrases
    suitable for natural cadence audio rendering.

    Args:
        mode_def: The active :class:`~voxwatch.modes.mode.ResponseMode`.
        stage: Stage key — one of ``"stage1"``, ``"stage2"``, ``"stage3"``.
        ai_vars: Dict of AI description variables (see module docstring).
            Used to substitute ``{variable}`` placeholders in the modifier.

    Returns:
        Full prompt string ready to pass to the AI vision API.
    """
    stage_cfg = mode_def.get_stage(stage)
    modifier = stage_cfg.prompt_modifier.strip()

    if modifier:
        # Apply variable substitution to the modifier itself so it can
        # reference dynamic values like {address_street} or {camera_name}.
        modifier = _substitute_vars(modifier, ai_vars)
        return modifier

    # No modifier — return a bare base instruction so the AI still knows
    # what output format is expected.
    return (
        "You are a security camera AI speaker. "
        "Return a JSON array of 1-2 short deterrent phrases (under 20 words each) "
        "that will be read aloud through the camera speaker."
    )


def get_mode_template(
    mode_def: ResponseMode,
    stage: str,
    ai_vars: dict[str, str],
    index: int = 0,
) -> str:
    """Render a fallback template string with variable substitution.

    Used when the AI call fails or returns unusable output.  Selects a
    template from the mode's stage definition and substitutes all
    ``{variable}`` placeholders using the provided AI variables dict.

    Any variable that is missing from ``ai_vars`` is replaced with the
    corresponding value from ``_VAR_FALLBACKS`` so the output is always
    grammatically complete (never contains a raw ``{placeholder}``).

    Args:
        mode_def: The active :class:`~voxwatch.modes.mode.ResponseMode`.
        stage: Stage key — one of ``"stage1"``, ``"stage2"``, ``"stage3"``.
        ai_vars: Dict of resolved AI description variables.
        index: Which template to select from the stage's template list.
            Defaults to 0 (the primary template).  Pass a random integer
            to vary the fallback phrasing across repeated triggers.

    Returns:
        Rendered fallback string with all variables substituted.  Falls back
        to the ``"standard"`` mode's template if this mode has none defined.
    """
    stage_cfg = mode_def.get_stage(stage)
    templates = stage_cfg.templates

    if not templates:
        # Last-resort fallback: use standard mode's template.
        standard = _BUILTIN_MODE_MAP.get("standard", ResponseMode(
            id="standard", category="core", name="Standard",
            description="", effect="",
        ))
        templates = standard.get_stage(stage).templates

    if not templates:
        return "Attention. You are on private property and being recorded."

    idx = index % len(templates)
    raw = templates[idx]
    return _substitute_vars(raw, ai_vars)


def build_ai_vars(
    config: dict,
    camera_name: str,
    *,
    clothing_description: str = "",
    location_on_property: str = "",
    behavior_description: str = "",
    suspect_count: str = "",
) -> dict[str, str]:
    """Assemble the AI description variables dict for template/prompt rendering.

    Combines AI-extracted values (appearance, location, behavior) with
    config-sourced values (address) and runtime values (time, camera name).
    Missing AI values are filled with sensible neutral strings so templates
    are always grammatically complete.

    Args:
        config: Full VoxWatch config dict (for address fields).
        camera_name: Frigate camera name from the detection event.
        clothing_description: Subject's outer clothing description from AI.
        location_on_property: Where on the property the subject was seen.
        behavior_description: What the subject was actively doing.
        suspect_count: Number of subjects (e.g. ``"one"``, ``"two"``).

    Returns:
        Dict mapping variable name to resolved string value.
    """
    prop = config.get("property", {})
    street = prop.get("street", "this address").strip() or "this address"
    full_address = prop.get("full_address", street).strip() or street

    return {
        "clothing_description": (
            clothing_description.strip() or _VAR_FALLBACKS["clothing_description"]
        ),
        "location_on_property": (
            location_on_property.strip() or _VAR_FALLBACKS["location_on_property"]
        ),
        "behavior_description": (
            behavior_description.strip() or _VAR_FALLBACKS["behavior_description"]
        ),
        "suspect_count": suspect_count.strip() or _VAR_FALLBACKS["suspect_count"],
        "address_street": street,
        "address_full": full_address,
        "time_of_day": _time_of_day_label(),
        "camera_name": camera_name.strip() or _VAR_FALLBACKS["camera_name"],
    }


def extract_ai_vars_from_dispatch_json(ai_json_str: str) -> dict[str, str]:
    """Extract AI description variables from a dispatch-mode JSON AI response.

    Dispatch modes instruct the AI to return a structured JSON object with
    fields like ``suspect_count``, ``description``, and ``location`` (stage 2)
    or ``behavior`` and ``movement`` (stage 3).  This function parses those
    fields and maps them to the standard variable names used by templates.

    On parse failure (invalid JSON, missing keys), all extracted values are
    empty strings so the caller can fall back gracefully.

    Args:
        ai_json_str: Raw AI response string expected to be a JSON object.

    Returns:
        Dict with extracted variable values.  Keys match the names used by
        :func:`build_ai_vars`.  Missing keys are empty strings.
    """
    import json  # local import — only needed here

    result: dict[str, str] = {
        "clothing_description": "",
        "location_on_property": "",
        "behavior_description": "",
        "suspect_count": "",
    }

    if not ai_json_str:
        return result

    try:
        data = json.loads(ai_json_str.strip())
    except (json.JSONDecodeError, ValueError):
        logger.debug(
            "extract_ai_vars_from_dispatch_json: could not parse JSON: %r",
            ai_json_str[:120],
        )
        return result

    if not isinstance(data, dict):
        return result

    # Stage 2 fields
    if "description" in data:
        result["clothing_description"] = str(data["description"])
    if "location" in data:
        result["location_on_property"] = str(data["location"])
    if "suspect_count" in data:
        result["suspect_count"] = str(data["suspect_count"])

    # Stage 3 fields
    if "behavior" in data:
        result["behavior_description"] = str(data["behavior"])
    if "movement" in data and not result["behavior_description"]:
        result["behavior_description"] = str(data["movement"])

    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_mode_id(config: dict, camera_name: str | None) -> str:
    """Resolve the effective mode ID from config and optional camera override.

    Args:
        config: Full VoxWatch config dict.
        camera_name: Optional Frigate camera name.

    Returns:
        Mode ID string.
    """
    rm_section = config.get("response_modes", {})

    # Per-camera override takes highest priority.
    if camera_name and rm_section:
        overrides: dict = rm_section.get("camera_overrides", {})
        override_id = overrides.get(camera_name, "").strip()
        if override_id:
            logger.debug(
                "_resolve_mode_id: camera '%s' has override mode '%s'",
                camera_name, override_id,
            )
            return override_id

    # New-style active_mode key.
    if rm_section:
        active = rm_section.get("active_mode", "").strip()
        if active:
            return active

    # Legacy fallback: the old response_mode.name / persona.name key.
    legacy_cfg: dict = config.get("response_mode", config.get("persona", {}))
    legacy_name = legacy_cfg.get("name", "").strip()
    if legacy_name:
        return legacy_name

    return "standard"


def _substitute_vars(text: str, ai_vars: dict[str, str]) -> str:
    """Substitute ``{variable}`` placeholders in a template string.

    Variables present in ``ai_vars`` are used directly.  Variables missing
    from ``ai_vars`` fall back to ``_VAR_FALLBACKS``.  Any remaining
    unresolved placeholders are left as-is (rather than raising) so a
    misconfigured template never crashes the service.

    Args:
        text: Template string with optional ``{variable}`` placeholders.
        ai_vars: Resolved AI description variable values.

    Returns:
        Template string with all known variables substituted.
    """
    merged = {**_VAR_FALLBACKS, **ai_vars}
    try:
        return text.format_map(_SafeFormatMap(merged))
    except (KeyError, ValueError):
        # Malformed format string — return as-is.
        return text


class _SafeFormatMap(dict):
    """dict subclass that returns the key name wrapped in braces for missing keys.

    This lets :func:`_substitute_vars` gracefully handle unknown
    ``{placeholder}`` tokens in user-supplied templates without raising
    ``KeyError``.
    """

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _parse_mode_from_dict(raw: dict[str, Any]) -> ResponseMode:
    """Parse a user-supplied mode dict (from config.yaml) into a ResponseMode.

    Expected YAML structure::

        id: my_mode
        category: custom
        name: My Mode
        description: Short description.
        effect: What it does to intruders.
        tone:
          mood: authoritative
          speed_multiplier: 1.0
          radio_effect: false
        voice:
          kokoro_voice: af_bella
        behavior:
          is_dispatch: false
          use_radio_effect: false
        stages:
          stage1:
            prompt_modifier: "You are ..."
            templates:
              - "First fallback template."
              - "Alternate fallback."
          stage2:
            prompt_modifier: "..."
            templates:
              - "..."

    Args:
        raw: Raw dict from YAML parsing.

    Returns:
        Populated :class:`~voxwatch.modes.mode.ResponseMode`.

    Raises:
        KeyError: If the ``id`` field is missing.
        ValueError: If ``id`` is empty or non-string.
    """
    mode_id = raw["id"]
    if not isinstance(mode_id, str) or not mode_id.strip():
        raise ValueError(f"Mode 'id' must be a non-empty string, got: {mode_id!r}")

    # Tone
    raw_tone = raw.get("tone", {}) or {}
    tone = ToneConfig(
        mood=str(raw_tone.get("mood", "neutral")),
        speed_multiplier=float(raw_tone.get("speed_multiplier", 1.0)),
        radio_effect=bool(raw_tone.get("radio_effect", False)),
    )

    # Voice
    raw_voice = raw.get("voice", {}) or {}
    voice = VoiceConfig(
        kokoro_voice=raw_voice.get("kokoro_voice") or None,
        openai_voice=raw_voice.get("openai_voice") or None,
        elevenlabs_voice=raw_voice.get("elevenlabs_voice") or None,
        piper_model=raw_voice.get("piper_model") or None,
    )

    # Behavior
    raw_beh = raw.get("behavior", {}) or {}
    behavior = BehaviorConfig(
        is_dispatch=bool(raw_beh.get("is_dispatch", False)),
        use_radio_effect=bool(raw_beh.get("use_radio_effect", False)),
        officer_response=bool(raw_beh.get("officer_response", True)),
        json_ai_output=bool(raw_beh.get("json_ai_output", False)),
        scene_context_prefix=bool(raw_beh.get("scene_context_prefix", True)),
    )

    # Stages
    raw_stages = raw.get("stages", {}) or {}
    stages: dict[str, StageConfig] = {}
    for stage_key, stage_raw in raw_stages.items():
        if not isinstance(stage_raw, dict):
            continue
        stages[stage_key] = StageConfig(
            prompt_modifier=str(stage_raw.get("prompt_modifier", "") or ""),
            templates=[
                str(t) for t in (stage_raw.get("templates") or [])
                if t is not None
            ],
        )

    return ResponseMode(
        id=mode_id.strip(),
        category=str(raw.get("category", "custom")),
        name=str(raw.get("name", mode_id)),
        description=str(raw.get("description", "")),
        effect=str(raw.get("effect", "")),
        tone=tone,
        voice=voice,
        behavior=behavior,
        stages=stages,
    )
