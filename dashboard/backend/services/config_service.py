"""
config_service.py — VoxWatch Configuration Read/Write Service

Provides safe, atomic access to config.yaml for the dashboard API.

Key design decisions:
  - ${ENV_VAR} tokens are preserved as-is in the YAML — they are never
    resolved here. The VoxWatch service resolves them at runtime; the
    dashboard just stores and retrieves the literal token string.
  - Sensitive fields (api_key, mqtt_password) are masked with '***MASKED***'
    in GET responses so they never travel over the API to the browser.
  - Writes are atomic: content is written to a .tmp file then renamed into
    place so a crash mid-write can never leave a truncated config.
  - The YAML is loaded and round-tripped through Pydantic for validation,
    then serialized back to YAML preserving structure (though not comments).
    Block comments in the original file are lost on write — the dashboard
    is expected to maintain inline field descriptions separately.

Usage:
    service = ConfigService()
    cfg = await service.get_config()          # returns masked VoxWatchConfig
    result = await service.validate_config(data)  # dry-run validation
    await service.save_config(data)            # atomically writes config.yaml
"""

import logging
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import ValidationError

from backend.config import VOXWATCH_CONFIG_PATH
from backend.models.config_models import (
    ConfigValidationResult,
    VoxWatchConfig,
)

logger = logging.getLogger("dashboard.config_service")

# Fields that contain secrets — masked in GET responses.
# Key is the dot-path of the field within the config tree.
#
# Security note: latitude and longitude are included here because precise
# location data (used for weather-based deterrent conditions) constitutes
# personally identifiable information under many privacy frameworks (GDPR,
# CCPA).  Exposing exact coordinates in API responses would allow anyone
# with dashboard access to determine the physical installation address.
# Masking them ensures they stay server-side only.
_SENSITIVE_PATHS: set[str] = {
    # Both AI provider slots can hold API keys now that primary and fallback
    # share the same unified AiProviderConfig model.
    "ai.primary.api_key",
    "ai.fallback.api_key",
    "frigate.mqtt_password",
    "conditions.latitude",
    "conditions.longitude",
    # TTS provider API keys
    "tts.elevenlabs_api_key",
    "tts.cartesia_api_key",
    "tts.openai_api_key",
}

# Placeholder used to replace sensitive values in API responses.
_MASK_VALUE = "***MASKED***"

# Regex matching an ${ENV_VAR} token so we know when to skip overwriting
# a masked field (i.e. the stored value is already a token — don't clobber it).
_ENV_TOKEN_RE = re.compile(r"^\$\{[^}]+\}$")


def _mask_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of *data* with sensitive paths replaced by the mask.

    Only values that are NOT already ${ENV_VAR} tokens are replaced — tokens
    are already opaque to the browser so masking them is redundant.

    Args:
        data: Config dict as produced by model.model_dump().

    Returns:
        New dict with sensitive fields masked.
    """
    masked = deepcopy(data)
    for dot_path in _SENSITIVE_PATHS:
        parts = dot_path.split(".")
        node = masked
        try:
            for part in parts[:-1]:
                node = node[part]
            original = node.get(parts[-1], "")
            # Only mask non-empty values that are not already ${TOKEN} references.
            # Empty strings are left as-is — there's nothing sensitive to hide.
            if (
                isinstance(original, str)
                and original  # skip empty strings
                and not _ENV_TOKEN_RE.match(original)
            ):
                node[parts[-1]] = _MASK_VALUE
        except (KeyError, TypeError):
            # Path doesn't exist in this config — nothing to mask
            pass
    return masked


def _is_masked(value: Any) -> bool:
    """Return True if *value* is the sentinel mask placeholder."""
    return value == _MASK_VALUE


class ConfigService:
    """Service layer for reading and writing the VoxWatch config.yaml.

    Attributes:
        config_path: Absolute path to the config.yaml file.
    """

    def __init__(self, config_path: str = VOXWATCH_CONFIG_PATH) -> None:
        """Initialize with path to config.yaml.

        Args:
            config_path: Filesystem path to the VoxWatch config.yaml.
                         Defaults to the VOXWATCH_CONFIG_PATH env var.
        """
        self.config_path = Path(config_path)

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_config(self) -> Dict[str, Any]:
        """Read and return the current config with sensitive fields masked.

        Reads the raw YAML, preserving ${ENV_VAR} tokens. Parses through
        Pydantic (validates structure) then returns as a plain dict with
        sensitive fields replaced by the mask placeholder.

        Returns:
            Config dict safe to serialize and send to the browser.

        Raises:
            FileNotFoundError: If config.yaml does not exist.
            ValueError: If the YAML cannot be parsed or fails validation.
        """
        raw = self._read_raw_yaml()
        # Parse through Pydantic to validate and fill defaults
        try:
            parsed = VoxWatchConfig.model_validate(raw)
        except ValidationError as exc:
            logger.warning("Config has validation issues but will be returned: %s", exc)
            # Still return the raw data — the dashboard needs to show it even
            # if it's currently broken so the user can fix it.
            return _mask_dict(raw)

        data = parsed.model_dump()
        return _mask_dict(data)

    async def get_raw_config(self) -> Dict[str, Any]:
        """Read the raw config without masking sensitive fields.

        Used internally for operations that need real API keys (e.g. AI provider
        testing). NEVER expose this directly to the browser API.

        Returns:
            Raw config dict with real API keys and passwords.
        """
        return self._read_raw_yaml()

    async def validate_config(self, data: Dict[str, Any]) -> ConfigValidationResult:
        """Validate a config dict without saving it.

        Runs the incoming data through the Pydantic model and collects all
        errors. Also checks for non-fatal warnings like unresolved API key tokens.

        Args:
            data: Config dict as submitted by the browser (may contain masked values).

        Returns:
            ConfigValidationResult with valid flag, errors list, and warnings list.
        """
        # Before validating, merge masked fields back from the current file so
        # the validator sees real values for fields the user didn't change.
        merged = await self._merge_masked_fields(data)

        errors: list[str] = []
        warnings: list[str] = []

        try:
            parsed = VoxWatchConfig.model_validate(merged)
        except ValidationError as exc:
            for error in exc.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                errors.append(f"{loc}: {error['msg']}")
            return ConfigValidationResult(valid=False, errors=errors, warnings=warnings)

        # Non-fatal warnings — api_key is Optional[str] on the unified model,
        # so guard every access before calling string methods.
        #
        # Providers that always need an API key (self-hosted providers such as
        # ollama do not use api_key, so skip the warning for them).
        _CLOUD_PROVIDERS = {"gemini", "openai", "anthropic", "grok"}

        primary_key = parsed.ai.primary.api_key
        if parsed.ai.primary.provider in _CLOUD_PROVIDERS:
            if primary_key and _ENV_TOKEN_RE.match(primary_key):
                warnings.append(
                    f"ai.primary.api_key is an unresolved token ({primary_key}) — "
                    "ensure the environment variable is set in the container"
                )
            if not primary_key:
                warnings.append(
                    "ai.primary.api_key is empty — Stage 2/3 will fall back to the fallback provider"
                )

        fallback_key = parsed.ai.fallback.api_key
        if parsed.ai.fallback.provider in _CLOUD_PROVIDERS:
            if fallback_key and _ENV_TOKEN_RE.match(fallback_key):
                warnings.append(
                    f"ai.fallback.api_key is an unresolved token ({fallback_key}) — "
                    "ensure the environment variable is set in the container"
                )
            if not fallback_key:
                warnings.append(
                    "ai.fallback.api_key is empty — fallback provider will not authenticate"
                )

        mqtt_pw = parsed.frigate.mqtt_password
        if mqtt_pw and _ENV_TOKEN_RE.match(mqtt_pw):
            warnings.append(
                f"frigate.mqtt_password is an unresolved token ({mqtt_pw}) — "
                "ensure the environment variable is set"
            )

        return ConfigValidationResult(valid=True, errors=errors, warnings=warnings)

    async def save_config(self, data: Dict[str, Any]) -> None:
        """Atomically write a new config to config.yaml.

        Steps:
          1. Merge masked fields back from the current file (don't overwrite
             secrets with the mask placeholder).
          2. Validate through Pydantic — raise if invalid.
          3. Write to a temp file alongside config.yaml.
          4. Rename temp file into place (atomic on POSIX; best-effort on Windows).

        Args:
            data: Config dict from the browser (may contain masked field values).

        Raises:
            ValidationError: If the data fails Pydantic validation.
            OSError: If the file cannot be written or renamed.
        """
        # Merge masked sentinel values back with real secrets from disk
        merged = await self._merge_masked_fields(data)

        # Full validation before touching the filesystem
        VoxWatchConfig.model_validate(merged)

        yaml_text = yaml.dump(
            merged,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # Atomic write: write to .tmp then rename
        config_dir = self.config_path.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir),
            prefix=".config_",
            suffix=".yaml.tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(yaml_text)
            os.replace(tmp_path, str(self.config_path))
        except Exception:
            # Clean up the temp file if anything goes wrong
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info("Config saved to %s", self.config_path)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_raw_yaml(self) -> Dict[str, Any]:
        """Read config.yaml and return the raw parsed dict.

        ${ENV_VAR} tokens are NOT resolved — they are kept as literal strings.

        Returns:
            Raw YAML content as a dict.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML cannot be parsed.
        """
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {self.config_path}. "
                "Create it from config/config.yaml in the VoxWatch repo."
            )
        with self.config_path.open("r", encoding="utf-8") as fh:
            try:
                raw = yaml.safe_load(fh) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"Failed to parse config.yaml: {exc}") from exc
        return raw

    async def _merge_masked_fields(self, incoming: Dict[str, Any]) -> Dict[str, Any]:
        """Replace mask placeholders in *incoming* with the real values from disk.

        When the browser submits a config update, masked fields (like api_key)
        arrive as '***MASKED***'. We must not save that placeholder — instead
        we restore the original value from the on-disk config.

        Args:
            incoming: Config dict from the browser PUT/POST body.

        Returns:
            Merged dict with mask placeholders replaced by real on-disk values.
        """
        merged = deepcopy(incoming)

        # Read real values from disk (best-effort — if the file doesn't exist
        # or can't be parsed, just return the incoming data unchanged)
        try:
            on_disk = self._read_raw_yaml()
        except (FileNotFoundError, ValueError):
            return merged

        for dot_path in _SENSITIVE_PATHS:
            parts = dot_path.split(".")
            # Navigate to the value in incoming
            in_node = merged
            disk_node = on_disk
            try:
                for part in parts[:-1]:
                    in_node = in_node[part]
                    disk_node = disk_node[part]
                field = parts[-1]
                if _is_masked(in_node.get(field)):
                    # Restore from disk
                    in_node[field] = disk_node.get(field, "")
            except (KeyError, TypeError):
                pass

        return merged


# ── Module-level singleton ────────────────────────────────────────────────────
# The FastAPI app imports this instance; it can be replaced in tests.

config_service = ConfigService()
