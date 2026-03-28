"""
openai_provider.py — OpenAI TTS Cloud Provider (Simple Cloud)

Uses the aiohttp library to call the OpenAI Audio Speech API directly,
avoiding a dependency on the openai Python SDK.  The raw HTTP approach
keeps the provider lightweight and avoids SDK version conflicts.

The OpenAI TTS API produces MP3 output.  The file is written to
``output_path`` as-is; the audio pipeline's ffmpeg step handles any
format conversion needed before pushing to the camera.

Config keys read from ``config["tts"]``:
    openai_api_key (str): OpenAI API key.  Falls back to the
        OPENAI_API_KEY environment variable if not set in config.
    openai_model (str): TTS model ID (default: "tts-1").
        Use "tts-1-hd" for higher quality at the cost of extra latency.
    openai_voice (str): Voice name (default: "onyx").
        Options: alloy, echo, fable, onyx, nova, shimmer.
        "onyx" is a deep, authoritative male voice.
    openai_speed (float): Speaking speed 0.25-4.0 (default: 1.0).
    openai_timeout (int): HTTP request timeout in seconds (default: 30).
    openai_base_url (str): API base URL override (default: "https://api.openai.com/v1").
        Useful for OpenAI-compatible local endpoints (e.g., LocalAI).

Usage:
    provider = OpenAIProvider(config)
    result = await provider.generate("Authorities contacted.", "/tmp/out.mp3")
"""

import logging
import os

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.openai")

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(TTSProvider):
    """TTS provider using the OpenAI Audio Speech REST API via aiohttp.

    Uses aiohttp directly rather than the openai SDK to minimize
    dependencies.  Fully async — no thread pool executor needed.

    Attributes:
        _api_key: OpenAI API key.
        _model: TTS model ID.
        _voice: Voice name.
        _speed: Speaking speed multiplier.
        _timeout: HTTP request timeout in seconds.
        _base_url: API base URL (supports OpenAI-compatible endpoints).
    """

    def __init__(self, config: dict) -> None:
        """Validate that aiohttp is available and resolve the API key.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If aiohttp is not installed or no API key
                is configured.
        """
        super().__init__(config)

        try:
            import aiohttp  # noqa: F401 — import check only
        except ImportError:
            raise TTSProviderError(
                self.name,
                "aiohttp package not installed. "
                "Install with: pip install aiohttp",
            )

        tts_cfg = config.get("tts", {})
        # Provider-specific sub-dict (nested config: tts.openai.api_key, etc.)
        openai_cfg = tts_cfg.get("openai", {})

        api_key: str | None = (
            # Nested: tts.openai.api_key  (config.yaml style)
            openai_cfg.get("api_key")
            # Flat: tts.openai_api_key  (legacy / env override style)
            or tts_cfg.get("openai_api_key")
            # Environment variable fallback
            or os.environ.get("OPENAI_API_KEY")
        )
        # Resolve ${ENV_VAR} placeholders that haven't been expanded yet.
        if api_key and api_key.startswith("${"):
            api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise TTSProviderError(
                self.name,
                "No API key found. Set tts.openai.api_key in config.yaml "
                "or the OPENAI_API_KEY environment variable.",
            )

        self._api_key: str = api_key
        self._model: str = openai_cfg.get("model") or tts_cfg.get("openai_model", "tts-1")
        self._voice: str = openai_cfg.get("voice") or tts_cfg.get("openai_voice", "onyx")
        self._speed: float = float(openai_cfg.get("speed") or tts_cfg.get("openai_speed", 1.0))
        self._timeout: int = int(openai_cfg.get("timeout") or tts_cfg.get("openai_timeout", 30))
        self._base_url: str = (openai_cfg.get("base_url") or tts_cfg.get("openai_base_url", _DEFAULT_BASE_URL)).rstrip("/")

        logger.debug(
            "OpenAIProvider ready: model=%s voice=%s speed=%.2f",
            self._model, self._voice, self._speed,
        )

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "openai"
        """
        return "openai"

    @property
    def is_local(self) -> bool:
        """The default OpenAI endpoint requires internet connectivity.

        Returns:
            False
        """
        return False

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech via OpenAI TTS API and write an audio file.

        Issues an async HTTP POST to /audio/speech and streams the binary
        response body directly to ``output_path``.  No thread pool executor
        is needed because aiohttp is natively async.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output audio file (MP3 by
                default, which ffmpeg converts in the audio pipeline).

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If the API returns an error, the request
                times out, or the file cannot be written.
        """
        import aiohttp

        url = f"{self._base_url}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "input": message,
            "voice": self._voice,
            "speed": self._speed,
            "response_format": "mp3",
        }

        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise TTSProviderError(
                            self.name,
                            f"API returned HTTP {resp.status}: {body[:300]}",
                        )

                    # Stream response body to disk in 64 KiB chunks so large
                    # audio clips do not need to be buffered fully in memory.
                    with open(output_path, "wb") as fh:
                        async for chunk in resp.content.iter_chunked(65536):
                            fh.write(chunk)

        except TTSProviderError:
            raise
        except TimeoutError:
            raise TTSProviderError(
                self.name,
                f"Request timed out after {self._timeout}s",
            )
        except Exception as exc:
            raise TTSProviderError(self.name, f"HTTP request failed: {exc}") from exc

        if not os.path.exists(output_path):
            raise TTSProviderError(
                self.name,
                f"Output file was not written: {output_path}",
            )

        duration = self.estimate_duration(message)
        logger.debug("OpenAI TTS generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )
