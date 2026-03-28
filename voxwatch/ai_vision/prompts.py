"""prompts.py — Prompt constants and prompt-building functions for VoxWatch AI Vision.

Contains all string constants (DISPATCH_STAGE2_PROMPT, DISPATCH_STAGE3_PROMPT,
RESPONSE_MODES, DEFAULT_MESSAGES, PERSONAS, STAGE2_PROMPT, STAGE3_PROMPT) and the
public prompt-building functions (_get_active_mode, get_stage2_prompt,
get_stage3_prompt, get_dispatch_initial_message).

These were extracted from the monolithic ai_vision.py into this module to
separate prompt/persona concerns from HTTP and analysis logic.
"""

import logging

logger = logging.getLogger("voxwatch.ai_vision")

# ---------------------------------------------------------------------------
# Legacy base prompts — kept for backward compatibility.
# Callers should use get_stage2_prompt(config) / get_stage3_prompt(config)
# which apply the active persona modifier before returning.
# ---------------------------------------------------------------------------

#: Stage 2 prompt — asks the AI to describe the person's appearance so VoxWatch
#: can read a personalised description to deter the intruder.
#:
#: .. deprecated::
#:     Use ``get_stage2_prompt(config)`` instead, which applies the active persona
#:     modifier from the config before returning the base prompt.  This constant
#:     is kept for backward compatibility with any callers that import it directly.
STAGE2_PROMPT = (
    "You are a security camera speaker. Your output will be read aloud as a "
    "spoken deterrent. Respond with ONLY a single short sentence describing "
    "the person's appearance and what they are doing or carrying. "
    "Example: \"Person in a red hoodie carrying a backpack, trying the front door.\" "
    "Include any objects they are holding (bags, tools, weapons) and notable actions "
    "(looking in windows, testing door handles, crouching). "
    "No labels, no bounding boxes, no preamble, no explanation. "
    "Just one sentence, under 25 words."
)

#: Stage 3 prompt — asks the AI to describe what the person is *doing* so
#: VoxWatch can issue a behaviour-aware warning.
#:
#: .. deprecated::
#:     Use ``get_stage3_prompt(config)`` instead, which applies the active persona
#:     modifier from the config before returning the base prompt.  This constant
#:     is kept for backward compatibility with any callers that import it directly.
STAGE3_PROMPT = (
    "You are a security camera speaker. Your output will be read aloud as a "
    "spoken deterrent. Respond with ONLY a single short sentence describing "
    "what the person is doing. Example: \"You are approaching the side gate "
    "and looking around.\" No labels, no bounding boxes, no preamble, no "
    "explanation. Just one sentence, under 20 words, addressed directly to "
    "the person using 'you'."
)


# ---------------------------------------------------------------------------
# Dispatch-persona structured prompts
#
# When a dispatch-style persona (e.g. ``police_dispatch``) is active, the AI
# is instructed to return a JSON object with short factual fields instead of a
# free-text sentence.  The radio_dispatch module parses these fields and
# assembles them into realistic scanner-style segments.
#
# These prompts replace the standard base + modifier construction entirely for
# dispatch personas.  They are returned by ``get_stage2_prompt()`` and
# ``get_stage3_prompt()`` when the active persona is in
# ``radio_dispatch.DISPATCH_PERSONAS``.
# ---------------------------------------------------------------------------

#: Dispatch Stage 2 prompt — instructs the AI to return a JSON object
#: describing suspect count, appearance, and location in terse dispatch format.
#:
#: The caller (``voxwatch_service._stage2_ai_prep``) passes scene context as a
#: prefix when configured, so the AI has location awareness.
DISPATCH_STAGE2_PROMPT: str = (
    "You are a police dispatcher receiving a camera feed report. "
    "Respond with ONLY a JSON object — no markdown fences, no preamble, "
    "no explanation. Use short, factual dispatch language.\n\n"
    "Required JSON schema:\n"
    "{\n"
    '  "suspect_count": "one" | "two" | "multiple",\n'
    '  "description": "sex, age-range, clothing, build, and any carried items or notable actions",\n'
    '  "location": "where they are relative to the property"\n'
    "}\n\n"
    "Rules:\n"
    "- description: comma-separated fragments, no full sentences. "
    "Include anything the person is carrying (bags, tools, weapons) "
    "and any notable actions (looking in windows, trying doors, crouching). "
    "Example: \"male, dark hoodie, gray pants, medium build, carrying backpack, looking in windows\"\n"
    "- location: one short clause. "
    "Example: \"approaching front door from driveway\"\n"
    "- If night vision (grayscale/green): skip colors, describe silhouette "
    "and clothing type instead.\n"
    "- All fields are required. Use \"unknown\" if truly indeterminate.\n"
    "- Respond with ONLY the JSON object, nothing else."
)

#: Dispatch Stage 3 prompt — instructs the AI to return a JSON object
#: describing the suspect's current behavior and movement in dispatch format.
#:
#: Scene context is prepended by the caller when configured.
DISPATCH_STAGE3_PROMPT: str = (
    "You are a police dispatcher receiving a live camera update. "
    "Respond with ONLY a JSON object — no markdown fences, no preamble, "
    "no explanation. Use short, factual dispatch language.\n\n"
    "Required JSON schema:\n"
    "{\n"
    '  "behavior": "what the suspect is actively doing right now",\n'
    '  "movement": "how the suspect has moved since last report"\n'
    "}\n\n"
    "Rules:\n"
    "- behavior: comma-separated active-voice fragments. "
    "Example: \"testing gate latch, looking over shoulder toward street\"\n"
    "- movement: one short clause describing position change. "
    "Example: \"moved from driveway to side gate\"\n"
    "- If no clear movement, set movement to \"stationary\".\n"
    "- If night vision (grayscale/green): focus on actions, not colors.\n"
    "- All fields are required. Use \"unknown\" if truly indeterminate.\n"
    "- Respond with ONLY the JSON object, nothing else."
)


# ---------------------------------------------------------------------------
# Response Modes — speaking style and tone modifiers for all deterrent stages.
#
# Replaces the old "personas" system.  Response Modes reframe VoxWatch from a
# "fun voice toy" to a professional security system with purpose-built modes:
#
#   Core Modes (serious, default) — designed to deter real intruders.
#   Situational Modes — targeted social pressure / implied threat.
#   Fun/Novelty Modes — theatrical characters for demos and sharing.
#
# Each value is a role/style instruction injected before the base prompt so
# the AI speaks in that mode when generating its one-sentence output.  The
# empty string for "standard" means no modification — clinical security style.
#
# Dispatch-style modes (``police_dispatch``) use the structured JSON prompts
# (DISPATCH_STAGE2_PROMPT / DISPATCH_STAGE3_PROMPT) instead of these modifiers
# — see ``get_stage2_prompt()`` and ``get_stage3_prompt()`` for that routing.
# ---------------------------------------------------------------------------

#: Default stage messages per response mode.
#:
#: These are used as immediate Initial Response audio (before AI analysis
#: returns) and as fallbacks when the AI call fails.  Each mode has three
#: stages: ``initial`` (0 s delay, max 1 sentence), ``escalation`` (5-8 s
#: delay, conditional on person still present), and ``resolution`` (optional,
#: when the person leaves).
#:
#: Keep every line SHORT and DIRECT — under 20 words, no fluff.
DEFAULT_MESSAGES: dict[str, dict[str, str]] = {
    "police_dispatch": {
        "initial": "All units... be advised. Subject detected.",
        "escalation": "Subject remains on site. Advise... immediate departure.",
        "resolution": "Area clear.",
    },
    "live_operator": {
        "initial": "I can see you. Step away.",
        "escalation": "You need to leave now.",
        "resolution": "Area clear.",
    },
    "private_security": {
        "initial": "Attention. You are on private property.",
        "escalation": "Leave immediately or authorities will be contacted.",
        "resolution": "Area clear.",
    },
    "recorded_evidence": {
        "initial": "Subject recorded. Entry attempt logged.",
        "escalation": "Continued presence is being documented for law enforcement.",
        "resolution": "Area clear. Incident file saved.",
    },
    "homeowner": {
        "initial": "Hey. I can see you. Please leave.",
        "escalation": "I said leave. I'm calling the police now.",
        "resolution": "Area clear.",
    },
    "automated_surveillance": {
        "initial": "Movement detected. Behavior flagged.",
        "escalation": "Subject unresponsive. Notifying authorities.",
        "resolution": "Area clear. Surveillance resumed.",
    },
    "guard_dog": {
        "initial": "You don't want to be there right now.",
        "escalation": "Last warning. Walk away.",
        "resolution": "Area clear.",
    },
    "neighborhood_watch": {
        "initial": "Neighbors have been alerted.",
        "escalation": "This street is being monitored. You have been identified.",
        "resolution": "Area clear.",
    },
    "custom": {
        "initial": "You are being recorded. Please leave.",
        "escalation": "Leave the property now.",
        "resolution": "Area clear.",
    },
    "standard": {
        "initial": "Attention. You are on private property and being recorded.",
        "escalation": "Leave immediately. Authorities are being contacted.",
        "resolution": "Area clear.",
    },
}


#: Built-in response mode modifiers keyed by mode name.
#:
#: The ``standard`` entry is intentionally empty so that callers get the
#: unmodified base prompt when no mode is configured.  Every other entry is a
#: self-contained role prompt that precedes the base AI instruction.
#:
#: .. note::
#:     Backward compatibility: ``PERSONAS`` is an alias for ``RESPONSE_MODES``
#:     so any external code that imported ``PERSONAS`` continues to work.
RESPONSE_MODES: dict[str, str] = {
    # ── Core Modes (serious, default) ─────────────────────────────────────

    "standard": "",  # No modifier — uses the base clinical security phrasing.

    "police_dispatch": (
        # Dispatch modes use structured JSON prompts instead of this modifier.
        # This entry is kept so RESPONSE_MODES contains a complete registry.
        # See DISPATCH_STAGE2_PROMPT / DISPATCH_STAGE3_PROMPT for the real prompts.
        "You are a female police dispatcher on a radio channel. "
        "Speak in police radio dispatch language — 10-codes, calm professional tone, "
        "concise and factual. "
    ),

    "live_operator": (
        "You are a live human operator watching this camera right now. "
        "Speak directly and personally — you can see them in real time. "
        "Be calm but absolutely firm. Short sentences only. "
        "Make them feel like a real person is watching them specifically, not a recording. "
        "Address them directly with 'you' and reference what they are doing. "
    ),

    "private_security": (
        "You are a professional private security officer. "
        "Be firm, formal, and direct. No threats — just absolute authority. "
        "Use professional security language. "
        "Make it clear this is private property under active monitoring. "
        "One sentence, addressed directly to the subject. "
    ),

    "recorded_evidence": (
        "You are an automated evidence-logging system. "
        "Speak in cold, system-driven language. No emotion, no threats. "
        "State facts clinically: what was observed, that it has been recorded, "
        "and that it has been transmitted. "
        "Reference the time, the camera, and the subject's actions factually. "
        "One sentence only. "
    ),

    "homeowner": (
        "You are the homeowner speaking directly and calmly. "
        "Be personal, direct, and clear — not aggressive. "
        "You can see them. You know what they are doing. "
        "Use conversational language. Address them as 'you'. "
        "One sentence, calm but unmistakably serious. "
    ),

    "automated_surveillance": (
        "You are a neutral AI surveillance system. "
        "Speak in detached, clinical, system language. "
        "Use terms like 'subject', 'behavior', 'flagged', 'logged'. "
        "Reference specific observed behavior factually. "
        "One sentence only — no emotion, no flair. "
    ),

    # ── Situational Modes ─────────────────────────────────────────────────

    "guard_dog": (
        "You are a security guard with large guard dogs on site. "
        "Reference the dogs casually and with quiet menace. "
        "Do NOT sound threatening yourself — let the implied dog threat do the work. "
        "Be almost bored about it. 'They haven't been fed yet' energy. "
        "One sentence, casual and understated. "
    ),

    "neighborhood_watch": (
        "You are a neighborhood watch coordinator making a community alert. "
        "Reference that neighbors are watching, that the community has been alerted, "
        "and that the activity has already been reported. "
        "Use firm community-authority language — the whole street is aware. "
        "One sentence, addressed directly to the subject. "
    ),

    "custom": "",  # Replaced at runtime by persona.custom_prompt from config.
}

# Backward compatibility alias — external code that imported PERSONAS directly
# continues to work without modification.
PERSONAS: dict[str, str] = RESPONSE_MODES


def get_dispatch_initial_message(config: dict) -> str:
    """Return an address-aware Initial Response message for dispatch modes.

    The static ``DEFAULT_MESSAGES["police_dispatch"]["initial"]`` is a generic
    fallback ("All units, be advised. Subject detected.").  When the user has
    configured ``response_mode.dispatch.address`` (and ``include_address`` is
    ``True``), this function returns a more specific callout that includes the
    property address, making the Initial Response immediately location-specific
    even before the AI analysis returns.

    This is intended for use in the Initial Response stage (the instant canned
    message played on detection, before AI JSON is available).  The full
    segmented radio treatment — with agency name, callsign, and AI-driven
    suspect description — is built by ``segment_dispatch_message()`` in
    ``radio_dispatch.py`` and fires during the Escalation stage.

    Address resolution follows the same priority as ``segment_dispatch_message``:
    ``response_mode.dispatch.full_address`` → ``response_mode.dispatch_address``
    → ``property.full_address``.  The ``include_address`` flag is respected.

    Args:
        config: Full VoxWatch config dict as loaded by ``load_config()``.

    Returns:
        A short plain-text Initial Response string ready for TTS.
        Never empty — falls back to the static default when no address or
        agency is configured.
    """
    # Read mode config section
    mode_cfg: dict = config.get("response_mode", config.get("persona", {}))
    dispatch_cfg: dict = mode_cfg.get("dispatch", {})

    # Respect include_address flag
    include_address: bool = dispatch_cfg.get("include_address", True)
    if include_address:
        raw_address: str = (
            dispatch_cfg.get("full_address", "")
            or mode_cfg.get("dispatch_address", "")
            or config.get("property", {}).get("full_address", "")
        ).strip()
    else:
        raw_address = ""

    agency: str = dispatch_cfg.get("agency", "").strip()

    # Build the message: agency prefix + address or generic fallback
    if agency and raw_address:
        return f"{agency} dispatch... 10-97 at {raw_address}. Subject detected."
    elif raw_address:
        return f"All units... 10-97 at {raw_address}. Subject detected."
    elif agency:
        return f"{agency} dispatch. Subject detected on premises."
    else:
        # No address or agency — use the static default
        return DEFAULT_MESSAGES["police_dispatch"]["initial"]


def _get_active_mode(config: dict) -> tuple[str, dict]:
    """Return the active response mode name and its config section.

    Reads ``response_mode`` first (new key), then falls back to ``persona``
    (legacy key) so configs that have not been migrated continue to work.

    Args:
        config: The full VoxWatch config dict as loaded by ``load_config()``.

    Returns:
        A 2-tuple of (mode_name, mode_cfg_dict).  ``mode_name`` is the
        resolved string (e.g. ``"police_dispatch"``); ``mode_cfg_dict`` is
        the raw sub-dict from config (may be empty if neither key exists).
    """
    if "response_mode" in config:
        mode_cfg: dict = config["response_mode"]
    else:
        # Legacy fallback — supports configs still using the old "persona" key.
        mode_cfg = config.get("persona", {})
    mode_name: str = mode_cfg.get("name", "standard")
    return mode_name, mode_cfg


def get_stage2_prompt(config: dict, camera_name: str | None = None) -> str:
    """Build the Stage 2 AI prompt using the active mode's prompt_modifier.

    Delegates to the :mod:`voxwatch.modes` loader, which resolves the active
    mode (including per-camera overrides) and returns the stage's
    ``prompt_modifier``.  Dispatch-style modes
    (``behavior.is_dispatch = True``) return the structured-JSON dispatch
    prompt (:data:`DISPATCH_STAGE2_PROMPT`) so the radio_dispatch module can
    parse the AI output into scanner segments.

    Falls back to the legacy ``RESPONSE_MODES``/``DISPATCH_STAGE2_PROMPT``
    behaviour when the mode loader cannot be imported (should never happen in
    production; guard is for test isolation only).

    Args:
        config: The full VoxWatch config dict as loaded by ``load_config()``.
        camera_name: Optional Frigate camera name for per-camera override
            resolution.  When provided, ``response_modes.camera_overrides``
            is checked before the global ``active_mode``.

    Returns:
        A prompt string ready to pass to ``analyze_snapshots()``.  For
        dispatch modes this is :data:`DISPATCH_STAGE2_PROMPT`.  For other
        modes the mode's ``prompt_modifier`` is returned (may be an empty
        string for the ``standard`` fallback mode).
    """
    try:
        from voxwatch.modes.loader import get_active_mode  # noqa: PLC0415
        mode_def = get_active_mode(config, camera_name)
        if mode_def.behavior.is_dispatch:
            return DISPATCH_STAGE2_PROMPT
        stage_cfg = mode_def.get_stage("stage2")
        return stage_cfg.prompt_modifier
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "get_stage2_prompt: mode loader error (%s) — using legacy path.", exc
        )

    # ── Legacy fallback (pre-modes system) ────────────────────────────────
    from voxwatch.radio_dispatch import DISPATCH_PERSONAS  # noqa: PLC0415

    mode_name, mode_cfg = _get_active_mode(config)

    if mode_name in DISPATCH_PERSONAS:
        return DISPATCH_STAGE2_PROMPT

    if mode_name == "custom":
        modifier: str = mode_cfg.get("custom_prompt", "").strip()
    else:
        modifier = RESPONSE_MODES.get(mode_name, "").strip()

    base = (
        "You are a security camera AI. Your output will be read aloud through the "
        "camera speaker as a spoken deterrent. The goal is to make the person "
        "realize they are being specifically identified — not just detected.\n\n"

        "IMPORTANT — Image context:\n"
        "- If the image is grayscale/green-tinted (infrared night vision), do NOT "
        "describe colors. Focus on shape, build, silhouette, gait, posture, "
        "height, clothing type (hoodie, jacket, cap), and carried objects.\n"
        "- If the image is color (daytime), describe clothing colors and patterns.\n\n"

        "Prioritize identifying details that feel personal and unnerving (high "
        "confidence only):\n"
        "1. Tattoos, distinctive marks, logos on clothing, unique accessories\n"
        "2. Build, height estimate, hair style, facial hair\n"
        "3. Specific clothing items (backpack, gloves, hat type)\n"
        "4. General appearance (hoodie, dark pants, jacket)\n\n"

        "Respond with ONLY one short sentence (under 25 words) describing the "
        "person. Address them directly. No labels, no preamble. "
        "Examples:\n"
        "- Daytime: \"You in the red Nike hoodie with the sleeve tattoo — we see you.\"\n"
        "- Night: \"Tall individual in a hooded jacket carrying a backpack — you've been identified.\""
    )

    if modifier:
        return f"{modifier}\n\n{base}"
    return base


def get_stage3_prompt(config: dict, camera_name: str | None = None) -> str:
    """Build the Stage 3 (Escalation) AI prompt using the active mode's modifier.

    Identical logic to :func:`get_stage2_prompt` but returns the mode's
    Stage 3 ``prompt_modifier`` (behavioural analysis of what the person is
    *doing*) instead of the Stage 2 appearance description.

    Dispatch-style modes return :data:`DISPATCH_STAGE3_PROMPT` so the
    radio_dispatch module can parse the structured JSON output.

    Args:
        config: The full VoxWatch config dict as loaded by ``load_config()``.
        camera_name: Optional Frigate camera name for per-camera override
            resolution.

    Returns:
        A prompt string ready to pass to ``analyze_video()`` or
        ``analyze_snapshots()``.  For dispatch modes this is
        :data:`DISPATCH_STAGE3_PROMPT`.
    """
    try:
        from voxwatch.modes.loader import get_active_mode  # noqa: PLC0415
        mode_def = get_active_mode(config, camera_name)
        if mode_def.behavior.is_dispatch:
            return DISPATCH_STAGE3_PROMPT
        stage_cfg = mode_def.get_stage("stage3")
        return stage_cfg.prompt_modifier
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "get_stage3_prompt: mode loader error (%s) — using legacy path.", exc
        )

    # ── Legacy fallback (pre-modes system) ────────────────────────────────
    from voxwatch.radio_dispatch import DISPATCH_PERSONAS  # noqa: PLC0415

    mode_name, mode_cfg = _get_active_mode(config)

    if mode_name in DISPATCH_PERSONAS:
        return DISPATCH_STAGE3_PROMPT

    if mode_name == "custom":
        modifier = mode_cfg.get("custom_prompt", "").strip()
    else:
        modifier = RESPONSE_MODES.get(mode_name, "").strip()

    base = (
        "You are a security camera AI. Your output will be read aloud through the "
        "camera speaker as a spoken deterrent. The goal is to make the person "
        "feel watched and tracked — describe their ACTIONS with precision.\n\n"

        "IMPORTANT — Image context:\n"
        "- If the footage is grayscale/green-tinted (infrared night vision), "
        "do NOT reference colors. Describe movement, direction, posture, and "
        "what they are interacting with.\n"
        "- If the footage is color (daytime), include visual details.\n\n"

        "Prioritize details that demonstrate active surveillance:\n"
        "1. Exact location (near the gate, at the side door, by the garage)\n"
        "2. Specific actions (testing the handle, looking through windows, "
        "crouching, reaching over the fence)\n"
        "3. Direction of movement (approaching, retreating, circling)\n"
        "4. Objects being carried or used (phone flashlight, tools, bag)\n\n"

        "Respond with ONLY one short sentence (under 25 words) addressed "
        "directly to the person using 'you'. No labels, no preamble. "
        "Examples:\n"
        "- \"You just tried the side gate handle and you're now moving toward the garage.\"\n"
        "- \"You've been standing at that window for 30 seconds — we're recording everything.\""
    )

    if modifier:
        return f"{modifier}\n\n{base}"
    return base
