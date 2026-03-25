"""
cartesia_provider.py — Cartesia Cloud TTS Provider (Fastest Cloud)

Uses the Cartesia Python SDK to generate low-latency, high-quality speech.
Cartesia's infrastructure is optimized for real-time use cases and typically
delivers audio faster than any other cloud provider, making it a strong
choice when latency matters and a Cartesia subscription is available.

The cartesia SDK is optional.  If it is not installed, this provider raises
``TTSProviderError`` at construction time so the factory skips it gracefully.

Config keys read from ``config["tts"]``:
    cartesia_api_key (str): Cartesia API key.  Falls back to the
        CARTESIA_API_KEY environment variable if not set in config.
    cartesia_voice_id (str): Voice ID (default: "694f9389-aac1-45b6-b726-9d9369183238").
        The default is "Barbershop Man" — a clear, authoritative male voice.
    cartesia_model (str): Model ID (default: "sonic-2").
    cartesia_speed (str | float): Speaking speed — either a label
        ("slowest", "slow", "normal", "fast", "fastest") or a float
        multiplier.  Default: "normal".
    cartesia_emotion (list[str]): Emotion tags to blend into the voice
        (e.g., ["anger:medium", "positivity:low"]).  Default: [] (neutral).
    cartesia_timeout (int): HTTP timeout in seconds (default: 30).

Install:
    pip install cartesia

Usage:
    provider = CartesiaProvider(config)
    result = await provider.generate("All activity recorded.", "/tmp/out.wav")
"""

import asyncio
import logging
import os
from typing import Any, Optional, Union

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.cartesia")

# Cartesia "Barbershop Man" voice — deep, authoritative, clear English male.
_DEFAULT_VOICE_ID = "694f9389-aac1-45b6-b726-9d9369183238"
_DEFAULT_MODEL = "sonic-2"


class CartesiaProvider(TTSProvider):
    """TTS provider using the Cartesia real-time synthesis API.

    Cartesia is optimized for sub-100 ms time-to-first-byte, making it
    the preferred cloud option when ultra-low latency is required.

    Attributes:
        _api_key: Cartesia API key.
        _voice_id: Target voice UUID.
        _model: Cartesia model identifier.
        _speed: Speaking speed label or float multiplier.
        _emotion: Emotion blend tags.
        _timeout: HTTP request timeout in seconds.
    """

    def __init__(self, config: dict) -> None:
        """Validate SDK availability and resolve API key.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If the cartesia SDK is not installed or
                no API key is configured.
        """
        super().__init__(config)

        try:
            import cartesia  # noqa: F401 — import check only
        except ImportError:
            raise TTSProviderError(
                self.name,
                "cartesia package not installed. "
                "Install with: pip install cartesia",
            )

        tts_cfg = config.get("tts", {})

        api_key: Optional[str] = (
            tts_cfg.get("cartesia_api_key")
            or os.environ.get("CARTESIA_API_KEY")
        )
        if not api_key:
            raise TTSProviderError(
                self.name,
                "No API key found. Set tts.cartesia_api_key in config.yaml "
                "or the CARTESIA_API_KEY environment variable.",
            )

        self._api_key: str = api_key
        self._voice_id: str = tts_cfg.get("cartesia_voice_id", _DEFAULT_VOICE_ID)
        self._model: str = tts_cfg.get("cartesia_model", _DEFAULT_MODEL)
        self._speed: Union[str, float] = tts_cfg.get("cartesia_speed", "normal")
        self._emotion: list[str] = tts_cfg.get("cartesia_emotion", [])
        self._timeout: int = int(tts_cfg.get("cartesia_timeout", 30))

        logger.debug(
            "CartesiaProvider ready: voice=%s model=%s speed=%s",
            self._voice_id, self._model, self._speed,
        )

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "cartesia"
        """
        return "cartesia"

    @property
    def is_local(self) -> bool:
        """Cartesia requires internet connectivity and an API key.

        Returns:
            False
        """
        return False

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech via Cartesia API and write a WAV file.

        Runs the synchronous SDK call in a thread pool executor so the
        event loop is not blocked during the HTTP request.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If the API call fails or times out.
        """
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, self._call_api, message, output_path),
                timeout=self._timeout + 5,
            )
        except asyncio.TimeoutError:
            raise TTSProviderError(
                self.name,
                f"API call timed out after {self._timeout}s",
            )
        except TTSProviderError:
            raise
        except Exception as exc:
            raise TTSProviderError(self.name, f"API call failed: {exc}") from exc

        if not os.path.exists(output_path):
            raise TTSProviderError(
                self.name,
                f"Output file was not written: {output_path}",
            )

        duration = self.estimate_duration(message)
        logger.debug("Cartesia generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )

    def _call_api(self, message: str, output_path: str) -> None:
        """Make the synchronous Cartesia API call (runs in executor thread).

        Requests PCM WAV output from Cartesia so the audio pipeline does not
        need to decode a compressed format before the ffmpeg conversion step.

        Args:
            message: Text to synthesize.
            output_path: Absolute path where the WAV file is written.

        Raises:
            TTSProviderError: If the Cartesia SDK raises an error.
        """
        from cartesia import Cartesia  # type: ignore[import]

        client = Cartesia(api_key=self._api_key)

        # Build voice controls dict only when non-default values are set.
        voice_controls: dict[str, Any] = {}
        if self._speed != "normal" and self._speed is not None:
            voice_controls["speed"] = self._speed
        if self._emotion:
            voice_controls["emotion"] = self._emotion

        try:
            # Request PCM (WAV) so no decode step is needed.
            output = client.tts.bytes(
                model_id=self._model,
                transcript=message,
                voice={"id": self._voice_id, **({"controls": voice_controls} if voice_controls else {})},
                output_format={
                    "container": "wav",
                    "encoding": "pcm_f32le",
                    "sample_rate": 44100,
                },
            )
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Cartesia SDK error: {exc}",
            ) from exc

        try:
            with open(output_path, "wb") as fh:
                fh.write(output)
        except OSError as exc:
            raise TTSProviderError(
                self.name,
                f"Failed to write WAV to {output_path}: {exc}",
            ) from exc
