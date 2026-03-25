"""natural_cadence.py — Natural Cadence Speech System for VoxWatch

Transforms a list of short AI-generated phrases into a single audio file that
sounds like a human speaker pausing naturally between thoughts, rather than a
TTS engine reading a continuous script.

The pipeline for a list of phrases is:

  1. ``parse_ai_response`` — accepts a JSON array string, a JSON code block, or
     plain text and returns a clean ``list[str]``.
  2. For each phrase: call the audio pipeline's TTS engine to generate a WAV
     segment, then optionally apply a speed-variation filter via ffmpeg's
     ``atempo`` filter.
  3. Between each pair of phrases: generate a silent WAV whose duration is
     determined by the trailing punctuation of the preceding phrase.
  4. Add optional leading/trailing silence pads around the entire sequence.
  5. Concatenate all WAV segments with ffmpeg's concat demuxer into a single
     output file.
  6. Optionally apply a post-processing pass (see ``voxwatch.speech.postprocess``).

All ffmpeg calls use ``asyncio.create_subprocess_exec`` to match the rest of
the VoxWatch audio pipeline.  Every operation is non-fatal: if any individual
step fails, the function logs the error and falls back to joining the phrase
list with spaces and calling the pipeline's standard ``generate_tts``.

Design notes:
  - Speed variation is applied via ffmpeg ``atempo``, not the TTS engine's own
    speed parameter.  This gives consistent results across all TTS providers.
  - Silence is generated via ffmpeg's ``lavfi`` null source (``anullsrc``), the
    same approach used elsewhere in ``audio_pipeline.py``.
  - All temporary files land in a ``TemporaryDirectory`` that is always cleaned
    up in a ``finally`` block regardless of success or failure.
  - The output WAV is written in standard PCM 44.1 kHz 16-bit stereo before the
    caller converts it to the camera codec via ``AudioPipeline.convert_audio``.
    Working at high quality internally prevents accumulated quantisation noise
    from the multiple ffmpeg passes.
"""

import asyncio
import json
import logging
import os
import random
import re
import tempfile
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # Avoid a circular import at module load time.  AudioPipeline is only used
    # in type annotations and as a runtime argument — never imported at the top
    # level.
    from voxwatch.audio_pipeline import AudioPipeline

logger = logging.getLogger("voxwatch.speech.cadence")

# Internal working format used for all cadence WAV segments before the final
# codec conversion step.  44.1 kHz 16-bit mono gives good quality headroom
# without generating excessively large temp files.
_WORK_SAMPLE_RATE = 44100
_WORK_CHANNELS = 1

# ffmpeg/ffprobe subprocess timeout in seconds — applied to every call.
_SUBPROCESS_TIMEOUT = 30

# Minimum phrase length (characters) worth synthesising — very short strings
# (e.g. a lone punctuation mark left by a bad AI parse) are skipped.
_MIN_PHRASE_CHARS = 2

# Maximum atempo factor for a single pass.  ffmpeg's atempo filter only accepts
# values in [0.5, 2.0].  We never exceed 1.08, so a single pass is sufficient.
_ATEMPO_MAX = 2.0
_ATEMPO_MIN = 0.5


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class CadenceConfig:
    """Tunable parameters for the natural cadence speech system.

    All pause values are in seconds.  Speed values are multipliers where
    1.0 = normal speed.  These defaults are chosen to approximate a calm,
    authoritative human speaker.

    Attributes:
        min_pause: Minimum silence inserted between any two phrases.
        max_pause: Maximum silence inserted between any two phrases (used when
            the preceding phrase ends with no recognised punctuation).
        period_pause: Pause inserted after a phrase ending with ``"."``.
        ellipsis_pause: Pause inserted after a phrase ending with ``"..."``.
        comma_pause: Pause inserted after a phrase ending with ``","``.
        min_speed: Lower bound for random per-phrase speed factor.
        max_speed: Upper bound for random per-phrase speed factor.
        speed_variation_enabled: When True, each phrase's playback speed is
            randomly varied within [min_speed, max_speed].  Set False for
            completely uniform speed (useful when the TTS provider already
            produces natural variation).
        leading_pause: Silence prepended before the first phrase.
        trailing_pause: Silence appended after the last phrase.
        postprocess: When True, apply light loudness normalisation and silence
            trimming via ``voxwatch.speech.postprocess.apply_natural_postprocess``
            after concatenation.
    """

    min_pause: float = 0.2
    max_pause: float = 0.6
    period_pause: float = 0.5
    ellipsis_pause: float = 0.7
    comma_pause: float = 0.2
    min_speed: float = 0.92
    max_speed: float = 1.08
    speed_variation_enabled: bool = True
    leading_pause: float = 0.3
    trailing_pause: float = 0.2
    postprocess: bool = True

    @classmethod
    def from_config(cls, config: dict) -> "CadenceConfig":
        """Build a CadenceConfig from a VoxWatch config dict.

        Reads values from ``config["speech"]["natural_cadence"]``, falling back
        to the dataclass defaults for any key that is missing.

        Args:
            config: Full VoxWatch config dict from ``voxwatch.config.load_config``.

        Returns:
            A fully populated CadenceConfig instance.
        """
        cadence = config.get("speech", {}).get("natural_cadence", {})
        return cls(
            min_pause=float(cadence.get("min_pause", cls.__dataclass_fields__["min_pause"].default)),
            max_pause=float(cadence.get("max_pause", cls.__dataclass_fields__["max_pause"].default)),
            period_pause=float(cadence.get("period_pause", cls.__dataclass_fields__["period_pause"].default)),
            ellipsis_pause=float(cadence.get("ellipsis_pause", cls.__dataclass_fields__["ellipsis_pause"].default)),
            comma_pause=float(cadence.get("comma_pause", cls.__dataclass_fields__["comma_pause"].default)),
            min_speed=float(cadence.get("min_speed", cls.__dataclass_fields__["min_speed"].default)),
            max_speed=float(cadence.get("max_speed", cls.__dataclass_fields__["max_speed"].default)),
            speed_variation_enabled=bool(cadence.get("speed_variation", cls.__dataclass_fields__["speed_variation_enabled"].default)),
            leading_pause=float(cadence.get("leading_pause", cls.__dataclass_fields__["leading_pause"].default)),
            trailing_pause=float(cadence.get("trailing_pause", cls.__dataclass_fields__["trailing_pause"].default)),
            postprocess=bool(cadence.get("postprocess", cls.__dataclass_fields__["postprocess"].default)),
        )


# ---------------------------------------------------------------------------
# Phrase parsing
# ---------------------------------------------------------------------------


def parse_ai_response(response: str) -> list[str]:
    """Parse an AI response string into a list of short spoken phrases.

    Accepts three input formats in priority order:

    1. **JSON array in a markdown code block** — e.g. the AI wrapped its output
       in `` ```json\\n[...]\\n``` ``.  The code-block delimiters are stripped
       before JSON parsing.
    2. **Bare JSON array** — the AI returned a raw ``["phrase 1", "phrase 2"]``
       string without any markdown wrapping.
    3. **Plain text fallback** — the response is split into sentences on
       ``. ``, ``! ``, and ``? `` boundaries.  Each sentence is stripped of
       leading/trailing whitespace and must contain at least one alphabetic
       character to be included.

    The function is intentionally lenient: any parse failure falls through to
    the next strategy.  The caller should always receive a non-empty list (as
    long as ``response`` is non-empty).

    Args:
        response: Raw AI response string.  May be a JSON array, a JSON array
            wrapped in a markdown code block, or arbitrary plain text.

    Returns:
        A list of non-empty phrase strings.  Returns ``[response]`` (the raw
        string as a single phrase) only when all other strategies fail and the
        text contains no sentence boundaries.

    Examples:
        >>> parse_ai_response('["Stop.", "You are being recorded."]')
        ['Stop.', 'You are being recorded.']
        >>> parse_ai_response("Stop. You are being recorded.")
        ['Stop.', 'You are being recorded.']
    """
    stripped = response.strip()

    # --- Strategy 1: JSON in a markdown code block -------------------------
    code_block_match = re.search(
        r"```(?:json)?\s*(\[.*?\])\s*```",
        stripped,
        flags=re.DOTALL,
    )
    if code_block_match:
        try:
            phrases = json.loads(code_block_match.group(1))
            if isinstance(phrases, list) and all(isinstance(p, str) for p in phrases):
                clean = [p.strip() for p in phrases if p.strip()]
                if clean:
                    logger.debug(
                        "parse_ai_response: parsed %d phrases from JSON code block",
                        len(clean),
                    )
                    return clean
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Strategy 2: Bare JSON array ---------------------------------------
    # Look for the first complete [...] array anywhere in the string.
    array_match = re.search(r"\[.*?\]", stripped, flags=re.DOTALL)
    if array_match:
        try:
            phrases = json.loads(array_match.group(0))
            if isinstance(phrases, list) and all(isinstance(p, str) for p in phrases):
                clean = [p.strip() for p in phrases if p.strip()]
                if clean:
                    logger.debug(
                        "parse_ai_response: parsed %d phrases from bare JSON array",
                        len(clean),
                    )
                    return clean
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Strategy 3: Plain text sentence split -----------------------------
    # Split on ". ", "! ", "? " boundaries while preserving the punctuation.
    sentences: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", stripped):
        part = part.strip()
        # Keep only parts that have at least one letter — filters out stray
        # punctuation, numbers, or empty strings.
        if part and any(ch.isalpha() for ch in part):
            sentences.append(part)

    if sentences:
        logger.debug(
            "parse_ai_response: split into %d sentences from plain text",
            len(sentences),
        )
        return sentences

    # --- Final fallback: treat the entire response as one phrase -----------
    logger.debug("parse_ai_response: using full response as single phrase")
    return [stripped] if stripped else []


# ---------------------------------------------------------------------------
# Pause duration calculation
# ---------------------------------------------------------------------------


def determine_pause_duration(phrase: str, cadence_config: CadenceConfig) -> float:
    """Calculate how long to pause after a phrase based on its trailing punctuation.

    Rules (evaluated in order, taking the first match):

    - Phrase ends with ``"..."`` → ``cadence_config.ellipsis_pause``
    - Phrase ends with ``"."`` or ``"!"`` or ``"?"`` → ``cadence_config.period_pause``
    - Phrase ends with ``","`` or ``";"`` or ``":"`` → ``cadence_config.comma_pause``
    - Otherwise → random value in [``cadence_config.min_pause``,
      ``cadence_config.max_pause``], drawn uniformly.

    The trailing whitespace of the phrase is stripped before matching so
    ``"Stop. "`` is treated the same as ``"Stop."``.

    Args:
        phrase: The spoken phrase whose trailing punctuation determines the gap.
        cadence_config: Active cadence settings.

    Returns:
        Pause duration in seconds (always positive).
    """
    tail = phrase.rstrip()
    if not tail:
        return cadence_config.min_pause

    if tail.endswith("..."):
        return cadence_config.ellipsis_pause
    if tail[-1] in ".!?":
        return cadence_config.period_pause
    if tail[-1] in ",;:":
        return cadence_config.comma_pause

    # No recognised terminal punctuation — pick a random mid-range pause.
    return random.uniform(cadence_config.min_pause, cadence_config.max_pause)


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------


async def generate_silence(
    duration: float,
    sample_rate: int,
    output_path: str,
) -> bool:
    """Generate a WAV file containing silence of the requested duration.

    Uses ffmpeg's ``lavfi`` null source (``anullsrc``) — the same strategy
    used by ``AudioPipeline._generate_silence``.  Output is PCM 16-bit signed
    at the requested sample rate, mono.

    Args:
        duration: Silence length in seconds.  Values below 0.05 are clamped
            to 0.05 to avoid producing degenerate zero-length files.
        sample_rate: Output sample rate in Hz.
        output_path: Absolute path for the output WAV file.

    Returns:
        True if ffmpeg succeeded and the file exists, False otherwise.
    """
    duration = max(duration, 0.05)
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=mono",
            "-t", f"{duration:.4f}",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", str(_WORK_CHANNELS),
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
        if proc.returncode == 0 and os.path.exists(output_path):
            return True
        logger.warning(
            "generate_silence: ffmpeg exit %d — %s",
            proc.returncode,
            stderr.decode("utf-8", errors="replace")[-200:],
        )
        return False
    except asyncio.TimeoutError:
        logger.error("generate_silence: ffmpeg timed out after %ds", _SUBPROCESS_TIMEOUT)
        return False
    except FileNotFoundError:
        logger.error("generate_silence: ffmpeg not found on PATH")
        return False


async def apply_speed_variation(
    input_path: str,
    output_path: str,
    speed: float,
) -> bool:
    """Apply a playback speed multiplier to a WAV file via ffmpeg's atempo filter.

    The ``atempo`` filter accepts values in [0.5, 2.0].  The ``speed`` argument
    is clamped to that range before use.

    Args:
        input_path: Source WAV file.
        output_path: Destination WAV file.
        speed: Speed multiplier.  1.0 = no change, 1.05 = 5 % faster, etc.

    Returns:
        True if ffmpeg succeeded and the output file exists, False otherwise.
    """
    speed = max(_ATEMPO_MIN, min(_ATEMPO_MAX, speed))
    if abs(speed - 1.0) < 0.001:
        # Trivial case: copy without re-encoding to avoid a needless pass.
        try:
            import shutil as _shutil
            _shutil.copy2(input_path, output_path)
            return True
        except OSError as exc:
            logger.warning("apply_speed_variation: file copy failed: %s", exc)
            return False

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", f"atempo={speed:.4f}",
            "-acodec", "pcm_s16le",
            "-ar", str(_WORK_SAMPLE_RATE),
            "-ac", str(_WORK_CHANNELS),
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
        if proc.returncode == 0 and os.path.exists(output_path):
            return True
        logger.warning(
            "apply_speed_variation: ffmpeg exit %d — %s",
            proc.returncode,
            stderr.decode("utf-8", errors="replace")[-200:],
        )
        return False
    except asyncio.TimeoutError:
        logger.error(
            "apply_speed_variation: ffmpeg timed out after %ds", _SUBPROCESS_TIMEOUT
        )
        return False
    except FileNotFoundError:
        logger.error("apply_speed_variation: ffmpeg not found on PATH")
        return False


async def concatenate_segments(
    segment_paths: list[str],
    output_path: str,
) -> bool:
    """Concatenate multiple WAV files into one using ffmpeg's concat demuxer.

    Writes a temporary concat list file (``concat_list.txt``) to the same
    directory as ``output_path`` and passes it to ffmpeg via ``-f concat``.
    The list file is removed on completion regardless of success or failure.

    All input files must share the same sample rate, channel count, and codec.
    The caller is responsible for ensuring this (all cadence segments are
    generated at ``_WORK_SAMPLE_RATE`` / mono / pcm_s16le).

    Args:
        segment_paths: Ordered list of absolute paths to WAV files.  Must
            contain at least one entry.
        output_path: Absolute path for the concatenated output WAV.

    Returns:
        True if ffmpeg succeeded and the output file exists and is non-empty.
    """
    if not segment_paths:
        logger.error("concatenate_segments: no segments provided")
        return False

    if len(segment_paths) == 1:
        # Single segment: copy directly, no concat needed.
        try:
            import shutil as _shutil
            _shutil.copy2(segment_paths[0], output_path)
            return os.path.exists(output_path)
        except OSError as exc:
            logger.warning("concatenate_segments: single-file copy failed: %s", exc)
            return False

    concat_list_path = output_path + "_concat_list.txt"
    try:
        with open(concat_list_path, "w", encoding="utf-8") as fh:
            for path in segment_paths:
                # ffmpeg concat demuxer requires forward slashes even on Windows
                # and paths with special characters must be quoted.
                safe_path = path.replace("\\", "/")
                fh.write(f"file '{safe_path}'\n")

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-acodec", "pcm_s16le",
            "-ar", str(_WORK_SAMPLE_RATE),
            "-ac", str(_WORK_CHANNELS),
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
        if proc.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 0:
                return True
            logger.warning("concatenate_segments: output file is empty")
            return False
        logger.error(
            "concatenate_segments: ffmpeg exit %d — %s",
            proc.returncode,
            stderr.decode("utf-8", errors="replace")[-400:],
        )
        return False
    except asyncio.TimeoutError:
        logger.error(
            "concatenate_segments: ffmpeg timed out after %ds", _SUBPROCESS_TIMEOUT
        )
        return False
    except FileNotFoundError:
        logger.error("concatenate_segments: ffmpeg not found on PATH")
        return False
    finally:
        try:
            os.remove(concat_list_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def generate_natural_speech(
    phrases: list[str],
    audio_pipeline: "AudioPipeline",
    output_path: str,
    config: dict,
    cadence_config: Optional[CadenceConfig] = None,
) -> bool:
    """Generate natural-sounding speech from a list of short phrases.

    This is the primary entry point for the natural cadence system.  It
    orchestrates the full pipeline:

      1. Build a ``CadenceConfig`` from the provided config dict (or use the
         supplied ``cadence_config`` directly).
      2. Filter out blank/trivially short phrases.
      3. For each phrase:
           a. Generate a TTS WAV segment via ``audio_pipeline.generate_tts``.
           b. Convert it to the internal working format (44.1 kHz 16-bit mono).
           c. Optionally apply a per-phrase speed variation with ffmpeg atempo.
      4. Build silence segments for leading pause, inter-phrase pauses, and
         trailing pause.
      5. Concatenate all segments in order with ffmpeg's concat demuxer.
      6. Optionally apply post-processing (normalisation + silence trim).
      7. Write the final result to ``output_path``.

    All intermediate files are created in a ``TemporaryDirectory`` that is
    always cleaned up in a ``finally`` block, even if an exception is raised.

    This function is intentionally non-fatal.  If any step in the pipeline
    fails (TTS error, ffmpeg error, etc.), it returns ``False`` so the caller
    can fall back to ``audio_pipeline.generate_tts`` with the joined phrases.

    Args:
        phrases: Ordered list of short phrases to speak.  Typically the result
            of ``parse_ai_response`` applied to the AI's structured output.
        audio_pipeline: Initialised ``AudioPipeline`` instance used to call the
            configured TTS engine for each phrase.
        output_path: Absolute path where the final WAV file should be written.
            The caller is responsible for subsequently converting this to the
            camera-compatible codec via ``AudioPipeline.convert_audio``.
        config: Full VoxWatch config dict.  Used to build a ``CadenceConfig``
            when ``cadence_config`` is not provided.
        cadence_config: Pre-built cadence configuration.  When None, one is
            created from ``config["speech"]["natural_cadence"]``.

    Returns:
        True if the output file was successfully generated and is non-empty.
        False on any error (the caller should fall back to standard TTS).
    """
    if cadence_config is None:
        cadence_config = CadenceConfig.from_config(config)

    # Filter trivially short phrases before allocating any resources.
    clean_phrases = [
        p.strip() for p in phrases
        if p.strip() and len(p.strip()) >= _MIN_PHRASE_CHARS
    ]
    if not clean_phrases:
        logger.warning("generate_natural_speech: no usable phrases after filtering")
        return False

    logger.info(
        "generate_natural_speech: building cadence audio for %d phrase(s)",
        len(clean_phrases),
    )

    tmp_dir_obj = tempfile.TemporaryDirectory(prefix="voxwatch_cadence_")
    try:
        tmp_dir = tmp_dir_obj.name
        segment_paths: list[str] = []

        # ── Leading silence ────────────────────────────────────────────────
        if cadence_config.leading_pause > 0:
            leading_path = os.path.join(tmp_dir, "lead_silence.wav")
            ok = await generate_silence(
                cadence_config.leading_pause, _WORK_SAMPLE_RATE, leading_path
            )
            if ok:
                segment_paths.append(leading_path)
            else:
                logger.warning(
                    "generate_natural_speech: leading silence generation failed — skipping"
                )

        # ── Per-phrase TTS + optional speed variation ──────────────────────
        for idx, phrase in enumerate(clean_phrases):
            phrase_label = f"phrase_{idx:02d}"

            # Step A: Generate TTS output (provider WAV, any format)
            raw_tts_path = os.path.join(tmp_dir, f"{phrase_label}_raw.wav")
            tts_ok = await audio_pipeline.generate_tts(phrase, raw_tts_path)
            if not tts_ok or not os.path.exists(raw_tts_path):
                logger.warning(
                    "generate_natural_speech: TTS failed for phrase %d ('%s…') — skipping phrase",
                    idx,
                    phrase[:40],
                )
                continue

            # Step B: Convert to internal working format (44.1 kHz 16-bit mono).
            # This normalises the sample rate/codec across providers before any
            # speed filter is applied.
            work_path = os.path.join(tmp_dir, f"{phrase_label}_work.wav")
            conv_ok = await _convert_to_work_format(raw_tts_path, work_path)
            if not conv_ok:
                logger.warning(
                    "generate_natural_speech: format conversion failed for phrase %d — skipping",
                    idx,
                )
                continue

            # Step C: Optional per-phrase speed variation via atempo.
            if cadence_config.speed_variation_enabled:
                speed = random.uniform(
                    cadence_config.min_speed, cadence_config.max_speed
                )
                sped_path = os.path.join(tmp_dir, f"{phrase_label}_sped.wav")
                speed_ok = await apply_speed_variation(work_path, sped_path, speed)
                if speed_ok:
                    work_path = sped_path
                    logger.debug(
                        "generate_natural_speech: phrase %d speed=%.3f", idx, speed
                    )
                else:
                    logger.warning(
                        "generate_natural_speech: atempo failed for phrase %d — using original speed",
                        idx,
                    )

            segment_paths.append(work_path)

            # Step D: Inter-phrase silence (skip after the last phrase).
            if idx < len(clean_phrases) - 1:
                pause_duration = determine_pause_duration(phrase, cadence_config)
                silence_path = os.path.join(tmp_dir, f"silence_{idx:02d}.wav")
                sil_ok = await generate_silence(
                    pause_duration, _WORK_SAMPLE_RATE, silence_path
                )
                if sil_ok:
                    segment_paths.append(silence_path)
                    logger.debug(
                        "generate_natural_speech: pause after phrase %d = %.3fs",
                        idx,
                        pause_duration,
                    )
                else:
                    logger.warning(
                        "generate_natural_speech: inter-phrase silence %d failed — omitting gap",
                        idx,
                    )

        if not segment_paths:
            logger.error(
                "generate_natural_speech: all phrases failed — no segments to concatenate"
            )
            return False

        # ── Trailing silence ───────────────────────────────────────────────
        if cadence_config.trailing_pause > 0:
            trailing_path = os.path.join(tmp_dir, "trail_silence.wav")
            ok = await generate_silence(
                cadence_config.trailing_pause, _WORK_SAMPLE_RATE, trailing_path
            )
            if ok:
                segment_paths.append(trailing_path)
            else:
                logger.warning(
                    "generate_natural_speech: trailing silence generation failed — skipping"
                )

        # ── Concatenation ──────────────────────────────────────────────────
        concat_path = os.path.join(tmp_dir, "concatenated.wav")
        concat_ok = await concatenate_segments(segment_paths, concat_path)
        if not concat_ok:
            logger.error("generate_natural_speech: concatenation failed")
            return False

        logger.info(
            "generate_natural_speech: concatenated %d segments into %s",
            len(segment_paths),
            os.path.basename(concat_path),
        )

        # ── Optional post-processing ───────────────────────────────────────
        if cadence_config.postprocess:
            try:
                from voxwatch.speech.postprocess import apply_natural_postprocess
                postproc_path = os.path.join(tmp_dir, "postprocessed.wav")
                pp_ok = await apply_natural_postprocess(concat_path, postproc_path)
                if pp_ok:
                    concat_path = postproc_path
                    logger.debug("generate_natural_speech: post-processing applied")
                else:
                    logger.warning(
                        "generate_natural_speech: post-processing failed — using unprocessed audio"
                    )
            except Exception as pp_exc:
                logger.warning(
                    "generate_natural_speech: post-processing raised %s — skipping",
                    pp_exc,
                )

        # ── Copy result to output path ─────────────────────────────────────
        import shutil as _shutil
        try:
            _shutil.copy2(concat_path, output_path)
        except OSError as copy_exc:
            logger.error(
                "generate_natural_speech: failed to copy result to %s: %s",
                output_path,
                copy_exc,
            )
            return False

        final_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        if final_size == 0:
            logger.error(
                "generate_natural_speech: output file is empty after copy: %s",
                output_path,
            )
            return False

        logger.info(
            "generate_natural_speech: complete — %s (%d bytes)",
            os.path.basename(output_path),
            final_size,
        )
        return True

    except Exception as exc:
        logger.error(
            "generate_natural_speech: unexpected error: %s",
            exc,
            exc_info=True,
        )
        return False
    finally:
        # Always clean up temp files regardless of success or failure.
        try:
            tmp_dir_obj.cleanup()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _convert_to_work_format(input_path: str, output_path: str) -> bool:
    """Convert any WAV to the internal working format (44.1 kHz 16-bit mono).

    This is an internal step called inside ``generate_natural_speech`` to
    normalise TTS output across different providers before applying speed
    filters or concatenating.

    Args:
        input_path: Source audio file (any format ffmpeg can decode).
        output_path: Destination WAV in pcm_s16le / 44100 Hz / mono format.

    Returns:
        True if ffmpeg succeeded and the output file exists.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", input_path,
            "-acodec", "pcm_s16le",
            "-ar", str(_WORK_SAMPLE_RATE),
            "-ac", str(_WORK_CHANNELS),
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
        if proc.returncode == 0 and os.path.exists(output_path):
            return True
        logger.warning(
            "_convert_to_work_format: ffmpeg exit %d — %s",
            proc.returncode,
            stderr.decode("utf-8", errors="replace")[-200:],
        )
        return False
    except asyncio.TimeoutError:
        logger.error(
            "_convert_to_work_format: ffmpeg timed out after %ds", _SUBPROCESS_TIMEOUT
        )
        return False
    except FileNotFoundError:
        logger.error("_convert_to_work_format: ffmpeg not found on PATH")
        return False
