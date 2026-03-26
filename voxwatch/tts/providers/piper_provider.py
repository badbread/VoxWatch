"""
piper_provider.py — Piper Neural TTS Provider (Default)

Shells out to the ``piper`` CLI binary using asyncio.create_subprocess_exec.
Piper produces high-quality, natural-sounding English speech and is the
default provider in VoxWatch because it is baked into the Docker image.

The model path is resolved in priority order:
  1. Absolute path if config value exists on disk
  2. PIPER_MODEL_PATH environment variable (set in Dockerfile)
  3. /usr/share/piper-voices/<model>.onnx (standard install location)
  4. The raw config string (piper's own fallback lookup)

Config keys read from ``config["tts"]``:
    piper_model (str): Model name or path (default: "en_US-lessac-medium").
    piper_speed (float): Speaking rate multiplier (default: 1.0).

Usage:
    provider = PiperProvider(config)
    result = await provider.generate("You are on camera.", "/tmp/out.wav")
"""

import asyncio
import logging
import os
import shutil

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.piper")

# Maximum seconds to wait for piper before treating it as hung.
_SUBPROCESS_TIMEOUT = 30


class PiperProvider(TTSProvider):
    """TTS provider using the Piper neural voice synthesis CLI.

    Piper is a fast, local, ONNX-backed TTS engine developed by
    rhasspy/piper.  It reads text from stdin and writes a WAV file
    to the path specified by ``--output_file``.

    Attributes:
        _model: Resolved model path passed to ``--model``.
        _speed: Speaking rate multiplier (e.g., 1.0 = normal).
        _timeout: Subprocess timeout in seconds.
    """

    def __init__(self, config: dict) -> None:
        """Locate the piper binary and resolve the model path.

        Args:
            config: Full VoxWatch config dict.

        Raises:
            TTSProviderError: If the piper binary is not found on PATH.
        """
        super().__init__(config)

        if not shutil.which("piper"):
            raise TTSProviderError(
                self.name,
                "piper binary not found on PATH. "
                "Install piper-tts or ensure the Docker image includes it.",
            )

        tts_cfg = config.get("tts", {})
        model_name: str = tts_cfg.get("piper_model", "en_US-lessac-medium")
        self._speed: float = float(tts_cfg.get("piper_speed", 1.0))
        self._timeout: int = int(tts_cfg.get("subprocess_timeout", _SUBPROCESS_TIMEOUT))
        self._model: str = self._resolve_model(model_name)

        logger.debug(
            "PiperProvider ready: model=%s speed=%.2f",
            self._model, self._speed,
        )

    def _resolve_model(self, model_name: str) -> str:
        """Resolve a model name or path to an accessible file path.

        Priority:
          1. If the value is already an absolute path that exists, use it.
          2. PIPER_MODEL_PATH environment variable (set in Dockerfile).
          3. /usr/share/piper-voices/<model>.onnx (standard install location).
          4. Fall through to the raw value (piper's own path resolution).

        Args:
            model_name: Config value — either a bare name like
                "en_US-lessac-medium" or a full path to a .onnx file.

        Returns:
            The best path to pass to ``piper --model``.
        """
        # Already an existing path — nothing to resolve.
        if os.path.exists(model_name):
            return model_name

        # Dockerfile bakes the model path into this env var.
        env_path = os.environ.get("PIPER_MODEL_PATH", "")
        if env_path and os.path.exists(env_path):
            logger.debug("Using PIPER_MODEL_PATH: %s", env_path)
            return env_path

        # Standard install location used by some piper packaging.
        candidate = f"/usr/share/piper-voices/{model_name}.onnx"
        if os.path.exists(candidate):
            logger.debug("Using standard voice path: %s", candidate)
            return candidate

        # Let piper handle its own model resolution (may work if model name
        # is in its built-in lookup table).
        logger.debug("Model path not found locally, passing raw name to piper: %s", model_name)
        return model_name

    @property
    def name(self) -> str:
        """Provider identifier used in logs and TTSResult.

        Returns:
            "piper"
        """
        return "piper"

    @property
    def is_local(self) -> bool:
        """Piper runs entirely on the local machine.

        Returns:
            True
        """
        return True

    async def generate(self, message: str, output_path: str) -> TTSResult:
        """Synthesize speech via the piper CLI and write a WAV file.

        Text is piped to piper via stdin.  Piper writes the WAV directly
        to ``output_path`` via ``--output_file``.

        Args:
            message: Text to synthesize.
            output_path: Absolute path for the output WAV file.

        Returns:
            TTSResult with path, estimated duration, and provider name.

        Raises:
            TTSProviderError: If piper exits non-zero, times out, or fails
                to write the output file.
        """
        cmd = [
            "piper",
            "--model", self._model,
            "--output_file", output_path,
        ]
        # piper 1.x exposes --length_scale to control speed (lower = faster).
        # length_scale = 1 / speed (e.g., speed 1.5 -> length_scale 0.67).
        if self._speed != 1.0:
            length_scale = 1.0 / self._speed
            cmd += ["--length_scale", f"{length_scale:.4f}"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(input=message.encode("utf-8")),
                timeout=self._timeout,
            )
        except TimeoutError:
            raise TTSProviderError(
                self.name,
                f"piper timed out after {self._timeout}s",
            )
        except Exception as exc:
            raise TTSProviderError(self.name, f"Subprocess error: {exc}") from exc

        if proc.returncode != 0 or not os.path.exists(output_path):
            stderr_text = stderr.decode("utf-8", errors="replace")[:300]
            raise TTSProviderError(
                self.name,
                f"piper exited {proc.returncode}: {stderr_text}",
            )

        duration = self.estimate_duration(message)
        logger.debug("Piper generated %s (est. %.1fs)", output_path, duration)
        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider_name=self.name,
        )
