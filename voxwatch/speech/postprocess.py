"""postprocess.py — Audio Post-Processing for Natural Cadence Speech

Applies a light audio post-processing pass to the concatenated natural cadence
output.  The goal is to make the final audio file sound more consistent and
polished without introducing audible artefacts:

  1. **Dynamic range compression** — a gentle compressor reduces loud peaks
     so quiet phrases and loud phrases feel equally present.  This matters
     because different TTS phrases may have different gain levels.
  2. **Silence trimming** — leading and trailing silence beyond a threshold is
     removed.  The natural cadence system adds its own controlled silence pads,
     so any additional silence from the TTS engine is unwanted.
  3. **Loudness normalisation** — the output level is normalised to a target
     integrated loudness of -16 LUFS (a broadcast-quality level appropriate for
     camera speaker output).

All processing is done via a single ffmpeg pass to avoid repeated
decode/encode cycles.  The filter chain is intentionally conservative — it
should be inaudible on well-produced TTS output and only noticeably improve
edge cases (very quiet voices, clipped peaks, leading TTS startup noise).

This module is imported lazily by ``generate_natural_speech`` in
``voxwatch.speech.natural_cadence`` so that a missing or broken postprocess
pass never crashes the main pipeline.
"""

import asyncio
import logging
import os

logger = logging.getLogger("voxwatch.speech.postprocess")

# ffmpeg subprocess timeout in seconds.
_SUBPROCESS_TIMEOUT = 30

# Target integrated loudness for normalisation (EBU R128 / ITU-R BS.1770).
# -16 LUFS is a reasonable level for camera speaker output — loud enough to be
# clearly audible outdoors but not clipping on cameras with limited dynamic
# range.
_TARGET_LUFS = -16.0

# Silence threshold for trimming (dB below full scale).  Audio quieter than
# this level at the edges of the file is trimmed away.
_SILENCE_THRESHOLD_DB = -50.0


async def apply_natural_postprocess(input_path: str, output_path: str) -> bool:
    """Apply light compression, silence trimming, and loudness normalisation.

    Runs a single ffmpeg pass with three chained audio filters:

    1. ``silenceremove`` — trims leading and trailing silence below
       ``_SILENCE_THRESHOLD_DB`` dB.  Uses a 0.1 s minimum silence duration so
       very brief quiet gaps between phrases are not accidentally removed.
    2. ``acompressor`` — gentle compressor with a 3:1 ratio, -18 dB threshold,
       and 10/200 ms attack/release.  This evening-out pass catches cases where
       different TTS phrases were generated at very different gain levels.
    3. ``loudnorm`` — EBU R128 two-pass loudness normalisation targeting
       ``_TARGET_LUFS`` LUFS integrated loudness.  Using the simpler single-pass
       mode (no ``measured_*`` params) sacrifices a small amount of accuracy for
       speed, which is acceptable for real-time deterrent audio generation.

    The output is written as PCM 16-bit signed at 44100 Hz mono, matching the
    internal working format used by the cadence pipeline.  The caller
    (``generate_natural_speech``) copies the result to ``output_path`` and then
    optionally converts it to the camera codec via ``AudioPipeline.convert_audio``.

    This function is intentionally non-fatal.  If ffmpeg fails for any reason,
    ``generate_natural_speech`` logs a warning and continues with the
    unprocessed concatenated audio.

    Args:
        input_path: Path to the concatenated WAV file produced by
            ``concatenate_segments``.  Expected format: pcm_s16le, 44100 Hz,
            mono.
        output_path: Absolute path for the post-processed output WAV.

    Returns:
        True if ffmpeg succeeded and ``output_path`` exists and is non-empty.
        False on any error, including ffmpeg not being on PATH, timeout, or
        a non-zero exit code.
    """
    # Build a single chained audio filter string.
    # silenceremove: trim leading silence >= 1 period, trailing silence >= 1 period,
    #   threshold -50 dB, minimum 0.1 s duration to avoid trimming natural short gaps.
    # acompressor: gentle 3:1 ratio at -18 dB threshold to even out gain across phrases.
    # loudnorm: EBU R128 single-pass targeting _TARGET_LUFS LUFS integrated loudness.
    filter_chain = (
        f"silenceremove=start_periods=1:start_silence=0.1:start_threshold={_SILENCE_THRESHOLD_DB}dB"
        f":stop_periods=1:stop_silence=0.1:stop_threshold={_SILENCE_THRESHOLD_DB}dB,"
        f"acompressor=threshold=-18dB:ratio=3:attack=10:release=200,"
        f"loudnorm=I={_TARGET_LUFS}:TP=-1.5:LRA=11"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", filter_chain,
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "1",
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )

        if proc.returncode != 0:
            logger.warning(
                "apply_natural_postprocess: ffmpeg exit %d — %s",
                proc.returncode,
                stderr.decode("utf-8", errors="replace")[-300:],
            )
            return False

        if not os.path.exists(output_path):
            logger.warning(
                "apply_natural_postprocess: ffmpeg succeeded but output file missing: %s",
                output_path,
            )
            return False

        size = os.path.getsize(output_path)
        if size == 0:
            logger.warning(
                "apply_natural_postprocess: output file is empty: %s", output_path
            )
            return False

        logger.debug(
            "apply_natural_postprocess: complete — %s (%d bytes)",
            os.path.basename(output_path),
            size,
        )
        return True

    except TimeoutError:
        logger.error(
            "apply_natural_postprocess: ffmpeg timed out after %ds", _SUBPROCESS_TIMEOUT
        )
        return False
    except FileNotFoundError:
        logger.error("apply_natural_postprocess: ffmpeg not found on PATH")
        return False
    except Exception as exc:
        logger.error(
            "apply_natural_postprocess: unexpected error: %s", exc, exc_info=True
        )
        return False
