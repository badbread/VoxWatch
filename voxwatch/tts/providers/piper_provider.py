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
import urllib.request

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.piper")

# Maximum seconds to wait for piper before treating it as hung.
_SUBPROCESS_TIMEOUT = 30

# Directory where auto-downloaded piper models are cached.
_DOWNLOAD_DIR = "/data/piper-voices"

# Hugging Face base URL for piper voice models.
_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

# Community / custom voices hosted outside the rhasspy repository.
# Maps model name → (onnx_url, json_url).
_CUSTOM_VOICES: dict[str, tuple[str, str]] = {
    "hal9000": (
        "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx",
        "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json",
    ),
}


def _hf_url(model_name: str) -> tuple[str, str]:
    """Build Hugging Face download URLs for a piper model.

    Checks the custom voice registry first, then falls back to the standard
    rhasspy/piper-voices repository URL pattern.

    Args:
        model_name: Piper model name like "en_US-lessac-medium" or "hal9000".

    Returns:
        Tuple of (onnx_url, json_url) for the model and its config file.

    Raises:
        ValueError: If the model name doesn't match the expected pattern.
    """
    # Check custom voice registry first.
    if model_name in _CUSTOM_VOICES:
        return _CUSTOM_VOICES[model_name]

    # Standard rhasspy format: <lang>_<region>-<voice>-<quality>
    parts = model_name.split("-")
    if len(parts) < 3:
        raise ValueError(f"Cannot parse model name: {model_name}")
    lang_region = parts[0]        # e.g. "en_US"
    voice = parts[1]              # e.g. "lessac"
    quality = parts[2]            # e.g. "medium"
    lang = lang_region.split("_")[0]  # e.g. "en"

    base_path = f"{_HF_BASE}/{lang}/{lang_region}/{voice}/{quality}"
    return (
        f"{base_path}/{model_name}.onnx",
        f"{base_path}/{model_name}.onnx.json",
    )


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
          2. /usr/share/piper-voices/<model>.onnx (baked into Docker image).
          3. /data/piper-voices/<model>.onnx (auto-downloaded cache).
          4. Auto-download from Hugging Face to /data/piper-voices/.
          5. PIPER_MODEL_PATH env var (legacy fallback for default voice only).
          6. Fall through to the raw value (piper's own path resolution).

        PIPER_MODEL_PATH is intentionally checked LAST — it points to the
        default baked-in model and must not override the user's voice selection.

        Args:
            model_name: Config value — either a bare name like
                "en_US-lessac-medium" or a full path to a .onnx file.

        Returns:
            The best path to pass to ``piper --model``.
        """
        # Already an existing path — nothing to resolve.
        if os.path.exists(model_name):
            return model_name

        # Standard install location (baked into Docker image).
        candidate = f"/usr/share/piper-voices/{model_name}.onnx"
        if os.path.exists(candidate):
            logger.debug("Using baked-in voice: %s", candidate)
            return candidate

        # Check auto-download cache.
        cached = os.path.join(_DOWNLOAD_DIR, f"{model_name}.onnx")
        if os.path.exists(cached):
            logger.debug("Using cached downloaded voice: %s", cached)
            return cached

        # Attempt auto-download from Hugging Face.
        downloaded = self._download_model(model_name)
        if downloaded:
            return downloaded

        # Legacy fallback: PIPER_MODEL_PATH env var (set in Dockerfile).
        # Only used if nothing else matched — avoids overriding user selection.
        env_path = os.environ.get("PIPER_MODEL_PATH", "")
        if env_path and os.path.exists(env_path):
            logger.debug("Using PIPER_MODEL_PATH fallback: %s", env_path)
            return env_path

        # Let piper handle its own model resolution.
        logger.debug("Model path not found locally, passing raw name to piper: %s", model_name)
        return model_name

    @staticmethod
    def _download_model(model_name: str) -> str | None:
        """Download a piper voice model from Hugging Face.

        Downloads both the .onnx model and its .onnx.json config file
        to the persistent cache directory (/data/piper-voices/).

        Args:
            model_name: Piper model name like "en_US-lessac-medium".

        Returns:
            Path to the downloaded .onnx file, or None on failure.
        """
        try:
            onnx_url, json_url = _hf_url(model_name)
        except ValueError as exc:
            logger.warning("Cannot auto-download model '%s': %s", model_name, exc)
            return None

        os.makedirs(_DOWNLOAD_DIR, exist_ok=True)
        onnx_path = os.path.join(_DOWNLOAD_DIR, f"{model_name}.onnx")
        json_path = os.path.join(_DOWNLOAD_DIR, f"{model_name}.onnx.json")

        logger.info(
            "Downloading piper voice '%s' from Hugging Face (first use)...",
            model_name,
        )

        try:
            # Download the .onnx.json config first (small, fast).
            urllib.request.urlretrieve(json_url, json_path)
            logger.debug("Downloaded model config: %s", json_path)

            # Download the .onnx model (typically 20-60 MB).
            urllib.request.urlretrieve(onnx_url, onnx_path)
            logger.info(
                "Downloaded piper voice '%s' (%.1f MB) to %s",
                model_name,
                os.path.getsize(onnx_path) / 1_048_576,
                onnx_path,
            )
            return onnx_path
        except Exception as exc:
            logger.warning(
                "Failed to download piper voice '%s': %s", model_name, exc
            )
            # Clean up partial downloads.
            for path in (onnx_path, json_path):
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            return None

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
