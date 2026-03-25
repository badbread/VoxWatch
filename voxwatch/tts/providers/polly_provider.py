"""
polly_provider.py — AWS Polly Cloud TTS Provider (Cheapest Cloud)

Uses boto3 to call the Amazon Polly neural text-to-speech API.  Polly
Neural TTS is priced per character and is the most cost-effective cloud
option for high-volume deployments.

AWS credentials are resolved by boto3's standard chain:
  1. Explicit values in config (aws_access_key_id / aws_secret_access_key)
  2. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables
  3. ~/.aws/credentials file
  4. IAM instance role (when running on EC2 / ECS / Fargate)

The boto3 package is optional.  If it is not installed, this provider
raises ``TTSProviderError`` at construction time.

Config keys read from ``config["tts"]``:
    polly_region (str): AWS region (default: "us-east-1").
    polly_voice_id (str): Polly VoiceId (default: "Matthew").
        Matthew is a US-English Neural voice — clear and authoritative.
    polly_engine (str): "neural" or "standard" (default: "neural").
        Neural is higher quality; use "standard" for regions that do not
        support Neural.
    polly_timeout (int): boto3 request timeout in seconds (default: 30).
    aws_access_key_id (str): Optional explicit key ID.
    aws_secret_access_key (str): Optional explicit secret.

Install:
    pip install boto3

Usage:
    provider = PollyProvider(config)
    result = await provider.generate("You are being recorded.", "/tmp/out.wav")
"""

import asyncio
import logging
import os
from typing import Optional

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.polly")


class PollyProvider(TTSProvider):
    """TTS provider using Amazon Polly neural voice synthesis.

    Polly returns PCM audio that is wrapped in a WAV header before writing
    so the rest of the pipeline treats it identically to other providers.

    Attributes:
        _region: AWS region name.
        _voice_id: Polly VoiceId (e.g., "Matthew").
        _engine: Synthesis engine ("neural" or "standard").
        _timeout: boto3 request timeout in seconds.
        _access_key_id: Optional explicit AWS access key ID.
        _secret_access_key: Optional explicit AWS secret access key.
    """

    def __init__(self, config: dict) -> None:
        """Validate boto3 availability and read config values.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If boto3 is not installed.
        """
        super().__init__(config)

        try:
            import boto3  # noqa: F401 — import check only
        except ImportError:
            raise TTSProviderError(
                self.name,
                "boto3 package not installed. "
                "Install with: pip install boto3",
            )

        tts_cfg = config.get("tts", {})
        self._region: str = tts_cfg.get("polly_region", "us-east-1")
        self._voice_id: str = tts_cfg.get("polly_voice_id", "Matthew")
        self._engine: str = tts_cfg.get("polly_engine", "neural")
        self._timeout: int = int(tts_cfg.get("polly_timeout", 30))
        self._access_key_id: Optional[str] = (
            tts_cfg.get("aws_access_key_id")
            or os.environ.get("AWS_ACCESS_KEY_ID")
        )
        self._secret_access_key: Optional[str] = (
            tts_cfg.get("aws_secret_access_key")
            or os.environ.get("AWS_SECRET_ACCESS_KEY")
        )

        logger.debug(
            "PollyProvider ready: voice=%s engine=%s region=%s",
            self._voice_id, self._engine, self._region,
        )

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "polly"
        """
        return "polly"

    @property
    def is_local(self) -> bool:
        """Polly requires internet connectivity and AWS credentials.

        Returns:
            False
        """
        return False

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech via AWS Polly and write a WAV file.

        The boto3 call is run in a thread pool executor so the event loop
        is not blocked during the synchronous HTTP request.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If the Polly API call fails or times out.
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
        logger.debug("Polly generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )

    def _call_api(self, message: str, output_path: str) -> None:
        """Make the synchronous Polly API call (runs in executor thread).

        Requests PCM output from Polly and wraps it in a standard WAV
        header.  Using PCM avoids an MP3 decode step and gives the audio
        pipeline raw PCM at 16 kHz (Polly Neural's native rate).

        Args:
            message: Text to synthesize.
            output_path: Absolute path where the WAV file is written.

        Raises:
            TTSProviderError: If Polly returns an error or IO fails.
        """
        import struct
        import wave

        import boto3  # type: ignore[import]
        from botocore.config import Config  # type: ignore[import]

        boto_cfg = Config(
            connect_timeout=self._timeout,
            read_timeout=self._timeout,
            retries={"max_attempts": 1},
        )

        session_kwargs: dict = {"region_name": self._region, "config": boto_cfg}
        if self._access_key_id and self._secret_access_key:
            session_kwargs["aws_access_key_id"] = self._access_key_id
            session_kwargs["aws_secret_access_key"] = self._secret_access_key

        try:
            polly = boto3.client("polly", **session_kwargs)
            response = polly.synthesize_speech(
                Text=message,
                OutputFormat="pcm",  # raw PCM — wrap in WAV ourselves
                VoiceId=self._voice_id,
                Engine=self._engine,
                SampleRate="16000",  # Polly Neural natively supports 16 kHz
            )
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Polly synthesize_speech failed: {exc}",
            ) from exc

        pcm_data: bytes = response["AudioStream"].read()

        # Wrap raw PCM in a RIFF WAV container.
        # Polly returns 16-bit signed little-endian mono PCM at 16 kHz.
        try:
            with wave.open(output_path, "wb") as wav_file:
                wav_file.setnchannels(1)        # mono
                wav_file.setsampwidth(2)        # 16-bit = 2 bytes per sample
                wav_file.setframerate(16000)    # 16 kHz
                wav_file.writeframes(pcm_data)
        except Exception as exc:
            raise TTSProviderError(
                self.name,
                f"Failed to write WAV to {output_path}: {exc}",
            ) from exc
