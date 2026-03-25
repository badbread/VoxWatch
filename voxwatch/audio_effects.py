"""
audio_effects.py — Radio Dispatch Audio Effects for VoxWatch

Transforms clean TTS audio into realistic police radio dispatch audio.
Provides segment splitting, per-segment radio processing, and final
composition into a single WAV that sounds like a real dispatch transmission.

Pipeline overview:
  1. ``segment_dispatch_message`` splits the AI description into 2-3 short
     spoken phrases formatted as authentic 10-code radio dispatch.
  2. ``compose_dispatch_audio`` orchestrates the full generation sequence:
       - TTS is run per segment via the caller-supplied ``tts_func``
       - ``apply_radio_effect`` applies bandpass + compression to each clip
       - ffmpeg concat demuxer stitches everything into one WAV:
           beep → seg1 → gap → static_short → seg2 → gap → static_short
           → seg3 (if present) → squelch
  3. ``generate_static_assets`` pre-generates reusable beep/static/squelch
     files at service startup so they are not recreated on every event.

All ffmpeg calls use ``asyncio.create_subprocess_exec`` so the event loop
is never blocked.  The module is importable without side effects — no
file I/O or subprocess calls occur at import time.

Usage:
    from voxwatch.audio_effects import (
        generate_static_assets,
        segment_dispatch_message,
        compose_dispatch_audio,
    )

    assets = await generate_static_assets("/data/audio/dispatch_assets")

    segments = segment_dispatch_message(ai_description, template_vars)

    async def my_tts(text, path):
        ...  # call your TTS provider

    success = await compose_dispatch_audio(
        segments, my_tts, "/data/audio/dispatch_out.wav", config, assets
    )
"""

import asyncio
import logging
import os
import re
import tempfile
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger("voxwatch.audio_effects")

# ---------------------------------------------------------------------------
# Subprocess timeout (seconds) — mirrors audio_pipeline.SUBPROCESS_TIMEOUT
# ---------------------------------------------------------------------------
_SUBPROCESS_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Dispatch 10-code reference dictionary
# ---------------------------------------------------------------------------

DISPATCH_10_CODES: dict[str, str] = {
    "10-4": "Acknowledged",
    "10-20": "Location",
    "10-21": "Phone call requested",
    "10-22": "Disregard",
    "10-31": "Crime in progress",
    "10-33": "Emergency",
    "10-97": "On scene",
    "10-98": "Available for assignment",
    "Code 3": "Emergency response — lights and sirens",
    "Code 4": "No further assistance needed",
    "Code 6": "Out of vehicle, investigating",
}

# ---------------------------------------------------------------------------
# Radio intensity presets
# ---------------------------------------------------------------------------

RADIO_INTENSITY_PRESETS: dict[str, dict[str, Any]] = {
    "low": {
        # Gentle bandpass — cuts only extreme frequencies
        "bandpass_low": 250,
        "bandpass_high": 3400,
        # Light compression: slower attack, more dynamic range
        "compand_attacks": "0.02",
        "compand_decays": "0.15",
        "compand_points": "-90/-90 -40/-35 -20/-18 0/-12",
        "compand_gain": "2",
        # Subtle noise
        "noise_level": 0.015,
    },
    "medium": {
        # Standard radio bandpass
        "bandpass_low": 300,
        "bandpass_high": 3000,
        # Moderate AGC compression
        "compand_attacks": "0.01",
        "compand_decays": "0.1",
        "compand_points": "-90/-90 -50/-40 -20/-15 0/-8",
        "compand_gain": "3",
        # Moderate noise
        "noise_level": 0.03,
    },
    "high": {
        # Tight radio bandpass — most telephony-like
        "bandpass_low": 400,
        "bandpass_high": 2800,
        # Aggressive AGC: everything sounds equally loud
        "compand_attacks": "0.005",
        "compand_decays": "0.05",
        "compand_points": "-90/-90 -60/-45 -20/-12 0/-5",
        "compand_gain": "5",
        # Heavy noise for gritty effect
        "noise_level": 0.05,
    },
}

# ---------------------------------------------------------------------------
# Asset filenames
# ---------------------------------------------------------------------------

_ASSET_NAMES: tuple[str, ...] = (
    "beep",
    "static_short",
    "static_long",
    "squelch",
    "gap_silence",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_static_assets(output_dir: str) -> dict[str, str]:
    """Generate and cache reusable dispatch audio assets at service startup.

    Creates five WAV files that are stitched around TTS segments during
    ``compose_dispatch_audio``.  If a file already exists it is skipped so
    repeated calls (e.g. after a hot-reload) do not regenerate unnecessarily.

    Assets generated:

    * ``beep.wav``         — 0.15 s 1 kHz sine tone (dispatch radio keying sound)
    * ``static_short.wav`` — 150 ms filtered pink noise (between-segment fill)
    * ``static_long.wav``  — 300 ms filtered pink noise (longer pause fill)
    * ``squelch.wav``      — 200 ms white noise burst with fade-out (radio release)
    * ``gap_silence.wav``  — 200 ms silence (inter-segment pause)

    All files are 16-bit PCM WAV at 22050 Hz mono so they are compatible with
    any TTS provider output and can be resampled by ffmpeg during the final
    concat step.

    Args:
        output_dir: Directory where asset WAVs will be written.  Created if
            it does not exist.

    Returns:
        Mapping of asset name (without ``.wav``) to absolute file path.
        Keys: ``beep``, ``static_short``, ``static_long``, ``squelch``,
        ``gap_silence``.  Returns only successfully created entries — callers
        should check for missing keys.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Each entry: (name, ffmpeg_args_after_output)
    # We build the full command below.
    asset_specs: list[tuple[str, list[str]]] = [
        # 0.15 s 1 kHz sine tone — the "radio keying" click/beep
        (
            "beep",
            [
                "-f", "lavfi",
                "-i", "sine=frequency=1000:duration=0.15",
                "-ar", "22050",
                "-ac", "1",
                "-sample_fmt", "s16",
            ],
        ),
        # 150 ms filtered pink noise — short static burst between segments
        (
            "static_short",
            [
                "-f", "lavfi",
                "-i", "anoisesrc=color=pink:duration=0.15:amplitude=0.3",
                "-af", "highpass=f=800,lowpass=f=3000",
                "-ar", "22050",
                "-ac", "1",
                "-sample_fmt", "s16",
            ],
        ),
        # 300 ms filtered pink noise — longer fill
        (
            "static_long",
            [
                "-f", "lavfi",
                "-i", "anoisesrc=color=pink:duration=0.30:amplitude=0.3",
                "-af", "highpass=f=800,lowpass=f=3000",
                "-ar", "22050",
                "-ac", "1",
                "-sample_fmt", "s16",
            ],
        ),
        # 200 ms white noise with fade-out — radio squelch release
        (
            "squelch",
            [
                "-f", "lavfi",
                "-i", "anoisesrc=color=white:duration=0.20:amplitude=0.25",
                "-af", "afade=t=out:st=0.05:d=0.15",
                "-ar", "22050",
                "-ac", "1",
                "-sample_fmt", "s16",
            ],
        ),
        # 200 ms silence — clean gap between segments
        (
            "gap_silence",
            [
                "-f", "lavfi",
                "-i", "anullsrc=r=22050:cl=mono",
                "-t", "0.20",
                "-ar", "22050",
                "-ac", "1",
                "-sample_fmt", "s16",
            ],
        ),
    ]

    results: dict[str, str] = {}

    for name, ffmpeg_input_args in asset_specs:
        out_path = os.path.join(output_dir, f"{name}.wav")

        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            logger.debug("Dispatch asset already exists, skipping: %s", out_path)
            results[name] = out_path
            continue

        cmd = ["ffmpeg", "-y"] + ffmpeg_input_args + [out_path]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
            )
            if proc.returncode == 0 and os.path.exists(out_path):
                logger.debug("Generated dispatch asset: %s", out_path)
                results[name] = out_path
            else:
                logger.error(
                    "Failed to generate dispatch asset '%s' (exit %d): %s",
                    name,
                    proc.returncode,
                    stderr.decode("utf-8", errors="replace")[-300:],
                )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out generating dispatch asset '%s' after %ds",
                name,
                _SUBPROCESS_TIMEOUT,
            )
        except FileNotFoundError:
            logger.error(
                "ffmpeg not found — cannot generate dispatch assets"
            )
            break  # ffmpeg missing; no point trying the rest

    return results


async def apply_radio_effect(
    input_path: str,
    output_path: str,
    config: dict,
) -> bool:
    """Apply radio dispatch audio processing to a clean TTS WAV file.

    Runs an ffmpeg filter chain that mimics the acoustic signature of a
    VHF/UHF police radio transmission:

    1. ``highpass``  — removes sub-bass frequencies radios cannot transmit.
    2. ``lowpass``   — removes high-frequency content above the radio passband.
    3. ``compand``   — aggressive dynamic compression simulating radio AGC
                       (automatic gain control).  Everything comes out at roughly
                       the same perceived loudness regardless of input level.
    4. ``volume``    — final level trim to prevent inter-sample clipping.

    The exact parameters are selected from ``RADIO_INTENSITY_PRESETS`` based on
    ``config["radio_effect"]["intensity"]`` (default ``"medium"``).  Individual
    ``bandpass_low``, ``bandpass_high``, and ``noise_level`` keys in
    ``config["radio_effect"]`` override the preset values when present.

    Args:
        input_path: Absolute path to the clean TTS WAV file (any sample rate).
        output_path: Absolute path for the radio-processed output WAV.
        config: Full VoxWatch config dict.  Reads ``config["radio_effect"]``
            for tuning parameters; falls back to ``"medium"`` preset defaults.

    Returns:
        True if ffmpeg exited with code 0 and ``output_path`` was written.
        False on any ffmpeg error or subprocess timeout.
    """
    radio_cfg: dict = config.get("radio_effect", {})

    # Select intensity preset then allow per-key overrides from config
    intensity: str = radio_cfg.get("intensity", "medium")
    if intensity not in RADIO_INTENSITY_PRESETS:
        logger.warning(
            "Unknown radio_effect.intensity '%s', falling back to 'medium'",
            intensity,
        )
        intensity = "medium"

    preset = dict(RADIO_INTENSITY_PRESETS[intensity])  # shallow copy to allow mutation

    # Per-key overrides from config (bandpass_low / bandpass_high / noise_level)
    bandpass_low: int = int(radio_cfg.get("bandpass_low", preset["bandpass_low"]))
    bandpass_high: int = int(radio_cfg.get("bandpass_high", preset["bandpass_high"]))

    # Build the ffmpeg audio filter string
    # compand format: attacks:decays points initial-volume/gain
    compand_filter = (
        f"compand="
        f"attacks={preset['compand_attacks']}:"
        f"decays={preset['compand_decays']}:"
        f"points={preset['compand_points']}:"
        f"gain={preset['compand_gain']}"
    )

    af_chain = ",".join([
        f"highpass=f={bandpass_low}",
        f"lowpass=f={bandpass_high}",
        compand_filter,
        "volume=0.9",
    ])

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", af_chain,
            "-ar", "22050",
            "-ac", "1",
            "-sample_fmt", "s16",
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
        if proc.returncode == 0 and os.path.exists(output_path):
            logger.debug(
                "Radio effect applied (%s intensity): %s -> %s",
                intensity,
                input_path,
                output_path,
            )
            return True

        logger.error(
            "apply_radio_effect ffmpeg failed (exit %d): %s",
            proc.returncode,
            stderr.decode("utf-8", errors="replace")[-400:],
        )
        return False

    except asyncio.TimeoutError:
        logger.error(
            "apply_radio_effect timed out after %ds for: %s",
            _SUBPROCESS_TIMEOUT,
            input_path,
        )
        return False
    except FileNotFoundError:
        logger.error("ffmpeg not found — cannot apply radio effect")
        return False


async def compose_dispatch_audio(
    segments: list[str],
    tts_func: Callable[[str, str], Coroutine[Any, Any, bool]],
    output_path: str,
    config: dict,
    static_assets: dict[str, str],
) -> bool:
    """Generate and compose a full police radio dispatch WAV from text segments.

    For each text segment the function:
      1. Generates TTS audio by calling ``tts_func(text, path) -> bool``.
      2. Applies radio processing via ``apply_radio_effect``.

    The processed clips are then assembled into a single WAV using the ffmpeg
    concat demuxer with the following structure:

        beep → seg1 → gap_silence → static_short → [seg2 → gap_silence
        → static_short → [seg3 →]] squelch

    The total duration is kept under 8 seconds: any segment whose TTS file
    exceeds 3.5 seconds is accepted as-is (the caller is responsible for
    splitting text into appropriately short phrases before calling this
    function).

    A temporary working directory scoped to this call is used for intermediate
    files.  It is cleaned up whether the function succeeds or fails.

    Args:
        segments: List of 2-3 short dispatch text phrases.  Each phrase should
            produce less than ~2 s of speech when synthesised.
        tts_func: Async callable ``(text: str, output_path: str) -> bool``.
            Should write a WAV file to ``output_path`` and return True on
            success.  Typically wraps ``AudioPipeline.generate_tts``.
        output_path: Absolute path for the final composed WAV file.
        config: Full VoxWatch config dict.
        static_assets: Mapping returned by ``generate_static_assets`` — must
            contain at least ``beep``, ``static_short``, ``squelch``, and
            ``gap_silence`` keys.

    Returns:
        True if the final WAV was successfully written to ``output_path``.
        False if TTS generation, radio processing, or ffmpeg concat failed for
        any segment.
    """
    if not segments:
        logger.error("compose_dispatch_audio called with empty segments list")
        return False

    # Validate required static assets are present
    required_assets = ("beep", "static_short", "squelch", "gap_silence")
    for asset in required_assets:
        if asset not in static_assets:
            logger.error(
                "Missing required static asset '%s' — run generate_static_assets first",
                asset,
            )
            return False

    # Use a temporary directory for all intermediate files
    with tempfile.TemporaryDirectory(prefix="voxwatch_dispatch_") as work_dir:
        processed_clips: list[str] = []

        for idx, text in enumerate(segments):
            # Step 1: TTS generation
            tts_path = os.path.join(work_dir, f"tts_{idx}.wav")
            tts_ok = await tts_func(text, tts_path)
            if not tts_ok or not os.path.exists(tts_path):
                logger.error(
                    "TTS failed for dispatch segment %d: %r", idx, text
                )
                return False

            # Step 2: Radio effect processing
            radio_path = os.path.join(work_dir, f"radio_{idx}.wav")
            radio_ok = await apply_radio_effect(tts_path, radio_path, config)
            if not radio_ok:
                logger.error(
                    "Radio effect failed for dispatch segment %d: %r", idx, text
                )
                return False

            processed_clips.append(radio_path)

        # Build the ordered file list for the concat demuxer.
        # Structure: beep → (seg → gap → static_short)* → squelch
        # The trailing static_short after the last segment is replaced by squelch.
        ordered_files: list[str] = [static_assets["beep"]]

        for clip_idx, clip_path in enumerate(processed_clips):
            ordered_files.append(clip_path)
            # After every segment add a gap + static burst, except after the last
            if clip_idx < len(processed_clips) - 1:
                ordered_files.append(static_assets["gap_silence"])
                ordered_files.append(static_assets["static_short"])

        # Always end with the squelch (radio release sound)
        ordered_files.append(static_assets["squelch"])

        # Write the ffmpeg concat list file
        concat_list_path = os.path.join(work_dir, "concat.txt")
        try:
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for file_path in ordered_files:
                    # ffmpeg concat demuxer requires forward slashes even on Windows
                    safe_path = file_path.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")
        except OSError as exc:
            logger.error("Failed to write concat list: %s", exc)
            return False

        # Run ffmpeg concat — output as 16-bit PCM WAV at 22050 Hz
        # The caller's audio pipeline will handle final codec conversion
        # (e.g. pcm_mulaw 8kHz for camera push)
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-ar", "22050",
                "-ac", "1",
                "-sample_fmt", "s16",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
            )
            if proc.returncode == 0 and os.path.exists(output_path):
                logger.info(
                    "Dispatch audio composed: %d segments -> %s",
                    len(segments),
                    output_path,
                )
                return True

            logger.error(
                "compose_dispatch_audio concat failed (exit %d): %s",
                proc.returncode,
                stderr.decode("utf-8", errors="replace")[-400:],
            )
            return False

        except asyncio.TimeoutError:
            logger.error(
                "compose_dispatch_audio concat timed out after %ds",
                _SUBPROCESS_TIMEOUT,
            )
            return False
        except FileNotFoundError:
            logger.error("ffmpeg not found — cannot compose dispatch audio")
            return False


def segment_dispatch_message(
    ai_description: str,
    template_vars: dict[str, str],
) -> list[str]:
    """Split an AI-generated description into spoken radio dispatch segments.

    Produces 2-3 short phrases formatted as authentic police radio dispatch,
    using 10-codes and procedural language.  Each segment is designed to be
    under ~2 seconds of spoken audio.

    The function uses ``template_vars`` to inject property-specific details
    (address, unit count, etc.) and extracts appearance/behaviour cues from
    ``ai_description`` to fill the remaining segments.

    Segment structure:
        Segment 1 — location call-out using the property address and a 10-code.
        Segment 2 — subject description (clothing, build, count) from the AI.
        Segment 3 — last-seen / activity detail (omitted when not extractable).

    Args:
        ai_description: Raw prose description returned by the AI vision module.
            May be multi-sentence.  Control characters should be stripped before
            calling this function (``_sanitize_tts_input`` in audio_pipeline).
        template_vars: Dict with optional keys:

            * ``address_street`` — short street address, e.g. ``"482 Elm St"``
            * ``full_address``   — full address for longer announcements
            * ``suspect_count``  — number string, e.g. ``"1"`` or ``"2"``
            * ``camera_name``    — camera label, e.g. ``"frontdoor"``

            Missing keys fall back to generic placeholder text.

    Returns:
        List of 2-3 non-empty strings, each suitable for TTS synthesis.
        Always returns at least 2 segments.
    """
    address_street: str = template_vars.get("address_street", "your location")
    suspect_count_str: str = template_vars.get("suspect_count", "1")

    # Normalise suspect count to a spoken word
    try:
        count_int = int(suspect_count_str)
    except ValueError:
        count_int = 1
    count_word = _number_to_word(count_int)

    # -----------------------------------------------------------------
    # Segment 1: Location/unit call-out
    # -----------------------------------------------------------------
    segment1 = (
        f"All units, 10-97 at {address_street}. "
        f"{count_word.capitalize()} suspect{'s' if count_int != 1 else ''} on property."
    )

    # -----------------------------------------------------------------
    # Segment 2: Appearance extracted from AI description
    # -----------------------------------------------------------------
    appearance = _extract_appearance(ai_description)
    if appearance:
        segment2 = appearance
    else:
        segment2 = "Subject description unavailable. Approach with caution."

    # -----------------------------------------------------------------
    # Segment 3: Activity / last seen (optional)
    # -----------------------------------------------------------------
    activity = _extract_activity(ai_description)
    if activity:
        return [segment1, segment2, activity]

    return [segment1, segment2]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _number_to_word(n: int) -> str:
    """Convert a small integer to its English word form.

    Args:
        n: Integer to convert (handles 0-9; higher numbers returned as digits).

    Returns:
        English word string (e.g. 1 -> "one", 2 -> "two") or digit string.
    """
    words = {
        0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
        5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    }
    return words.get(n, str(n))


def _extract_appearance(description: str) -> str:
    """Extract subject appearance details from an AI description.

    Scans ``description`` for sentences containing clothing, build, or colour
    references and reformats them into a compact dispatch-style phrase.

    Args:
        description: Raw AI prose (may be multiple sentences).

    Returns:
        A single concise appearance sentence for TTS, or an empty string if
        no appearance cues were detected.
    """
    if not description:
        return ""

    # Keywords that signal an appearance-relevant sentence
    appearance_keywords = re.compile(
        r"\b(wear(ing)?|hoodie|jacket|shirt|pants|jeans|hat|cap|backpack|bag"
        r"|dark|light|black|white|red|blue|green|grey|gray|brown|tall|short"
        r"|build|male|female|man|woman|person|individual|subject|adult"
        r"|hoodie|coat|clothing)\b",
        re.IGNORECASE,
    )

    sentences = _split_sentences(description)
    appearance_parts: list[str] = []

    for sent in sentences:
        if appearance_keywords.search(sent):
            # Clean up the sentence for radio brevity
            clean = sent.strip().rstrip(".")
            appearance_parts.append(clean)
        if len(appearance_parts) >= 2:
            break

    if not appearance_parts:
        return ""

    combined = ". ".join(appearance_parts)
    # Trim to a comfortable dispatch length (≤ 120 chars spoken in ~2s)
    if len(combined) > 120:
        combined = combined[:117] + "..."

    return combined + "."


def _extract_activity(description: str) -> str:
    """Extract last-seen activity or location from an AI description.

    Looks for sentences describing movement, position, or behaviour — useful
    as a third dispatch segment.

    Args:
        description: Raw AI prose (may be multiple sentences).

    Returns:
        A single concise activity/location sentence, or an empty string when
        no actionable activity detail is found.
    """
    if not description:
        return ""

    activity_keywords = re.compile(
        r"\b(near|at|by|seen|last|approach(ing)?|mov(ing|ed)|walk(ing|ed)"
        r"|run(ning)?|stand(ing)?|loiter(ing)?|gate|door|fence|driveway"
        r"|front|rear|side|yard|porch|window|vehicle|car|truck"
        r"|carrying|holding|look(ing)?)\b",
        re.IGNORECASE,
    )

    sentences = _split_sentences(description)

    for sent in sentences:
        if activity_keywords.search(sent):
            clean = sent.strip().rstrip(".")
            if len(clean) > 100:
                clean = clean[:97] + "..."
            return f"Last seen {clean.lower()}." if not clean.lower().startswith("last") else f"{clean}."

    return ""


def _split_sentences(text: str) -> list[str]:
    """Split text into individual sentences on common punctuation boundaries.

    Args:
        text: Multi-sentence prose string.

    Returns:
        List of individual sentence strings with leading/trailing whitespace
        stripped.  Empty strings are excluded.
    """
    # Split on period, exclamation, or question mark followed by whitespace
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in raw if s.strip()]
