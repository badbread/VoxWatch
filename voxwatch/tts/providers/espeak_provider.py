"""
espeak_provider.py — espeak-ng / espeak Fallback TTS Provider

This provider is the last resort in the fallback chain.  It shells out to
espeak-ng (or espeak if espeak-ng is absent) using asyncio.create_subprocess_exec
so the event loop is not blocked during synthesis.

espeak produces robotic-sounding speech but is:
  - Universally available in the VoxWatch Docker image
  - Zero-latency (no model loading, no network)
  - Effectively impossible to fail if the binary exists

Config keys read from ``config["tts"]``:
    espeak_speed (int): Words per minute passed to -s (default: 130).
    espeak_pitch (int): Pitch 0-99 passed to -p (default: 30).

Usage:
    provider = EspeakProvider(config)
    result = await provider.generate("You are being recorded.", "/tmp/out.wav")
"""

import asyncio
import logging
import os
import shutil

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.espeak")

# Maximum seconds to wait for espeak to finish before treating it as hung.
_SUBPROCESS_TIMEOUT = 30


class EspeakProvider(TTSProvider):
    """TTS provider using espeak-ng (or espeak) as an absolute last resort.

    The ``--`` sentinel is passed before the message text so that a message
    beginning with a hyphen (e.g. AI output like "- Warning") is never
    misinterpreted as a command-line flag.

    Attributes:
        _cmd: The resolved binary name ("espeak-ng" or "espeak").
        _speed: Words-per-minute speaking rate.
        _pitch: Voice pitch (0-99).
        _timeout: Subprocess timeout in seconds.
    """

    def __init__(self, config: dict) -> None:
        """Locate the espeak binary and read config values.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If neither espeak-ng nor espeak is found on PATH.
        """
        super().__init__(config)
        tts_cfg = config.get("tts", {})

        self._speed: int = int(tts_cfg.get("espeak_speed", 130))
        self._pitch: int = int(tts_cfg.get("espeak_pitch", 30))
        self._timeout: int = int(tts_cfg.get("subprocess_timeout", _SUBPROCESS_TIMEOUT))

        # Prefer espeak-ng (newer, more maintained) but accept espeak if
        # that is all that is available.
        if shutil.which("espeak-ng"):
            self._cmd = "espeak-ng"
        elif shutil.which("espeak"):
            self._cmd = "espeak"
            logger.warning(
                "espeak-ng not found — falling back to espeak (quality may differ)"
            )
        else:
            raise TTSProviderError(
                self.name,
                "Neither espeak-ng nor espeak found on PATH. "
                "Install espeak-ng: apt-get install espeak-ng",
            )

        logger.debug(
            "EspeakProvider ready: cmd=%s speed=%d pitch=%d",
            self._cmd, self._speed, self._pitch,
        )

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "espeak"
        """
        return "espeak"

    @property
    def is_local(self) -> bool:
        """espeak runs on the local machine with no network dependency.

        Returns:
            True
        """
        return True

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech with espeak and write a WAV file.

        Passes ``-s`` (speed) and ``-p`` (pitch) from config.  Uses ``--``
        before the message text to prevent flag injection from AI-generated
        content that may begin with a hyphen.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If espeak exits non-zero or times out.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cmd,
                "-w", output_path,
                "-s", str(self._speed),
                "-p", str(self._pitch),
                # "--" ends option parsing — prevents a leading "-" in message
                # from being parsed as a flag (flag injection prevention).
                "--", message,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise TTSProviderError(
                self.name,
                f"Process timed out after {self._timeout}s",
            )
        except Exception as exc:
            raise TTSProviderError(self.name, f"Subprocess error: {exc}") from exc

        if proc.returncode != 0 or not os.path.exists(output_path):
            stderr_text = stderr.decode("utf-8", errors="replace")[:300]
            raise TTSProviderError(
                self.name,
                f"Exit code {proc.returncode}: {stderr_text}",
            )

        duration = self.estimate_duration(message)
        logger.debug("espeak generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )
