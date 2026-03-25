#!/usr/bin/env python3
"""
test_tts_providers.py -- VoxWatch TTS Provider Comparison Tool

Exercises every configured TTS provider (or a single named one), measures
generation latency, validates the output WAV, and prints a formatted
comparison table.

When ``voxwatch.tts.factory`` is importable (i.e. the provider layer has been
implemented) each provider is exercised through the factory's standard
``generate_with_fallback`` path -- the same code path the live service uses.

When the factory is not yet available (e.g. during early development) the
script falls back to a built-in probe for each provider that detects the
required binary, SDK, or API key and invokes the provider directly via
subprocess or SDK calls.  This makes the script useful at every stage of the
project lifecycle.

Providers tested (by name):
    piper       -- Piper neural TTS (local, requires piper CLI on PATH)
    espeak      -- espeak / espeak-ng (local, requires binary on PATH)
    pyttsx3     -- pyttsx3 / Windows SAPI (local, requires pyttsx3 package)
    elevenlabs  -- ElevenLabs cloud TTS (requires ELEVENLABS_API_KEY env var)
    openai      -- OpenAI TTS (requires OPENAI_API_KEY env var)
    google      -- Google Cloud Text-to-Speech (requires GOOGLE_APPLICATION_CREDENTIALS)
    azure       -- Azure Cognitive Services TTS (requires AZURE_TTS_KEY + AZURE_TTS_REGION)

Prerequisites:
    pip install pyyaml

    For cloud providers, set the appropriate environment variable before running.

Usage:
    python test_tts_providers.py --provider all
    python test_tts_providers.py --provider piper
    python test_tts_providers.py --provider piper espeak
    python test_tts_providers.py --provider all --message "Leave now!"
    python test_tts_providers.py --provider all --config /config/config.yaml
    python test_tts_providers.py --provider all --output-dir /tmp/tts_test
"""

import argparse
import asyncio
import os
import shutil
import struct
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MESSAGE = (
    "Attention. Individual in a dark hoodie detected near the garage. "
    "You have been recorded."
)

DEFAULT_OUTPUT_DIR = "./test_tts_output"

# All provider names the script knows how to test.  Order determines the
# table display order.
ALL_PROVIDER_NAMES = [
    "piper",
    "espeak",
    "pyttsx3",
    "elevenlabs",
    "openai",
    "google",
    "azure",
]

# TTS subprocess timeout in seconds
TTS_TIMEOUT = 30

# Minimum WAV file size that we consider non-empty (44 bytes is header only)
MIN_WAV_BYTES = 100

# Status constants used in the results table
STATUS_OK = "OK"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProviderResult:
    """Holds the outcome of testing one TTS provider.

    Attributes:
        name: Short provider identifier (e.g. "piper").
        status: One of STATUS_OK, STATUS_FAIL, or STATUS_SKIP.
        latency_seconds: Time spent generating audio, or None if not measured.
        file_size_bytes: Size of the output WAV, or None if not produced.
        output_path: Absolute path to the saved WAV file, or None.
        note: Human-readable reason for SKIP or FAIL.
        warnings: Optional extra lines printed below the table row.
    """

    name: str
    status: str = STATUS_SKIP
    latency_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    output_path: Optional[str] = None
    note: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for provider selection, message, and paths.

    Returns:
        argparse.Namespace with all fields populated.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Test VoxWatch TTS providers: measure latency, validate output, "
            "and print a comparison table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python test_tts_providers.py --provider all\n"
            "  python test_tts_providers.py --provider piper espeak\n"
            '  python test_tts_providers.py --provider piper --message "Leave now!"\n'
        ),
    )
    parser.add_argument(
        "--provider",
        nargs="+",
        default=["all"],
        metavar="PROVIDER",
        help=(
            'Provider name(s) to test, or "all" to test every known provider. '
            f"Known providers: {', '.join(ALL_PROVIDER_NAMES)}. "
            "(default: all)"
        ),
    )
    parser.add_argument(
        "--message",
        default=DEFAULT_MESSAGE,
        help=(
            "Text to synthesize for each provider. "
            f'(default: "{DEFAULT_MESSAGE[:60]}...")'
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Directory where audio files are saved. (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "Path to VoxWatch config.yaml.  When provided, per-provider "
            "settings (e.g. piper_model) are read from the config. "
            "Falls back to built-in defaults when omitted."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_voxwatch_config(config_path: Optional[str]) -> dict:
    """Load the VoxWatch configuration file if a path is provided.

    Attempts to import ``voxwatch.config.load_config`` for full env-var
    substitution and validation.  If the package is not installed, falls back
    to a plain yaml.safe_load so the script works outside a venv as well.

    Args:
        config_path: Path to config.yaml, or None to use built-in defaults.

    Returns:
        Config dict (may be empty if no path is provided or load fails).
    """
    if not config_path:
        return {}

    if not os.path.exists(config_path):
        print(f"[WARN] Config file not found: {config_path} -- using built-in defaults")
        return {}

    # Prefer the official loader so env vars are substituted correctly
    try:
        from voxwatch.config import load_config  # type: ignore[import]
        print(f"[INFO] Loading config via voxwatch.config: {config_path}")
        return load_config(config_path)
    except ImportError:
        pass

    # Fallback: plain YAML (no env-var substitution, no validation)
    try:
        import yaml  # type: ignore[import]
        with open(config_path) as fh:
            raw = yaml.safe_load(fh) or {}
        print(f"[INFO] Loaded config (plain YAML, no env substitution): {config_path}")
        return raw
    except ImportError:
        print("[WARN] pyyaml not installed -- cannot load config.yaml (pip install pyyaml)")
    except Exception as exc:
        print(f"[WARN] Failed to load config: {exc}")

    return {}


# ---------------------------------------------------------------------------
# Factory-based generation path
# ---------------------------------------------------------------------------


def try_factory_generate(
    provider_name: str,
    message: str,
    output_path: str,
    config: dict,
) -> Optional[float]:
    """Attempt to generate audio via the voxwatch TTS factory.

    Uses ``voxwatch.tts.factory.get_provider`` to instantiate the named
    provider (with warmup) and then calls ``provider.generate()`` via asyncio.
    This is the same code path the live service uses.

    Args:
        provider_name: Short provider name (e.g. "piper").
        message: Text to synthesize.
        output_path: Where to write the output WAV.
        config: VoxWatch config dict (may be empty).

    Returns:
        Generation latency in seconds if successful, or None if the factory
        is not available or the provider could not be instantiated.
    """
    try:
        from voxwatch.tts.factory import get_provider  # type: ignore[import]
        from voxwatch.tts.base import TTSProviderError  # type: ignore[import]
    except ImportError:
        # Factory not yet implemented -- caller will use standalone probes
        return None

    # Build a minimal config if none was provided
    effective_config = dict(config)
    effective_config.setdefault("tts", {})
    effective_config["tts"]["provider"] = provider_name

    try:
        provider = get_provider(effective_config)
    except TTSProviderError as exc:
        # Provider init failed (missing binary, API key, etc.) -- propagate
        raise
    except Exception as exc:
        print(f"[INFO] Factory could not create '{provider_name}': {exc}")
        return None

    async def _run() -> float:
        """Run provider warmup and generation, returning latency in seconds."""
        await provider.warmup()
        t0 = time.monotonic()
        await provider.generate(message, output_path)
        return time.monotonic() - t0

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# WAV validation
# ---------------------------------------------------------------------------


def validate_wav(file_path: str) -> tuple[bool, str]:
    """Check that a file is a valid WAV by inspecting its header bytes.

    Reads the first 44 bytes and verifies the RIFF/WAVE magic numbers.
    Does not validate the audio data itself -- just confirms the file is a
    well-formed WAV container.

    Args:
        file_path: Path to the file to inspect.

    Returns:
        A (is_valid, reason) tuple.  ``reason`` is empty when valid, or a
        human-readable error string when invalid.
    """
    if not os.path.exists(file_path):
        return False, "file does not exist"

    size = os.path.getsize(file_path)
    if size < MIN_WAV_BYTES:
        return False, f"file too small ({size} bytes -- probably empty)"

    try:
        with open(file_path, "rb") as fh:
            header = fh.read(12)
    except OSError as exc:
        return False, f"cannot read file: {exc}"

    if len(header) < 12:
        return False, "file shorter than minimum WAV header (12 bytes)"

    # WAV header layout (bytes 0-3): "RIFF"
    # bytes 8-11: "WAVE"
    riff_magic = header[0:4]
    wave_magic = header[8:12]

    if riff_magic != b"RIFF":
        return False, f"missing RIFF header (got {riff_magic!r})"
    if wave_magic != b"WAVE":
        return False, f"missing WAVE marker (got {wave_magic!r})"

    return True, ""


# ---------------------------------------------------------------------------
# Standalone provider probes
# ---------------------------------------------------------------------------
# Each probe_ function tests exactly one provider without the factory.
# They return a ProviderResult with status/latency/path filled in.
# These functions are used when voxwatch.tts.factory is not importable.


def probe_piper(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the Piper neural TTS binary directly.

    Requires the ``piper`` executable on PATH and a voice model file.
    The model is resolved from config (``tts.piper_model``) or the
    ``PIPER_MODEL_PATH`` environment variable, falling back to the model
    name as a bare string (which Piper accepts if the model is in its
    search path).

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="piper")

    # Check binary presence
    if not shutil.which("piper"):
        result.status = STATUS_SKIP
        result.note = "piper not on PATH (install piper-tts or add to PATH)"
        return result

    # Resolve model path
    model = config.get("tts", {}).get("piper_model", "en_US-lessac-medium")
    model_path = model

    if not os.path.exists(model_path):
        env_path = os.environ.get("PIPER_MODEL_PATH", "")
        if env_path and os.path.exists(env_path):
            model_path = env_path
        else:
            candidate = f"/usr/share/piper-voices/{model}.onnx"
            if os.path.exists(candidate):
                model_path = candidate
            # else: leave as bare model name and let piper resolve it

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["piper", "--model", model_path, "--output_file", output_path],
            input=message.encode("utf-8"),
            capture_output=True,
            timeout=TTS_TIMEOUT,
        )
        latency = time.monotonic() - t0

        if proc.returncode == 0 and os.path.exists(output_path):
            result.status = STATUS_OK
            result.latency_seconds = latency
            result.output_path = output_path
            result.file_size_bytes = os.path.getsize(output_path)
        else:
            result.status = STATUS_FAIL
            stderr_tail = proc.stderr.decode("utf-8", errors="replace").strip()[-200:]
            result.note = f"piper exited {proc.returncode}: {stderr_tail}"

    except subprocess.TimeoutExpired:
        result.status = STATUS_FAIL
        result.note = f"piper timed out after {TTS_TIMEOUT}s"
    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)

    return result


def probe_espeak(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the espeak / espeak-ng binary directly.

    Tries espeak-ng first (preferred), then falls back to espeak.  Both
    accept the same ``-w <output> -- <message>`` invocation.

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="espeak")

    cmd = None
    for candidate in ("espeak-ng", "espeak"):
        if shutil.which(candidate):
            cmd = candidate
            break

    if cmd is None:
        result.status = STATUS_SKIP
        result.note = "espeak / espeak-ng not on PATH"
        return result

    t0 = time.monotonic()
    try:
        # "--" ends option parsing so a leading "-" in message is not a flag
        proc = subprocess.run(
            [cmd, "-w", output_path, "--", message],
            capture_output=True,
            timeout=TTS_TIMEOUT,
        )
        latency = time.monotonic() - t0

        if proc.returncode == 0 and os.path.exists(output_path):
            result.status = STATUS_OK
            result.latency_seconds = latency
            result.output_path = output_path
            result.file_size_bytes = os.path.getsize(output_path)
            result.note = cmd  # show which binary was used
        else:
            result.status = STATUS_FAIL
            stderr_tail = proc.stderr.decode("utf-8", errors="replace").strip()[-200:]
            result.note = f"{cmd} exited {proc.returncode}: {stderr_tail}"

    except subprocess.TimeoutExpired:
        result.status = STATUS_FAIL
        result.note = f"{cmd} timed out after {TTS_TIMEOUT}s"
    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)

    return result


def probe_pyttsx3(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the pyttsx3 Python TTS library (Windows SAPI / macOS NSSpeech / espeak).

    pyttsx3 wraps the platform's native TTS engine, so it requires no extra
    binaries but does require the pyttsx3 package to be installed.

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="pyttsx3")

    try:
        import pyttsx3  # type: ignore[import]  # noqa: F401
    except ImportError:
        result.status = STATUS_SKIP
        result.note = "pyttsx3 not installed (pip install pyttsx3)"
        return result

    t0 = time.monotonic()
    try:
        engine = pyttsx3.init()
        engine.save_to_file(message, output_path)
        engine.runAndWait()
        latency = time.monotonic() - t0

        if os.path.exists(output_path) and os.path.getsize(output_path) > MIN_WAV_BYTES:
            result.status = STATUS_OK
            result.latency_seconds = latency
            result.output_path = output_path
            result.file_size_bytes = os.path.getsize(output_path)
        else:
            result.status = STATUS_FAIL
            result.note = "pyttsx3 produced no output (check platform TTS engine)"
    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)

    return result


def probe_elevenlabs(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the ElevenLabs cloud TTS API.

    Requires the ``elevenlabs`` SDK and a valid API key in the
    ``ELEVENLABS_API_KEY`` environment variable.  The voice and model are
    read from config (``tts.elevenlabs_voice``, ``tts.elevenlabs_model``)
    or left at ElevenLabs defaults.

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="elevenlabs")

    try:
        import elevenlabs  # type: ignore[import]  # noqa: F401
    except ImportError:
        result.status = STATUS_SKIP
        result.note = "elevenlabs SDK not installed (pip install elevenlabs)"
        return result

    api_key = os.environ.get("ELEVENLABS_API_KEY") or config.get("tts", {}).get(
        "elevenlabs_api_key", ""
    )
    if not api_key or api_key.startswith("${"):
        result.status = STATUS_SKIP
        result.note = "ELEVENLABS_API_KEY not set"
        return result

    voice = config.get("tts", {}).get("elevenlabs_voice", "Rachel")
    model = config.get("tts", {}).get("elevenlabs_model", "eleven_multilingual_v2")

    t0 = time.monotonic()
    try:
        from elevenlabs.client import ElevenLabs  # type: ignore[import]

        client = ElevenLabs(api_key=api_key)
        audio_bytes = client.text_to_speech.convert(
            text=message,
            voice_id=voice,
            model_id=model,
            output_format="pcm_44100",
        )
        latency = time.monotonic() - t0

        # elevenlabs returns raw PCM; wrap in WAV so downstream tools work
        _write_pcm_as_wav(audio_bytes, output_path, sample_rate=44100)

        result.status = STATUS_OK
        result.latency_seconds = latency
        result.output_path = output_path
        result.file_size_bytes = os.path.getsize(output_path)

    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)[:120]

    return result


def probe_openai(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the OpenAI TTS API (tts-1 / tts-1-hd models).

    Requires the ``openai`` SDK and a valid API key in the ``OPENAI_API_KEY``
    environment variable.  Voice and model are read from config
    (``tts.openai_voice``, ``tts.openai_model``) with sensible defaults.

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="openai")

    try:
        import openai  # type: ignore[import]  # noqa: F401
    except ImportError:
        result.status = STATUS_SKIP
        result.note = "openai SDK not installed (pip install openai)"
        return result

    api_key = os.environ.get("OPENAI_API_KEY") or config.get("tts", {}).get(
        "openai_api_key", ""
    )
    if not api_key or api_key.startswith("${"):
        result.status = STATUS_SKIP
        result.note = "OPENAI_API_KEY not set"
        return result

    voice = config.get("tts", {}).get("openai_voice", "onyx")
    model = config.get("tts", {}).get("openai_model", "tts-1")

    t0 = time.monotonic()
    try:
        from openai import OpenAI  # type: ignore[import]

        client = OpenAI(api_key=api_key)
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=message,
            response_format="wav",
        )
        latency = time.monotonic() - t0

        # OpenAI streams the audio -- write directly to file
        with open(output_path, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)

        result.status = STATUS_OK
        result.latency_seconds = latency
        result.output_path = output_path
        result.file_size_bytes = os.path.getsize(output_path)

    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)[:120]

    return result


def probe_google(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the Google Cloud Text-to-Speech API.

    Requires the ``google-cloud-texttospeech`` SDK and credentials set via
    ``GOOGLE_APPLICATION_CREDENTIALS`` (path to a service account JSON file)
    or Application Default Credentials (gcloud auth application-default login).

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="google")

    try:
        from google.cloud import texttospeech  # type: ignore[import]
    except ImportError:
        result.status = STATUS_SKIP
        result.note = "google-cloud-texttospeech not installed (pip install google-cloud-texttospeech)"
        return result

    # Credentials check: environment variable or ADC
    creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds_file and not os.path.exists(creds_file):
        result.status = STATUS_SKIP
        result.note = f"GOOGLE_APPLICATION_CREDENTIALS path not found: {creds_file}"
        return result

    language_code = config.get("tts", {}).get("google_language", "en-US")
    voice_name = config.get("tts", {}).get("google_voice", "en-US-Neural2-D")

    t0 = time.monotonic()
    try:
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=message)
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=22050,
        )
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        latency = time.monotonic() - t0

        with open(output_path, "wb") as fh:
            fh.write(response.audio_content)

        result.status = STATUS_OK
        result.latency_seconds = latency
        result.output_path = output_path
        result.file_size_bytes = os.path.getsize(output_path)

    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)[:120]

    return result


def probe_azure(message: str, output_path: str, config: dict) -> ProviderResult:
    """Test the Azure Cognitive Services Text-to-Speech API.

    Requires the ``azure-cognitiveservices-speech`` SDK and two environment
    variables: ``AZURE_TTS_KEY`` (subscription key) and ``AZURE_TTS_REGION``
    (e.g. "eastus").

    Args:
        message: Text to synthesize.
        output_path: Where to write the WAV output.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult populated with status, latency, and file metadata.
    """
    result = ProviderResult(name="azure")

    try:
        import azure.cognitiveservices.speech as speechsdk  # type: ignore[import]
    except ImportError:
        result.status = STATUS_SKIP
        result.note = "azure-cognitiveservices-speech not installed (pip install azure-cognitiveservices-speech)"
        return result

    api_key = os.environ.get("AZURE_TTS_KEY") or config.get("tts", {}).get("azure_key", "")
    region = os.environ.get("AZURE_TTS_REGION") or config.get("tts", {}).get(
        "azure_region", ""
    )

    if not api_key or api_key.startswith("${"):
        result.status = STATUS_SKIP
        result.note = "AZURE_TTS_KEY not set"
        return result
    if not region or region.startswith("${"):
        result.status = STATUS_SKIP
        result.note = "AZURE_TTS_REGION not set"
        return result

    voice_name = config.get("tts", {}).get("azure_voice", "en-US-GuyNeural")

    t0 = time.monotonic()
    try:
        speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
        speech_config.speech_synthesis_voice_name = voice_name

        # Write to a temp file then move, since Azure SDK needs a concrete path
        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        azure_result = synthesizer.speak_text_async(message).get()
        latency = time.monotonic() - t0

        if azure_result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            result.status = STATUS_OK
            result.latency_seconds = latency
            result.output_path = output_path
            result.file_size_bytes = os.path.getsize(output_path)
        else:
            cancellation = speechsdk.SpeechSynthesisCancellationDetails(azure_result)
            result.status = STATUS_FAIL
            result.note = f"{cancellation.reason}: {cancellation.error_details}"

    except Exception as exc:
        result.status = STATUS_FAIL
        result.note = str(exc)[:120]

    return result


# ---------------------------------------------------------------------------
# Helper: raw PCM -> WAV wrapper
# ---------------------------------------------------------------------------


def _write_pcm_as_wav(
    pcm_bytes: bytes,
    output_path: str,
    sample_rate: int = 44100,
    num_channels: int = 1,
    bits_per_sample: int = 16,
) -> None:
    """Wrap raw PCM bytes in a RIFF/WAV container and write to disk.

    ElevenLabs and some other APIs return raw PCM without a WAV header.
    This function prepends the standard 44-byte header so downstream tools
    (ffprobe, validate_wav) can process the file normally.

    Args:
        pcm_bytes: Raw PCM audio data (no header).
        output_path: Where to write the WAV file.
        sample_rate: Sample rate in Hz (e.g. 44100, 22050, 8000).
        num_channels: Number of audio channels (1=mono, 2=stereo).
        bits_per_sample: Bit depth (16 for standard PCM).
    """
    data_size = len(pcm_bytes)
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8

    with open(output_path, "wb") as fh:
        # RIFF chunk descriptor
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + data_size))  # ChunkSize
        fh.write(b"WAVE")
        # fmt sub-chunk
        fh.write(b"fmt ")
        fh.write(struct.pack("<I", 16))             # SubChunk1Size (PCM)
        fh.write(struct.pack("<H", 1))              # AudioFormat (PCM = 1)
        fh.write(struct.pack("<H", num_channels))
        fh.write(struct.pack("<I", sample_rate))
        fh.write(struct.pack("<I", byte_rate))
        fh.write(struct.pack("<H", block_align))
        fh.write(struct.pack("<H", bits_per_sample))
        # data sub-chunk
        fh.write(b"data")
        fh.write(struct.pack("<I", data_size))
        fh.write(pcm_bytes)


# ---------------------------------------------------------------------------
# Provider dispatch table
# ---------------------------------------------------------------------------

# Maps provider name -> standalone probe function.
# Each probe takes (message, output_path, config) and returns ProviderResult.
_PROBE_FUNCTIONS = {
    "piper": probe_piper,
    "espeak": probe_espeak,
    "pyttsx3": probe_pyttsx3,
    "elevenlabs": probe_elevenlabs,
    "openai": probe_openai,
    "google": probe_google,
    "azure": probe_azure,
}


# ---------------------------------------------------------------------------
# Core test runner
# ---------------------------------------------------------------------------


def test_provider(
    provider_name: str,
    message: str,
    output_dir: str,
    config: dict,
) -> ProviderResult:
    """Run the full test sequence for a single TTS provider.

    Execution order:
      1. Attempt generation via voxwatch.tts.factory (if importable).
      2. Fall back to the built-in standalone probe if the factory is absent.
      3. Validate the output WAV header.
      4. Populate and return a ProviderResult.

    Args:
        provider_name: Short provider name (e.g. "piper").
        message: Text to synthesize.
        output_dir: Directory where the WAV file will be saved.
        config: VoxWatch config dict (may be empty).

    Returns:
        ProviderResult with all fields filled in.
    """
    if provider_name not in _PROBE_FUNCTIONS:
        return ProviderResult(
            name=provider_name,
            status=STATUS_SKIP,
            note=f"unknown provider '{provider_name}' -- known: {', '.join(ALL_PROVIDER_NAMES)}",
        )

    output_path = os.path.join(
        os.path.abspath(output_dir), f"tts_{provider_name}.wav"
    )

    # --- Attempt factory path first ---
    print(f"[INFO] Testing provider: {provider_name}")

    factory_result: Optional[ProviderResult] = None
    try:
        from voxwatch.tts.factory import get_provider  # type: ignore[import]
        from voxwatch.tts.base import TTSProviderError  # type: ignore[import]

        print(f"[INFO]   Using voxwatch.tts.factory path")
        latency = try_factory_generate(provider_name, message, output_path, config)

        if latency is not None:
            # Factory succeeded
            is_valid, reason = validate_wav(output_path)
            if is_valid:
                factory_result = ProviderResult(
                    name=provider_name,
                    status=STATUS_OK,
                    latency_seconds=latency,
                    output_path=output_path,
                    file_size_bytes=os.path.getsize(output_path),
                )
            else:
                factory_result = ProviderResult(
                    name=provider_name,
                    status=STATUS_FAIL,
                    latency_seconds=latency,
                    note=f"invalid WAV output: {reason}",
                )
            return factory_result

    except ImportError:
        # Factory not available -- fall through to standalone probe
        print(f"[INFO]   voxwatch.tts.factory not available, using standalone probe")
    except Exception as exc:
        # Factory raised TTSProviderError or similar -- provider can't run
        exc_str = str(exc)
        if "no api key" in exc_str.lower() or "not set" in exc_str.lower():
            return ProviderResult(
                name=provider_name,
                status=STATUS_SKIP,
                note=exc_str[:100],
            )
        return ProviderResult(
            name=provider_name,
            status=STATUS_FAIL,
            note=exc_str[:120],
        )

    # --- Standalone probe path ---
    probe_fn = _PROBE_FUNCTIONS[provider_name]
    result = probe_fn(message, output_path, config)

    # Validate WAV if generation reported OK
    if result.status == STATUS_OK:
        is_valid, reason = validate_wav(output_path)
        if not is_valid:
            result.status = STATUS_FAIL
            result.note = f"invalid WAV output: {reason}"

    return result


# ---------------------------------------------------------------------------
# Table formatting
# ---------------------------------------------------------------------------


def format_size(bytes_: Optional[int]) -> str:
    """Format a file size in bytes as a human-readable string.

    Args:
        bytes_: File size in bytes, or None if unavailable.

    Returns:
        Formatted string like "48 KB" or "--" if None.
    """
    if bytes_ is None:
        return "--"
    if bytes_ < 1024:
        return f"{bytes_}B"
    return f"{bytes_ // 1024}KB"


def format_latency(seconds: Optional[float]) -> str:
    """Format a latency value as a concise string.

    Args:
        seconds: Latency in seconds, or None if not measured.

    Returns:
        Formatted string like "0.4s" or "--" if None.
    """
    if seconds is None:
        return "--"
    return f"{seconds:.2f}s"


def print_results_table(
    results: list[ProviderResult],
    message: str,
    output_dir: str,
) -> None:
    """Print the final comparison table with a header and one row per provider.

    Status symbols:
        OK   -- generation succeeded and WAV is valid
        FAIL -- generation failed or WAV is invalid
        SKIP -- provider not available (missing binary, SDK, or API key)

    Args:
        results: List of ProviderResult objects, one per provider tested.
        message: The test message that was synthesized (shown in header).
        output_dir: Directory where audio files were saved (shown in footer).
    """
    # Column widths
    col_provider = 16
    col_latency = 10
    col_size = 10
    col_status = 8

    total_width = col_provider + col_latency + col_size + col_status + 12

    print()
    print("=" * total_width)
    print("  VoxWatch TTS Provider Test")
    print("=" * total_width)

    # Truncate message for display
    msg_display = message if len(message) <= 72 else message[:69] + "..."
    print(f'\n  Message: "{msg_display}"\n')

    # Header row
    header = (
        f"  {'Provider':<{col_provider}}"
        f"{'Latency':<{col_latency}}"
        f"{'Size':<{col_size}}"
        f"{'Status':<{col_status}}"
        f"  Note"
    )
    separator = "  " + "-" * (total_width - 4)
    print(header)
    print(separator)

    ok_count = 0
    fail_count = 0
    skip_count = 0

    for result in results:
        # Status label with bracket prefix matching existing test file style
        if result.status == STATUS_OK:
            status_label = "[OK]"
            ok_count += 1
        elif result.status == STATUS_FAIL:
            status_label = "[FAIL]"
            fail_count += 1
        else:
            status_label = "[SKIP]"
            skip_count += 1

        note_display = f"  ({result.note})" if result.note else ""

        row = (
            f"  {result.name:<{col_provider}}"
            f"{format_latency(result.latency_seconds):<{col_latency}}"
            f"{format_size(result.file_size_bytes):<{col_size}}"
            f"{status_label:<{col_status}}"
            f"{note_display}"
        )
        print(row)

    print(separator)
    print()

    # Summary line
    print(
        f"  Results: {ok_count} OK / {fail_count} FAIL / {skip_count} SKIP"
        f"  ({len(results)} tested)"
    )

    # Show where files were saved (only if any succeeded)
    saved = [r for r in results if r.output_path and r.status == STATUS_OK]
    if saved:
        abs_dir = os.path.abspath(output_dir)
        print(f"\n  Audio files saved to: {abs_dir}/")
        for res in saved:
            fname = os.path.basename(res.output_path)
            print(
                f"    {fname:<40}  "
                f"{format_latency(res.latency_seconds):<8}  "
                f"{format_size(res.file_size_bytes)}"
            )

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments, run provider tests, and print the comparison table.

    Resolves the list of providers to test (expanding "all" to every known
    provider name), creates the output directory, tests each provider in
    sequence, and prints the results table.
    """
    args = parse_args()

    # Resolve provider list
    provider_names_raw = [p.lower() for p in args.provider]
    if "all" in provider_names_raw:
        provider_names = list(ALL_PROVIDER_NAMES)
    else:
        # Deduplicate while preserving order
        seen: set[str] = set()
        provider_names = []
        for name in provider_names_raw:
            if name not in seen:
                provider_names.append(name)
                seen.add(name)

    # Create output directory
    output_dir = args.output_dir
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        print(f"[FAIL] Cannot create output directory '{output_dir}': {exc}")
        sys.exit(1)

    # Load config
    config = load_voxwatch_config(args.config)

    print()
    print(f"[INFO] Testing {len(provider_names)} provider(s): {', '.join(provider_names)}")
    print(f"[INFO] Output directory: {os.path.abspath(output_dir)}")
    print()

    # Run each provider
    results: list[ProviderResult] = []
    for name in provider_names:
        try:
            result = test_provider(name, args.message, output_dir, config)
        except Exception as exc:
            # Defensive catch -- no individual provider failure should abort the run
            result = ProviderResult(
                name=name,
                status=STATUS_FAIL,
                note=f"unexpected error: {exc}",
            )
        results.append(result)

        # Print per-provider status line immediately so the user can see progress
        if result.status == STATUS_OK:
            print(
                f"[OK] {name}: {format_latency(result.latency_seconds)}"
                f"  {format_size(result.file_size_bytes)}"
            )
        elif result.status == STATUS_FAIL:
            print(f"[FAIL] {name}: {result.note}")
        else:
            print(f"[SKIP] {name}: {result.note}")

    # Print summary table
    print_results_table(results, args.message, output_dir)

    # Exit with a non-zero code if any provider that was expected to work failed.
    # SKIP is not a failure -- only FAIL counts.
    if any(r.status == STATUS_FAIL for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
