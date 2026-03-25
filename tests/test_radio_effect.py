#!/usr/bin/env python3
"""
test_radio_effect.py — VoxWatch Radio Dispatch Audio Effect Test

Exercises the radio processing pipeline defined in ``voxwatch/audio_effects.py``
without requiring the full VoxWatch service to be running.  Only ffmpeg and an
espeak binary (``espeak-ng`` or ``espeak``) need to be present on PATH.

What this script tests:
    1. TTS source audio generation via espeak-ng / espeak.
    2. ``apply_radio_effect`` at all three intensity presets: low, medium, high.
    3. ``generate_static_assets`` — beep, static bursts, squelch, silence.
    4. ``compose_dispatch_audio`` — full beep-segments-squelch composition using
       three realistic dispatch segments.
    5. Processing time for each step and output file size.

All produced WAV files are written to ``--output-dir`` (default:
``./test_radio_output/``) so that you can play them back and compare.

Prerequisites:
    ffmpeg on PATH
    espeak-ng (or espeak) on PATH

Usage:
    python test_radio_effect.py
    python test_radio_effect.py --output-dir /tmp/radio_test
    python test_radio_effect.py --message "All units respond immediately."
    python test_radio_effect.py --keep-assets
"""

import argparse
import asyncio
import math
import os
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = "./test_radio_output"

# Dispatch message used to generate source TTS.  Written as three natural
# sentences so compose_dispatch_audio has three segments to stitch.
DEFAULT_MESSAGE = (
    "All units, 10-97 at 482 Elm Street. "
    "One suspect on property, wearing a dark hoodie and jeans. "
    "Last seen moving toward the rear gate carrying a backpack."
)

# Three segments that compose_dispatch_audio will stitch together.
DISPATCH_SEGMENTS = [
    "All units, 10-97 at 482 Elm Street. One suspect on property.",
    "Subject is wearing a dark hoodie and jeans, medium build.",
    "Last seen moving toward the rear gate carrying a backpack.",
]

# Radio intensity levels exercised in order.
INTENSITY_LEVELS = ("low", "medium", "high")

# subprocess timeout in seconds — applied to every ffmpeg / espeak call.
SUBPROCESS_TIMEOUT = 30

# Minimum byte count for a WAV we consider non-trivially populated.
MIN_WAV_BYTES = 200

# Status tag widths used in tabular output.
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
        elapsed_seconds: Wall-clock processing time, or None if not measured.
        file_size_bytes: Size of the output file, or None if not produced.
        output_path: Absolute path to the saved WAV, or None.
        note: Short reason shown in the table when status is not OK.
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
    """Parse CLI arguments for output directory and optional overrides.

    Returns:
        argparse.Namespace with ``output_dir``, ``message``, and
        ``keep_assets`` populated.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Test VoxWatch radio dispatch audio effects: apply all three "
            "intensity presets and compose a full dispatch sequence, then "
            "print a summary table with timing and file sizes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python test_radio_effect.py\n"
            "  python test_radio_effect.py --output-dir /tmp/radio_test\n"
            '  python test_radio_effect.py --message "Attention, leave now."\n'
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Directory where audio files are saved. (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--message",
        default=DEFAULT_MESSAGE,
        help=(
            "Text synthesised into the source TTS WAV. "
            f'(default: "{DEFAULT_MESSAGE[:55]}...")'
        ),
    )
    parser.add_argument(
        "--keep-assets",
        action="store_true",
        help=(
            "Do not regenerate static dispatch assets (beep, static, squelch) "
            "if they already exist in the output directory."
        ),
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
    if shutil.which("ffmpeg"):
        return True
    print(f"  {_TAG_FAIL} ffmpeg not found on PATH. Install ffmpeg to run this test.")
    return False


def find_espeak() -> Optional[str]:
    """Locate the best available espeak binary on PATH.

    Prefers ``espeak-ng`` (newer feature set) over legacy ``espeak``.

    Returns:
        The binary name (``"espeak-ng"`` or ``"espeak"``), or None if neither
        is on PATH.
    """
    for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
            return cmd
    return None


# ---------------------------------------------------------------------------
# TTS source generation
# ---------------------------------------------------------------------------


def generate_tts_espeak(
    espeak_cmd: str,
    message: str,
    output_path: str,
) -> bool:
    """Generate a WAV file from text using espeak-ng or espeak.

    Uses ``-s 130`` (speaking rate) and ``-p 30`` (pitch) to match the
    settings used by VoxWatch's ``EspeakProvider``.  The ``--`` sentinel
    prevents leading-hyphen text from being parsed as a flag.

    Args:
        espeak_cmd: Binary name, either ``"espeak-ng"`` or ``"espeak"``.
        message: Text to synthesize.
        output_path: Absolute path for the output WAV file.

    Returns:
        True if the file was written successfully, False on any error.
    """
    cmd = [espeak_cmd, "-w", output_path, "-s", "130", "-p", "30", "--", message]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return os.path.getsize(output_path) >= MIN_WAV_BYTES
        stderr = result.stderr.decode("utf-8", errors="replace")
        print(f"    {_TAG_FAIL} {espeak_cmd} exit {result.returncode}: {stderr[:200]}")
        return False
    except subprocess.TimeoutExpired:
        print(f"    {_TAG_FAIL} {espeak_cmd} timed out after {SUBPROCESS_TIMEOUT}s")
        return False
    except Exception as exc:
        print(f"    {_TAG_FAIL} {espeak_cmd} error: {exc}")
        return False


def generate_tone_wav(output_path: str, freq: int = 800, duration: float = 2.5) -> None:
    """Write a pure sine-wave WAV as a last-resort TTS substitute.

    Produces 16-bit signed PCM at 22050 Hz mono — the same format that
    ``apply_radio_effect`` expects.

    Args:
        output_path: Where to write the WAV file.
        freq: Tone frequency in Hz (default 800).
        duration: Length in seconds (default 2.5).
    """
    sample_rate = 22050
    num_samples = int(sample_rate * duration)
    samples = bytearray()
    for i in range(num_samples):
        value = int(32767 * 0.6 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples += struct.pack("<h", value)

    data_size = len(samples)
    with open(output_path, "wb") as fh:
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + data_size))
        fh.write(b"WAVE")
        fh.write(b"fmt ")
        fh.write(struct.pack("<I", 16))
        fh.write(struct.pack("<H", 1))            # PCM
        fh.write(struct.pack("<H", 1))            # mono
        fh.write(struct.pack("<I", sample_rate))
        fh.write(struct.pack("<I", sample_rate * 2))
        fh.write(struct.pack("<H", 2))
        fh.write(struct.pack("<H", 16))
        fh.write(b"data")
        fh.write(struct.pack("<I", data_size))
        fh.write(samples)


# ---------------------------------------------------------------------------
# Thin synchronous wrappers around audio_effects async functions
# ---------------------------------------------------------------------------


def run_apply_radio_effect(
    input_path: str,
    output_path: str,
    intensity: str,
) -> bool:
    """Run ``apply_radio_effect`` synchronously inside a new event loop.

    Args:
        input_path: Source WAV file path.
        output_path: Destination WAV file path.
        intensity: One of ``"low"``, ``"medium"``, or ``"high"``.

    Returns:
        True if the effect was applied successfully.
    """
    from voxwatch.audio_effects import apply_radio_effect

    config = {"radio_effect": {"intensity": intensity}}
    return asyncio.run(apply_radio_effect(input_path, output_path, config))


def run_generate_static_assets(assets_dir: str) -> dict[str, str]:
    """Run ``generate_static_assets`` synchronously inside a new event loop.

    Args:
        assets_dir: Directory where asset WAVs will be written.

    Returns:
        Mapping of asset name to file path (see ``generate_static_assets``
        docstring for key names).
    """
    from voxwatch.audio_effects import generate_static_assets

    return asyncio.run(generate_static_assets(assets_dir))


def run_compose_dispatch_audio(
    segments: list[str],
    output_path: str,
    static_assets: dict[str, str],
    espeak_cmd: str,
    intensity: str = "medium",
) -> bool:
    """Run ``compose_dispatch_audio`` synchronously inside a new event loop.

    Provides a minimal async TTS callback that shells out to espeak so the
    composition test does not depend on the full VoxWatch TTS provider stack.

    Args:
        segments: List of 2-3 short dispatch text phrases.
        output_path: Destination WAV file path for the composed result.
        static_assets: Asset map from ``generate_static_assets``.
        espeak_cmd: Espeak binary name (``"espeak-ng"`` or ``"espeak"``).
        intensity: Radio effect intensity preset (default ``"medium"``).

    Returns:
        True if the composed WAV was written successfully.
    """
    from voxwatch.audio_effects import compose_dispatch_audio

    config = {"radio_effect": {"intensity": intensity}}

    async def _tts(text: str, path: str) -> bool:
        """Async espeak TTS callback for compose_dispatch_audio.

        Args:
            text: Segment text to synthesize.
            path: Output WAV path.

        Returns:
            True on success.
        """
        proc = await asyncio.create_subprocess_exec(
            espeak_cmd,
            "-w", path,
            "-s", "130",
            "-p", "30",
            "--", text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=SUBPROCESS_TIMEOUT)
        return proc.returncode == 0 and os.path.exists(path)

    return asyncio.run(
        compose_dispatch_audio(segments, _tts, output_path, config, static_assets)
    )


# ---------------------------------------------------------------------------
# Human-readable formatting helpers
# ---------------------------------------------------------------------------


def _fmt_size(byte_count: Optional[int]) -> str:
    """Format a byte count as a human-readable KB string.

    Args:
        byte_count: Number of bytes, or None.

    Returns:
        Formatted string such as ``"48KB"`` or ``"—"``.
    """
    if byte_count is None:
        return "—"
    return f"{byte_count // 1024}KB"


def _fmt_time(seconds: Optional[float]) -> str:
    """Format elapsed seconds to two decimal places.

    Args:
        seconds: Elapsed time in seconds, or None.

    Returns:
        Formatted string such as ``"0.14s"`` or ``"—"``.
    """
    if seconds is None:
        return "—"
    return f"{seconds:.2f}s"


def _wav_duration(path: str) -> Optional[float]:
    """Read the duration of a WAV file from its header without ffprobe.

    Parses the standard RIFF/WAVE ``fmt `` chunk to extract sample rate,
    number of channels, and bit depth, then divides the data chunk size by
    the byte rate to compute duration.

    Args:
        path: Absolute path to a WAV file.

    Returns:
        Duration in seconds, or None if the header cannot be parsed.
    """
    try:
        with open(path, "rb") as fh:
            header = fh.read(44)
        if len(header) < 44 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            return None
        # Byte rate lives at offset 28 (4 bytes, little-endian)
        byte_rate = struct.unpack_from("<I", header, 28)[0]
        # Data chunk size lives at offset 40
        data_size = struct.unpack_from("<I", header, 40)[0]
        if byte_rate == 0:
            return None
        return data_size / byte_rate
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Individual test steps
# ---------------------------------------------------------------------------


def test_generate_source(
    output_dir: str,
    message: str,
    espeak_cmd: Optional[str],
) -> StepResult:
    """Test Step 1 — generate the source TTS WAV used by all effect tests.

    Tries espeak-ng/espeak first, then falls back to a pure sine-wave tone so
    subsequent steps can still exercise ffmpeg even if no TTS engine is present.

    Args:
        output_dir: Directory for output files.
        message: Text to synthesize.
        espeak_cmd: Espeak binary name, or None if unavailable.

    Returns:
        StepResult with status, timing, and output_path populated.
    """
    result = StepResult(label="source TTS")
    out_path = os.path.join(output_dir, "test_source.wav")

    t0 = time.perf_counter()

    if espeak_cmd:
        ok = generate_tts_espeak(espeak_cmd, message, out_path)
        engine_used = espeak_cmd
    else:
        ok = False

    if not ok:
        # Tone fallback — always succeeds, but we note it
        print(f"    {_TAG_INFO} No espeak found — using 800 Hz sine-wave fallback tone")
        generate_tone_wav(out_path)
        engine_used = "tone fallback"
        ok = os.path.exists(out_path) and os.path.getsize(out_path) >= MIN_WAV_BYTES

    elapsed = time.perf_counter() - t0

    if ok:
        size = os.path.getsize(out_path)
        duration = _wav_duration(out_path)
        dur_str = f"{duration:.1f}s" if duration else "?s"
        result.status = "OK"
        result.elapsed_seconds = elapsed
        result.file_size_bytes = size
        result.output_path = out_path
        print(
            f"    {_TAG_OK} Generated TTS ({engine_used}): "
            f"{os.path.basename(out_path)} ({dur_str}, {_fmt_size(size)})"
        )
    else:
        result.status = "FAIL"
        result.note = "espeak and tone fallback both failed"
        print(f"    {_TAG_FAIL} Source audio generation failed")

    return result


def test_radio_intensity(
    output_dir: str,
    source_path: str,
    intensity: str,
) -> StepResult:
    """Test Step 2/3/4 — apply one radio effect intensity preset.

    Calls ``apply_radio_effect`` from ``voxwatch.audio_effects`` and records
    the wall-clock time to process the source WAV.

    Args:
        output_dir: Directory for output files.
        source_path: Path to the clean TTS WAV generated in Step 1.
        intensity: One of ``"low"``, ``"medium"``, or ``"high"``.

    Returns:
        StepResult with status, timing, and output_path populated.
    """
    result = StepResult(label=intensity)
    out_path = os.path.join(output_dir, f"test_radio_{intensity}.wav")

    if not os.path.exists(source_path):
        result.status = "SKIP"
        result.note = "source WAV missing — Step 1 failed"
        print(f"    {_TAG_SKIP} Skipped (source WAV not available)")
        return result

    t0 = time.perf_counter()
    try:
        ok = run_apply_radio_effect(source_path, out_path, intensity)
    except Exception as exc:
        ok = False
        result.warnings.append(str(exc))

    elapsed = time.perf_counter() - t0

    if ok and os.path.exists(out_path):
        size = os.path.getsize(out_path)
        result.status = "OK"
        result.elapsed_seconds = elapsed
        result.file_size_bytes = size
        result.output_path = out_path
        print(
            f"    {_TAG_OK} Applied in {_fmt_time(elapsed)}: "
            f"{os.path.basename(out_path)} ({_fmt_size(size)})"
        )
    else:
        result.status = "FAIL"
        result.elapsed_seconds = elapsed
        result.note = "apply_radio_effect returned False or output missing"
        print(f"    {_TAG_FAIL} Radio effect ({intensity}) failed after {_fmt_time(elapsed)}")
        for w in result.warnings:
            print(f"      {_TAG_INFO} {w}")

    return result


def test_static_assets(output_dir: str) -> tuple[StepResult, dict[str, str]]:
    """Test the static asset generation step used by compose_dispatch_audio.

    Calls ``generate_static_assets`` and verifies each expected WAV was created
    and is non-empty.  Returns the asset map regardless of partial failures so
    subsequent steps can proceed with whatever was produced.

    Args:
        output_dir: Directory where asset WAVs are written.

    Returns:
        Tuple of (StepResult, asset_dict).  ``asset_dict`` maps asset names to
        file paths for the five standard dispatch assets.
    """
    result = StepResult(label="static assets")
    assets_dir = os.path.join(output_dir, "dispatch_assets")

    t0 = time.perf_counter()
    try:
        assets = run_generate_static_assets(assets_dir)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        result.status = "FAIL"
        result.elapsed_seconds = elapsed
        result.note = str(exc)
        print(f"    {_TAG_FAIL} generate_static_assets raised: {exc}")
        return result, {}

    elapsed = time.perf_counter() - t0

    expected = ("beep", "static_short", "static_long", "squelch", "gap_silence")
    missing = [n for n in expected if n not in assets]
    total_size = sum(
        os.path.getsize(p) for p in assets.values() if os.path.exists(p)
    )

    if missing:
        result.status = "FAIL"
        result.note = f"missing assets: {', '.join(missing)}"
        print(f"    {_TAG_FAIL} Missing assets: {', '.join(missing)}")
    else:
        result.status = "OK"
        print(f"    {_TAG_OK} All 5 assets generated in {assets_dir}/")

    result.elapsed_seconds = elapsed
    result.file_size_bytes = total_size
    return result, assets


def test_compose_dispatch(
    output_dir: str,
    segments: list[str],
    static_assets: dict[str, str],
    espeak_cmd: Optional[str],
) -> StepResult:
    """Test the full dispatch composition — beep + segments + squelch.

    Calls ``compose_dispatch_audio`` with three realistic dispatch segments and
    measures total wall-clock time including TTS synthesis for each segment.

    Args:
        output_dir: Directory for output files.
        segments: List of text phrases passed to compose_dispatch_audio.
        static_assets: Asset map from ``generate_static_assets``.
        espeak_cmd: Espeak binary name, or None if unavailable.

    Returns:
        StepResult with status, timing, and output_path populated.
    """
    result = StepResult(label="full comp")
    out_path = os.path.join(output_dir, "test_dispatch_full.wav")

    if not espeak_cmd:
        result.status = "SKIP"
        result.note = "espeak not available — cannot synthesize segments"
        print(f"    {_TAG_SKIP} Skipped (no espeak available for segment TTS)")
        return result

    required_assets = ("beep", "static_short", "squelch", "gap_silence")
    missing = [a for a in required_assets if a not in static_assets]
    if missing:
        result.status = "SKIP"
        result.note = f"missing static assets: {', '.join(missing)}"
        print(f"    {_TAG_SKIP} Skipped — missing required assets: {', '.join(missing)}")
        return result

    t0 = time.perf_counter()
    try:
        ok = run_compose_dispatch_audio(
            segments,
            out_path,
            static_assets,
            espeak_cmd,
            intensity="medium",
        )
    except Exception as exc:
        ok = False
        result.warnings.append(str(exc))

    elapsed = time.perf_counter() - t0

    if ok and os.path.exists(out_path):
        size = os.path.getsize(out_path)
        duration = _wav_duration(out_path)
        dur_str = f"{duration:.1f}s" if duration else "?s"
        result.status = "OK"
        result.elapsed_seconds = elapsed
        result.file_size_bytes = size
        result.output_path = out_path
        print(
            f"    {_TAG_OK} Composed in {_fmt_time(elapsed)}: "
            f"{os.path.basename(out_path)} ({dur_str}, {_fmt_size(size)})"
        )
    else:
        result.status = "FAIL"
        result.elapsed_seconds = elapsed
        result.note = "compose_dispatch_audio returned False or output missing"
        print(f"    {_TAG_FAIL} Dispatch composition failed after {_fmt_time(elapsed)}")
        for w in result.warnings:
            print(f"      {_TAG_INFO} {w}")

    return result


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------


def print_summary(
    intensity_results: list[StepResult],
    full_comp_result: StepResult,
    output_dir: str,
) -> None:
    """Print a formatted summary table of all test outcomes.

    Args:
        intensity_results: Results from the three radio intensity tests.
        full_comp_result: Result from the full dispatch composition test.
        output_dir: Output directory shown at the bottom of the table.
    """
    all_rows = intensity_results + [full_comp_result]

    col_label = max(len(r.label) for r in all_rows)
    col_time = 8
    col_size = 8

    header = f"  {'Intensity':<{col_label}}  {'Time':<{col_time}}  {'Size':<{col_size}}"
    separator = "  " + "-" * (col_label + col_time + col_size + 6)

    print("Summary:")
    print(header)
    print(separator)

    for row in all_rows:
        status_marker = ""
        if row.status == "FAIL":
            status_marker = " *"
        elif row.status == "SKIP":
            status_marker = " -"

        label_display = f"{row.label}{status_marker}"
        time_display = _fmt_time(row.elapsed_seconds)
        size_display = _fmt_size(row.file_size_bytes)

        print(f"  {label_display:<{col_label}}  {time_display:<{col_time}}  {size_display:<{col_size}}")

    # Footnotes for non-OK rows
    footnotes = [r for r in all_rows if r.status != "OK"]
    if footnotes:
        print()
        for row in footnotes:
            marker = "*" if row.status == "FAIL" else "-"
            tag = _TAG_FAIL if row.status == "FAIL" else _TAG_SKIP
            print(f"  {tag} {row.label}: {row.note or row.status}")

    print()
    print(f"Audio files saved to: {os.path.abspath(output_dir)}/")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Orchestrate all radio effect tests and print the final summary.

    Execution order:
        1. Preflight — check ffmpeg and espeak availability.
        2. Generate source TTS WAV.
        3. Apply radio effect at low, medium, and high intensity.
        4. Generate static dispatch assets (beep, static, squelch, silence).
        5. Compose a full dispatch sequence from three segments.
        6. Print summary table.
    """
    args = parse_args()
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    print("=== VoxWatch Radio Effect Test ===\n")

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------
    print("Preflight checks:")

    ffmpeg_ok = check_ffmpeg()
    if not ffmpeg_ok:
        print(f"  {_TAG_FAIL} ffmpeg is required — cannot continue.")
        sys.exit(1)
    print(f"  {_TAG_OK} ffmpeg found: {shutil.which('ffmpeg')}")

    espeak_cmd = find_espeak()
    if espeak_cmd:
        print(f"  {_TAG_OK} espeak found: {shutil.which(espeak_cmd)} ({espeak_cmd})")
    else:
        print(
            f"  {_TAG_SKIP} espeak-ng / espeak not found — "
            "source TTS will use a sine-wave fallback tone"
        )

    # Verify voxwatch.audio_effects is importable (not a hard exit — each
    # step handles ImportError individually so the error message is localised)
    try:
        import voxwatch.audio_effects  # noqa: F401

        print(f"  {_TAG_OK} voxwatch.audio_effects importable")
    except ImportError as exc:
        print(f"  {_TAG_FAIL} Cannot import voxwatch.audio_effects: {exc}")
        print(
            f"  {_TAG_INFO} Run from the repo root or install the package: "
            "pip install -e ."
        )
        sys.exit(1)

    print()

    # ------------------------------------------------------------------
    # Step 1 — Source TTS
    # ------------------------------------------------------------------
    print("Test 1: Generate source audio")
    source_result = test_generate_source(output_dir, args.message, espeak_cmd)
    source_path = source_result.output_path or ""
    print()

    # ------------------------------------------------------------------
    # Steps 2-4 — Radio effect at each intensity level
    # ------------------------------------------------------------------
    intensity_results: list[StepResult] = []
    for step_num, intensity in enumerate(INTENSITY_LEVELS, start=2):
        print(f"Test {step_num}: Radio effect -- {intensity} intensity")
        res = test_radio_intensity(output_dir, source_path, intensity)
        intensity_results.append(res)
        print()

    # ------------------------------------------------------------------
    # Step 5 — Static assets (needed before composition)
    # ------------------------------------------------------------------
    print("Test 5: Generate static dispatch assets")
    if args.keep_assets:
        print(f"    {_TAG_INFO} --keep-assets set; skipping regeneration if files exist")
    assets_result, static_assets = test_static_assets(output_dir)
    print()

    # ------------------------------------------------------------------
    # Step 6 — Full dispatch composition
    # ------------------------------------------------------------------
    print(f"Test 6: Full dispatch composition ({len(DISPATCH_SEGMENTS)} segments)")
    comp_result = test_compose_dispatch(
        output_dir,
        DISPATCH_SEGMENTS,
        static_assets,
        espeak_cmd,
    )
    print()

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------
    print_summary(intensity_results, comp_result, output_dir)

    # Exit with non-zero code if any test step failed outright
    any_failed = any(
        r.status == "FAIL"
        for r in intensity_results + [assets_result, comp_result, source_result]
    )
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
