"""
ai_vision.py — AI Vision Analysis Module for VoxWatch

Handles all computer-vision work in the Stage 2 and Stage 3 deterrent pipeline:
  - Fetching snapshots and video clips from the Frigate NVR API
  - Analyzing images with a configurable AI provider (primary) or fallback provider
  - Analyzing video clips with the primary provider, falling back to snapshots for
    providers that do not support video (OpenAI, Anthropic, Grok, Ollama)
  - Checking whether a person is still present on a camera via the Frigate API

Supported providers (configure under ``ai.primary.provider`` and
``ai.fallback.provider`` in config.yaml):

  ``gemini``    — Google Gemini via the Gemini REST API (no SDK).
                  Supports multiple images and video.  Uses raw aiohttp — no
                  google-generativeai SDK required.
  ``openai``    — OpenAI chat completions API (gpt-4o, gpt-4-vision-preview, etc.)
                  Supports multiple images.  Uses raw aiohttp — no openai SDK.
  ``grok``      — xAI Grok API.  OpenAI-compatible endpoint, same code path as
                  ``openai`` but with a different base URL.
  ``anthropic`` — Anthropic Claude API (claude-3-5-sonnet, claude-3-haiku, etc.)
                  Supports multiple images.  Uses raw aiohttp — no anthropic SDK.
  ``ollama``    — Local Ollama vision model (e.g. llava:7b).  Single-image only.
  ``custom``    — Any OpenAI-compatible REST endpoint.  Supply ``host`` in config.

Provider strategy:
  - The primary provider is attempted first.
  - On failure, the fallback provider is tried.
  - If both fail a safe default string is returned so the pipeline continues.
  - Providers that do not support video (all except Gemini) trigger an automatic
    fallback to snapshot analysis for Stage 3.

Shared aiohttp session:
  - A single module-level ``aiohttp.ClientSession`` is reused across all HTTP calls
    to avoid the overhead of creating and tearing down a TCP connection pool on every
    invocation.  The session is created lazily on first use via ``_get_session()``.
  - Call ``await init_session()`` at service startup and ``await close_session()``
    at graceful shutdown to manage the session lifecycle explicitly.

Stage 2 usage (person description):
    images = await grab_snapshots(config, event_id, camera_name, count=3, interval_ms=1000)
    description = await analyze_snapshots(images, STAGE2_PROMPT, config)

Stage 3 usage (behavior analysis):
    clip = await grab_video_clip(config, event_id, duration_seconds=5)
    if clip:
        analysis = await analyze_video(clip, STAGE3_PROMPT, config, fallback_images=images)
    else:
        analysis = await analyze_snapshots(images, STAGE3_PROMPT, config)

Prerequisites:
  - pip install aiohttp
  - For Gemini: api_key set in config (or via env var substitution) — no SDK needed
  - For OpenAI/Grok/Anthropic/custom: api_key set in config (or via env var substitution)
  - For Ollama: Ollama running locally with a vision model pulled (ollama pull llava:7b)
"""

import asyncio
import base64
import logging

import aiohttp

# ── Helpers ───────────────────────────────────────────────────────────────────

def _frigate_base_url(config: dict) -> str:
    """Build the Frigate API base URL from the config dict.

    Reads ``config["frigate"]["host"]`` and ``config["frigate"].get("port", 5000)``
    and assembles them into an ``http://host:port`` string.

    This helper centralises the URL construction that previously appeared as
    three identical inline blocks across ``grab_snapshots``, ``grab_video_clip``,
    and ``check_person_still_present``. Any future change to the scheme or
    path prefix only needs to happen here.

    Args:
        config: Full VoxWatch config dict (must contain a ``frigate`` section
            with at least a ``host`` key).

    Returns:
        Base URL string, e.g. ``"http://192.168.1.10:5000"``.
    """
    frigate_cfg = config["frigate"]
    host = frigate_cfg["host"]
    port = frigate_cfg.get("port", 5000)
    return f"http://{host}:{port}"


logger = logging.getLogger("voxwatch.ai_vision")

# ── Shared aiohttp session ─────────────────────────────────────────────────────
# Reusing a single ClientSession avoids the cost of creating a new TCP
# connection pool for every HTTP call (snapshot fetches, Ollama, Frigate checks).
# The session is created lazily by _get_session() on first use so that no
# network resources are allocated at import time or before the event loop starts.
_session: aiohttp.ClientSession | None = None


async def init_session() -> None:
    """Create the module-level aiohttp session explicitly at service startup.

    Calling this is optional — ``_get_session()`` will create the session lazily
    if it has not been initialised.  Calling it at startup is preferred so that
    connection-pool creation happens at a predictable point rather than during
    the first live detection.

    Safe to call multiple times: a second call is a no-op if the session already
    exists and is open.
    """
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
        logger.debug("ai_vision: shared aiohttp session created")


async def close_session() -> None:
    """Close the module-level aiohttp session at service shutdown.

    Should be awaited during graceful shutdown to release the underlying TCP
    connection pool and avoid ``ResourceWarning`` noise in logs.  Safe to call
    even if the session was never created (no-op in that case).
    """
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None
        logger.debug("ai_vision: shared aiohttp session closed")


async def _get_session() -> aiohttp.ClientSession:
    """Return the shared aiohttp session, creating it lazily if necessary.

    This is the single point through which all HTTP calls in this module obtain
    their session.  Functions that previously opened ``async with
    aiohttp.ClientSession() as session`` now call ``session = await
    _get_session()`` and use it directly (without a context-manager close).

    Returns:
        The module-level ``aiohttp.ClientSession``.  Guaranteed to be open.
    """
    global _session
    if _session is None or _session.closed:
        await init_session()
    # _session is always non-None after init_session(); satisfy the type checker.
    assert _session is not None
    return _session


# ---------------------------------------------------------------------------
# Prompts used by the calling pipeline (Stage 2 and Stage 3).
# These are defined here so callers can import them for consistency, but the
# caller may pass any prompt string — nothing in this module hard-codes them.
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
    "the person's appearance. Example: \"Person wearing a red hoodie and dark "
    "jeans near the front door.\" No labels, no bounding boxes, no preamble, "
    "no explanation. Just one sentence, under 20 words."
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
    '  "description": "sex, age-range, clothing top-to-bottom, build",\n'
    '  "location": "where they are relative to the property"\n'
    "}\n\n"
    "Rules:\n"
    "- description: comma-separated fragments, no full sentences. "
    "Example: \"male, dark hoodie, gray pants, medium build\"\n"
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


# ---------------------------------------------------------------------------
# Public API — Frigate data retrieval
# ---------------------------------------------------------------------------

async def grab_snapshots(
    config: dict,
    event_id: str,
    camera_name: str,
    count: int,
    interval_ms: int,
) -> list[bytes]:
    """Fetch a series of JPEG snapshots from Frigate for an event.

    The first snapshot is pulled from the event's canonical snapshot endpoint,
    which is the best still Frigate has captured for that event.  Subsequent
    snapshots are pulled from the camera's "latest" endpoint at ``interval_ms``
    milliseconds apart so we capture the person at different moments.

    Uses the module-level shared aiohttp session (see ``_get_session``).
    A per-call ``aiohttp.ClientTimeout`` is set on each individual request
    rather than on the session itself, so this function does not interfere with
    timeouts used by concurrent calls on the same session.

    Args:
        config: Full VoxWatch config dict.
        event_id: Frigate event ID string (e.g. "1716400000.123456-abc123").
        camera_name: Frigate camera name (e.g. "frontdoor").
        count: Total number of snapshots to collect.
        interval_ms: Milliseconds to wait between each additional snapshot.

    Returns:
        List of raw JPEG bytes.  May be shorter than ``count`` if any
        individual fetch fails — the caller should handle an empty list
        gracefully.
    """
    base_url = _frigate_base_url(config)

    # AI timeout drives how long we wait per image fetch.
    # Use the longer of the two provider timeouts so we don't bail early.
    ai_timeout = max(
        config.get("ai", {}).get("primary", {}).get("timeout_seconds", 5),
        config.get("ai", {}).get("fallback", {}).get("timeout_seconds", 8),
    )
    http_timeout = aiohttp.ClientTimeout(total=ai_timeout)

    images: list[bytes] = []

    session = await _get_session()

    # --- First snapshot: event snapshot endpoint ---
    # Frigate stores the highest-quality still for the event here.
    event_url = f"{base_url}/api/events/{event_id}/snapshot.jpg"
    snapshot = await _fetch_image(session, event_url, label="event snapshot",
                                  timeout=http_timeout)
    if snapshot:
        images.append(snapshot)
    else:
        logger.warning("Could not fetch event snapshot for %s", event_id)

    # --- Additional snapshots: camera latest endpoint ---
    # We poll the live camera feed to capture the person in motion.
    latest_url = f"{base_url}/api/{camera_name}/latest.jpg"
    for i in range(1, count):
        # Wait before each additional fetch so frames are meaningfully different.
        await asyncio.sleep(interval_ms / 1000.0)
        frame = await _fetch_image(session, latest_url,
                                   label=f"latest frame {i}/{count - 1}",
                                   timeout=http_timeout)
        if frame:
            images.append(frame)

    logger.info("Grabbed %d/%d snapshots for event %s", len(images), count, event_id)
    return images


async def grab_video_clip(
    config: dict,
    event_id: str,
    duration_seconds: int,
) -> bytes | None:
    """Download an MP4 video clip from Frigate for a specific event.

    Frigate generates a clip for an event once sufficient footage has been
    buffered.  If the clip is not yet available (HTTP 404) or the download
    fails, we return None and the caller should fall back to snapshots.

    Uses the module-level shared aiohttp session (see ``_get_session``).

    Args:
        config: Full VoxWatch config dict.
        event_id: Frigate event ID string.
        duration_seconds: Expected clip length (used only for logging context;
            Frigate controls the actual clip duration based on its own config).

    Returns:
        Raw MP4 bytes, or None if the clip could not be fetched.
    """
    clip_url = f"{_frigate_base_url(config)}/api/events/{event_id}/clip.mp4"

    # Video clips can be several megabytes — allow more time than for images.
    timeout_seconds = config.get("stage3", {}).get("video_clip_seconds", 5) + 10
    http_timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    logger.info("Fetching video clip for event %s (%ds expected)", event_id, duration_seconds)

    try:
        session = await _get_session()
        async with session.get(clip_url, timeout=http_timeout) as resp:
            if resp.status == 200:
                data = await resp.read()
                logger.info("Video clip fetched: %d bytes", len(data))
                return data
            elif resp.status == 404:
                # Clip not yet generated — this is normal for very recent events.
                logger.warning("Video clip not ready yet (HTTP 404) for event %s",
                               event_id)
                return None
            else:
                logger.error("Unexpected HTTP %d fetching clip for event %s",
                             resp.status, event_id)
                return None
    except TimeoutError:
        logger.error("Timed out fetching video clip for event %s (timeout=%ds)",
                     event_id, timeout_seconds)
        return None
    except aiohttp.ClientError as exc:
        logger.error("Network error fetching video clip: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API — AI analysis
# ---------------------------------------------------------------------------

async def analyze_snapshots(
    images: list[bytes],
    prompt: str,
    config: dict,
) -> str:
    """Analyse a list of JPEG snapshots with AI and return a text description.

    Tries the primary provider first, then falls back to the fallback provider
    if the primary fails or is not configured.  All providers are supported for
    snapshot analysis; Ollama is single-image only (uses the last frame).

    Provider routing reads ``config["ai"]["primary"]["provider"]`` and
    ``config["ai"]["fallback"]["provider"]``.  Supported values: ``gemini``,
    ``openai``, ``grok``, ``anthropic``, ``ollama``, ``custom``.

    Args:
        images: List of raw JPEG bytes.  Must contain at least one image.
        prompt: Instruction for the AI (e.g. STAGE2_PROMPT or STAGE3_PROMPT).
        config: Full VoxWatch config dict.

    Returns:
        AI-generated description string.  Returns a safe default message if
        all providers fail so the pipeline can continue.
    """
    if not images:
        logger.warning("analyze_snapshots called with no images")
        return "A person was detected but could not be described."

    ai_cfg = config.get("ai", {})

    # Try primary provider, then fall back.
    for role in ("primary", "fallback"):
        provider_cfg = ai_cfg.get(role, {})
        if not provider_cfg:
            continue

        provider: str = provider_cfg.get("provider", "gemini")
        api_key: str = provider_cfg.get("api_key", "")
        model: str = provider_cfg.get("model", "")
        timeout: int = provider_cfg.get("timeout_seconds", 8)

        # Skip providers whose API key is a bare placeholder (unresolved env var).
        if provider != "ollama" and (not api_key or api_key.startswith("${")):
            logger.warning(
                "%s provider %r has no valid API key — skipping", role, provider
            )
            continue

        try:
            result = await _dispatch_snapshot_call(
                images, prompt, provider, provider_cfg, api_key, model, timeout
            )
            logger.info("%s provider %r snapshot analysis succeeded", role, provider)
            return result
        except Exception as exc:
            if role == "primary":
                logger.warning(
                    "Primary provider %r snapshot analysis failed: %s — trying fallback",
                    provider, exc,
                )
            else:
                logger.error(
                    "Fallback provider %r snapshot analysis also failed: %s",
                    provider, exc,
                )

    return "A person was detected on camera."


async def _dispatch_snapshot_call(
    images: list[bytes],
    prompt: str,
    provider: str,
    provider_cfg: dict,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    """Route a snapshot analysis call to the correct provider implementation.

    This is a pure dispatch helper — all error handling is done in the callers
    (``analyze_snapshots`` and ``analyze_video``).  Raises on any failure so
    the caller can log it and try the next provider.

    Args:
        images: List of raw JPEG bytes.
        prompt: Text instruction for the AI.
        provider: Provider name string (``gemini``, ``openai``, ``grok``,
            ``anthropic``, ``ollama``, ``custom``).
        provider_cfg: The raw config sub-dict for this provider (used to pull
            Gemini's full config and Ollama/custom host).
        api_key: Resolved API key string.
        model: Model identifier string.
        timeout: Request timeout in seconds.

    Returns:
        AI response text.

    Raises:
        ValueError: If ``provider`` is not recognised.
        Exception: Any network or API error from the underlying call.
    """
    if provider == "gemini":
        # _call_gemini_images reads the full config itself — pass a synthetic
        # config that preserves the structure it expects.
        synthetic_cfg = {"ai": {"primary": provider_cfg}}
        return await _call_gemini_images(images, prompt, synthetic_cfg)

    elif provider in ("openai", "grok"):
        base_url = (
            "https://api.openai.com/v1"
            if provider == "openai"
            else "https://api.x.ai/v1"
        )
        return await _call_openai_compat(images, prompt, api_key, model, base_url, timeout)

    elif provider == "anthropic":
        return await _call_anthropic(images, prompt, api_key, model, timeout)

    elif provider == "ollama":
        # Ollama handles only one image reliably — use the last (most recent) frame.
        best_image = images[-1]
        # _call_ollama reads fallback config by key — rebuild the expected shape.
        # When ollama is used as primary, we still need to pass the right section;
        # build a synthetic config that puts provider_cfg under "fallback" since
        # _call_ollama always reads from config["ai"]["fallback"].
        synthetic_cfg = {"ai": {"fallback": provider_cfg}}
        return await _call_ollama(best_image, prompt, synthetic_cfg)

    elif provider == "custom":
        host: str = provider_cfg.get("host", "http://localhost:8080/v1")
        return await _call_openai_compat(images, prompt, api_key, model, host, timeout)

    else:
        raise ValueError(f"Unknown AI provider: {provider!r}")


async def analyze_video(
    video_bytes: bytes,
    prompt: str,
    config: dict,
    fallback_images: list[bytes] | None = None,
) -> str:
    """Analyse an MP4 video clip with AI and return a text description.

    Only Gemini natively supports video analysis.  All other providers
    (OpenAI, Grok, Anthropic, Ollama, custom) do not accept video and will
    automatically trigger a fallback to snapshot analysis when they are
    configured as the primary provider.

    Provider selection:
      1. If primary provider is ``gemini``: upload the video to the Gemini
         Files API and analyse it directly.
      2. If primary provider is anything else, or if Gemini video fails:
         fall back to ``analyze_snapshots`` using ``fallback_images`` (if
         ``stage3.fallback_to_snapshots`` is enabled in config).
      3. If no snapshot fallback is available: return a safe default string.

    Args:
        video_bytes: Raw MP4 bytes from ``grab_video_clip``.
        prompt: Instruction for the AI (e.g. STAGE3_PROMPT).
        config: Full VoxWatch config dict.
        fallback_images: Optional list of JPEG bytes to use when the primary
            provider does not support video, or when Gemini video fails.

    Returns:
        AI-generated description string.
    """
    primary_cfg = config.get("ai", {}).get("primary", {})
    provider: str = primary_cfg.get("provider", "gemini")

    # Only Gemini supports direct video analysis.  For every other provider
    # we skip straight to snapshot fallback and log an informational note so
    # users understand why the video is not being analysed directly.
    _VIDEO_CAPABLE_PROVIDERS = {"gemini"}

    if provider not in _VIDEO_CAPABLE_PROVIDERS:
        logger.info(
            "Primary provider %r does not support video analysis — "
            "using snapshot fallback for Stage 3",
            provider,
        )
    else:
        # --- Primary: Gemini video upload ---
        api_key: str = primary_cfg.get("api_key", "")
        if api_key and not api_key.startswith("${"):
            try:
                result = await _call_gemini_video(video_bytes, prompt, config)
                logger.info("Gemini video analysis succeeded")
                return result
            except Exception as exc:
                logger.warning(
                    "Gemini video analysis failed: %s — falling back to snapshots", exc
                )
        else:
            logger.warning(
                "Gemini API key not configured — skipping video analysis"
            )

    # --- Fallback: snapshot analysis ---
    # All non-video-capable providers and any Gemini failure end up here.
    stage3_cfg = config.get("stage3", {})
    if stage3_cfg.get("fallback_to_snapshots", True) and fallback_images:
        logger.info("Falling back to snapshot analysis for Stage 3")
        return await analyze_snapshots(fallback_images, prompt, config)

    # --- Last resort: no snapshots available ---
    logger.warning("No fallback images available for Stage 3 analysis")
    return "The person's actions could not be fully analysed."


async def check_person_still_present(config: dict, camera_name: str) -> bool:
    """Query Frigate to determine whether a person is currently detected on a camera.

    Calls the Frigate current events API, which returns the set of active
    (ongoing, not yet ended) events.  We check whether any of them are for
    the target camera and have the label "person".

    This is used before Stage 3 to avoid wasting time on AI analysis and
    TTS generation if the intruder has already left.

    Uses the module-level shared aiohttp session (see ``_get_session``).

    Args:
        config: Full VoxWatch config dict.
        camera_name: Frigate camera name (e.g. "frontdoor").

    Returns:
        True if Frigate reports an active person detection on that camera.
        Returns False on any error so the pipeline can continue safely.
    """
    base = _frigate_base_url(config)

    # Frigate 0.17 closes events quickly (16-66s) and reopens new ones.
    # The end_time is ALWAYS set within seconds even if the person is still
    # standing there. So checking for end_time=None is unreliable.
    #
    # Strategy: check if any person event ended within the last 30 seconds
    # OR is still active. If yes, the person is likely still there.
    # This catches both rapid event cycling and genuinely active events.
    events_url = (
        f"{base}/api/events"
        f"?camera={camera_name}&label=person&limit=5"
    )

    # Short timeout — this check is on the critical latency path.
    http_timeout = aiohttp.ClientTimeout(total=5)

    try:
        session = await _get_session()
        import time as _time
        now = _time.time()

        async with session.get(events_url, timeout=http_timeout) as resp:
            if resp.status != 200:
                logger.warning("Frigate events API returned HTTP %d for camera %s",
                               resp.status, camera_name)
                # Default to True (assume present) so Stage 3 still fires.
                # False negatives are worse than false positives here.
                return True

            events = await resp.json()

            for e in events:
                if e.get("label") != "person":
                    continue

                end_time = e.get("end_time")

                # Still active (no end_time) — person definitely there
                if end_time is None:
                    logger.info("Person still present on %s (active event %s)",
                                camera_name, str(e.get("id", "?"))[:12])
                    return True

                # Event ended recently — person likely still there.
                # Frigate cycles events rapidly, so a 30s recency window
                # accounts for the gap between event close and next event open.
                seconds_ago = now - end_time
                if seconds_ago < 30:
                    logger.info(
                        "Person likely still present on %s (event ended %.1fs ago)",
                        camera_name, seconds_ago,
                    )
                    return True

            logger.info("No recent person events on %s — person likely left",
                        camera_name)
            return False

    except TimeoutError:
        logger.warning("Timed out checking person presence on %s", camera_name)
        return False
    except aiohttp.ClientError as exc:
        logger.warning("Network error checking person presence: %s", exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error in check_person_still_present: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Internal helpers — Gemini
# ---------------------------------------------------------------------------

async def _call_gemini_images(
    images: list[bytes],
    prompt: str,
    config: dict,
) -> str:
    """Call Google Gemini with one or more JPEG images via the REST API.

    Uses the Gemini ``generateContent`` REST endpoint directly via the shared
    aiohttp session.  No google-generativeai SDK is required — the API key is
    passed as a query parameter per-request, so there is no global SDK state
    and no threading lock needed.

    Safety filters are disabled via ``safetySettings`` because security camera
    descriptions of people (clothing, build, actions, posture) can trigger
    false positives on harassment and dangerous-content categories.  This is a
    private security system, not user-facing content generation.

    Args:
        images: List of raw JPEG bytes to analyse.  All images are sent in a
            single request as ``inline_data`` content parts.
        prompt: Text instruction for the model.
        config: Full VoxWatch config dict.  Reads ``config["ai"]["primary"]``
            for ``api_key``, ``model``, and ``timeout_seconds``.

    Returns:
        Model response text.

    Raises:
        ValueError: On HTTP 400 (bad request / invalid key) or non-200 status,
            empty candidate list, or empty response text.
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds ``timeout_seconds``.
    """
    primary_cfg = config["ai"]["primary"]
    api_key: str = primary_cfg["api_key"]
    model_name: str = primary_cfg.get("model", "gemini-2.5-flash")
    timeout_seconds: int = primary_cfg.get("timeout_seconds", 5)

    # Build multimodal content parts: text prompt first, then one inline_data
    # entry per image.  Gemini accepts multiple images in a single request,
    # giving the model cross-frame context for appearance comparison.
    parts: list[dict] = [{"text": prompt}]
    for idx, img_bytes in enumerate(images):
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("ascii"),
            }
        })
        logger.debug(
            "Gemini images: added image %d/%d to request (%d bytes)",
            idx + 1, len(images), len(img_bytes),
        )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": parts}],
        # Disable all safety filters — security camera descriptions regularly
        # trigger harassment / dangerous-content false positives without these.
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.3,
        },
    }

    logger.debug(
        "Calling Gemini REST API with model %r (%d image(s))",
        model_name, len(images),
    )

    session = await _get_session()
    async with session.post(
        url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
    ) as resp:
        if resp.status == 400:
            body = await resp.json()
            error = body.get("error", {}).get("message", "Unknown error")
            raise ValueError(f"Gemini API error (400): {error}")
        if resp.status != 200:
            body_text = await resp.text()
            raise ValueError(
                f"Gemini API returned HTTP {resp.status}: {body_text[:200]}"
            )
        data = await resp.json()

    # Extract the generated text from the response structure:
    #   {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates in response")

    response_parts = candidates[0].get("content", {}).get("parts", [])
    text = " ".join(p.get("text", "") for p in response_parts).strip()
    if not text:
        raise ValueError("Gemini returned an empty text response")

    return text


async def _call_gemini_video(
    video_bytes: bytes,
    prompt: str,
    config: dict,
) -> str:
    """Upload an MP4 video to the Gemini Files API and analyse it via REST.

    The Gemini Files API requires a three-step flow:

    1. Upload the video bytes via a multipart POST to the upload endpoint.
       The response contains a ``file.name`` (e.g. ``"files/abc123"``).
    2. Poll the file metadata endpoint until ``state`` becomes ``"ACTIVE"``.
       Gemini typically processes a short security-camera clip in 2–5 seconds.
    3. Call ``generateContent`` referencing the uploaded file via its URI.
    4. Delete the uploaded file to avoid accumulating storage on the account.

    All network calls use the shared aiohttp session and pass the API key as a
    query parameter — no google-generativeai SDK required.

    Safety filters are disabled for the same reason as ``_call_gemini_images``:
    security camera footage of people in motion regularly triggers false
    positives on harassment and dangerous-content categories.

    Args:
        video_bytes: Raw MP4 bytes from ``grab_video_clip``.
        prompt: Text instruction for the model (e.g. STAGE3_PROMPT).
        config: Full VoxWatch config dict.  Reads ``config["ai"]["primary"]``
            for ``api_key``, ``model``, and ``timeout_seconds``.

    Returns:
        Model response text.

    Raises:
        ValueError: On non-200 HTTP responses, upload failure, processing
            timeout, empty candidate list, or empty response text.
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the overall operation exceeds the timeout.
    """
    primary_cfg = config["ai"]["primary"]
    api_key: str = primary_cfg["api_key"]
    model_name: str = primary_cfg.get("model", "gemini-2.5-flash")
    # Video analysis takes longer than image analysis — triple the base timeout
    # to allow for upload time + Gemini processing latency.
    timeout_seconds: int = primary_cfg.get("timeout_seconds", 5) * 3

    session = await _get_session()

    # ── Step 1: Upload the video to the Gemini Files API ──────────────────────
    # The upload endpoint accepts a multipart POST with the video bytes.
    # The Content-Type header must declare the MIME type of the file being
    # uploaded so Gemini can identify it as a video for processing.
    logger.debug(
        "Uploading %d-byte video to Gemini Files API (model=%r)",
        len(video_bytes), model_name,
    )

    upload_url = (
        f"https://generativelanguage.googleapis.com/upload/v1beta/files"
        f"?key={api_key}"
    )

    # Build a minimal multipart body with the video bytes.
    # FormData handles the boundary encoding automatically.
    upload_data = aiohttp.FormData()
    upload_data.add_field(
        name="file",
        value=video_bytes,
        content_type="video/mp4",
        filename="clip.mp4",
    )

    http_timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with session.post(upload_url, data=upload_data, timeout=http_timeout) as resp:
        if resp.status != 200:
            body_text = await resp.text()
            raise ValueError(
                f"Gemini Files API upload returned HTTP {resp.status}: "
                f"{body_text[:200]}"
            )
        upload_data_resp = await resp.json()

    # The upload response nests the file metadata under the "file" key.
    file_meta: dict = upload_data_resp.get("file", {})
    file_name: str = file_meta.get("name", "")
    file_uri: str = file_meta.get("uri", "")

    if not file_name or not file_uri:
        raise ValueError(
            f"Gemini Files API upload response missing file name or URI: "
            f"{upload_data_resp}"
        )

    logger.debug("Gemini file uploaded: name=%r uri=%r", file_name, file_uri)

    # ── Step 2: Poll until the file state becomes ACTIVE ──────────────────────
    # Gemini processes the video asynchronously.  The file transitions from
    # PROCESSING → ACTIVE once Gemini has ingested it.  We poll the metadata
    # endpoint with a 1-second sleep between checks; typical processing time
    # for a short clip is 2–5 seconds.
    status_url = (
        f"https://generativelanguage.googleapis.com/v1beta/{file_name}"
        f"?key={api_key}"
    )
    poll_timeout = aiohttp.ClientTimeout(total=10)

    for attempt in range(30):  # Max 30 × 1 s = 30 s
        async with session.get(status_url, timeout=poll_timeout) as resp:
            if resp.status != 200:
                body_text = await resp.text()
                raise ValueError(
                    f"Gemini file status check returned HTTP {resp.status}: "
                    f"{body_text[:200]}"
                )
            status_data = await resp.json()

        state: str = status_data.get("state", "")
        if state == "ACTIVE":
            logger.debug(
                "Gemini file %r is ACTIVE after %d poll(s)", file_name, attempt + 1
            )
            break
        if state == "FAILED":
            raise ValueError(
                f"Gemini file {file_name!r} processing failed (state=FAILED)"
            )
        # Still PROCESSING — wait 1 second before the next poll.
        await asyncio.sleep(1)
    else:
        raise TimeoutError(
            f"Gemini file {file_name!r} did not become ACTIVE within 30 seconds"
        )

    # ── Step 3: Call generateContent with the uploaded file reference ─────────
    generate_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    generate_payload = {
        "contents": [{
            "parts": [
                # Reference the uploaded file by its URI.
                {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                {"text": prompt},
            ]
        }],
        # Disable safety filters — same rationale as _call_gemini_images.
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.3,
        },
    }

    logger.debug("Calling Gemini generateContent for video file %r", file_name)

    async with session.post(
        generate_url, json=generate_payload, timeout=http_timeout
    ) as resp:
        if resp.status == 400:
            body = await resp.json()
            error = body.get("error", {}).get("message", "Unknown error")
            raise ValueError(f"Gemini generateContent error (400): {error}")
        if resp.status != 200:
            body_text = await resp.text()
            raise ValueError(
                f"Gemini generateContent returned HTTP {resp.status}: "
                f"{body_text[:200]}"
            )
        gen_data = await resp.json()

    # ── Step 4: Delete the uploaded file to free Gemini storage ──────────────
    # Gemini's Files API has a per-account storage limit.  Always clean up
    # after a successful (or failed) generateContent call.
    delete_url = (
        f"https://generativelanguage.googleapis.com/v1beta/{file_name}"
        f"?key={api_key}"
    )
    try:
        async with session.delete(
            delete_url, timeout=aiohttp.ClientTimeout(total=5)
        ) as del_resp:
            if del_resp.status not in (200, 204):
                logger.debug(
                    "Gemini file delete returned HTTP %d for %r",
                    del_resp.status, file_name,
                )
            else:
                logger.debug("Gemini file %r deleted", file_name)
    except Exception as cleanup_exc:
        # Non-fatal — log and continue.
        logger.debug(
            "Could not delete Gemini file %r: %s", file_name, cleanup_exc
        )

    # ── Extract and return the response text ──────────────────────────────────
    candidates = gen_data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini video analysis returned no candidates")

    response_parts = candidates[0].get("content", {}).get("parts", [])
    text = " ".join(p.get("text", "") for p in response_parts).strip()
    if not text:
        raise ValueError("Gemini video analysis returned an empty text response")

    return text


# ---------------------------------------------------------------------------
# Internal helpers — Ollama
# ---------------------------------------------------------------------------

async def _call_ollama(
    image: bytes,
    prompt: str,
    config: dict,
) -> str:
    """Call a local Ollama vision model with a single JPEG image.

    Ollama exposes a REST API at POST /api/generate.  We send the image as a
    base64-encoded string in the ``images`` array.  Ollama/LLaVA handles one
    image reliably; multi-image support is inconsistent so we always pass exactly
    one image.

    Uses the module-level shared aiohttp session (see ``_get_session``).

    Args:
        image: Raw JPEG bytes of the single image to analyse.
        prompt: Text instruction for the model.
        config: Full VoxWatch config dict.

    Returns:
        Model response text.

    Raises:
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds the configured timeout.
        ValueError: If the Ollama response cannot be parsed.
    """
    fallback_cfg = config.get("ai", {}).get("fallback", {})
    ollama_host: str = fallback_cfg.get("host", "http://localhost:11434")
    model_name: str = fallback_cfg.get("model", "llava:7b")
    timeout_seconds: int = fallback_cfg.get("timeout_seconds", 8)

    # Encode the image as base64 — Ollama's API requires a list of base64 strings.
    image_b64 = base64.b64encode(image).decode("utf-8")

    payload = {
        "model": model_name,
        "prompt": prompt,
        "images": [image_b64],  # List format required by Ollama REST API
        "stream": False,        # We want the full response in one JSON blob
    }

    generate_url = f"{ollama_host.rstrip('/')}/api/generate"
    http_timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    logger.debug("Calling Ollama at %s with model %s (%d-byte image)",
                 generate_url, model_name, len(image))

    session = await _get_session()
    async with session.post(generate_url, json=payload, timeout=http_timeout) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise ValueError(
                f"Ollama returned HTTP {resp.status}: {body[:200]}"
            )
        data = await resp.json()

    # Ollama's non-streaming response puts the full text in the "response" key.
    response_text: str = data.get("response", "").strip()
    if not response_text:
        raise ValueError(f"Ollama returned an empty response for model {model_name!r}")

    return response_text


# ---------------------------------------------------------------------------
# Internal helpers — OpenAI-compatible (OpenAI, Grok, custom endpoints)
# ---------------------------------------------------------------------------

async def _call_openai_compat(
    images: list[bytes],
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    timeout: int,
) -> str:
    """Call any OpenAI-compatible chat completions endpoint with vision images.

    Works with OpenAI (gpt-4o, gpt-4-vision-preview, etc.), xAI Grok
    (grok-2-vision, grok-vision-beta, etc.), and any third-party API that
    implements the OpenAI chat completions format.

    Images are encoded as base64 data URIs and supplied as ``image_url``
    content parts inside the user message.  The OpenAI vision format accepts
    multiple images in a single request so all captured frames are sent.

    Uses the module-level shared aiohttp session (see ``_get_session``).
    Does NOT use the openai SDK — raw aiohttp is used to keep the Docker
    image small and avoid an extra transitive dependency.

    Default base URLs:
      - OpenAI: ``https://api.openai.com/v1``
      - Grok:   ``https://api.x.ai/v1``
      - Custom: controlled by the caller via the ``base_url`` argument.

    Args:
        images: List of raw JPEG bytes to analyse.  All images are sent in
            a single API call as separate ``image_url`` content parts.
        prompt: Text instruction for the model.
        api_key: Bearer token (OpenAI API key or equivalent).
        model: Model identifier string (e.g. ``"gpt-4o"`` or
            ``"grok-vision-beta"``).
        base_url: Root URL of the API endpoint, without a trailing slash
            (e.g. ``"https://api.openai.com/v1"``).
        timeout: Request timeout in seconds.

    Returns:
        Model response text from ``choices[0].message.content``.

    Raises:
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds ``timeout`` seconds.
        ValueError: On HTTP 401 (invalid key), HTTP 404 (model not found),
            other non-200 status codes, or an empty/unparseable response.
    """
    # Build the list of content parts: one image_url entry per image.
    # The OpenAI vision spec uses data URIs: "data:image/jpeg;base64,<b64>".
    content_parts: list[dict] = []
    for idx, img_bytes in enumerate(images):
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        logger.debug(
            "OpenAI-compat: added image %d/%d to request (%d bytes)",
            idx + 1, len(images), len(img_bytes),
        )

    # Append the text instruction after all images.
    content_parts.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content_parts}],
        # max_tokens guards against runaway generation; the prompts request a
        # single short sentence so 150 tokens is more than sufficient.
        "max_tokens": 150,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    completions_url = f"{base_url.rstrip('/')}/chat/completions"
    http_timeout = aiohttp.ClientTimeout(total=timeout)

    logger.debug(
        "Calling OpenAI-compat endpoint %s with model %r (%d image(s))",
        completions_url, model, len(images),
    )

    session = await _get_session()
    async with session.post(
        completions_url, json=payload, headers=headers, timeout=http_timeout
    ) as resp:
        if resp.status == 401:
            raise ValueError(
                f"OpenAI-compat: HTTP 401 from {completions_url} — "
                "check your API key"
            )
        if resp.status == 404:
            raise ValueError(
                f"OpenAI-compat: HTTP 404 from {completions_url} — "
                f"model {model!r} not found"
            )
        if resp.status != 200:
            body = await resp.text()
            raise ValueError(
                f"OpenAI-compat: HTTP {resp.status} from {completions_url}: "
                f"{body[:200]}"
            )
        data = await resp.json()

    # Navigate the standard OpenAI response structure.
    try:
        response_text: str = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"OpenAI-compat: could not parse response from {completions_url}: "
            f"{exc} — raw response: {str(data)[:200]}"
        ) from exc

    if not response_text:
        raise ValueError(
            f"OpenAI-compat: empty response from model {model!r} "
            f"at {completions_url}"
        )

    return response_text


# ---------------------------------------------------------------------------
# Internal helpers — Anthropic
# ---------------------------------------------------------------------------

async def _call_anthropic(
    images: list[bytes],
    prompt: str,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    """Call the Anthropic Messages API with one or more JPEG images.

    Uses the Anthropic ``/v1/messages`` endpoint directly via aiohttp rather
    than the anthropic SDK, keeping the Docker image small.

    Images are encoded as base64 and supplied as ``image`` content blocks of
    type ``"base64"``.  Anthropic's vision models accept multiple images in a
    single message, so all captured frames are sent together.

    Supported models include ``claude-3-5-sonnet-20241022``,
    ``claude-3-5-haiku-20241022``, ``claude-3-opus-20240229``, etc.

    Uses the module-level shared aiohttp session (see ``_get_session``).
    Does NOT use the anthropic SDK.

    Args:
        images: List of raw JPEG bytes to analyse.  All images are sent in
            a single API call as separate image content blocks.
        prompt: Text instruction for the model.
        api_key: Anthropic API key (starts with ``"sk-ant-"``).
        model: Anthropic model identifier string
            (e.g. ``"claude-3-5-haiku-20241022"``).
        timeout: Request timeout in seconds.

    Returns:
        Model response text from ``content[0].text``.

    Raises:
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds ``timeout`` seconds.
        ValueError: On HTTP 401 (invalid key), HTTP 404 (model not found),
            other non-200 status codes, or an empty/unparseable response.
    """
    # Build the list of content blocks: one image block per image, then text.
    # Anthropic's vision format uses a structured "source" object with base64 data.
    content_blocks: list[dict] = []
    for idx, img_bytes in enumerate(images):
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64,
            },
        })
        logger.debug(
            "Anthropic: added image %d/%d to request (%d bytes)",
            idx + 1, len(images), len(img_bytes),
        )

    # Append the text instruction after all images.
    content_blocks.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
        "max_tokens": 150,
        "messages": [{"role": "user", "content": content_blocks}],
    }

    headers = {
        "x-api-key": api_key,
        # anthropic-version is required; this value enables all current features.
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    messages_url = "https://api.anthropic.com/v1/messages"
    http_timeout = aiohttp.ClientTimeout(total=timeout)

    logger.debug(
        "Calling Anthropic API with model %r (%d image(s))",
        model, len(images),
    )

    session = await _get_session()
    async with session.post(
        messages_url, json=payload, headers=headers, timeout=http_timeout
    ) as resp:
        if resp.status == 401:
            raise ValueError(
                "Anthropic: HTTP 401 — check your API key"
            )
        if resp.status == 404:
            raise ValueError(
                f"Anthropic: HTTP 404 — model {model!r} not found"
            )
        if resp.status != 200:
            body = await resp.text()
            raise ValueError(
                f"Anthropic: HTTP {resp.status}: {body[:200]}"
            )
        data = await resp.json()

    # Anthropic's response puts the text in content[0].text.
    try:
        response_text: str = data["content"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"Anthropic: could not parse response: {exc} — "
            f"raw response: {str(data)[:200]}"
        ) from exc

    if not response_text:
        raise ValueError(
            f"Anthropic: empty response from model {model!r}"
        )

    return response_text


# ---------------------------------------------------------------------------
# Private utility
# ---------------------------------------------------------------------------

async def _fetch_image(
    session: aiohttp.ClientSession,
    url: str,
    label: str = "image",
    timeout: aiohttp.ClientTimeout | None = None,
) -> bytes | None:
    """Fetch a JPEG image from a URL using an existing aiohttp session.

    Intended for internal use only.  A per-request ``timeout`` may be supplied
    to override the session default for this individual call.

    Args:
        session: Active aiohttp.ClientSession to reuse.
        url: Full URL to fetch.
        label: Human-readable description for log messages.
        timeout: Optional per-request timeout.  If None, the session's default
            timeout is used.

    Returns:
        Raw image bytes, or None if the fetch failed.
    """
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.read()
                logger.debug("Fetched %s: %d bytes", label, len(data))
                return data
            else:
                logger.warning("HTTP %d fetching %s from %s", resp.status, label, url)
                return None
    except TimeoutError:
        logger.warning("Timed out fetching %s from %s", label, url)
        return None
    except aiohttp.ClientError as exc:
        logger.warning("Network error fetching %s: %s", label, exc)
        return None
