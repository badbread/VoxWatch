"""
factory.py — TTS Provider Factory and Fallback Chain for VoxWatch

Central entry point for all TTS operations.  Reads ``config["tts"]["provider"]``
to pick the primary provider, constructs a fallback chain (ordered list of
providers to try if the primary fails), and exposes ``generate_with_fallback``
which tries each provider in sequence until one succeeds.

The espeak provider is always appended as the final fallback regardless of
what is in ``config["tts"]["fallback_chain"]``, because it has no external
dependencies and must always produce audio.

Provider name strings (used in config):
    "piper"       — Default local neural TTS (best quality / no cost)
    "kokoro"      — Recommended local ONNX neural TTS
    "elevenlabs"  — Premium cloud TTS (highest quality)
    "cartesia"    — Fastest cloud TTS
    "polly"       — Cheapest cloud TTS (AWS)
    "openai"      — Simple cloud TTS (OpenAI)
    "espeak"      — Last-resort local fallback (always works)

Config keys read from ``config["tts"]``:
    provider (str): Primary provider name (default: "piper").
    fallback_chain (list[str]): Ordered list of provider names to try
        after the primary fails.  espeak is always appended automatically.

Example config.yaml:
    tts:
      provider: piper
      fallback_chain: [kokoro, espeak]

Usage:
    from voxwatch.tts.factory import generate_with_fallback

    result = await generate_with_fallback(
        message="You are on camera.",
        output_path="/data/audio/stage1_tts.wav",
        config=config,
    )
    print(result.provider_name, result.duration_seconds)
"""

import logging

from voxwatch.tts.base import TTSProvider, TTSProviderError, TTSResult

logger = logging.getLogger("voxwatch.tts.factory")

# Canonical ordering of all provider names.
_ALL_PROVIDERS = ("piper", "kokoro", "elevenlabs", "cartesia", "polly", "openai", "espeak")


def _build_provider(name: str, config: dict) -> tuple[TTSProvider | None, str]:
    """Instantiate a single TTS provider by name, returning None on failure.

    Import errors and ``TTSProviderError`` raised during construction are
    caught here so the factory can silently skip unavailable providers
    without propagating exceptions to the caller.

    Args:
        name: Provider name string (e.g., "piper", "elevenlabs").
        config: Full VoxWatch config dict.

    Returns:
        A ``(provider, error_message)`` tuple.  On success the provider is
        an initialized ``TTSProvider`` instance and the error string is empty.
        On failure the provider is ``None`` and the error string describes why
        (e.g. "No API key found", "Unknown provider: xyz").
    """
    try:
        if name == "piper":
            from voxwatch.tts.providers.piper_provider import PiperProvider
            return PiperProvider(config), ""
        elif name == "kokoro":
            from voxwatch.tts.providers.kokoro_provider import KokoroProvider
            return KokoroProvider(config), ""
        elif name == "elevenlabs":
            from voxwatch.tts.providers.elevenlabs_provider import ElevenLabsProvider
            return ElevenLabsProvider(config), ""
        elif name == "cartesia":
            from voxwatch.tts.providers.cartesia_provider import CartesiaProvider
            return CartesiaProvider(config), ""
        elif name == "polly":
            from voxwatch.tts.providers.polly_provider import PollyProvider
            return PollyProvider(config), ""
        elif name == "openai":
            from voxwatch.tts.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(config), ""
        elif name == "espeak":
            from voxwatch.tts.providers.espeak_provider import EspeakProvider
            return EspeakProvider(config), ""
        else:
            logger.warning("Unknown TTS provider name: '%s' — skipping", name)
            return None, f"Unknown provider: {name}"
    except TTSProviderError as exc:
        logger.warning("Provider '%s' unavailable: %s", name, exc)
        return None, str(exc)
    except Exception as exc:
        logger.warning("Failed to instantiate provider '%s': %s", name, exc)
        return None, str(exc)


def get_provider(config: dict) -> TTSProvider:
    """Build and return the configured primary TTS provider.

    Reads ``config["tts"]["provider"]`` to determine which provider to
    instantiate.  Falls back to espeak if the configured provider is
    unavailable.

    Args:
        config: Full VoxWatch config dict.

    Returns:
        The primary TTSProvider instance.

    Raises:
        RuntimeError: If even espeak cannot be instantiated (should never
            happen in a correctly built Docker image).
    """
    tts_cfg = config.get("tts", {})
    # Accept both "provider" (core config) and "engine" (dashboard config) field names
    provider_name: str = tts_cfg.get("provider", tts_cfg.get("engine", "piper"))

    logger.info("Initializing primary TTS provider: %s", provider_name)
    provider, _err = _build_provider(provider_name, config)

    if provider is not None:
        return provider

    logger.warning(
        "Primary provider '%s' unavailable, falling back to espeak",
        provider_name,
    )
    fallback, _err = _build_provider("espeak", config)
    if fallback is None:
        raise RuntimeError(
            "Cannot instantiate any TTS provider — espeak-ng is not installed. "
            "The Docker image must include espeak-ng."
        )
    return fallback


def get_fallback_chain(config: dict) -> list[TTSProvider]:
    """Build the ordered list of fallback TTS providers.

    Reads ``config["tts"]["fallback_chain"]`` for the ordered provider
    names to try after the primary fails.  The espeak provider is always
    appended as the last entry regardless of what the config specifies,
    guaranteeing the chain always terminates with a provider that works.

    Duplicate names are deduplicated while preserving order.  Unavailable
    providers (missing binary, SDK, or key) are silently excluded.

    Args:
        config: Full VoxWatch config dict.

    Returns:
        Ordered list of available fallback TTSProvider instances.  The
        list is never empty because espeak is always appended.

    Raises:
        RuntimeError: If espeak is also unavailable (should never happen
            in a correctly built Docker image).
    """
    tts_cfg = config.get("tts", {})
    chain_names: list[str] = list(tts_cfg.get("fallback_chain", []))

    # Ensure espeak is always the final fallback — deduplicate first.
    deduped: list[str] = []
    seen: set[str] = set()
    for name in chain_names:
        if name != "espeak" and name not in seen:
            deduped.append(name)
            seen.add(name)
    deduped.append("espeak")

    providers: list[TTSProvider] = []
    for name in deduped:
        instance, _err = _build_provider(name, config)
        if instance is not None:
            providers.append(instance)
        else:
            logger.debug("Fallback provider '%s' excluded (unavailable)", name)

    if not providers:
        raise RuntimeError(
            "Fallback chain is empty — espeak-ng must be installed. "
            "The Docker image must include espeak-ng."
        )

    logger.info(
        "TTS fallback chain: %s",
        " -> ".join(p.name for p in providers),
    )
    return providers


async def generate_with_fallback(
    message: str,
    output_path: str,
    config: dict,
) -> TTSResult:
    """Generate speech using the primary provider with automatic fallback.

    Tries the configured primary provider first.  On failure, tries each
    provider in the fallback chain in order, logging the failure reason at
    each step.  The last provider in the chain is always espeak, which
    is guaranteed to succeed if the binary is present.

    This function constructs fresh provider instances on every call so
    that configuration changes are picked up without a service restart.
    For hot-path callers that need pre-warmed providers, use
    ``get_provider`` and ``get_fallback_chain`` directly.

    Args:
        message: Text to synthesize.  Should already be sanitized of
            control characters by the caller (see ``_sanitize_tts_input``
            in audio_pipeline.py).
        output_path: Absolute path where the output WAV file must be
            written.  The directory must already exist.
        config: Full VoxWatch config dict.

    Returns:
        TTSResult from whichever provider first succeeded.

    Raises:
        TTSProviderError: If every provider in the chain fails.  In
            practice this should never happen if espeak-ng is installed.
    """
    # Build primary provider.
    tts_cfg = config.get("tts", {})
    primary_name: str = tts_cfg.get("provider", "piper")
    primary, init_error = _build_provider(primary_name, config)

    # Tracks why the primary failed so fallback results can report it.
    primary_failure_reason: str = ""

    if primary is not None:
        try:
            result = await primary.generate(message, output_path)
            logger.debug("TTS generated by primary provider: %s", primary.name)
            return result
        except TTSProviderError as exc:
            primary_failure_reason = str(exc)
            logger.warning(
                "Primary TTS provider '%s' failed: %s — trying fallback chain",
                primary.name, exc,
            )
        except Exception as exc:
            primary_failure_reason = str(exc)
            logger.warning(
                "Primary TTS provider '%s' raised unexpected error: %s — trying fallback chain",
                primary_name, exc,
            )
    else:
        primary_failure_reason = init_error or f"Provider '{primary_name}' is not available"
        logger.warning(
            "Primary TTS provider '%s' is unavailable — trying fallback chain",
            primary_name,
        )

    # Try each provider in the fallback chain.
    chain = get_fallback_chain(config)
    last_error: TTSProviderError | None = None

    for provider in chain:
        # Skip the primary provider if it already appeared in the chain
        # to avoid calling a known-failed provider twice.
        if provider.name == primary_name:
            logger.debug("Skipping '%s' in fallback chain (already tried as primary)", provider.name)
            continue

        try:
            result = await provider.generate(message, output_path)
            logger.info("TTS fallback succeeded with provider: %s", provider.name)
            # Attach the primary failure reason so callers know why fallback was used.
            result.fallback_reason = primary_failure_reason
            return result
        except TTSProviderError as exc:
            logger.warning(
                "Fallback TTS provider '%s' failed: %s",
                provider.name, exc,
            )
            last_error = exc
        except Exception as exc:
            logger.warning(
                "Fallback TTS provider '%s' raised unexpected error: %s",
                provider.name, exc,
            )
            last_error = TTSProviderError(provider.name, str(exc))

    # All providers exhausted.
    raise TTSProviderError(
        "factory",
        f"All TTS providers failed. Last error: {last_error}",
    )
