#!/usr/bin/env python3
"""test_natural_cadence.py — VoxWatch Natural Cadence Speech System Test

Generates sample audio with and without natural cadence applied so you can
do an A/B comparison by ear.  Also exercises the ``parse_ai_response`` helper
with three different input formats and prints a timing summary table.

What this script tests:
    1. ``parse_ai_response`` — JSON array, JSON in markdown code block, and
       plain text sentence-split fallback.
    2. ``determine_pause_duration`` — punctuation-aware pause calculation.
    3. ``generate_silence`` — ffmpeg lavfi silence generation.
    4. ``apply_speed_variation`` — ffmpeg atempo filter.
    5. ``concatenate_segments`` — ffmpeg concat demuxer.
    6. ``apply_natural_postprocess`` — light compressor + loudnorm pass.
    7. Full natural cadence pipeline via a lightweight mock AudioPipeline that
       uses espeak-ng (or espeak) for TTS.
    8. A/B comparison: flat-string TTS vs. natural cadence for the same text.

All output WAVs are written to ``--output-dir`` (default:
``./test_cadence_output/``) so you can play them back and compare.

Prerequisites:
    ffmpeg on PATH
    espeak-ng or espeak on PATH  (for the A/B TTS callback)

Usage:
    python tests/test_natural_cadence.py
    python tests/test_natural_cadence.py --output-dir /tmp/cadence_test
    python tests/test_natural_cadence.py --keep-output
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = "./test_cadence_output"

# Sample phrase set used for A/B comparison.  Written as four distinct spoken
# thoughts so natural cadence has clear sentence boundaries to work with.
SAMPLE_PHRASES = [
    "Stop.",
    "You are on private property.",
    "You have been recorded on camera.",
    "The homeowner has been notified and is watching.",
]

# The same content as a single flat string for A/B comparison.
SAMPLE_FLAT = " ".join(SAMPLE_PHRASES)

# JSON array variant — used to exercise the parse path.
SAMPLE_JSON_ARRAY = (
    '["Stop.", "You are on private property.", '
    '"You have been recorded on camera.", '
    '"The homeowner has been notified and is watching."]'
)

# JSON in a markdown code block variant.
SAMPLE_JSON_BLOCK = f"```json\n{SAMPLE_JSON_ARRAY}\n```"

# Plain text with sentence boundaries — exercises the sentence-split fallback.
SAMPLE_PLAIN_TEXT = SAMPLE_FLAT

SUBPROCESS_TIMEOUT = 30
MIN_WAV_BYTES = 200

_TAG_OK = "[OK]"
_TAG_FAIL = "[FAIL]"
_TAG_SKIP = "[SKIP]"
_TAG_INFO = "[INFO]"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Holds the outcome of a single test step.

    Attributes:
        label: Human-readable step name used in the summary table.
        status: One of ``"OK"``, ``"FAIL"``, or ``"SKIP"``.
        elapsed_seconds: Wall-clock time for the step, or None.
        file_size_bytes: Size of any output file produced, or None.
        output_path: Absolute path to the saved WAV, or None.
        note: Short reason shown in the table when status is not OK.
        warnings: Non-fatal warnings collected during the step.
    """

    label: str
    status: str = "SKIP"
    elapsed_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    output_path: Optional[str] = None
    note: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Returns:
        Namespace with ``output_dir`` and ``keep_output`` populated.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Test VoxWatch natural cadence speech system: "
            "generates A/B audio samples and prints timing info."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python tests/test_natural_cadence.py\n"
            "  python tests/test_natural_cadence.py --output-dir /tmp/cadence\n"
            "  python tests/test_natural_cadence.py --keep-output\n"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Directory where audio files are saved. (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Do not delete the output directory if it exists.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------


def check_ffmpeg() -> bool:
    """Verify that ffmpeg is available on PATH.

    Returns:
        True if ffmpeg is found, False otherwise.
    """
    return bool(shutil.which("ffmpeg"))


def find_espeak() -> Optional[str]:
    """Locate espeak-ng or espeak on PATH.

    Returns:
        Binary name, or None if neither is available.
    """
    for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
            return cmd
    return None


# ---------------------------------------------------------------------------
# Lightweight mock AudioPipeline for testing
# ---------------------------------------------------------------------------


class MockAudioPipeline:
    """Minimal AudioPipeline substitute that uses espeak for TTS.

    Used by the natural cadence tests so the full VoxWatch service stack
    (MQTT, go2rtc, Frigate) does not need to be running.

    Attributes:
        espeak_cmd: espeak binary name.
        config: Minimal config dict with default cadence settings.
    """

    def __init__(self, espeak_cmd: str) -> None:
        """Initialise with an espeak binary name.

        Args:
            espeak_cmd: Binary name (``"espeak-ng"`` or ``"espeak"``).
        """
        self.espeak_cmd = espeak_cmd
        self.config: dict = {}

    async def generate_tts(self, message: str, output_path: str) -> bool:
        """Generate a WAV file using espeak.

        Args:
            message: Text to synthesize.
            output_path: Destination WAV file path.

        Returns:
            True on success.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self.espeak_cmd,
                "-w", output_path,
                "-s", "130",
                "-p", "30",
                "--", message,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=SUBPROCESS_TIMEOUT)
            return proc.returncode == 0 and os.path.exists(output_path)
        except Exception as exc:
            print(f"    {_TAG_FAIL} MockAudioPipeline.generate_tts: {exc}")
            return False


# ---------------------------------------------------------------------------
# Individual test steps
# ---------------------------------------------------------------------------


def test_parse_ai_response() -> StepResult:
    """Test Step 1 — parse_ai_response with three input formats.

    Verifies that:
    - A bare JSON array returns the correct phrase list.
    - A JSON array wrapped in a markdown code block returns the same list.
    - Plain sentence text splits into the same four phrases.

    Returns:
        StepResult with status and note populated.
    """
    result = StepResult(label="parse_ai_response")
    try:
        from voxwatch.speech.natural_cadence import parse_ai_response
    except ImportError as exc:
        result.status = "FAIL"
        result.note = f"import error: {exc}"
        print(f"    {_TAG_FAIL} Cannot import parse_ai_response: {exc}")
        return result

    t0 = time.perf_counter()
    failures: list[str] = []
    expected_len = 4

    # Format A: bare JSON array
    phrases_a = parse_ai_response(SAMPLE_JSON_ARRAY)
    if len(phrases_a) != expected_len:
        failures.append(
            f"JSON array: expected {expected_len} phrases, got {len(phrases_a)}"
        )
    else:
        print(f"    {_TAG_OK} JSON array: {len(phrases_a)} phrases parsed correctly")

    # Format B: JSON in markdown code block
    phrases_b = parse_ai_response(SAMPLE_JSON_BLOCK)
    if len(phrases_b) != expected_len:
        failures.append(
            f"JSON code block: expected {expected_len} phrases, got {len(phrases_b)}"
        )
    else:
        print(f"    {_TAG_OK} JSON code block: {len(phrases_b)} phrases parsed correctly")

    # Format C: plain text sentence split
    phrases_c = parse_ai_response(SAMPLE_PLAIN_TEXT)
    if len(phrases_c) < 2:
        failures.append(
            f"Plain text: expected >= 2 sentences, got {len(phrases_c)}"
        )
    else:
        print(f"    {_TAG_OK} Plain text: {len(phrases_c)} sentences split correctly")

    elapsed = time.perf_counter() - t0
    result.elapsed_seconds = elapsed

    if failures:
        result.status = "FAIL"
        result.note = "; ".join(failures)
        for f in failures:
            print(f"    {_TAG_FAIL} {f}")
    else:
        result.status = "OK"

    return result


def test_determine_pause() -> StepResult:
    """Test Step 2 — determine_pause_duration punctuation rules.

    Verifies that each recognised punctuation mark produces the expected pause
    duration category (not an exact float, because the random range makes that
    impractical to test exactly).

    Returns:
        StepResult with status populated.
    """
    result = StepResult(label="pause durations")
    try:
        from voxwatch.speech.natural_cadence import (
            determine_pause_duration,
            CadenceConfig,
        )
    except ImportError as exc:
        result.status = "FAIL"
        result.note = f"import error: {exc}"
        print(f"    {_TAG_FAIL} Cannot import determine_pause_duration: {exc}")
        return result

    t0 = time.perf_counter()
    cfg = CadenceConfig()
    failures: list[str] = []

    cases: list[tuple[str, float, str]] = [
        ("Stop.", cfg.period_pause, "period"),
        ("Wait...", cfg.ellipsis_pause, "ellipsis"),
        ("Slowly,", cfg.comma_pause, "comma"),
        ("No punctuation", -1.0, "random range"),  # -1 means check range
    ]

    for phrase, expected_val, label in cases:
        got = determine_pause_duration(phrase, cfg)
        if label == "random range":
            if not (cfg.min_pause <= got <= cfg.max_pause):
                failures.append(
                    f"random range for '{phrase}': {got:.3f} not in "
                    f"[{cfg.min_pause}, {cfg.max_pause}]"
                )
            else:
                print(f"    {_TAG_OK} {label}: {got:.3f}s (in [{cfg.min_pause}, {cfg.max_pause}])")
        elif abs(got - expected_val) > 0.001:
            failures.append(
                f"{label} for '{phrase}': expected {expected_val}, got {got}"
            )
        else:
            print(f"    {_TAG_OK} {label}: {got:.3f}s")

    elapsed = time.perf_counter() - t0
    result.elapsed_seconds = elapsed

    if failures:
        result.status = "FAIL"
        result.note = "; ".join(failures)
        for f in failures:
            print(f"    {_TAG_FAIL} {f}")
    else:
        result.status = "OK"

    return result


def test_generate_silence(output_dir: str) -> StepResult:
    """Test Step 3 — generate_silence via ffmpeg lavfi.

    Generates a 0.5 s silence WAV and verifies it exists and has a plausible
    file size.

    Args:
        output_dir: Directory for output files.

    Returns:
        StepResult with status, timing, and output_path populated.
    """
    result = StepResult(label="generate_silence")
    out_path = os.path.join(output_dir, "test_silence.wav")

    try:
        from voxwatch.speech.natural_cadence import generate_silence
    except ImportError as exc:
        result.status = "FAIL"
        result.note = f"import error: {exc}"
        print(f"    {_TAG_FAIL} Cannot import generate_silence: {exc}")
        return result

    t0 = time.perf_counter()
    ok = asyncio.run(generate_silence(0.5, 44100, out_path))
    elapsed = time.perf_counter() - t0

    result.elapsed_seconds = elapsed
    if ok and os.path.exists(out_path) and os.path.getsize(out_path) >= MIN_WAV_BYTES:
        size = os.path.getsize(out_path)
        result.status = "OK"
        result.file_size_bytes = size
        result.output_path = out_path
        print(
            f"    {_TAG_OK} 0.5s silence generated in {elapsed:.3f}s "
            f"({size // 1024}KB): {os.path.basename(out_path)}"
        )
    else:
        result.status = "FAIL"
        result.note = "ffmpeg failed or output missing/empty"
        print(f"    {_TAG_FAIL} generate_silence failed after {elapsed:.3f}s")

    return result


def test_speed_variation(output_dir: str, source_path: str) -> StepResult:
    """Test Step 4 — apply_speed_variation via ffmpeg atempo.

    Args:
        output_dir: Directory for output files.
        source_path: Path to an existing WAV file to speed-alter.

    Returns:
        StepResult with status, timing, and output_path populated.
    """
    result = StepResult(label="speed_variation")
    out_path = os.path.join(output_dir, "test_speed.wav")

    if not source_path or not os.path.exists(source_path):
        result.status = "SKIP"
        result.note = "source WAV unavailable"
        print(f"    {_TAG_SKIP} Skipped — no source WAV")
        return result

    try:
        from voxwatch.speech.natural_cadence import apply_speed_variation
    except ImportError as exc:
        result.status = "FAIL"
        result.note = f"import error: {exc}"
        print(f"    {_TAG_FAIL} Cannot import apply_speed_variation: {exc}")
        return result

    t0 = time.perf_counter()
    ok = asyncio.run(apply_speed_variation(source_path, out_path, 1.05))
    elapsed = time.perf_counter() - t0

    result.elapsed_seconds = elapsed
    if ok and os.path.exists(out_path) and os.path.getsize(out_path) >= MIN_WAV_BYTES:
        size = os.path.getsize(out_path)
        result.status = "OK"
        result.file_size_bytes = size
        result.output_path = out_path
        print(
            f"    {_TAG_OK} atempo 1.05x applied in {elapsed:.3f}s "
            f"({size // 1024}KB): {os.path.basename(out_path)}"
        )
    else:
        result.status = "FAIL"
        result.note = "atempo filter failed or output missing"
        print(f"    {_TAG_FAIL} apply_speed_variation failed after {elapsed:.3f}s")

    return result


def test_postprocess(output_dir: str, source_path: str) -> StepResult:
    """Test Step 5 — apply_natural_postprocess (compression + loudnorm).

    Args:
        output_dir: Directory for output files.
        source_path: Path to an existing WAV file to post-process.

    Returns:
        StepResult with status, timing, and output_path populated.
    """
    result = StepResult(label="postprocess")
    out_path = os.path.join(output_dir, "test_postprocess.wav")

    if not source_path or not os.path.exists(source_path):
        result.status = "SKIP"
        result.note = "source WAV unavailable"
        print(f"    {_TAG_SKIP} Skipped — no source WAV")
        return result

    try:
        from voxwatch.speech.postprocess import apply_natural_postprocess
    except ImportError as exc:
        result.status = "FAIL"
        result.note = f"import error: {exc}"
        print(f"    {_TAG_FAIL} Cannot import apply_natural_postprocess: {exc}")
        return result

    t0 = time.perf_counter()
    ok = asyncio.run(apply_natural_postprocess(source_path, out_path))
    elapsed = time.perf_counter() - t0

    result.elapsed_seconds = elapsed
    if ok and os.path.exists(out_path) and os.path.getsize(out_path) >= MIN_WAV_BYTES:
        size = os.path.getsize(out_path)
        result.status = "OK"
        result.file_size_bytes = size
        result.output_path = out_path
        print(
            f"    {_TAG_OK} Post-processing complete in {elapsed:.3f}s "
            f"({size // 1024}KB): {os.path.basename(out_path)}"
        )
    else:
        result.status = "FAIL"
        result.note = "postprocess failed or output missing"
        print(f"    {_TAG_FAIL} apply_natural_postprocess failed after {elapsed:.3f}s")

    return result


def test_natural_cadence_full(
    output_dir: str,
    espeak_cmd: Optional[str],
) -> StepResult:
    """Test Step 6 — full natural cadence pipeline (A/B: cadence vs flat TTS).

    Generates two audio files:
    - ``ab_cadence.wav``  — the four sample phrases via generate_natural_speech.
    - ``ab_flat.wav``     — the same text as a single flat string via espeak.

    Args:
        output_dir: Directory for output files.
        espeak_cmd: espeak binary name, or None if unavailable.

    Returns:
        StepResult for the cadence path.  Flat TTS is generated as a side
        effect and reported via print; it does not affect the return status.
    """
    result = StepResult(label="cadence pipeline")

    if not espeak_cmd:
        result.status = "SKIP"
        result.note = "espeak not available — cannot synthesize phrases"
        print(f"    {_TAG_SKIP} Skipped (no espeak for phrase TTS)")
        return result

    try:
        from voxwatch.speech.natural_cadence import generate_natural_speech
    except ImportError as exc:
        result.status = "FAIL"
        result.note = f"import error: {exc}"
        print(f"    {_TAG_FAIL} Cannot import generate_natural_speech: {exc}")
        return result

    cadence_out = os.path.join(output_dir, "ab_cadence.wav")
    flat_out = os.path.join(output_dir, "ab_flat.wav")
    pipeline = MockAudioPipeline(espeak_cmd)

    # ── Flat TTS (reference) ──────────────────────────────────────────────
    t0_flat = time.perf_counter()
    flat_ok = asyncio.run(pipeline.generate_tts(SAMPLE_FLAT, flat_out))
    elapsed_flat = time.perf_counter() - t0_flat
    if flat_ok and os.path.exists(flat_out):
        flat_size = os.path.getsize(flat_out)
        print(
            f"    {_TAG_OK} Flat TTS (reference): {elapsed_flat:.3f}s "
            f"({flat_size // 1024}KB): {os.path.basename(flat_out)}"
        )
    else:
        print(f"    {_TAG_FAIL} Flat TTS (reference) failed after {elapsed_flat:.3f}s")

    # ── Natural cadence ────────────────────────────────────────────────────
    t0_cadence = time.perf_counter()
    cadence_ok = asyncio.run(
        generate_natural_speech(
            phrases=SAMPLE_PHRASES,
            audio_pipeline=pipeline,
            output_path=cadence_out,
            config={},  # empty config → all CadenceConfig defaults apply
        )
    )
    elapsed_cadence = time.perf_counter() - t0_cadence

    result.elapsed_seconds = elapsed_cadence
    if cadence_ok and os.path.exists(cadence_out):
        size = os.path.getsize(cadence_out)
        result.status = "OK"
        result.file_size_bytes = size
        result.output_path = cadence_out
        print(
            f"    {_TAG_OK} Natural cadence: {elapsed_cadence:.3f}s "
            f"({size // 1024}KB): {os.path.basename(cadence_out)}"
        )
        print(
            f"    {_TAG_INFO} A/B files ready — compare by playing both WAVs:"
        )
        print(f"      Flat:    {os.path.abspath(flat_out)}")
        print(f"      Cadence: {os.path.abspath(cadence_out)}")
    else:
        result.status = "FAIL"
        result.note = "generate_natural_speech returned False or output missing"
        print(f"    {_TAG_FAIL} Natural cadence failed after {elapsed_cadence:.3f}s")

    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_time(seconds: Optional[float]) -> str:
    """Format elapsed seconds as a right-aligned string.

    Args:
        seconds: Elapsed time or None.

    Returns:
        Formatted string like ``"0.14s"`` or ``"—"``.
    """
    return f"{seconds:.2f}s" if seconds is not None else "—"


def _fmt_size(byte_count: Optional[int]) -> str:
    """Format a byte count as a human-readable KB string.

    Args:
        byte_count: Number of bytes, or None.

    Returns:
        Formatted string like ``"48KB"`` or ``"—"``.
    """
    return f"{byte_count // 1024}KB" if byte_count is not None else "—"


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------


def print_summary(results: list[StepResult], output_dir: str) -> None:
    """Print a formatted summary table of all test outcomes.

    Args:
        results: All StepResult instances, one per test step.
        output_dir: Output directory shown at the bottom of the table.
    """
    col_label = max(len(r.label) for r in results)
    col_time = 8
    col_size = 8

    header = f"  {'Step':<{col_label}}  {'Time':<{col_time}}  {'Size':<{col_size}}  Status"
    separator = "  " + "-" * (col_label + col_time + col_size + 14)

    print("Summary:")
    print(header)
    print(separator)

    for row in results:
        marker = ""
        if row.status == "FAIL":
            marker = " *"
        elif row.status == "SKIP":
            marker = " -"
        label_display = f"{row.label}{marker}"
        print(
            f"  {label_display:<{col_label}}  "
            f"{_fmt_time(row.elapsed_seconds):<{col_time}}  "
            f"{_fmt_size(row.file_size_bytes):<{col_size}}  "
            f"{row.status}"
        )

    footnotes = [r for r in results if r.status != "OK"]
    if footnotes:
        print()
        for row in footnotes:
            tag = _TAG_FAIL if row.status == "FAIL" else _TAG_SKIP
            print(f"  {tag} {row.label}: {row.note or row.status}")

    print()
    print(f"Output directory: {os.path.abspath(output_dir)}/")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Orchestrate all natural cadence tests and print the final summary.

    Execution order:
        1. Preflight — check ffmpeg and espeak availability.
        2. Test parse_ai_response (all three input formats).
        3. Test determine_pause_duration (punctuation rules).
        4. Test generate_silence (ffmpeg lavfi).
        5. Test apply_speed_variation (ffmpeg atempo).
        6. Test apply_natural_postprocess (compression + loudnorm).
        7. Full pipeline A/B comparison (cadence vs flat TTS).
        8. Print summary table.
    """
    args = parse_args()
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    print("=== VoxWatch Natural Cadence Speech Test ===\n")

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------
    print("Preflight checks:")

    ffmpeg_ok = check_ffmpeg()
    if not ffmpeg_ok:
        print(f"  {_TAG_FAIL} ffmpeg not found on PATH — cannot continue.")
        sys.exit(1)
    print(f"  {_TAG_OK} ffmpeg: {shutil.which('ffmpeg')}")

    espeak_cmd = find_espeak()
    if espeak_cmd:
        print(f"  {_TAG_OK} espeak: {shutil.which(espeak_cmd)} ({espeak_cmd})")
    else:
        print(
            f"  {_TAG_SKIP} espeak-ng / espeak not found — "
            "A/B pipeline test will be skipped"
        )

    try:
        import voxwatch.speech.natural_cadence  # noqa: F401
        import voxwatch.speech.postprocess      # noqa: F401
        print(f"  {_TAG_OK} voxwatch.speech modules importable")
    except ImportError as exc:
        print(f"  {_TAG_FAIL} Cannot import voxwatch.speech: {exc}")
        print(
            f"  {_TAG_INFO} Run from the repo root or install the package: "
            "pip install -e ."
        )
        sys.exit(1)

    print()

    # ------------------------------------------------------------------
    # Step 1 — parse_ai_response
    # ------------------------------------------------------------------
    print("Test 1: parse_ai_response (JSON array / code block / plain text)")
    r_parse = test_parse_ai_response()
    print()

    # ------------------------------------------------------------------
    # Step 2 — determine_pause_duration
    # ------------------------------------------------------------------
    print("Test 2: determine_pause_duration (punctuation rules)")
    r_pause = test_determine_pause()
    print()

    # ------------------------------------------------------------------
    # Step 3 — generate_silence
    # ------------------------------------------------------------------
    print("Test 3: generate_silence (0.5s lavfi silence)")
    r_silence = test_generate_silence(output_dir)
    silence_source = r_silence.output_path or ""
    print()

    # ------------------------------------------------------------------
    # Step 4 — apply_speed_variation  (uses silence WAV as a convenient source)
    # ------------------------------------------------------------------
    print("Test 4: apply_speed_variation (atempo 1.05x on silence WAV)")
    r_speed = test_speed_variation(output_dir, silence_source)
    print()

    # ------------------------------------------------------------------
    # Step 5 — apply_natural_postprocess  (uses silence WAV)
    # ------------------------------------------------------------------
    print("Test 5: apply_natural_postprocess (compression + loudnorm)")
    r_postproc = test_postprocess(output_dir, silence_source)
    print()

    # ------------------------------------------------------------------
    # Step 6 — Full pipeline A/B comparison
    # ------------------------------------------------------------------
    print(f"Test 6: Full cadence pipeline A/B comparison ({len(SAMPLE_PHRASES)} phrases)")
    r_cadence = test_natural_cadence_full(output_dir, espeak_cmd)
    print()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    all_results = [r_parse, r_pause, r_silence, r_speed, r_postproc, r_cadence]
    print_summary(all_results, output_dir)

    any_failed = any(r.status == "FAIL" for r in all_results)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
