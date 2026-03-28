"""
base.py — Abstract Base Classes and Shared Types for VoxWatch TTS

Defines the contract that every TTS provider must fulfill, the result
dataclass the rest of the pipeline consumes, and the exception type used
to signal provider-level failures.

All providers are async-first: ``generate`` is a coroutine so that
cloud providers can issue HTTP requests without blocking the event loop.
Local providers that shell out to a subprocess also benefit from the
async subprocess API (asyncio.create_subprocess_exec), which keeps the
event loop unblocked while the model generates audio.

Usage:
    from voxwatch.tts.base import TTSProvider, TTSResult, TTSProviderError

    class MyProvider(TTSProvider):
        @property
        def name(self) -> str:
            return "my_provider"

        @property
        def is_local(self) -> bool:
            return True

        async def generate(self, message: str, output_path: str) -> TTSResult:
            ...
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("voxwatch.tts")

# Average spoken words per minute used when a file duration cannot be measured.
# 150 wpm is a common estimate for clear, deliberate speech.
_DEFAULT_WPM = 150.0


@dataclass
class TTSResult:
    """Successful result from a TTS provider.

    Attributes:
        path: Absolute path to the generated WAV file.  The file is written
            at the highest quality the provider supports — the audio pipeline
            handles downconversion to the camera codec via ffmpeg.
        duration_seconds: Estimated or measured duration of the audio clip.
            Used by the caller to time subsequent audio pushes.
        provider_name: Human-readable name of the provider that produced
            this result (e.g., "piper", "elevenlabs").  Useful for logging
            and telemetry.
        fallback_reason: If the result came from a fallback provider, this
            contains a human-readable reason why the primary failed (e.g.
            "HTTP 429: quota exceeded").  Empty string when no fallback occurred.
    """

    path: str
    duration_seconds: float
    provider_name: str
    fallback_reason: str = ""


class TTSProviderError(Exception):
    """Raised when a TTS provider fails to generate audio.

    Wraps the underlying error so the factory's fallback chain can catch
    a single exception type rather than provider-specific ones.

    Attributes:
        provider_name: Name of the provider that raised this error.
        message: Human-readable failure description.
    """

    def __init__(self, provider_name: str, message: str) -> None:
        """Initialize the error with provider context.

        Args:
            provider_name: Name of the failing provider (e.g., "elevenlabs").
            message: Description of what went wrong.
        """
        self.provider_name = provider_name
        super().__init__(f"[{provider_name}] {message}")


class TTSProvider(ABC):
    """Abstract base class for all VoxWatch TTS providers.

    Subclasses must implement ``name``, ``is_local``, and ``generate``.
    ``warmup`` and ``estimate_duration`` have default implementations that
    subclasses may override.

    All providers receive the full ``config`` dict so they can read their
    own section (``config["tts"]``) as well as cross-section values such
    as subprocess timeouts.  Providers must validate their own dependencies
    (CLI binaries, SDK imports, API keys) inside ``__init__`` and raise
    ``TTSProviderError`` if they cannot proceed.

    Attributes:
        config: Full VoxWatch config dict passed through from the factory.
    """

    def __init__(self, config: dict) -> None:
        """Store config and validate provider-specific prerequisites.

        Subclasses must call ``super().__init__(config)`` and then check
        their own dependencies (binary on PATH, SDK import, API key set).
        Raise ``TTSProviderError`` if the provider cannot work.

        Args:
            config: Full VoxWatch config dict from config.py.

        Raises:
            TTSProviderError: If a required binary, SDK, or API key is
                missing so the factory can skip this provider immediately.
        """
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider used in logs and telemetry.

        Returns:
            Provider name string (e.g., "piper", "kokoro", "elevenlabs").
        """
        ...

    @property
    @abstractmethod
    def is_local(self) -> bool:
        """Whether this provider runs entirely on the local machine.

        Local providers (piper, kokoro, espeak) have no network dependency
        and no per-character cost.  Cloud providers require an API key and
        incur usage charges.

        Returns:
            True for local providers, False for cloud providers.
        """
        ...

    @abstractmethod
    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Generate speech audio from text and write it to output_path.

        The output file must be a valid WAV at the highest quality the
        provider supports.  The audio pipeline's ffmpeg step handles all
        downconversion to the camera-compatible codec.

        Args:
            message: Text to synthesize.  Already sanitized of control
                characters by the time it reaches this method.
            output_path: Absolute path where the output WAV must be written.

        Returns:
            TTSResult with the path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If synthesis fails for any reason.
        """
        ...

    async def warmup(self) -> None:
        """Optional startup hook called once after the provider is created.

        Use this to load models into memory, establish SDK connections, or
        pre-allocate resources.  Providers that have expensive model loading
        (e.g., kokoro-onnx) should do that work here rather than inside
        ``generate`` so the first real call is fast.

        The default implementation does nothing and is safe to leave
        un-overridden for providers that have no meaningful startup cost.
        """

    async def close(self) -> None:
        """Optional shutdown hook to release provider resources.

        Called during service shutdown to close HTTP sessions, release
        GPU memory, or clean up temporary files.  The default does nothing.
        Providers with persistent connections (kokoro, elevenlabs) should
        override this to close their aiohttp sessions cleanly.
        """

    def estimate_duration(self, message: str) -> float:
        """Estimate the spoken duration of a message in seconds.

        Used as a fallback when the provider does not return a measured
        duration and the output file cannot be inspected via ffprobe.
        Assumes a speaking rate of 150 words per minute with a small
        minimum floor to avoid zero-duration estimates.

        Args:
            message: The text that will be (or was) synthesized.

        Returns:
            Estimated duration in seconds (always >= 0.5).
        """
        word_count = len(message.split())
        estimated = (word_count / _DEFAULT_WPM) * 60.0
        return max(estimated, 0.5)
