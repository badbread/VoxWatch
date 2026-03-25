"""
elevenlabs_provider.py — ElevenLabs Premium Cloud TTS Provider

Uses the ElevenLabs Python SDK to generate high-quality, expressive speech.
Supports both streaming and non-streaming modes.  Streaming is preferred
because it allows writing the audio file as bytes arrive, reducing total
latency for longer messages.

The elevenlabs SDK is optional.  If it is not installed, this provider
raises ``TTSProviderError`` at construction time so the factory skips it
without crashing the service.

Config keys read from ``config["tts"]``:
    elevenlabs_api_key (str): ElevenLabs API key.  Falls back to the
        ELEVENLABS_API_KEY environment variable if not set in config.
    elevenlabs_voice_id (str): Voice ID to use (default: "JBFqnCBsd6RMkjVDRZzb").
        The default is "George" — a clear, authoritative male voice.
    elevenlabs_model (str): Model ID (default: "eleven_flash_v2_5").
        eleven_flash_v2_5 is the lowest-latency production model.
    elevenlabs_stability (float): Voice stability 0-1 (default: 0.5).
    elevenlabs_similarity_boost (float): Similarity boost 0-1 (default: 0.75).
    elevenlabs_use_streaming (bool): Stream audio chunks (default: True).
    elevenlabs_timeout (int): HTTP timeout in seconds (default: 30).

Install:
    pip install elevenlabs

Usage:
    provider = ElevenLabsProvider(config)
    result = await provider.generate("Authorities are being contacted.", "/tmp/out.wav")
"""

import asyncio
import logging
import os
from typing import Optional

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.elevenlabs")

# ElevenLabs "George" voice — authoritative, clear English male voice.
_DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
_DEFAULT_MODEL = "eleven_flash_v2_5"


class ElevenLabsProvider(TTSProvider):
    """TTS provider using the ElevenLabs cloud synthesis API.

    Generates studio-quality speech with controllable stability and
    similarity.  Requires an ElevenLabs API key and internet connectivity.

    Attributes:
        _api_key: ElevenLabs API key.
        _voice_id: Target voice identifier.
        _model: ElevenLabs model ID.
        _stability: Voice stability 0-1.
        _similarity_boost: Voice similarity boost 0-1.
        _use_streaming: Whether to use the streaming API.
        _timeout: HTTP request timeout in seconds.
    """

    def __init__(self, config: dict) -> None:
        """Validate SDK availability and resolve API key.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If the elevenlabs SDK is not installed or
                no API key is configured.
        """
        super().__init__(config)

        try:
            import elevenlabs  # noqa: F401 — import check only
        except ImportError:
            raise TTSProviderError(
                self.name,
                "elevenlabs package not installed. "
                "Install with: pip install elevenlabs",
            )

        tts_cfg = config.get("tts", {})

        # Prefer config value, fall back to environment variable.
        api_key: Optional[str] = (
            tts_cfg.get("elevenlabs_api_key")
            or os.environ.get("ELEVENLABS_API_KEY")
        )
        if not api_key:
            raise TTSProviderError(
                self.name,
                "No API key found. Set tts.elevenlabs_api_key in config.yaml "
                "or the ELEVENLABS_API_KEY environment variable.",
            )

        self._api_key: str = api_key
        self._voice_id: str = tts_cfg.get("elevenlabs_voice_id", _DEFAULT_VOICE_ID)
        self._model: str = tts_cfg.get("elevenlabs_model", _DEFAULT_MODEL)
        self._stability: float = float(tts_cfg.get("elevenlabs_stability", 0.5))
        self._similarity_boost: float = float(tts_cfg.get("elevenlabs_similarity_boost", 0.75))
        self._use_streaming: bool = bool(tts_cfg.get("elevenlabs_use_streaming", True))
        self._timeout: int = int(tts_cfg.get("elevenlabs_timeout", 30))

        logger.debug(
            "ElevenLabsProvider ready: voice=%s model=%s streaming=%s",
            self._voice_id, self._model, self._use_streaming,
        )

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "elevenlabs"
        """
        return "elevenlabs"

    @property
    def is_local(self) -> bool:
        """ElevenLabs requires internet connectivity and an API key.

        Returns:
            False
        """
        return False

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech via ElevenLabs API and write a WAV file.

        Runs the synchronous ElevenLabs SDK call in a thread pool executor
        so the event loop is not blocked during the HTTP request.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV/MP3 file.
                ElevenLabs returns MP3 by default; the audio pipeline's
                ffmpeg step converts it to the camera-compatible codec.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If the API call fails, times out, or the
                response cannot be written to disk.
        """
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, self._call_api, message, output_path),
                timeout=self._timeout + 5,  # executor timeout slightly wider than HTTP timeout
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
        logger.debug("ElevenLabs generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )

    def _call_api(self, message: str, output_path: str) -> None:
        """Make the synchronous ElevenLabs API call (runs in executor thread).

        Uses streaming if enabled so audio bytes are written incrementally,
        reducing peak memory usage for long messages.

        Args:
            message: Text to synthesize.
            output_path: Absolute path where audio bytes are written.

        Raises:
            TTSProviderError: If the API returns an error or IO fails.
        """
        from elevenlabs import VoiceSettings  # type: ignore[import]
        from elevenlabs.client import ElevenLabs  # type: ignore[import]

        client = ElevenLabs(api_key=self._api_key)
        voice_settings = VoiceSettings(
            stability=self._stability,
            similarity_boost=self._similarity_boost,
        )

        try:
            if self._use_streaming:
                audio_stream = client.text_to_speech.convert_as_stream(
                    text=message,
                    voice_id=self._voice_id,
                    model_id=self._model,
                    voice_settings=voice_settings,
                )
                with open(output_path, "wb") as fh:
                    for chunk in audio_stream:
                        if chunk:
                            fh.write(chunk)
            else:
                audio_bytes = client.text_to_speech.convert(
                    text=message,
                    voice_id=self._voice_id,
                    model_id=self._model,
                    voice_settings=voice_settings,
                )
                with open(output_path, "wb") as fh:
                    fh.write(audio_bytes)
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"ElevenLabs SDK error: {exc}",
            ) from exc
