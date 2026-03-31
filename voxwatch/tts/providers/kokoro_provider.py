"""
kokoro_provider.py — Kokoro TTS Provider (Local ONNX or Remote HTTP)

Supports two modes:

1. **Remote HTTP** (recommended): Connects to a Kokoro HTTP server running
   on a GPU machine. Set ``kokoro.host`` in config to the server URL.
   No local dependencies needed beyond ``aiohttp`` (already in requirements).

2. **Local ONNX**: Runs the Kokoro-82M model locally via ``kokoro-onnx``.
   Requires ``pip install kokoro-onnx soundfile``. Uses thread pool executor
   to avoid blocking the event loop during inference.

Remote mode is preferred because it offloads GPU inference to a dedicated
machine and keeps the VoxWatch container lightweight.

Config keys read from ``config["tts"]["kokoro"]``:
    host (str):  HTTP server URL (e.g., "http://localhost:8880").
                 If set, remote mode is used. If absent, local mode.
    voice (str): Voice name (default: "af_heart").
    speed (float): Speaking rate multiplier (default: 1.0).
    device (str): "cuda" or "cpu" for local mode only (default: "cpu").

Install (local mode only):
    pip install kokoro-onnx soundfile

Usage:
    provider = KokoroProvider(config)
    await provider.warmup()
    result = await provider.generate("Alert.", "/tmp/out.wav")
"""

import asyncio
import logging
import os
from typing import Any

import aiohttp

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.kokoro")


class KokoroProvider(TTSProvider):
    """TTS provider using Kokoro — remote HTTP server or local ONNX model.

    Automatically selects remote mode when ``kokoro.host`` is configured,
    otherwise falls back to local ONNX inference.

    Attributes:
        _voice: Kokoro voice name (e.g., "af_heart").
        _speed: Speaking rate multiplier.
        _host: Remote HTTP server URL (None for local mode).
        _device: Inference device for local mode ("cpu" or "cuda").
        _kokoro: Lazy-loaded local Kokoro model (None until warmup, unused in remote mode).
        _session: aiohttp session for remote mode.
    """

    def __init__(self, config: dict) -> None:
        """Initialize Kokoro provider.

        In remote mode (host configured): validates the host URL format.
        In local mode: validates that kokoro-onnx and soundfile are installed.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If local dependencies are missing (local mode only).
        """
        super().__init__(config)

        tts_cfg = config.get("tts", {})
        # Support both nested (kokoro.host) and flat (kokoro_host) config styles.
        # Flat keys (written by the dashboard) take priority over nested keys
        # because the dashboard is the most recent source of truth.
        kokoro_cfg = tts_cfg.get("kokoro", {})
        self._voice: str = tts_cfg.get("kokoro_voice") or kokoro_cfg.get("voice", "af_heart")
        self._speed: float = float(tts_cfg.get("kokoro_speed") or kokoro_cfg.get("speed", 1.0))
        self._host: str | None = tts_cfg.get("kokoro_host") or kokoro_cfg.get("host")
        self._device: str = tts_cfg.get("kokoro_device") or kokoro_cfg.get("device", "cpu")
        # Filter out null/empty host
        if self._host in (None, "", "null"):
            self._host = None
        self._kokoro: Any | None = None
        self._session: aiohttp.ClientSession | None = None

        if self._host:
            # Remote mode — no local dependencies needed
            logger.info(
                "KokoroProvider initialized in REMOTE mode: host=%s voice=%s speed=%.2f",
                self._host, self._voice, self._speed,
            )
        else:
            # Local mode — validate ONNX dependencies
            try:
                import kokoro_onnx  # noqa: F401
            except ImportError:
                raise TTSProviderError(
                    self.name,
                    "kokoro-onnx package not installed. "
                    "Install with: pip install kokoro-onnx  "
                    "Or use remote mode by setting tts.kokoro.host in config.",
                )
            try:
                import soundfile  # noqa: F401
            except ImportError:
                raise TTSProviderError(
                    self.name,
                    "soundfile package not installed (required for local WAV output). "
                    "Install with: pip install soundfile",
                )
            logger.info(
                "KokoroProvider initialized in LOCAL mode: voice=%s speed=%.2f device=%s",
                self._voice, self._speed, self._device,
            )

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "kokoro"
        """
        return "kokoro"

    @property
    def is_local(self) -> bool:
        """True if running in local ONNX mode, False if using remote HTTP server.

        Returns:
            True for local mode, False for remote mode.
        """
        return self._host is None

    async def warmup(self) -> None:
        """Prepare the provider for fast generation.

        Remote mode: creates an aiohttp session and verifies the server is reachable.
        Local mode: loads the Kokoro ONNX model into memory.
        """
        if self._host:
            await self._warmup_remote()
        else:
            await self._warmup_local()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp session.

        Reuses the same session across all requests to avoid the
        'Unclosed client session' warnings that occur when creating
        a new session per request.

        Returns:
            Active aiohttp.ClientSession instance.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def _warmup_remote(self) -> None:
        """Create HTTP session and verify remote Kokoro server is reachable.

        Raises:
            TTSProviderError: If the server health endpoint is unreachable.
        """
        session = await self._get_session()
        try:
            # Try multiple health endpoints — Docker Kokoro uses /voices,
            # older versions use /health.
            connected = False
            for health_url in (f"{self._host}/voices", f"{self._host}/health"):
                try:
                    async with session.get(health_url) as resp:
                        if resp.status == 200:
                            logger.info(
                                "Kokoro remote server connected: %s",
                                self._host,
                            )
                            connected = True
                            break
                except Exception:
                    continue
            if not connected:
                logger.warning(
                    "Kokoro server at %s health check failed — will retry on generate",
                    self._host,
                )
        except Exception as exc:
            logger.warning(
                "Kokoro server at %s not reachable during warmup: %s — will retry on generate",
                self._host, exc,
            )

    async def _warmup_local(self) -> None:
        """Load the Kokoro ONNX model into memory.

        Model loading is CPU/IO-intensive so it runs in a thread pool executor.

        Raises:
            TTSProviderError: If model loading fails.
        """
        logger.info("Loading Kokoro model (device=%s)...", self._device)
        loop = asyncio.get_event_loop()
        try:
            self._kokoro = await loop.run_in_executor(None, self._load_model)
            logger.info("Kokoro model loaded successfully")
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Failed to load Kokoro model: {exc}",
            ) from exc

    def _load_model(self) -> Any:
        """Load the Kokoro model synchronously (runs in executor thread).

        Returns:
            Initialized Kokoro model object.
        """
        from kokoro_onnx import Kokoro  # type: ignore[import]
        return Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech with Kokoro and write a WAV file.

        Routes to remote HTTP or local ONNX based on configuration.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, duration, and provider name.

        Raises:
            TTSProviderError: If generation fails.
        """
        if self._host:
            return await self._generate_remote(message, output_path)
        else:
            return await self._generate_local(message, output_path)

    async def _generate_remote(self, message: str, output_path: str) -> TTSResult:
        """Generate speech via the remote Kokoro HTTP server.

        Tries the OpenAI-compatible ``/v1/audio/speech`` endpoint first
        (used by Docker-based Kokoro deployments).  Falls back to the
        legacy ``/tts`` endpoint if the new one returns 404.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If the HTTP request fails or returns non-200.
        """
        session = await self._get_session()

        audio_data: bytes | None = None

        try:
            # ── Try OpenAI-compatible endpoint first ──────────────────────
            openai_payload = {
                "model": "kokoro",
                "input": message,
                "voice": self._voice,
                "speed": self._speed,
                "response_format": "wav",
            }
            async with session.post(
                f"{self._host}/v1/audio/speech",
                json=openai_payload,
            ) as resp:
                if resp.status == 404:
                    # Endpoint doesn't exist — try legacy below
                    logger.debug(
                        "Kokoro /v1/audio/speech returned 404, trying legacy /tts"
                    )
                elif resp.status != 200:
                    body = await resp.text()
                    raise TTSProviderError(
                        self.name,
                        f"Kokoro server returned HTTP {resp.status}: {body[:200]}",
                    )
                else:
                    audio_data = await resp.read()

            # ── Fall back to legacy /tts endpoint ─────────────────────────
            if audio_data is None:
                legacy_payload = {
                    "text": message,
                    "voice": self._voice,
                    "speed": self._speed,
                }
                async with session.post(
                    f"{self._host}/tts",
                    json=legacy_payload,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise TTSProviderError(
                            self.name,
                            f"Kokoro server returned HTTP {resp.status}: {body[:200]}",
                        )
                    audio_data = await resp.read()

            logger.debug(
                "Kokoro remote generated %d bytes",
                len(audio_data),
            )

            with open(output_path, "wb") as f:
                f.write(audio_data)

        except TTSProviderError:
            raise
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Failed to reach Kokoro server at {self._host}: {exc}",
            ) from exc

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
            raise TTSProviderError(
                self.name,
                f"Output file is empty or missing: {output_path}",
            )

        # Estimate duration from file size (WAV at ~24kHz 16-bit mono = ~48KB/s)
        file_size = os.path.getsize(output_path)
        duration = max(file_size / 48000.0, 0.5)

        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )

    async def _generate_local(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech with local Kokoro ONNX model.

        Inference runs in a thread pool executor to avoid blocking the event loop.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, measured duration, and provider name.

        Raises:
            TTSProviderError: If warmup was never called or inference fails.
        """
        if self._kokoro is None:
            raise TTSProviderError(
                self.name,
                "Model not loaded — call warmup() before generate()",
            )

        loop = asyncio.get_event_loop()
        try:
            duration = await loop.run_in_executor(
                None,
                self._run_inference,
                message,
                output_path,
            )
        except TTSProviderError:
            raise
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Inference failed: {exc}",
            ) from exc

        logger.debug("Kokoro local generated %s (%.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )

    def _run_inference(self, message: str, output_path: str) -> float:
        """Run synchronous Kokoro inference and save WAV (runs in executor thread).

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            Measured audio duration in seconds.

        Raises:
            TTSProviderError: If inference or file write fails.
        """
        import soundfile as sf  # type: ignore[import]

        try:
            samples, sample_rate = self._kokoro.create(
                message,
                voice=self._voice,
                speed=self._speed,
                lang="en-us",
            )
        except Exception as exc:
            raise TTSProviderError(self.name, f"kokoro.create() failed: {exc}") from exc

        try:
            sf.write(output_path, samples, sample_rate)
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Failed to write WAV to {output_path}: {exc}",
            ) from exc

        if not os.path.exists(output_path):
            raise TTSProviderError(
                self.name,
                f"Output file was not written: {output_path}",
            )

        duration = len(samples) / float(sample_rate) if sample_rate > 0 else 0.0
        return max(duration, 0.5)

    async def close(self) -> None:
        """Close the aiohttp session (remote mode only).

        Called during service shutdown to release network resources.
        """
        if self._session and not self._session.closed:
            await self._session.close()
