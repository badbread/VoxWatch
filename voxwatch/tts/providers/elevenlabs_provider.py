"""
elevenlabs_provider.py — ElevenLabs Premium Cloud TTS Provider

Uses the ElevenLabs REST API directly via aiohttp — NO SDK required.
This keeps the Docker image lean (no elevenlabs pip package) while
providing full access to ElevenLabs' text-to-speech capabilities.

The API returns MP3 audio by default.  The audio pipeline's ffmpeg
step handles conversion to camera-compatible codec downstream.

Config keys read from ``config["tts"]``:
    elevenlabs_api_key (str): ElevenLabs API key.  Falls back to the
        ELEVENLABS_API_KEY environment variable if not set in config.
    elevenlabs_voice_id (str): Voice ID to use (default: George).
    elevenlabs_model (str): Model ID (default: eleven_flash_v2_5).
    elevenlabs_stability (float): Voice stability 0-1 (default: 0.5).
    elevenlabs_similarity_boost (float): Similarity boost 0-1 (default: 0.75).
    elevenlabs_timeout (int): HTTP timeout in seconds (default: 30).
"""

import logging
import os

import aiohttp

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.elevenlabs")

# ElevenLabs API endpoint for text-to-speech
_API_BASE = "https://api.elevenlabs.io/v1"

# ElevenLabs "George" voice — authoritative, clear English male voice.
_DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
_DEFAULT_MODEL = "eleven_flash_v2_5"


class ElevenLabsProvider(TTSProvider):
    """TTS provider using the ElevenLabs REST API directly.

    No SDK dependency — uses aiohttp for all HTTP communication.
    Generates studio-quality speech with controllable stability and
    similarity.  Requires an ElevenLabs API key and internet connectivity.

    Attributes:
        _api_key: ElevenLabs API key.
        _voice_id: Target voice identifier.
        _model: ElevenLabs model ID.
        _stability: Voice stability 0-1.
        _similarity_boost: Voice similarity boost 0-1.
        _timeout: HTTP request timeout in seconds.
        _session: Shared aiohttp session (created lazily, closed on shutdown).
    """

    def __init__(self, config: dict) -> None:
        """Resolve API key from config or environment.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If no API key is configured.
        """
        super().__init__(config)

        tts_cfg = config.get("tts", {})

        # Prefer config value, fall back to environment variable.
        api_key: str | None = (
            tts_cfg.get("elevenlabs_api_key")
            or os.environ.get("ELEVENLABS_API_KEY")
        )
        # Skip unresolved ${ENV_VAR} tokens
        if api_key and api_key.startswith("${"):
            api_key = os.environ.get("ELEVENLABS_API_KEY")

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
        self._timeout: int = int(tts_cfg.get("elevenlabs_timeout", 30))
        self._session: aiohttp.ClientSession | None = None

        logger.debug(
            "ElevenLabsProvider ready: voice=%s model=%s",
            self._voice_id, self._model,
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp session.

        Returns:
            Active aiohttp.ClientSession instance.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            )
        return self._session

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult."""
        return "elevenlabs"

    @property
    def is_local(self) -> bool:
        """ElevenLabs requires internet connectivity and an API key."""
        return False

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech via ElevenLabs REST API.

        Makes a direct HTTP POST to the ElevenLabs text-to-speech endpoint.
        Audio is streamed to disk in 64KB chunks to minimize memory usage.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output audio file.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If the API call fails or returns an error.
        """
        session = await self._get_session()
        url = f"{_API_BASE}/text-to-speech/{self._voice_id}"

        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": message,
            "model_id": self._model,
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
            },
        }

        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    raise TTSProviderError(
                        self.name, "Invalid API key"
                    )
                if resp.status == 404:
                    raise TTSProviderError(
                        self.name,
                        f"Voice ID '{self._voice_id}' not found",
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise TTSProviderError(
                        self.name,
                        f"API returned {resp.status}: {body[:200]}",
                    )

                # Stream audio to disk in chunks
                with open(output_path, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(65536):
                        fh.write(chunk)

        except TTSProviderError:
            raise
        except aiohttp.ClientError as exc:
            raise TTSProviderError(
                self.name, f"HTTP request failed: {exc}"
            ) from exc
        except Exception as exc:
            raise TTSProviderError(
                self.name, f"API call failed: {exc}"
            ) from exc

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise TTSProviderError(
                self.name, f"Output file empty or not written: {output_path}"
            )

        duration = self.estimate_duration(message)
        logger.debug("ElevenLabs generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )

    async def warmup(self) -> None:
        """Pre-create the aiohttp session for faster first request."""
        await self._get_session()
        logger.debug("ElevenLabs session pre-created")

    async def shutdown(self) -> None:
        """Close the aiohttp session cleanly."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
