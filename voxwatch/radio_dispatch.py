"""
radio_dispatch.py — Segmented Radio Dispatch Audio for VoxWatch

Handles the police_dispatch (and similar) response mode's multi-segment audio
pipeline.  When a dispatch-style response mode is active, the standard single-TTS
approach is replaced with a two-step process:

  1. ``segment_dispatch_message()`` — takes the AI's structured JSON output and
     builds a list of short, plain-English dispatch segments to be spoken
     sequentially.  Each segment is a self-contained sentence that reads
     naturally over a police scanner.

  2. ``compose_dispatch_audio()`` — generates TTS for each segment in order,
     applies the radio static effect to each clip, inserts brief squelch pauses
     between them, and concatenates everything into a single WAV file that the
     caller can hand to ``AudioPipeline.push_audio()``.

Design goals:
  - Fully additive: no existing response mode code or pipeline logic is touched
    when a non-dispatch mode is active.
  - Non-fatal: every failure path falls back to a plain-text message so the
    deterrent always plays something.
  - Testable in isolation: both public functions accept simple Python types and
    return plain strings or booleans — no dependency on the running event loop
    beyond what callers already have.

Supported dispatch response mode names (mirrors the check in
``VoxWatchService._is_dispatch_mode()``):
  - ``"police_dispatch"``        — female dispatcher, 10-codes
  - ``"tony_montana_dispatch"``  — Tony Montana doing dispatch (theatrical)

Usage (from the service pipeline)::

    from voxwatch.radio_dispatch import segment_dispatch_message, compose_dispatch_audio

    # Initial Response / Stage 2: AI returned structured JSON
    segments = segment_dispatch_message(ai_json_str, stage="stage2", config=config)
    output_path = await compose_dispatch_audio(
        segments=segments,
        output_path="/data/audio/stage2_ready.wav",
        audio_pipeline=self._audio,
        config=config,
        stage_label="stage2",
    )
    # output_path is ready to push (or None on total failure)

Prerequisites:
  - ffmpeg on PATH (for concatenation and radio effect — same as audio_pipeline)
  - Working TTS provider (via the AudioPipeline's generate_tts method)
"""

import asyncio
import contextlib
import json
import logging
import os
import random

logger = logging.getLogger("voxwatch.radio_dispatch")

# ---------------------------------------------------------------------------
# Dispatch response mode registry
# ---------------------------------------------------------------------------

#: Response mode names that use the dispatch pipeline.  Any mode whose name
#: appears in this set will have its AI prompt replaced with a structured-JSON
#: prompt and its audio processed through this module instead of the standard
#: prefix/suffix concatenation.
#:
#: .. note::
#:     ``DISPATCH_PERSONAS`` is a backward-compatible alias for
#:     ``DISPATCH_MODES`` — external code that imported the old name still works.
DISPATCH_MODES: frozenset[str] = frozenset(
    {
        "police_dispatch",
        "tony_montana_dispatch",
    }
)

# Backward compatibility alias.
DISPATCH_PERSONAS: frozenset[str] = DISPATCH_MODES

# Squelch pause (seconds) inserted between consecutive dispatch segments to
# simulate the brief dead air between radio transmissions.
_SQUELCH_PAUSE_SECONDS: float = 0.45

# Duration (seconds) of the radio tuning static noise used in the channel intro.
_TUNING_STATIC_SECONDS: float = 1.0

# Duration (seconds) of the squelch pause that follows the random chatter
# snippet before the main dispatch call begins.
_INTRO_SQUELCH_SECONDS: float = 0.5

# Timeout (seconds) for the tuning static generation ffmpeg call.
_TUNING_STATIC_TIMEOUT_SECONDS: int = 10

# Timeout (seconds) for the channel intro concat ffmpeg call.
_INTRO_CONCAT_TIMEOUT_SECONDS: int = 20

# Maximum number of segments to generate per call.  Caps runaway AI output
# that might produce dozens of sentences.
_MAX_SEGMENTS: int = 6

# Timeout (seconds) for each ffmpeg segment-concatenation subprocess.
_CONCAT_TIMEOUT_SECONDS: int = 20

# Timeout (seconds) for the silence-generation ffmpeg call.
_SILENCE_GEN_TIMEOUT_SECONDS: int = 10

# Minimum and maximum pause (seconds) between the dispatcher's last segment
# and the officer acknowledgment.  Randomised on each call for realism.
_OFFICER_PAUSE_MIN: float = 1.5
_OFFICER_PAUSE_MAX: float = 2.5

# Default Kokoro voice to use for the officer response.  Overridden by
# config["response_mode"]["dispatch"]["officer_voice"].
_OFFICER_DEFAULT_VOICE: str = "am_fenrir"

# ---------------------------------------------------------------------------
# Channel intro — random chatter pool
# ---------------------------------------------------------------------------

#: Pool of short "tail end of another call" snippets played through the radio
#: effect before the main dispatch call.  Each entry is one sentence that
#: sounds like the close of a routine police transmission.  A random entry is
#: chosen on each event so the intro never repeats identically.
RANDOM_CHATTER: list[str] = [
    "...ten four, all clear... Oak Avenue. Resuming patrol.",
    "...copy that. No further action needed. Ten eight.",
    "...subject has left the area. Show us clear.",
    "...negative on that vehicle. Plates don't match. Disregard.",
    "...ten four, wrapping up on scene. Back in service.",
    "...all units, previous call... Fifth Street is code four. Resume normal.",
    "...roger. Suspect not located. Area canvas complete.",
    "...ten four. Alarm company confirms... false alarm. Resuming patrol.",
    "...show me ten eight. Heading back to district.",
    "...copy. Welfare check complete. All occupants accounted for.",
]

# ---------------------------------------------------------------------------
# Officer response text pool
# ---------------------------------------------------------------------------

#: Pool of short officer acknowledgment lines.  One is chosen at random on
#: each event so the response never sounds identical.  Template slots:
#:   {callsign} — unit designation from config (e.g. "Unit seven")
#:   {eta}      — spoken ETA word (e.g. "two") — always a word, never a digit
OFFICER_RESPONSES: list[str] = [
    "Copy... {callsign}, en route. E T A... {eta} minutes.",
    "Ten four... {callsign} responding.",
    "Copy, {callsign} responding, code three.",
    "Roger... {callsign} en route, E T A {eta}.",
    "Ten four. Show {callsign} responding.",
    "Copy that... {callsign} is ten seventy-six. E T A {eta} minutes.",
]

#: Spoken-word equivalents for small ETA integers.  ETA is randomised in
#: the range 2–5 and then converted to a word so TTS says "two" not "2".
_ETA_WORDS: dict[int, str] = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
}


# ---------------------------------------------------------------------------
# 10-code normalization for TTS
# ---------------------------------------------------------------------------

#: Maps numeric 10-codes to their spoken form so TTS engines say
#: "ten thirty-one" instead of "ten dash thirty-one".
_TEN_CODE_SPOKEN: dict[str, str] = {
    "10-4": "ten four",
    "10-15": "ten fifteen",
    "10-20": "ten twenty",
    "10-29": "ten twenty-nine",
    "10-31": "ten thirty-one",
    "10-70": "ten seventy",
    "10-97": "ten ninety-seven",
}


def normalize_dispatch_text(text: str) -> str:
    """Convert 10-codes, addresses, and dispatch shorthand to spoken-word form.

    TTS engines read "10-31" literally as "ten dash thirty-one" which sounds
    wrong.  Real dispatchers say "ten thirty-one".  This function replaces all
    known 10-codes with their spoken equivalents before the text is sent to TTS.

    Also normalizes:
      - "Code 3" → "code three"
      - Address numbers: "16039 Elm Street" → "one six zero three nine Elm Street"
        (dispatchers read address numbers digit-by-digit for clarity)

    Args:
        text: Raw dispatch text potentially containing 10-codes and addresses.

    Returns:
        Text with all codes and numbers normalized for natural TTS pronunciation.
    """

    result = text
    # Step 1: Replace known 10-codes FIRST (before digit expansion)
    for code, spoken in _TEN_CODE_SPOKEN.items():
        result = result.replace(code, spoken)

    # Step 2: Normalize "Code 3" → "code three"
    result = result.replace("Code 3", "code three")
    result = result.replace("code 3", "code three")

    # Step 3: Expand address numbers digit-by-digit
    # Dispatchers read "16039" as "one six zero three nine" for clarity.
    # Match sequences of 3+ digits that appear before a word (likely an address).
    result = _expand_address_numbers(result)

    return result


#: Digit-to-word map for address number expansion.
_DIGIT_WORDS: dict[str, str] = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}


def _expand_address_numbers(text: str) -> str:
    """Expand street address numbers to digit-by-digit spoken form.

    Dispatchers read address numbers one digit at a time for clarity over
    radio: "16039 Elm Street" becomes "one six zero three nine Elm Street".

    Only expands numbers that are 3+ digits and appear before a capitalized
    word (likely a street name), to avoid expanding other numbers like
    "ETA 2 minutes" or unit designations.

    Args:
        text: Text potentially containing address numbers.

    Returns:
        Text with address numbers expanded to digit words.
    """
    import re

    def _digits_to_words(match: re.Match) -> str:
        """Convert a matched number to space-separated digit words."""
        num_str = match.group(1)
        words = " ".join(_DIGIT_WORDS[d] for d in num_str)
        return words + match.group(2)  # Preserve the space + following text

    # Match 3+ digit numbers followed by a space and an uppercase letter
    # (e.g. "16039 Elm" but not "2 minutes" or "Unit 7")
    result = re.sub(r'\b(\d{3,})\b(\s+[A-Z])', _digits_to_words, text)
    return result


# ---------------------------------------------------------------------------
# Public: message segmentation
# ---------------------------------------------------------------------------


def segment_dispatch_message(
    ai_output: str,
    stage: str,
    config: dict,
) -> list[str]:
    """Convert AI structured JSON output into ordered dispatch speech segments.

    The dispatch AI prompts (``DISPATCH_STAGE2_PROMPT`` / ``DISPATCH_STAGE3_PROMPT``
    in ``ai_vision.py``) instruct the model to respond with a JSON object
    containing short factual fields.  This function parses that JSON and
    assembles the fields into natural-sounding dispatch sentences.

    If the AI returned a plain-text string (non-JSON, or the model ignored the
    format instruction), the string is used as a single segment so the
    deterrent always plays something.

    Address and agency resolution priority (first truthy value wins for address):

    1. ``response_mode.dispatch.full_address`` — new structured field set by
       the dashboard Dispatch Settings panel.
    2. ``response_mode.dispatch_address`` — legacy flat field (deprecated path).
    3. ``property.full_address`` — legacy top-level property section (deprecated).

    When ``response_mode.dispatch.include_address`` is ``False`` the resolved
    address is suppressed and all segments use generic phrasing ("the property")
    even if an address string is configured.

    Args:
        ai_output: Raw string returned by the AI vision module.  Expected to be
            a JSON object for Stage 2::

                {
                    "suspect_count": "one",
                    "description": "male, dark hoodie, gray pants",
                    "location": "approaching front door from driveway"
                }

            Or for Stage 3::

                {
                    "behavior": "testing gate latch, looking over shoulder",
                    "movement": "moved from driveway to side gate"
                }

            Non-JSON input is used verbatim as a single segment.
        stage: ``"stage2"`` or ``"stage3"``.  Controls which JSON schema is
            expected and which message template is applied.
        config: Full VoxWatch config dict.  Used to look up dispatch sub-config
            fields (``response_mode.dispatch``) for address, agency, and
            callsign that are injected into the spoken segments.

    Returns:
        Ordered list of plain-text strings, each representing one spoken
        dispatch segment.  Always contains at least one element.
    """
    # Read from response_mode first (new key), fall back to persona (legacy key).
    if "response_mode" in config:
        mode_cfg: dict = config["response_mode"]
    else:
        mode_cfg = config.get("persona", {})

    # ── Dispatch sub-config (new structured fields from the dashboard UI) ────
    dispatch_cfg: dict = mode_cfg.get("dispatch", {})

    # Resolve address: new sub-config full_address → legacy flat field →
    # legacy top-level property section.
    raw_address: str = (
        dispatch_cfg.get("full_address", "")
        or mode_cfg.get("dispatch_address", "")
        or config.get("property", {}).get("full_address", "")
    ).strip()

    # Honour the include_address flag — when False, suppress the address even
    # if one is configured so the user can reference the field without it
    # appearing in the spoken output.
    include_address: bool = dispatch_cfg.get("include_address", True)
    address: str = raw_address if include_address else ""

    # Agency name — e.g. "County Sheriff" → "County Sheriff dispatch, 10-97..."
    agency: str = dispatch_cfg.get("agency", "").strip()

    # Unit callsign — e.g. "Unit 7" → "Unit 7, respond code 3."
    callsign: str = dispatch_cfg.get("callsign", "").strip()

    persona_name: str = mode_cfg.get("name", "standard")

    # Try to parse the AI output as JSON.  AI models sometimes wrap JSON in
    # markdown fences (```json ... ```) — strip those before parsing.
    cleaned = ai_output.strip()
    if cleaned.startswith("```"):
        # Strip the opening fence line and the closing fence
        lines = cleaned.splitlines()
        # Drop first line (```json or ```) and last line (```) if it's a fence
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip().startswith("```"):
            inner_lines = inner_lines[:-1]
        cleaned = "\n".join(inner_lines).strip()

    parsed: dict | None = None
    try:
        candidate = json.loads(cleaned)
        if isinstance(candidate, dict):
            parsed = candidate
    except (json.JSONDecodeError, ValueError):
        # Non-JSON fallback handled below
        pass

    if parsed is None:
        # AI returned free text — use it verbatim as one segment
        logger.debug(
            "radio_dispatch: AI output is not JSON — using as single segment. "
            "Output: %s",
            ai_output[:200],
        )
        return [ai_output.strip()]

    # ── Stage 2: appearance + initial dispatch ────────────────────────────
    if stage == "stage2":
        return _build_stage2_segments(parsed, address, persona_name, agency, callsign)

    # ── Stage 3: behavioral escalation ───────────────────────────────────
    if stage == "stage3":
        return _build_stage3_segments(parsed, address, persona_name, agency, callsign)

    # Unknown stage — fall back to raw AI text if parseable
    logger.warning("radio_dispatch: unknown stage '%s' — returning raw AI output", stage)
    return [ai_output.strip()]


def _build_stage2_segments(
    parsed: dict,
    address: str,
    persona_name: str,
    agency: str = "",
    callsign: str = "",
) -> list[str]:
    """Build Stage 2 dispatch segments from parsed AI JSON.

    Constructs a 2–3 segment dispatch call describing the initial contact:
    an all-units alert (optionally prefixed with agency name and including
    the property address), a suspect description, and a location / unit
    callout.

    When ``agency`` is provided the first segment becomes:
    "County Sheriff dispatch, 10-97 at 123 Main Street."

    When ``callsign`` is provided the last segment closes with:
    "Unit 7, respond code 3." instead of "Nearest unit respond code 3."

    Args:
        parsed: Parsed AI JSON dict.  Expected keys: ``suspect_count``,
            ``description``, ``location``.  Missing keys degrade gracefully.
        address: Property address for the dispatch message.  Empty string
            when not configured or when include_address is False.
        persona_name: Active response mode name, used for mode-specific
            phrasing if needed in future extensions.
        agency: Optional responding agency name (e.g. "County Sheriff").
            Empty string when not configured.
        callsign: Optional unit callsign (e.g. "Unit 7").  Empty string
            when not configured.

    Returns:
        List of 2–3 plain-text dispatch segments.
    """
    suspect_count: str = parsed.get("suspect_count", "one").strip()
    description: str = parsed.get("description", "unknown clothing").strip()
    location: str = parsed.get("location", "").strip()

    segments: list[str] = []

    # Segment 1: Initial all-units alert.
    # Format varies based on which optional fields are configured:
    #   agency + address  → "County Sheriff dispatch, 10-97 at 123 Main St. ..."
    #   address only      → "All units, 10-97 at 123 Main St. ..."
    #   neither           → "All units, 10-97. ..."
    if agency and address:
        seg1_header = f"{agency} dispatch... 10-97 at {address}."
    elif agency:
        seg1_header = f"{agency} dispatch... 10-97."
    elif address:
        seg1_header = f"All units... 10-97 at {address}."
    else:
        seg1_header = "All units... 10-97."
    segments.append(f"{seg1_header} Reporting {suspect_count} subject on scene.")

    # Segment 2: Suspect description — add pauses between details.
    # Real dispatchers pause between each descriptor: "male... dark hoodie...
    # medium build."  Split on commas and rejoin with periods for hard pauses.
    desc_parts = [p.strip() for p in description.split(",") if p.strip()]
    if len(desc_parts) > 1:
        # Join with ". " to create hard pauses between each detail
        spaced_desc = ". ".join(desc_parts)
        segments.append(f"Suspect described as... {spaced_desc}.")
    else:
        segments.append(f"Suspect described as... {description}.")

    # Segment 3: Location + unit callout.
    # When callsign is configured address it directly; otherwise use generic.
    unit_phrase = f"{callsign}, respond... code three." if callsign else "Nearest unit, respond... code three."
    if location:
        segments.append(f"Last seen {location}. {unit_phrase}")
    else:
        segments.append(unit_phrase)

    return segments[:_MAX_SEGMENTS]


def _build_stage3_segments(
    parsed: dict,
    address: str,
    persona_name: str,
    agency: str = "",
    callsign: str = "",
) -> list[str]:
    """Build Stage 3 dispatch segments from parsed AI JSON.

    Constructs a 2–3 segment escalation update: a dispatch update header,
    the current behavior, and a crime-in-progress callout with backup request.

    When ``agency`` is configured the header names it:
    "County Sheriff dispatch update. 123 Main St. Suspect still on scene."

    When ``callsign`` is configured the backup request addresses it directly:
    "Unit 7, requesting backup." instead of "Requesting backup."

    Args:
        parsed: Parsed AI JSON dict.  Expected keys: ``behavior``, ``movement``.
            Missing keys degrade gracefully.
        address: Property address for the dispatch message.  Empty string
            when not configured or when include_address is False.
        persona_name: Active response mode name, used for mode-specific
            phrasing if needed in future extensions.
        agency: Optional responding agency name (e.g. "County Sheriff").
            Empty string when not configured.
        callsign: Optional unit callsign (e.g. "Unit 7").  Empty string
            when not configured.

    Returns:
        List of 2–3 plain-text dispatch segments.
    """
    behavior: str = parsed.get("behavior", "").strip()
    movement: str = parsed.get("movement", "").strip()

    segments: list[str] = []

    # Segment 1: Dispatch update header.
    # Include agency name and address when configured.
    update_prefix = f"{agency} dispatch... update." if agency else "Dispatch update."
    if address:
        segments.append(f"{update_prefix} {address}. Suspect still on scene.")
    else:
        segments.append(f"{update_prefix} Suspect still on scene.")

    # Segment 2: Behavior description
    if behavior:
        segments.append(f"Subject is... {behavior}.")
    elif movement:
        segments.append(f"Subject has {movement}.")
    else:
        segments.append("Subject is still in the area.")

    # Segment 3: Escalation — crime in progress.
    # Address callsign directly in the backup request when configured.
    backup_phrase = f"{callsign}... requesting backup." if callsign else "Requesting backup."
    if movement and behavior:
        segments.append(
            f"Be advised... subject has {movement}. "
            f"This is now a ten thirty-one, crime in progress. {backup_phrase}"
        )
    else:
        segments.append(
            f"This is now a ten thirty-one, crime in progress. {backup_phrase}"
        )

    return segments[:_MAX_SEGMENTS]


# ---------------------------------------------------------------------------
# Public: channel intro generation
# ---------------------------------------------------------------------------


async def _generate_system_voice_tts(
    text: str,
    output_path: str,
    audio_pipeline: object,
    config: dict,
) -> bool:
    """Generate TTS with piper for the 'connecting to channel' intro.

    The channel intro ("Connecting to dispatch frequency...") is a system
    announcement, not a human voice on the radio.  Piper's robotic tone
    sells the illusion of an automated security panel before the scanner
    audio kicks in.  Falls back to the standard TTS pipeline if piper is
    unavailable.

    Args:
        text: Text to synthesize (e.g. "Connecting to County Sheriff dispatch frequency...").
        output_path: Where to write the WAV file.
        audio_pipeline: The AudioPipeline instance with generate_tts().
        config: VoxWatch config dict.

    Returns:
        True if generation succeeded.
    """
    # Use piper for the robotic system voice — it sounds like an
    # automated panel, not a human, which is exactly what we want.
    try:
        piper_cfg = config.get("tts", {})
        piper_host = piper_cfg.get("piper_host", "").strip()
        if not piper_host:
            # Piper runs as a sidecar in Docker — try the default URL.
            piper_host = "http://piper:5000"

        import aiohttp
        async with aiohttp.ClientSession() as session, session.post(
            f"{piper_host}/api/tts",
            params={"text": text},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.read()
                with open(output_path, "wb") as f:
                    f.write(data)
                if os.path.exists(output_path):
                    logger.debug(
                        "System voice TTS via piper: %d bytes", len(data),
                    )
                    return True
    except Exception as exc:
        logger.debug("Piper system voice failed: %s — falling back", exc)

    # Fallback: use the standard TTS pipeline (whatever is configured).
    try:
        return await audio_pipeline.generate_tts(text, output_path)
    except Exception:
        return False


async def _copy_audio_to_wav(
    source_path: str,
    output_path: str,
    codec: str,
    sample_rate: str,
) -> bool:
    """Convert or copy an audio file to the pipeline's target codec/rate.

    Uses ffmpeg to transcode any supported input format (WAV, MP3, etc.)
    to the camera backchannel codec.  The input file is read from
    ``source_path`` and the result is written to ``output_path``.  Both
    paths must be absolute.

    Args:
        source_path: Absolute path to the input audio file.  Must exist.
            Supports any ffmpeg-decodable format (WAV, MP3, OGG, …).
        output_path: Absolute path where the converted WAV will be written.
        codec: ffmpeg codec name for the output (e.g. "pcm_mulaw").
        sample_rate: Output sample rate as a string (e.g. "8000").

    Returns:
        ``True`` if ffmpeg exited with return code 0 and ``output_path``
        exists.  ``False`` on any failure (missing ffmpeg, bad source, etc.).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", source_path,
            "-acodec", codec,
            "-ar", sample_rate,
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        return proc.returncode == 0 and os.path.exists(output_path)
    except Exception as exc:
        logger.debug("_copy_audio_to_wav: ffmpeg error: %s", exc)
        return False


async def generate_channel_intro(
    audio_pipeline,
    config: dict,
    output_dir: str,
) -> str | None:
    """Generate the "connecting to live radio" intro sequence.

    Builds a short 3-4 second preamble that plays before the main dispatch
    call to sell the illusion of tuning into an active police radio frequency.

    Source priority (first available wins):

    1. **Custom audio file** — ``dispatch.intro_audio`` in config points to a
       WAV or MP3 the user uploaded.  Converted to camera codec and used
       directly, skipping all TTS/chatter steps.

    2. **Pre-cached generated intro** — ``/data/audio/dispatch_intro_cached.wav``
       exists from a previous "Generate & Save" call in the dashboard.
       Converted to camera codec and used directly.

    3. **Auto-generate** — the full TTS + radio-chatter sequence is built
       from ``dispatch.intro_text`` (or the default connecting phrase when
       intro_text is empty).  The sequence is:

         a. Clean AI voice — configurable intro text with ``{agency}`` token.
         b. Radio tuning static — ~1 second pink-noise tremolo.
         c. Random chatter tail — one sentence from ``RANDOM_CHATTER``
            processed through the full radio effect.
         d. 0.5 s squelch pause before the main dispatch call.

    The tuning static WAV is generated fresh each call but is cheap to
    produce (pure ffmpeg lavfi, no TTS round-trip).

    Args:
        audio_pipeline: Live ``AudioPipeline`` instance.  Used for TTS
            generation, audio conversion, and the radio effect method.
        config: Full VoxWatch config dict.  The dispatch sub-config is read
            from ``config["response_mode"]["dispatch"]``.  Relevant keys:

            * ``intro_audio``   — path to a custom WAV/MP3 (highest priority).
            * ``intro_text``    — template text for auto-generation;
              supports ``{agency}`` substitution.
            * ``agency``        — agency name substituted into intro_text.

        output_dir: Directory where temporary and output WAV files will be
            written.  Should be ``audio_pipeline._serve_dir``.

    Returns:
        Absolute path to the composed intro WAV on success, or ``None`` if
        intro generation failed (caller should skip the intro and play the
        dispatch call directly — the failure is non-fatal).
    """
    codec: str = config.get("audio", {}).get("codec", "pcm_mulaw")
    sample_rate: str = str(config.get("audio", {}).get("sample_rate", 8000))

    # Resolve dispatch sub-config.
    dispatch_cfg: dict = (
        config.get("response_mode", config.get("persona", {})).get("dispatch", {})
    )
    agency: str = dispatch_cfg.get("agency", "").strip()

    # ── Priority 1: custom audio file ────────────────────────────────────────
    custom_intro_path: str = dispatch_cfg.get("intro_audio", "").strip()
    if custom_intro_path and os.path.exists(custom_intro_path):
        logger.debug(
            "radio_dispatch: using custom intro file: %s",
            custom_intro_path,
        )
        converted_path = os.path.join(output_dir, "channel_intro.wav")
        ok = await _copy_audio_to_wav(
            custom_intro_path, converted_path, codec, sample_rate
        )
        if ok:
            logger.debug("radio_dispatch: custom intro converted and ready.")
            return converted_path
        logger.warning(
            "radio_dispatch: custom intro file could not be converted (%s) "
            "— falling through to cached/auto-generate.",
            custom_intro_path,
        )

    # ── Priority 2: pre-cached generated intro ───────────────────────────────
    cached_intro_path = "/data/audio/dispatch_intro_cached.wav"
    if os.path.exists(cached_intro_path):
        logger.debug(
            "radio_dispatch: using cached generated intro: %s",
            cached_intro_path,
        )
        converted_path = os.path.join(output_dir, "channel_intro.wav")
        ok = await _copy_audio_to_wav(
            cached_intro_path, converted_path, codec, sample_rate
        )
        if ok:
            logger.debug("radio_dispatch: cached intro converted and ready.")
            return converted_path
        logger.warning(
            "radio_dispatch: cached intro could not be converted — "
            "falling through to auto-generate."
        )

    # ── Priority 3: auto-generate from intro_text ────────────────────────────
    # Resolve the connecting voice text.  The intro_text config key supports
    # an {agency} template token.  When intro_text is not configured the
    # default phrase is used so old configs keep working without changes.
    default_intro_text: str = (
        "Connecting to {agency} dispatch frequency..."
        if agency
        else "Connecting to dispatch frequency..."
    )
    intro_text_template: str = (
        dispatch_cfg.get("intro_text", "").strip() or default_intro_text
    )
    try:
        connecting_text: str = intro_text_template.format(agency=agency)
    except (KeyError, ValueError):
        # Malformed template — use verbatim (graceful degradation).
        connecting_text = intro_text_template

    all_temp_paths: list[str] = []
    intro_parts: list[str] = []

    try:
        # ── Part 1: system voice for "Connecting to..." ──────────────────────
        # Uses a different Kokoro voice (calm, neutral) than the dispatcher
        # to sound like a modern security system / automated panel.
        # Falls back to espeak only if Kokoro is unavailable.
        connecting_tts_path = os.path.join(output_dir, "intro_connecting_tts.wav")
        connecting_conv_path = os.path.join(output_dir, "intro_connecting_conv.wav")
        all_temp_paths.extend([connecting_tts_path, connecting_conv_path])

        tts_ok = await _generate_system_voice_tts(
            connecting_text, connecting_tts_path, audio_pipeline, config,
        )
        if not tts_ok:
            logger.warning("radio_dispatch: intro connecting TTS failed — skipping intro")
            _cleanup_paths(all_temp_paths)
            return None

        conv_ok = await audio_pipeline.convert_audio(connecting_tts_path, connecting_conv_path)
        if not conv_ok:
            logger.warning("radio_dispatch: intro connecting conversion failed — skipping intro")
            _cleanup_paths(all_temp_paths)
            return None

        # No radio effect on the connecting voice — it is the AI system speaking.
        intro_parts.append(connecting_conv_path)

        # ── Part 2: radio tuning static ──────────────────────────────────────
        tuning_path = os.path.join(output_dir, "intro_tuning_static.wav")
        all_temp_paths.append(tuning_path)
        tuning_ok = await _generate_tuning_static(tuning_path, sample_rate, codec)
        if tuning_ok:
            intro_parts.append(tuning_path)
        else:
            logger.debug("radio_dispatch: tuning static generation failed — skipping that part")

        # ── Part 3: random chatter tail (radio-processed) ────────────────────
        chatter_text = normalize_dispatch_text(random.choice(RANDOM_CHATTER))
        chatter_tts_path = os.path.join(output_dir, "intro_chatter_tts.wav")
        chatter_conv_path = os.path.join(output_dir, "intro_chatter_conv.wav")
        all_temp_paths.extend([chatter_tts_path, chatter_conv_path])

        # Use a different Kokoro voice for the chatter when one is available so
        # it sounds like a distinct officer rather than the main dispatcher.
        chatter_tts_ok = await _generate_chatter_tts(
            chatter_text, chatter_tts_path, audio_pipeline, config
        )

        if chatter_tts_ok:
            chatter_conv_ok = await audio_pipeline.convert_audio(
                chatter_tts_path, chatter_conv_path
            )
            if chatter_conv_ok:
                # Apply the full radio effect — this audio is "coming through the scanner".
                try:
                    await audio_pipeline._apply_radio_effect(chatter_conv_path)
                except Exception as exc:
                    logger.debug(
                        "radio_dispatch: radio effect on chatter failed: %s — keeping clean", exc
                    )
                intro_parts.append(chatter_conv_path)
            else:
                logger.debug("radio_dispatch: chatter conversion failed — skipping chatter")
        else:
            logger.debug("radio_dispatch: chatter TTS failed — skipping chatter")

        # ── Part 4: squelch pause before the main dispatch begins ─────────────
        intro_squelch_path = os.path.join(output_dir, "intro_squelch.wav")
        all_temp_paths.append(intro_squelch_path)
        squelch_ok = await _generate_fixed_pause(
            intro_squelch_path, _INTRO_SQUELCH_SECONDS, sample_rate, codec
        )
        if squelch_ok:
            intro_parts.append(intro_squelch_path)

        if not intro_parts:
            logger.warning("radio_dispatch: no intro parts produced — skipping intro")
            _cleanup_paths(all_temp_paths)
            return None

        # ── Concatenate all intro parts into one file ─────────────────────────
        intro_output_path = os.path.join(output_dir, "channel_intro.wav")
        concat_list_path = os.path.join(output_dir, "intro_concat.txt")
        all_temp_paths.append(concat_list_path)

        with open(concat_list_path, "w", encoding="utf-8") as fh:
            for part_path in intro_parts:
                fh.write(f"file '{part_path}'\n")

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-acodec", codec,
            "-ar", sample_rate,
            "-ac", "1",
            intro_output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_INTRO_CONCAT_TIMEOUT_SECONDS)

        if proc.returncode != 0 or not os.path.exists(intro_output_path):
            logger.warning(
                "radio_dispatch: intro concat failed (rc=%d) — skipping intro",
                proc.returncode,
            )
            _cleanup_paths(all_temp_paths)
            return None

        logger.debug(
            "radio_dispatch: channel intro composed (%d parts) → %s",
            len(intro_parts),
            os.path.basename(intro_output_path),
        )
        _cleanup_paths(all_temp_paths)
        return intro_output_path

    except Exception as exc:
        logger.warning(
            "radio_dispatch: channel intro generation error: %s — skipping intro", exc
        )
        _cleanup_paths(all_temp_paths)
        return None


# ---------------------------------------------------------------------------
# Public: audio composition
# ---------------------------------------------------------------------------


async def compose_dispatch_audio(
    segments: list[str],
    output_path: str,
    audio_pipeline,
    config: dict,
    stage_label: str,
) -> str | None:
    """Generate and compose segmented dispatch audio into a single WAV file.

    For each segment:
      1. Generate TTS to a temporary file via ``audio_pipeline.generate_tts()``.
      2. Convert to the camera's codec via ``audio_pipeline.convert_audio()``.
      3. Apply the radio static effect via ``audio_pipeline._apply_radio_effect()``.
      4. Insert a squelch-pause WAV between segments.

    The resulting files are concatenated with ffmpeg into ``output_path``.  If
    TTS or conversion fails for any individual segment, that segment is silently
    skipped so the remaining segments still play.  If all segments fail, ``None``
    is returned and the caller should fall back to plain TTS.

    The function is non-fatal by design: every exception is caught and logged;
    the pipeline always gets either a completed audio file or a clear ``None``
    signal to fall back on.

    Args:
        segments: Ordered list of plain-text strings, one per dispatch segment.
            Produced by ``segment_dispatch_message()``.
        output_path: Absolute path where the final concatenated WAV should be
            written.  The caller is responsible for placing this under the
            AudioPipeline's ``_serve_dir`` so it can be pushed via go2rtc.
        audio_pipeline: Live ``AudioPipeline`` instance.  Used for TTS
            generation, audio conversion, and the radio effect method.
        config: Full VoxWatch config dict.  Passed through to audio_pipeline
            helpers that need codec/sample-rate settings.
        stage_label: Label string used for temp-file naming and log messages.
            Expected values: ``"stage2"`` or ``"stage3"``.

    Returns:
        ``output_path`` on success, or ``None`` if composition failed entirely.
    """
    if not segments:
        logger.warning("radio_dispatch: compose called with empty segments list")
        return None

    serve_dir: str = audio_pipeline._serve_dir
    codec: str = config.get("audio", {}).get("codec", "pcm_mulaw")
    sample_rate: str = str(config.get("audio", {}).get("sample_rate", 8000))

    # ── Optional channel intro ────────────────────────────────────────────────
    # When enabled (default True) a short "connecting to live radio" preamble
    # is generated and prepended to the dispatch audio.  Failure is non-fatal:
    # the main dispatch call plays regardless.
    dispatch_cfg: dict = (
        config.get("response_mode", config.get("persona", {})).get("dispatch", {})
    )
    channel_intro_enabled: bool = dispatch_cfg.get("channel_intro", True)
    intro_path: str | None = None
    if channel_intro_enabled:
        intro_path = await generate_channel_intro(
            audio_pipeline=audio_pipeline,
            config=config,
            output_dir=serve_dir,
        )
        if intro_path:
            logger.debug("radio_dispatch: channel intro ready at %s", os.path.basename(intro_path))
        else:
            logger.debug("radio_dispatch: channel intro skipped (generation failed or disabled)")

    # ── Dispatcher voice / speed config ──────────────────────────────────────
    # When the TTS provider supports per-role voice selection, inject the
    # dispatcher-specific voice into a shallow config copy so the dispatcher
    # sounds different from both the officer and the main deterrent voice.
    # The live config is never mutated — only the local copy changes.
    tts_provider: str = config.get("tts", {}).get("provider", "piper")
    is_kokoro: bool = tts_provider == "kokoro"
    is_openai_tts: bool = tts_provider == "openai"
    is_elevenlabs: bool = tts_provider == "elevenlabs"
    dispatcher_speed: float = float(dispatch_cfg.get("dispatcher_speed", 0.9))

    # Resolve dispatcher voice by active provider.
    # Provider priority: per-role dispatch field → provider default.
    # We do NOT fall back to the global tts voice so the dispatcher always
    # sounds professional regardless of the user's main deterrent voice choice.
    if is_kokoro:
        dispatcher_voice: str = (
            dispatch_cfg.get("dispatcher_voice", "").strip() or "af_bella"
        )
    elif is_openai_tts:
        dispatcher_voice = (
            dispatch_cfg.get("dispatcher_openai_voice", "").strip() or "nova"
        )
    elif is_elevenlabs:
        dispatcher_voice = (
            dispatch_cfg.get("dispatcher_elevenlabs_voice", "").strip()
            or "46zEzba8Y8yQ0bVcv5O9"  # Steady Dispatcher — police female
        )
    else:
        dispatcher_voice = ""  # Not used for piper/espeak

    # Build a dispatcher-specific config copy with voice and speed overrides.
    # Only the relevant provider sub-dict is copied; everything else is shared
    # by reference to keep the copy cheap.
    if is_kokoro:
        dispatcher_config: dict = dict(config)
        disp_tts_section: dict = dict(config.get("tts", {}))
        disp_kokoro_section: dict = dict(disp_tts_section.get("kokoro", {}))
        disp_kokoro_section["voice"] = dispatcher_voice
        disp_kokoro_section["speed"] = dispatcher_speed
        disp_tts_section["kokoro"] = disp_kokoro_section
        dispatcher_config["tts"] = disp_tts_section
    elif is_openai_tts:
        dispatcher_config = dict(config)
        disp_tts_section = dict(config.get("tts", {}))
        disp_openai_section: dict = dict(disp_tts_section.get("openai", {}))
        disp_openai_section["voice"] = dispatcher_voice
        disp_openai_section["speed"] = dispatcher_speed
        disp_tts_section["openai"] = disp_openai_section
        dispatcher_config["tts"] = disp_tts_section
    elif is_elevenlabs:
        dispatcher_config = dict(config)
        disp_tts_section = dict(config.get("tts", {}))
        disp_el_section: dict = dict(disp_tts_section.get("elevenlabs", {}))
        disp_el_section["voice_id"] = dispatcher_voice
        disp_tts_section["elevenlabs"] = disp_el_section
        dispatcher_config["tts"] = disp_tts_section
    else:
        dispatcher_config = config

    # Temporary per-segment WAV files that will be concatenated.
    segment_paths: list[str] = []
    # Track all temp files for cleanup even if we bail early.  Include the
    # intro WAV here so every failure-path _cleanup_paths() call removes it.
    all_temp_paths: list[str] = ([intro_path] if intro_path else [])

    # Cache the live audio_pipeline config so it can be restored after each
    # segment TTS call that swaps in the dispatcher config.
    original_pipeline_config = audio_pipeline.config

    # --- Generate and process each segment ---
    for idx, segment_text in enumerate(segments):
        seg_tts_path = os.path.join(serve_dir, f"{stage_label}_dispatch_tts_{idx}.wav")
        seg_conv_path = os.path.join(serve_dir, f"{stage_label}_dispatch_conv_{idx}.wav")
        all_temp_paths.extend([seg_tts_path, seg_conv_path])

        # Step A: TTS generation — normalize 10-codes to spoken form first
        # so TTS says "ten thirty-one" not "ten dash thirty-one".
        # For providers that support per-role voices (Kokoro, OpenAI, ElevenLabs),
        # temporarily swap in the dispatcher config (voice + speed).  The finally
        # block always restores the original pipeline config so that subsequent
        # segments and the officer response use the correct settings.
        spoken_text = normalize_dispatch_text(segment_text)
        disp_needs_swap: bool = is_kokoro or is_openai_tts or is_elevenlabs
        if disp_needs_swap:
            audio_pipeline.config = dispatcher_config
        tts_ok: bool = False
        _tts_exc_logged: bool = False
        try:
            tts_ok = await audio_pipeline.generate_tts(spoken_text, seg_tts_path)
        except Exception as exc:
            logger.warning(
                "radio_dispatch: TTS failed for segment %d/%d: %s — skipping segment",
                idx + 1,
                len(segments),
                exc,
            )
            _tts_exc_logged = True
        finally:
            if disp_needs_swap:
                audio_pipeline.config = original_pipeline_config

        if not tts_ok:
            if not _tts_exc_logged:
                logger.warning(
                    "radio_dispatch: TTS returned False for segment %d/%d — skipping",
                    idx + 1,
                    len(segments),
                )
            continue

        # Step B: Convert to camera codec
        try:
            conv_ok = await audio_pipeline.convert_audio(seg_tts_path, seg_conv_path)
        except Exception as exc:
            logger.warning(
                "radio_dispatch: audio conversion failed for segment %d/%d: %s — skipping",
                idx + 1,
                len(segments),
                exc,
            )
            continue

        if not conv_ok:
            logger.warning(
                "radio_dispatch: convert_audio returned False for segment %d/%d — skipping",
                idx + 1,
                len(segments),
            )
            continue

        # Step C: Apply radio static effect
        try:
            await audio_pipeline._apply_radio_effect(seg_conv_path)
        except Exception as exc:
            # Non-fatal: keep the clean audio if the radio effect fails
            logger.debug(
                "radio_dispatch: radio effect failed for segment %d/%d: %s — "
                "keeping clean audio",
                idx + 1,
                len(segments),
                exc,
            )

        segment_paths.append(seg_conv_path)
        logger.debug(
            "radio_dispatch: segment %d/%d ready: '%s...'",
            idx + 1,
            len(segments),
            segment_text[:60],
        )

    if not segment_paths:
        logger.error(
            "radio_dispatch: all %d segments failed — cannot compose dispatch audio",
            len(segments),
        )
        _cleanup_paths(all_temp_paths)
        return None

    # --- Generate squelch-pause WAV ---
    squelch_path = os.path.join(serve_dir, f"{stage_label}_dispatch_squelch.wav")
    all_temp_paths.append(squelch_path)
    squelch_ok = await _generate_squelch_pause(
        squelch_path, sample_rate, codec,
    )

    # --- Concatenate segments with squelch pauses between them ---
    concat_list_path = os.path.join(serve_dir, f"{stage_label}_dispatch_concat.txt")
    all_temp_paths.append(concat_list_path)

    try:
        with open(concat_list_path, "w", encoding="utf-8") as fh:
            # Prepend the channel intro when it was successfully generated.
            # It already contains the connecting voice + tuning static +
            # random chatter + closing squelch as one continuous clip.
            if intro_path and os.path.exists(intro_path):
                fh.write(f"file '{intro_path}'\n")
            for i, seg_path in enumerate(segment_paths):
                fh.write(f"file '{seg_path}'\n")
                # Insert squelch pause between segments (not after the last one)
                if squelch_ok and i < len(segment_paths) - 1:
                    fh.write(f"file '{squelch_path}'\n")
    except OSError as exc:
        logger.error(
            "radio_dispatch: cannot write concat list: %s — aborting", exc
        )
        _cleanup_paths(all_temp_paths)
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-acodec", codec,
            "-ar", sample_rate,
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_CONCAT_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.error("radio_dispatch: ffmpeg concat timed out — aborting")
        _cleanup_paths(all_temp_paths)
        return None
    except Exception as exc:
        logger.error("radio_dispatch: ffmpeg concat error: %s — aborting", exc)
        _cleanup_paths(all_temp_paths)
        return None

    if proc.returncode != 0 or not os.path.exists(output_path):
        logger.error(
            "radio_dispatch: ffmpeg concat returned rc=%d — aborting",
            proc.returncode,
        )
        _cleanup_paths(all_temp_paths)
        return None

    logger.info(
        "radio_dispatch: composed %d segment(s) into %s",
        len(segment_paths),
        os.path.basename(output_path),
    )

    # ── Optional officer response ─────────────────────────────────────────────
    # When officer_response is enabled (default True), generate a short male-
    # voice acknowledgment and append it after a randomised pause so the final
    # output is: [dispatcher segments] + [pause] + [officer clip].
    # The whole thing becomes a single WAV pushed as one audio event.
    # Failure at any sub-step is non-fatal: the dispatcher audio is preserved.
    officer_response_enabled: bool = dispatch_cfg.get("officer_response", True)
    if officer_response_enabled:
        officer_wav_path = os.path.join(serve_dir, f"{stage_label}_officer_resp.wav")
        officer_pause_path = os.path.join(serve_dir, f"{stage_label}_officer_pause.wav")

        # Step 1: Generate the randomised silence between dispatcher and officer.
        pause_duration: float = random.uniform(_OFFICER_PAUSE_MIN, _OFFICER_PAUSE_MAX)
        pause_ok = await _generate_fixed_pause(
            officer_pause_path, pause_duration, sample_rate, codec
        )

        # Step 2: Generate the officer response audio clip.
        officer_result = await generate_officer_response(
            audio_pipeline=audio_pipeline,
            config=config,
            output_path=officer_wav_path,
        )

        if officer_result and pause_ok and os.path.exists(officer_pause_path):
            # All three pieces ready — append pause + officer clip to the
            # dispatcher output using a final ffmpeg concat pass.
            import shutil as _shutil_officer
            interim_path = output_path + ".pre_officer.wav"
            try:
                _shutil_officer.copy2(output_path, interim_path)
            except OSError as exc:
                logger.warning(
                    "radio_dispatch: could not copy dispatcher audio for officer concat: %s "
                    "— playing dispatcher only",
                    exc,
                )
                _cleanup_paths([officer_wav_path, officer_pause_path])
            else:
                officer_concat_list = os.path.join(
                    serve_dir, f"{stage_label}_officer_concat.txt"
                )
                merged_ok = False
                try:
                    with open(officer_concat_list, "w", encoding="utf-8") as fh:
                        fh.write(f"file '{interim_path}'\n")
                        fh.write(f"file '{officer_pause_path}'\n")
                        fh.write(f"file '{officer_wav_path}'\n")
                    proc2 = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", officer_concat_list,
                        "-acodec", codec,
                        "-ar", sample_rate,
                        "-ac", "1",
                        output_path,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(proc2.wait(), timeout=_CONCAT_TIMEOUT_SECONDS)
                    if proc2.returncode == 0 and os.path.exists(output_path):
                        merged_ok = True
                        logger.info(
                            "radio_dispatch: officer response appended to %s "
                            "(pause=%.1fs)",
                            os.path.basename(output_path),
                            pause_duration,
                        )
                    else:
                        logger.warning(
                            "radio_dispatch: officer concat failed (rc=%d) "
                            "— restoring dispatcher-only audio",
                            proc2.returncode,
                        )
                except Exception as exc:
                    logger.warning(
                        "radio_dispatch: officer concat error: %s "
                        "— restoring dispatcher-only audio",
                        exc,
                    )
                finally:
                    if not merged_ok:
                        with contextlib.suppress(OSError):
                            _shutil_officer.copy2(interim_path, output_path)
                    _cleanup_paths(
                        [officer_concat_list, interim_path, officer_wav_path, officer_pause_path]
                    )
        else:
            _cleanup_paths([officer_wav_path, officer_pause_path])
            logger.debug(
                "radio_dispatch: officer response unavailable "
                "(result=%s pause_ok=%s) — playing dispatcher only",
                bool(officer_result),
                pause_ok,
            )

    # Clean up all segment temp files (the concat output is kept for the push).
    # The intro WAV is already in all_temp_paths (added at initialisation above)
    # and is removed here since it has been folded into the final output_path.
    _cleanup_paths(all_temp_paths)
    return output_path


# ---------------------------------------------------------------------------
# Public: officer response generation
# ---------------------------------------------------------------------------


async def generate_officer_response(
    audio_pipeline,
    config: dict,
    output_path: str,
) -> str | None:
    """Generate an officer radio acknowledgment response clip.

    Selects a random acknowledgment line from ``OFFICER_RESPONSES``, fills in
    the configured callsign and a randomised ETA word (2–5 minutes, always
    spelled out as a word so TTS says "two" not "2"), normalises any embedded
    10-codes via ``normalize_dispatch_text``, and synthesises TTS using a male
    Kokoro voice that is distinct from the dispatcher's configured voice.

    Voice selection strategy:
      - When Kokoro is the active TTS provider, the officer voice is injected
        by temporarily swapping ``audio_pipeline.config`` for a shallow copy
        containing ``officer_voice``.  The swap is atomic within a try/finally
        block so the live config is always restored even on exception.
      - For all other TTS providers, the default voice is used and the
        resulting audio is pitch-shifted downward via ffmpeg's ``asetrate``
        trick to audibly distinguish it from the dispatcher.

    The clip also receives the same radio effect processing as the dispatcher
    segments so both voices sound like they came from the same channel.

    Args:
        audio_pipeline: Live ``AudioPipeline`` instance used for TTS
            generation (``generate_tts``), codec conversion
            (``convert_audio``), and radio processing
            (``_apply_radio_effect``).
        config: Full VoxWatch config dict.  Reads
            ``response_mode.dispatch.officer_callsign``,
            ``response_mode.dispatch.officer_voice``, and
            ``response_mode.dispatch.callsign`` (fallback callsign).
        output_path: Absolute path where the finished officer WAV should be
            written.  The caller is responsible for any cleanup.

    Returns:
        ``output_path`` on success, or ``None`` if any step fails.  Failure
        is intentionally non-fatal — the caller still pushes the dispatcher
        audio without the officer clip.
    """
    dispatch_cfg: dict = (
        config.get("response_mode", config.get("persona", {}))
        .get("dispatch", {})
    )

    # ── Callsign ──────────────────────────────────────────────────────────────
    # Prefer officer_callsign, fall back to the shared dispatch callsign,
    # then a human-readable default.
    callsign: str = (
        dispatch_cfg.get("officer_callsign", "").strip()
        or dispatch_cfg.get("callsign", "").strip()
        or "Unit seven"
    )

    # ── ETA ───────────────────────────────────────────────────────────────────
    eta_int: int = random.randint(2, 5)
    eta_word: str = _ETA_WORDS.get(eta_int, str(eta_int))

    # ── Response text ─────────────────────────────────────────────────────────
    template: str = random.choice(OFFICER_RESPONSES)
    response_text: str = template.format(callsign=callsign, eta=eta_word)
    response_text = normalize_dispatch_text(response_text)

    logger.debug("radio_dispatch: officer response text: '%s'", response_text)

    # ── Voice / config setup ──────────────────────────────────────────────────
    serve_dir: str = audio_pipeline._serve_dir
    config.get("audio", {}).get("codec", "pcm_mulaw")
    str(config.get("audio", {}).get("sample_rate", 8000))

    tts_provider: str = config.get("tts", {}).get("provider", "piper")
    is_kokoro: bool = tts_provider == "kokoro"
    is_openai_tts: bool = tts_provider == "openai"
    is_elevenlabs: bool = tts_provider == "elevenlabs"
    officer_speed: float = float(dispatch_cfg.get("officer_speed", 1.0))

    # Resolve officer voice by active provider.
    # Each provider has its own config field so the user can set distinct
    # male voices for the officer regardless of the global TTS voice.
    if is_kokoro:
        officer_voice: str = (
            dispatch_cfg.get("officer_voice", "").strip() or _OFFICER_DEFAULT_VOICE
        )
    elif is_openai_tts:
        officer_voice = (
            dispatch_cfg.get("officer_openai_voice", "").strip() or "onyx"
        )
    elif is_elevenlabs:
        officer_voice = (
            dispatch_cfg.get("officer_elevenlabs_voice", "").strip()
            or "ErXwobaYiN019PkySvjV"  # Antoni — deep male
        )
    else:
        officer_voice = ""  # Not used for piper/espeak; pitch-shift applied instead

    # Build an officer config copy with the male voice and speed injected so
    # that generate_tts() picks them up.  Only the relevant provider sub-dict
    # is copied; everything else is shared by reference to keep the copy cheap.
    if is_kokoro:
        officer_config: dict = dict(config)
        tts_section: dict = dict(config.get("tts", {}))
        kokoro_section: dict = dict(tts_section.get("kokoro", {}))
        kokoro_section["voice"] = officer_voice
        kokoro_section["speed"] = officer_speed
        tts_section["kokoro"] = kokoro_section
        officer_config["tts"] = tts_section
    elif is_openai_tts:
        officer_config = dict(config)
        tts_section = dict(config.get("tts", {}))
        openai_section: dict = dict(tts_section.get("openai", {}))
        openai_section["voice"] = officer_voice
        openai_section["speed"] = officer_speed
        tts_section["openai"] = openai_section
        officer_config["tts"] = tts_section
    elif is_elevenlabs:
        officer_config = dict(config)
        tts_section = dict(config.get("tts", {}))
        el_section: dict = dict(tts_section.get("elevenlabs", {}))
        el_section["voice_id"] = officer_voice
        tts_section["elevenlabs"] = el_section
        officer_config["tts"] = tts_section
    else:
        officer_config = config

    # ── TTS generation ────────────────────────────────────────────────────────
    tts_path = os.path.join(serve_dir, "_officer_tts.wav")
    conv_path = os.path.join(serve_dir, "_officer_conv.wav")
    temp_paths: list[str] = [tts_path, conv_path]

    # Temporarily swap audio_pipeline.config so generate_tts picks up the
    # officer_voice override.  The swap applies for any provider that has a
    # per-role voice configured (kokoro, openai, elevenlabs).  The finally
    # block always restores the original config even on exception.
    needs_config_swap: bool = is_kokoro or is_openai_tts or is_elevenlabs
    original_config = audio_pipeline.config
    if needs_config_swap:
        audio_pipeline.config = officer_config
    try:
        tts_ok = await audio_pipeline.generate_tts(response_text, tts_path)
    except Exception as exc:
        logger.warning(
            "radio_dispatch: officer TTS generation raised an exception: %s "
            "— skipping officer response",
            exc,
        )
        _cleanup_paths(temp_paths)
        return None
    finally:
        if needs_config_swap:
            audio_pipeline.config = original_config

    if not tts_ok:
        logger.warning(
            "radio_dispatch: officer TTS returned False — skipping officer response"
        )
        _cleanup_paths(temp_paths)
        return None

    # ── Pitch-shift for providers without per-role voice selection ────────────
    # For providers that don't support voice selection per role (piper, espeak,
    # cartesia, polly), lower the voice pitch by declaring a higher input sample
    # rate so ffmpeg slows playback then resamples back to the correct rate.
    # This shifts perceived pitch downward ~2 semitones, producing a distinct-
    # sounding voice with minimal quality loss.
    # Kokoro, OpenAI, and ElevenLabs are excluded — they each have dedicated
    # male voice options configured above.
    if not is_kokoro and not is_openai_tts and not is_elevenlabs:
        pitched_path = os.path.join(serve_dir, "_officer_pitched.wav")
        temp_paths.append(pitched_path)
        pitch_ok = await _pitch_shift_down(tts_path, pitched_path)
        if pitch_ok and os.path.exists(pitched_path):
            try:
                os.replace(pitched_path, tts_path)
                temp_paths = [p for p in temp_paths if p != pitched_path]
            except OSError:
                pass  # Non-fatal — continue with unshifted audio

    # ── Convert to camera codec ───────────────────────────────────────────────
    try:
        conv_ok = await audio_pipeline.convert_audio(tts_path, conv_path)
    except Exception as exc:
        logger.warning(
            "radio_dispatch: officer audio conversion raised an exception: %s "
            "— skipping officer response",
            exc,
        )
        _cleanup_paths(temp_paths)
        return None

    if not conv_ok:
        logger.warning(
            "radio_dispatch: officer convert_audio returned False — skipping officer response"
        )
        _cleanup_paths(temp_paths)
        return None

    # ── Radio effect ──────────────────────────────────────────────────────────
    try:
        await audio_pipeline._apply_radio_effect(conv_path)
    except Exception as exc:
        # Non-fatal: a clean-audio officer response is still better than none.
        logger.debug(
            "radio_dispatch: radio effect failed for officer clip: %s "
            "— using clean audio",
            exc,
        )

    # ── Move to caller's output_path ──────────────────────────────────────────
    try:
        if conv_path != output_path:
            import shutil as _shutil
            _shutil.move(conv_path, output_path)
            temp_paths = [p for p in temp_paths if p != conv_path]
    except OSError as exc:
        logger.warning(
            "radio_dispatch: could not move officer clip to '%s': %s "
            "— skipping officer response",
            output_path,
            exc,
        )
        _cleanup_paths(temp_paths)
        return None

    _cleanup_paths(temp_paths)

    # Resolve a readable voice label for the log message.
    if is_kokoro or is_openai_tts or is_elevenlabs:
        voice_label = f"{tts_provider}:{officer_voice}"
    else:
        voice_label = f"{tts_provider}:pitch-shifted"
    logger.info(
        "radio_dispatch: officer response ready — voice=%s callsign='%s' eta=%s min",
        voice_label,
        callsign,
        eta_word,
    )
    return output_path


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _generate_squelch_pause(
    output_path: str,
    sample_rate: str,
    codec: str,
) -> bool:
    """Generate a short silence WAV for use as the inter-segment squelch gap.

    Uses ffmpeg's ``anullsrc`` lavfi source to produce exactly
    ``_SQUELCH_PAUSE_SECONDS`` of silence encoded in the camera's codec.
    This is the same technique used by ``AudioPipeline._generate_tone_gap()``.

    Args:
        output_path: Path where the silence WAV should be written.
        sample_rate: Sample rate string (e.g. ``"8000"``).
        codec: ffmpeg codec name (e.g. ``"pcm_mulaw"``).

    Returns:
        True if the file was created successfully, False otherwise.
    """
    try:
        duration = str(_SQUELCH_PAUSE_SECONDS)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=mono",
            "-t", duration,
            "-acodec", codec,
            "-ar", sample_rate,
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_SILENCE_GEN_TIMEOUT_SECONDS)
        success = proc.returncode == 0 and os.path.exists(output_path)
        if not success:
            logger.debug(
                "radio_dispatch: squelch pause generation failed (rc=%d)",
                proc.returncode,
            )
        return success
    except Exception as exc:
        logger.debug("radio_dispatch: squelch pause generation error: %s", exc)
        return False


async def _generate_tuning_static(
    output_path: str,
    sample_rate: str,
    codec: str,
) -> bool:
    """Generate a short radio-tuning static WAV using ffmpeg lavfi.

    Uses pink noise passed through a tremolo filter and a bandpass to create
    the characteristic sweeping sound of a scanner locking onto a frequency.
    The tremolo's rapid amplitude oscillation (8 Hz, 70% depth) mimics the
    pulsing you hear when a radio scans across channels.

    Filter chain:
      - ``anoisesrc`` — pink noise source at low amplitude (0.08) to avoid
        overpowering speech
      - ``tremolo=f=8:d=0.7`` — 8 Hz tremolo at 70% depth for the scanning pulse
      - ``highpass=f=200`` — remove sub-bass content
      - ``lowpass=f=4000`` — remove frequencies above typical radio range

    Args:
        output_path: Path where the tuning static WAV should be written.
        sample_rate: Sample rate string (e.g. ``"8000"``).
        codec: ffmpeg codec name (e.g. ``"pcm_mulaw"``).

    Returns:
        True if the file was created successfully, False otherwise.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anoisesrc=d={_TUNING_STATIC_SECONDS}:c=pink:a=0.08",
            "-af", "tremolo=f=8:d=0.7,highpass=f=200,lowpass=f=4000",
            "-acodec", codec,
            "-ar", sample_rate,
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_TUNING_STATIC_TIMEOUT_SECONDS)
        success = proc.returncode == 0 and os.path.exists(output_path)
        if not success:
            logger.debug(
                "radio_dispatch: tuning static generation failed (rc=%d)", proc.returncode
            )
        return success
    except Exception as exc:
        logger.debug("radio_dispatch: tuning static generation error: %s", exc)
        return False


async def _generate_fixed_pause(
    output_path: str,
    duration_seconds: float,
    sample_rate: str,
    codec: str,
) -> bool:
    """Generate a silence WAV of an arbitrary duration.

    A generalised form of ``_generate_squelch_pause()`` that accepts an
    explicit duration so callers can produce pauses of varying lengths without
    sharing the module-level ``_SQUELCH_PAUSE_SECONDS`` constant.

    Args:
        output_path: Path where the silence WAV should be written.
        duration_seconds: Length of silence to generate, in seconds.
        sample_rate: Sample rate string (e.g. ``"8000"``).
        codec: ffmpeg codec name (e.g. ``"pcm_mulaw"``).

    Returns:
        True if the file was created successfully, False otherwise.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=mono",
            "-t", str(duration_seconds),
            "-acodec", codec,
            "-ar", sample_rate,
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_SILENCE_GEN_TIMEOUT_SECONDS)
        success = proc.returncode == 0 and os.path.exists(output_path)
        if not success:
            logger.debug(
                "radio_dispatch: fixed pause generation failed (rc=%d)", proc.returncode
            )
        return success
    except Exception as exc:
        logger.debug("radio_dispatch: fixed pause generation error: %s", exc)
        return False


async def _generate_chatter_tts(
    text: str,
    output_path: str,
    audio_pipeline,
    config: dict,
) -> bool:
    """Generate TTS for a random chatter snippet using the dispatcher voice.

    The chatter is background radio traffic heard before the main dispatch
    call begins.  It should use the **same dispatcher voice** so it sounds
    like the same channel / same person handling multiple calls — which is
    how real dispatch radio works.

    The officer voice is reserved exclusively for the officer acknowledgment
    segment at the end of the dispatch sequence.

    Args:
        text: Normalised chatter text to synthesise (10-codes already expanded).
        output_path: Path where the TTS WAV should be written.
        audio_pipeline: Live ``AudioPipeline`` instance.
        config: Full VoxWatch config dict.

    Returns:
        True if TTS was generated successfully, False otherwise.
    """
    # Use the dispatcher voice for chatter — same voice as the main dispatch
    # segments.  This is just the standard TTS pipeline voice which is already
    # configured as the dispatcher voice.
    try:
        return await audio_pipeline.generate_tts(text, output_path)
    except Exception as exc:
        logger.debug("radio_dispatch: chatter TTS failed: %s", exc)
        return False


async def _pitch_shift_down(
    input_path: str,
    output_path: str,
    semitones: float = 2.0,
) -> bool:
    """Lower the pitch of a WAV file using the ffmpeg asetrate trick.

    Works by declaring the audio was recorded at a higher sample rate than it
    actually was (``asetrate``), then resampling it back down to the original
    rate (``aresample``).  This stretches the waveform in time and lowers the
    perceived pitch without time-stretching artefacts, at the cost of a very
    slight slowdown — imperceptible for a 1–2 second clip.

    ``semitones=2.0`` applies a downward shift of two semitones, enough to
    make a default TTS voice sound noticeably deeper and male without sounding
    unnatural.  The formula for the rate multiplier is
    ``2 ** (semitones / 12)``.

    Args:
        input_path: Path to the source WAV file.
        output_path: Path for the pitch-shifted output WAV.
        semitones: Number of semitones to shift downward (positive = lower
            pitch).  Default 2.0.

    Returns:
        True if ffmpeg exited cleanly and ``output_path`` was written,
        False on any error.
    """
    # Rate multiplier for downward shift: above 1.0 = lower perceived pitch
    rate_multiplier: float = 2 ** (semitones / 12.0)

    # Read the original sample rate from the input file to preserve it.
    # We default to 22050 Hz (typical Kokoro / Piper output) if detection fails.
    original_rate: int = 22050
    try:
        probe_proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate",
            "-of", "csv=p=0",
            input_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(probe_proc.communicate(), timeout=5)
        rate_str = stdout.decode("utf-8", errors="replace").strip()
        if rate_str.isdigit():
            original_rate = int(rate_str)
    except Exception:
        pass  # Non-fatal — use the default

    shifted_rate: int = int(original_rate * rate_multiplier)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", f"asetrate={shifted_rate},aresample={original_rate}",
            "-ar", str(original_rate),
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_SILENCE_GEN_TIMEOUT_SECONDS)
        success = proc.returncode == 0 and os.path.exists(output_path)
        if not success:
            logger.debug(
                "radio_dispatch: pitch-shift failed (rc=%d) for: %s",
                proc.returncode,
                input_path,
            )
        return success
    except Exception as exc:
        logger.debug("radio_dispatch: pitch-shift error: %s", exc)
        return False


def _cleanup_paths(paths: list[str]) -> None:
    """Remove a list of file paths, ignoring errors for missing files.

    Used to clean up all temporary segment and concat files after composition,
    regardless of whether composition succeeded or failed.

    Args:
        paths: List of absolute file paths to remove.
    """
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
