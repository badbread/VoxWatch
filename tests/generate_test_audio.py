#!/usr/bin/env python3
"""
generate_test_audio.py — Generate Test Audio in Multiple Formats

Creates a WAV file via TTS (Piper > espeak > fallback tone) then converts it
to every codec format that Reolink cameras might accept over a go2rtc
backchannel.  The G.711 A-law 8 kHz mono file is the most likely to work.

Prerequisites:
  - ffmpeg installed and on PATH
  - (Optional) piper CLI or espeak for TTS

Usage:
  python generate_test_audio.py
  python generate_test_audio.py --message "Stop right there!" --output-dir ./audio
"""

import argparse
import os
import shutil
import struct
import subprocess
import sys
import math


# ── Default message spoken during tests ──────────────────────────
DEFAULT_MESSAGE = (
    "Attention. You are being recorded on camera. "
    "This is a test of the audio system. "
    "The homeowner has been notified."
)

# ── Conversion targets ───────────────────────────────────────────
# Each tuple: (output filename, ffmpeg codec args, description)
CONVERSIONS = [
    (
        "test_message_alaw.wav",
        ["-acodec", "pcm_alaw", "-ar", "8000", "-ac", "1"],
        "G.711 A-law, 8 kHz, mono (BEST BET for Reolink)",
    ),
    (
        "test_message_mulaw.wav",
        ["-acodec", "pcm_mulaw", "-ar", "8000", "-ac", "1"],
        "G.711 mu-law, 8 kHz, mono",
    ),
    (
        "test_message_pcm16_8k.wav",
        ["-acodec", "pcm_s16le", "-ar", "8000", "-ac", "1"],
        "PCM 16-bit signed LE, 8 kHz, mono",
    ),
    (
        "test_message_pcm16_48k.wav",
        ["-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1"],
        "PCM 16-bit signed LE, 48 kHz, mono",
    ),
    (
        "test_message_alaw.raw",
        ["-f", "alaw", "-acodec", "pcm_alaw", "-ar", "8000", "-ac", "1"],
        "Raw A-law (no header), 8 kHz, mono — for pipe-based approaches",
    ),
]


def parse_args():
    """Parse CLI arguments for message text and output directory.

    Returns:
        argparse.Namespace with message and output_dir fields.
    """
    parser = argparse.ArgumentParser(
        description="Generate test audio files for Voxwatch camera speaker tests."
    )
    parser.add_argument(
        "--message", default=DEFAULT_MESSAGE, help="Text to speak (default: standard test message)"
    )
    parser.add_argument(
        "--output-dir", default=".", help="Directory to save audio files (default: current dir)"
    )
    return parser.parse_args()


def generate_with_piper(message: str, output_path: str) -> bool:
    """Try to generate TTS audio using the Piper CLI.

    Piper produces natural-sounding speech and is the preferred engine.
    Model: en_US-lessac-medium (must be downloaded separately).

    Args:
        message: Text to convert to speech.
        output_path: Where to save the resulting WAV file.

    Returns:
        True if Piper succeeded, False otherwise.
    """
    if not shutil.which("piper"):
        print("[INFO] Piper CLI not found on PATH, skipping.")
        return False

    print("[INFO] Generating TTS with Piper (en_US-lessac-medium)...")
    try:
        result = subprocess.run(
            [
                "piper",
                "--model", "en_US-lessac-medium",
                "--output_file", output_path,
            ],
            input=message.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            print(f"[OK] Piper generated {output_path}")
            return True
        else:
            stderr = result.stderr.decode("utf-8", errors="replace")
            print(f"[WARN] Piper failed (exit {result.returncode}): {stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("[WARN] Piper timed out after 30 s.")
        return False
    except Exception as e:
        print(f"[WARN] Piper error: {e}")
        return False


def generate_with_espeak(message: str, output_path: str) -> bool:
    """Fallback TTS using espeak (robotic but universally available on Linux).

    Args:
        message: Text to convert to speech.
        output_path: Where to save the resulting WAV file.

    Returns:
        True if espeak succeeded, False otherwise.
    """
    # Try both 'espeak-ng' (newer) and 'espeak' (legacy)
    for cmd in ("espeak-ng", "espeak"):
        if not shutil.which(cmd):
            continue

        print(f"[INFO] Generating TTS with {cmd}...")
        try:
            result = subprocess.run(
                [cmd, "-w", output_path, message],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and os.path.exists(output_path):
                print(f"[OK] {cmd} generated {output_path}")
                return True
            else:
                stderr = result.stderr.decode("utf-8", errors="replace")
                print(f"[WARN] {cmd} failed (exit {result.returncode}): {stderr[:200]}")
        except Exception as e:
            print(f"[WARN] {cmd} error: {e}")

    print("[INFO] espeak / espeak-ng not found on PATH, skipping.")
    return False


def generate_tone(output_path: str, freq: int = 800, duration: float = 3.0, sample_rate: int = 16000):
    """Last-resort fallback: generate a pure sine-wave tone as a WAV file.

    This proves the audio pipeline works even without any TTS engine.

    Args:
        output_path: Where to save the WAV file.
        freq: Tone frequency in Hz (default 800).
        duration: Length in seconds (default 3).
        sample_rate: Samples per second (default 16000).
    """
    print(f"[INFO] No TTS engine available — generating {freq} Hz tone ({duration}s)...")
    num_samples = int(sample_rate * duration)
    # 16-bit signed PCM samples
    samples = bytearray()
    for i in range(num_samples):
        value = int(32767 * 0.8 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples += struct.pack("<h", value)

    # Write a minimal WAV header + data
    data_size = len(samples)
    with open(output_path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk — PCM, 1 channel, 16-bit
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))          # chunk size
        f.write(struct.pack("<H", 1))           # PCM format
        f.write(struct.pack("<H", 1))           # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))  # byte rate
        f.write(struct.pack("<H", 2))           # block align
        f.write(struct.pack("<H", 16))          # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(samples)

    print(f"[OK] Tone generated: {output_path}")


def convert_with_ffmpeg(source_wav: str, output_path: str, codec_args: list, description: str) -> bool:
    """Use ffmpeg to transcode the source WAV into a target format.

    Args:
        source_wav: Path to the input WAV file.
        output_path: Path for the converted output file.
        codec_args: List of ffmpeg codec/format arguments.
        description: Human-readable description for logging.

    Returns:
        True if conversion succeeded, False otherwise.
    """
    if not shutil.which("ffmpeg"):
        print("[FAIL] ffmpeg not found on PATH. Install ffmpeg to convert audio formats.")
        return False

    cmd = ["ffmpeg", "-y", "-i", source_wav] + codec_args + [output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"  [OK] {os.path.basename(output_path):35s} {size:>8,} bytes  — {description}")
            return True
        else:
            stderr = result.stderr.decode("utf-8", errors="replace")
            print(f"  [FAIL] {os.path.basename(output_path):33s} — {stderr[-200:]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  [FAIL] {os.path.basename(output_path):33s} — ffmpeg timed out")
        return False
    except Exception as e:
        print(f"  [FAIL] {os.path.basename(output_path):33s} — {e}")
        return False


def main():
    """Entry point — generate TTS, convert to all target formats, print summary."""
    args = parse_args()
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("  VOXWATCH — Test Audio Generator")
    print("=" * 60)

    # ── Step 1: Generate base WAV via TTS (or tone fallback) ─────
    base_wav = os.path.join(output_dir, "test_message_source.wav")

    generated = generate_with_piper(args.message, base_wav)
    if not generated:
        generated = generate_with_espeak(args.message, base_wav)
    if not generated:
        generate_tone(base_wav)

    if not os.path.exists(base_wav):
        print("[FAIL] No audio file was generated. Cannot continue.")
        sys.exit(1)

    source_size = os.path.getsize(base_wav)
    print(f"\n[INFO] Source WAV: {base_wav} ({source_size:,} bytes)")

    # ── Step 2: Convert to all target formats ────────────────────
    print("\n--- Converting to camera-compatible formats ---")
    results = []
    for filename, codec_args, description in CONVERSIONS:
        out_path = os.path.join(output_dir, filename)
        ok = convert_with_ffmpeg(base_wav, out_path, codec_args, description)
        results.append((filename, ok, out_path))

    # ── Step 3: Summary ──────────────────────────────────────────
    print("\n--- Summary ---")
    for filename, ok, path in results:
        status = "[OK]  " if ok else "[FAIL]"
        size_str = f"{os.path.getsize(path):,} bytes" if ok and os.path.exists(path) else "—"
        print(f"  {status} {filename:35s} {size_str}")

    # Tell the user which file to try first
    alaw_path = os.path.join(output_dir, "test_message_alaw.wav")
    if os.path.exists(alaw_path):
        print(f"\n[INFO] Try this file first with test_audio_push.py:")
        print(f"       {alaw_path}")
        print("       Reolink cameras typically expect G.711 A-law 8 kHz mono.")
    print()


if __name__ == "__main__":
    main()
