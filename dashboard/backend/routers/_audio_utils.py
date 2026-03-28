"""
_audio_utils.py — Shared utilities for the audio router sub-modules.

This module centralises helpers that are used by more than one audio sub-module
so the logic lives in exactly one place within the dashboard package.

Contents:
    _PIPER_MODEL_RE          — Regex for validating Piper model names.
    _resolve_cloud_tts_key() — Read a cloud TTS API key from saved config.
    _get_voxwatch_preview_url() — Build the VoxWatch Preview API base URL.
    _sanitize_tts_message()  — Strip Unicode control characters from TTS text.
    _normalize_dispatch_for_tts() — Expand 10-codes and address numbers for TTS.

NOTE: The dashboard runs in a separate Docker container from the VoxWatch
service and therefore cannot import from the ``voxwatch`` package directly.
``_normalize_dispatch_for_tts`` is a copy of ``normalize_dispatch_text`` in
``voxwatch/radio_dispatch.py`` and must be kept in sync if that function
changes.
"""

import re
import unicodedata

from backend.services.config_service import config_service

# ── Shared constants ──────────────────────────────────────────────────────────

#: Regex for validating Piper model names in preview requests.
#: Mirrors the camera-name pattern — model names are interpolated into CLI args.
_PIPER_MODEL_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ── Shared helpers ────────────────────────────────────────────────────────────


async def _resolve_cloud_tts_key(key_name: str) -> str:
    """Resolve a cloud TTS API key from the saved config.

    Checks both nested config (e.g. tts.openai.api_key) and flat config
    (e.g. tts.openai_api_key) for backwards compatibility, and resolves
    ${ENV_VAR} tokens to actual values.

    Args:
        key_name: The config key name, either flat (e.g. "openai_api_key")
            or the provider name will be extracted to check nested config.

    Returns:
        The resolved API key, or empty string if not found.
    """
    import os

    def _resolve(val: str) -> str:
        if not val or not isinstance(val, str) or val.startswith("***"):
            return ""
        env_match = re.match(r"\$\{(\w+)\}", val)
        if env_match:
            return os.environ.get(env_match.group(1), "")
        return val

    try:
        raw_cfg = await config_service.get_raw_config()
        tts = raw_cfg.get("tts", {})

        # Try nested config first: tts.<provider>.api_key
        # Extract provider name from key_name (e.g. "openai_api_key" -> "openai")
        provider = key_name.replace("_api_key", "")
        nested = tts.get(provider, {})
        if isinstance(nested, dict):
            resolved = _resolve(nested.get("api_key", ""))
            if resolved:
                return resolved

        # Fall back to flat config: tts.<key_name>
        return _resolve(tts.get(key_name, ""))
    except Exception:
        return ""


async def _get_voxwatch_preview_url() -> str:
    """Build the VoxWatch Preview API URL.

    The Preview API binds to 127.0.0.1 for security (not externally
    accessible).  Both containers use host networking, so localhost
    is the correct address for inter-container communication.

    Returns:
        Full URL string, e.g. ``"http://127.0.0.1:8892/api/preview"``.
    """
    try:
        cfg = await config_service.get_config()
        port: int = int(cfg.get("preview_api_port", 8892))
    except Exception:
        port = 8892
    return f"http://127.0.0.1:{port}/api/preview"


def _sanitize_tts_message(message: str) -> str:
    """Strip Unicode control characters from TTS text before passing to subprocess.

    Mirrors ``_sanitize_tts_input`` in ``voxwatch/audio_pipeline.py``.
    Removes code points whose Unicode category starts with "C" (control,
    format, surrogate, private-use, unassigned) while preserving all
    printable letters, digits, punctuation, symbols, and whitespace.

    Args:
        message: Raw text from the preview request body.

    Returns:
        Cleaned string safe for TTS subprocess consumption.
    """
    return "".join(
        ch for ch in message
        if not unicodedata.category(ch).startswith("C")
    )


def _normalize_dispatch_for_tts(text: str) -> str:
    """Normalize dispatch text for natural TTS pronunciation.

    Converts 10-codes to spoken form and expands address numbers
    digit-by-digit, matching how real dispatchers speak.

    NOTE: This is a copy of ``normalize_dispatch_text`` in
    ``voxwatch/radio_dispatch.py``.  The dashboard container cannot import
    the voxwatch package directly, so the function is duplicated here.
    Keep both in sync if the normalization logic changes.

    Args:
        text: Raw dispatch text.

    Returns:
        Normalized text ready for TTS.
    """
    # 10-code replacements
    ten_codes = {
        "10-4": "ten four", "10-15": "ten fifteen", "10-20": "ten twenty",
        "10-29": "ten twenty-nine", "10-31": "ten thirty-one",
        "10-70": "ten seventy", "10-97": "ten ninety-seven",
    }
    result = text
    for code, spoken in ten_codes.items():
        result = result.replace(code, spoken)
    result = result.replace("Code 3", "code three")
    result = result.replace("code 3", "code three")

    # Expand address numbers (3+ digits before a capitalized word)
    digit_words = {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    }

    def expand_digits(match: re.Match) -> str:
        words = " ".join(digit_words[d] for d in match.group(1))
        return words + match.group(2)

    result = re.sub(r'\b(\d{3,})\b(\s+[A-Z])', expand_digits, result)
    return result
