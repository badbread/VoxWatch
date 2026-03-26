"""
config.py — Configuration Loading and Validation for VoxWatch

Loads config.yaml, substitutes environment variables (${VAR} syntax),
validates required fields, and provides typed access to all settings.

Usage:
    from voxwatch.config import load_config
    config = load_config("/config/config.yaml")
    print(config["frigate"]["host"])
"""

import logging
import os
import re
import sys
from typing import Any

import yaml

logger = logging.getLogger("voxwatch.config")

# Pattern to match ${ENV_VAR} or ${ENV_VAR:default_value} in YAML strings
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")

# Required top-level config keys
REQUIRED_KEYS = ["frigate", "go2rtc", "cameras"]


def _substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${ENV_VAR} patterns in config values.

    Supports default values: ${VAR:default} uses 'default' if VAR is unset.
    Only operates on string values — dicts and lists are traversed recursively.

    Args:
        value: A config value (str, dict, list, or primitive).

    Returns:
        The value with all environment variable references resolved.
    """
    if isinstance(value, str):
        def replace_match(match):
            var_name = match.group(1)
            default = match.group(2)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            logger.warning("Environment variable %s is not set and has no default", var_name)
            return match.group(0)  # Leave unresolved as-is
        return ENV_VAR_PATTERN.sub(replace_match, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def _apply_defaults(config: dict) -> dict:
    """Apply sensible defaults for any missing optional config sections.

    This ensures the service can start with a minimal config.yaml that only
    specifies the required fields (frigate, go2rtc, cameras).

    Args:
        config: The raw parsed config dict.

    Returns:
        Config dict with defaults filled in.
    """
    # Detection conditions defaults
    conditions = config.setdefault("conditions", {})
    conditions.setdefault("min_score", 0.7)
    conditions.setdefault("cooldown_seconds", 60)
    active_hours = conditions.setdefault("active_hours", {})
    active_hours.setdefault("mode", "always")  # "always", "sunset_sunrise", or "fixed"
    active_hours.setdefault("start", "22:00")
    active_hours.setdefault("end", "06:00")
    conditions.setdefault("latitude", 37.7749)
    conditions.setdefault("longitude", -122.4194)

    # AI vision defaults
    ai = config.setdefault("ai", {})
    primary = ai.setdefault("primary", {})
    primary.setdefault("provider", "gemini")
    primary.setdefault("model", "gemini-2.5-flash")
    primary.setdefault("api_key", "${GEMINI_API_KEY}")
    primary.setdefault("timeout_seconds", 5)
    fallback = ai.setdefault("fallback", {})
    fallback.setdefault("provider", "ollama")
    fallback.setdefault("model", "llava:7b")
    fallback.setdefault("host", "http://localhost:11434")
    fallback.setdefault("timeout_seconds", 8)

    # Stage settings
    stage2 = config.setdefault("stage2", {})
    stage2.setdefault("snapshot_count", 3)
    stage2.setdefault("snapshot_interval_ms", 1000)

    stage3 = config.setdefault("stage3", {})
    stage3.setdefault("enabled", True)
    stage3.setdefault("video_clip_seconds", 5)
    stage3.setdefault("person_still_present_check", True)
    stage3.setdefault("fallback_to_snapshots", True)
    stage3.setdefault("fallback_snapshot_count", 5)

    # TTS defaults — multi-provider system (see voxwatch/tts/factory.py)
    # Only the provider name, fallback chain, and per-engine sub-dicts that
    # the factory actually reads need defaults here.  Cloud provider settings
    # (api_key, voice_id, etc.) intentionally have no defaults — they must be
    # set explicitly in config.yaml or via environment variables.
    tts_cfg = config.setdefault("tts", {})
    # Accept both "provider" (core) and "engine" (dashboard) field names.
    # If "engine" is set but "provider" is not, copy engine to provider
    # so the factory always has a consistent key to read.
    if "provider" not in tts_cfg and "engine" in tts_cfg:
        tts_cfg["provider"] = tts_cfg["engine"]
    tts_cfg.setdefault("provider", "piper")
    tts_cfg.setdefault("fallback_chain", ["piper"])
    tts_cfg.setdefault("espeak", {"speed": 130, "pitch": 30})
    tts_cfg.setdefault("piper", {"model": "en_US-lessac-medium", "speed": 1.0})

    # Audio output format defaults — PCMU (mu-law) confirmed working with Reolink CX410
    audio = config.setdefault("audio", {})
    audio.setdefault("codec", "pcm_mulaw")
    audio.setdefault("sample_rate", 8000)
    audio.setdefault("channels", 1)
    # Attention tone played before TTS speech.  "none" disables the feature.
    # Built-in values: "short" (0.5s beep), "long" (1s two-tone), "siren" (1.5s sweep).
    # A path to a custom WAV file is also accepted.
    audio.setdefault("attention_tone", "none")
    audio.setdefault("attention_tone_volume", 1.0)

    # Pre-cached messages
    messages = config.setdefault("messages", {})
    messages.setdefault("stage1", (
        "Attention. You are on private property. "
        "You are being recorded on camera. "
        "The homeowner has been notified."
    ))
    messages.setdefault("stage2_prefix", "Individual detected.")
    messages.setdefault("stage2_suffix",
                        "You have been identified and recorded. The homeowner has been notified.")
    messages.setdefault("stage3_prefix", "Warning.")
    messages.setdefault("stage3_suffix",
                        "All activity has been recorded and transmitted. Authorities are being contacted.")
    # Per-stage attention tone overrides.  When absent, the global
    # audio.attention_tone default is used.  Set to "none" to silence a
    # specific stage even when a global tone is configured.
    # Valid values: "none", "short", "long", "siren", or a custom WAV path.
    # These keys are intentionally NOT set here so that missing keys fall
    # through to the global default in AudioPipeline._get_stage_tone().

    # Logging defaults — rotation prevents unbounded disk growth
    log = config.setdefault("logging", {})
    log.setdefault("level", "INFO")
    log.setdefault("file", "/data/voxwatch.log")
    log.setdefault("max_bytes", 10 * 1024 * 1024)  # 10 MB per log file
    log.setdefault("backup_count", 5)               # Keep 5 rotated backups (50 MB total max)
    log.setdefault("events_max_bytes", 5 * 1024 * 1024)  # 5 MB events.jsonl before rotation

    # Audio push settings — HTTP server for go2rtc to fetch audio files
    push = config.setdefault("audio_push", {})
    push.setdefault("serve_port", 8891)

    # Response Mode — speaking style for all deterrent stages.
    # Replaces the old "persona" section.  If "response_mode" is absent but
    # "persona" is present (legacy config), copy persona into response_mode so
    # the rest of the service always has a consistent key to read.
    if "response_mode" not in config and "persona" in config:
        config["response_mode"] = config["persona"]
    response_mode = config.setdefault("response_mode", {})
    response_mode.setdefault("name", "private_security")
    response_mode.setdefault("custom_prompt", "")

    # Response Modes — structured YAML-based mode system (new).
    # ``response_modes.active_mode`` is the preferred key; when absent the
    # loader falls back to ``response_mode.name`` (legacy compat via
    # ``voxwatch.modes.loader._resolve_mode_id``).  We deliberately do NOT
    # default ``active_mode`` here so that existing configs that only set
    # ``response_mode.name`` continue to route through the legacy fallback
    # path unchanged.
    rm_section = config.setdefault("response_modes", {})
    # ``camera_overrides`` — per-camera mode override map, always a dict.
    rm_section.setdefault("camera_overrides", {})
    # ``modes`` — user-defined mode list.  Built-ins are always available.
    rm_section.setdefault("modes", [])

    # Dispatch sub-config — only used when response_mode.name is a dispatch mode
    # (e.g. "police_dispatch").  All fields default to empty string / True so the
    # pipeline can always do a simple truthiness check rather than a KeyError guard.
    # When address fields are blank the pipeline falls back to generic phrasing.
    dispatch = response_mode.setdefault("dispatch", {})
    dispatch.setdefault("address", "")
    dispatch.setdefault("city", "")
    dispatch.setdefault("state", "")
    dispatch.setdefault("full_address", "")
    dispatch.setdefault("agency", "")
    dispatch.setdefault("callsign", "")
    dispatch.setdefault("include_address", True)
    # Channel intro — plays before the main dispatch call to simulate tuning
    # into an active police radio frequency.  Sequence: clean connecting voice
    # → tuning static → random "other call" tail end (radio-processed) →
    # squelch pause → main dispatch.  Defaults to True (enabled).
    dispatch.setdefault("channel_intro", True)
    # Officer response — short male-voice acknowledgment appended after the
    # dispatcher segments.  Flow: dispatcher → 1.5–2.5 s pause → officer clip.
    # Defaults to True.  Set False to disable for Tony Montana or novelty modes.
    dispatch.setdefault("officer_response", True)
    # Officer callsign — the unit identifier spoken in the officer response.
    # Falls back to the shared dispatch callsign when empty; final fallback is
    # the human-readable "Unit seven".
    dispatch.setdefault("officer_callsign", "")
    # Dispatcher voice — per-provider voice selection for all dispatcher segments.
    # The active field is determined by tts.provider:
    #   kokoro     → dispatcher_voice (Kokoro voice ID)
    #   openai     → dispatcher_openai_voice
    #   elevenlabs → dispatcher_elevenlabs_voice
    #   piper/espeak → no voice selection (single voice per model)
    # af_bella is warm but professional; af_sarah is clear and measured;
    # af_nicole is authoritative.  af_heart (old default) is too casual.
    dispatch.setdefault("dispatcher_voice", "af_bella")
    # OpenAI TTS voice for the dispatcher.  "nova" is clean and professional —
    # closest to a real dispatcher voice from the available OpenAI options.
    dispatch.setdefault("dispatcher_openai_voice", "nova")
    # ElevenLabs voice ID for the dispatcher.  Blank = use the default
    # Bella voice (EXAVITQu4vr4xnSDxMaL) at runtime.  Set to a specific voice
    # ID to override.  Get IDs from elevenlabs.io/voice-library.
    dispatch.setdefault("dispatcher_elevenlabs_voice", "Xb7hH8MSUJpSbSDYk0k2")  # Alice — clinical, professional female
    # Dispatcher speed — real dispatchers speak slightly slower than normal
    # conversation to ensure clarity over radio.  0.9 = 90% of normal speed.
    dispatch.setdefault("dispatcher_speed", 0.9)
    # Officer voice — per-provider voice selection for the officer response.
    # am_fenrir is a deep male Kokoro voice that contrasts with the dispatcher.
    # Only used when tts.provider is "kokoro"; other per-role providers below.
    dispatch.setdefault("officer_voice", "am_fenrir")
    # OpenAI TTS voice for the officer.  "onyx" is the deepest male option —
    # best for an authoritative officer sound distinct from the dispatcher.
    dispatch.setdefault("officer_openai_voice", "onyx")
    # ElevenLabs voice ID for the officer.  Blank = use the default Antoni
    # voice (ErXwobaYiN019PkySvjV) at runtime.  Must be a male voice to
    # sound convincing — do not use a female voice for the officer.
    dispatch.setdefault("officer_elevenlabs_voice", "onwK4e9ZLuTAKqWW03F9")  # Daniel — deep, clear male
    # Officer speed — officers speak at normal conversational pace.
    dispatch.setdefault("officer_speed", 1.0)

    # Pipeline smart escalation — controls Initial Response and Escalation timing.
    # Detection fires the pipeline; Initial Response is immediate; Escalation
    # fires after `delay` seconds if the person is still present.
    pipeline = config.setdefault("pipeline", {})
    initial_resp = pipeline.setdefault("initial_response", {})
    initial_resp.setdefault("delay", 0)
    initial_resp.setdefault("enabled", True)
    escalation = pipeline.setdefault("escalation", {})
    escalation.setdefault("delay", 6)
    escalation.setdefault("condition", "person_still_present")
    escalation.setdefault("enabled", True)
    resolution = pipeline.setdefault("resolution", {})
    resolution.setdefault("enabled", False)
    resolution.setdefault("message", "Area clear.")

    # Property address — substituted into radio dispatch message segments.
    # Users should override these values in config.yaml with their real address.
    # The full_address field is used in longer announcements; address_street is
    # the short form used in the initial 10-code location call-out.
    prop = config.setdefault("property", {})
    prop.setdefault("street", "Your Street Address")
    prop.setdefault("city", "Your City")
    prop.setdefault("state", "CA")
    prop.setdefault("full_address", "Your Street Address, Your City, CA")

    # Speech — natural cadence system settings.
    # When enabled, multi-phrase AI responses are rendered with human-like
    # inter-phrase pauses and optional per-phrase speed variation instead of
    # being read as a single continuous string.
    speech = config.setdefault("speech", {})
    cadence = speech.setdefault("natural_cadence", {})
    cadence.setdefault("enabled", True)
    cadence.setdefault("min_pause", 0.2)       # seconds — minimum inter-phrase silence
    cadence.setdefault("max_pause", 0.6)       # seconds — maximum inter-phrase silence
    cadence.setdefault("period_pause", 0.5)    # seconds — pause after "."
    cadence.setdefault("ellipsis_pause", 0.7)  # seconds — pause after "..."
    cadence.setdefault("comma_pause", 0.2)     # seconds — pause after ","
    cadence.setdefault("speed_variation", True)   # per-phrase speed jitter (atempo)
    cadence.setdefault("min_speed", 0.92)         # lower bound for speed multiplier
    cadence.setdefault("max_speed", 1.08)         # upper bound for speed multiplier
    cadence.setdefault("leading_pause", 0.3)      # silence before first phrase
    cadence.setdefault("trailing_pause", 0.2)     # silence after last phrase
    cadence.setdefault("postprocess", True)       # apply loudnorm + silence trim

    # Radio dispatch effect settings — controls the audio processing applied
    # to TTS output to simulate a police radio transmission.
    # intensity selects a preset from RADIO_INTENSITY_PRESETS in audio_effects.py.
    # Individual bandpass_low/bandpass_high/noise_level keys override the preset.
    radio = config.setdefault("radio_effect", {})
    radio.setdefault("enabled", True)
    radio.setdefault("intensity", "medium")   # "low", "medium", or "high"
    radio.setdefault("bandpass_low", 300)     # Hz — high-pass cutoff frequency
    radio.setdefault("bandpass_high", 3000)   # Hz — low-pass cutoff frequency
    radio.setdefault("noise_level", 0.03)     # 0.0-1.0 background static amplitude
    radio.setdefault("squelch_enabled", True) # append squelch release at end

    return config


def validate_config(config: dict) -> list[str]:
    """Validate the config for required fields and sane values.

    Args:
        config: The loaded config dict.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    for key in REQUIRED_KEYS:
        if key not in config:
            errors.append(f"Missing required config section: '{key}'")

    # Validate Frigate settings
    frigate = config.get("frigate", {})
    if not frigate.get("host"):
        errors.append("frigate.host is required")

    # Validate go2rtc settings
    go2rtc = config.get("go2rtc", {})
    if not go2rtc.get("host"):
        errors.append("go2rtc.host is required")

    # Validate at least one camera is configured
    cameras = config.get("cameras", {})
    if not cameras:
        errors.append("At least one camera must be configured in 'cameras' section")

    enabled_cameras = [name for name, cam in cameras.items() if cam.get("enabled", True)]
    if not enabled_cameras:
        errors.append("At least one camera must be enabled")

    # Validate AI API key is available (after env var substitution)
    ai_key = config.get("ai", {}).get("primary", {}).get("api_key", "")
    if ai_key.startswith("${"):
        logger.warning("Gemini API key not set — Stage 2/3 will fall back to Ollama")

    return errors


def load_config(config_path: str) -> dict:
    """Load, validate, and return the VoxWatch configuration.

    Reads the YAML file, substitutes environment variables, applies defaults,
    and validates required fields. Exits the process if the config is invalid.

    Args:
        config_path: Path to the config.yaml file.

    Returns:
        Fully resolved config dict ready for use by the service.
    """
    if not os.path.exists(config_path):
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    with open(config_path) as f:
        try:
            raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error("Failed to parse config file: %s", e)
            sys.exit(1)

    # Substitute environment variables (e.g., ${GEMINI_API_KEY})
    config = _substitute_env_vars(raw_config)

    # Apply defaults for any missing optional sections
    config = _apply_defaults(config)

    # Validate
    errors = validate_config(config)
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        sys.exit(1)

    logger.info("Configuration loaded from %s", config_path)
    logger.info("Monitored cameras: %s",
                [n for n, c in config["cameras"].items() if c.get("enabled", True)])

    return config


def load_config_or_none(config_path: str) -> dict | None:
    """Load and validate config without raising or calling sys.exit on failure.

    Identical to ``load_config`` but returns ``None`` instead of exiting the
    process when the config file is missing or invalid.  This is the right
    function to use in polling loops that wait for a config to be written (e.g.
    the first-run setup wizard flow).

    Unlike ``reload_config``, this function never raises — it swallows all
    errors and returns ``None`` so the caller can simply check truthiness.

    Args:
        config_path: Path to the config.yaml file.

    Returns:
        Fully resolved config dict ready for use by the service, or ``None``
        if the file is absent or unparseable.
    """
    if not os.path.exists(config_path):
        # File not yet written — normal during first-run setup.
        return None

    with open(config_path) as f:
        try:
            raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning("Config file exists but could not be parsed: %s", e)
            return None

    config = _substitute_env_vars(raw_config)
    config = _apply_defaults(config)

    errors = validate_config(config)
    if errors:
        for err in errors:
            logger.warning("Config validation error (will retry): %s", err)
        return None

    return config


def reload_config(config_path: str) -> dict:
    """Load and validate config without calling sys.exit on failure.

    Identical to ``load_config`` but raises ``ValueError`` instead of exiting
    the process so callers (e.g. the hot-reload watcher) can catch errors and
    keep the old config running rather than crashing the service.

    Args:
        config_path: Path to the config.yaml file.

    Returns:
        Fully resolved config dict ready for use by the service.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the YAML is unparseable or validation fails.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        try:
            raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse config YAML: {exc}") from exc

    config = _substitute_env_vars(raw_config)
    config = _apply_defaults(config)

    errors = validate_config(config)
    if errors:
        raise ValueError(
            "Config validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return config
