"""providers/__init__.py — Provider registry and snapshot/video dispatch.

Exports:
    _dispatch_snapshot_call(images, prompt, provider, provider_cfg,
                            api_key, model, timeout) -> str

Routes snapshot and video calls to the correct provider implementation based
on the provider name string from config.  All provider functions are imported
here so callers only need to import from this package.
"""

import logging

from .anthropic import _call_anthropic
from .gemini import _call_gemini_images, _call_gemini_video
from .ollama import _call_ollama
from .openai_compat import _call_openai_compat

logger = logging.getLogger("voxwatch.ai_vision")

__all__ = [
    "_call_anthropic",
    "_call_gemini_images",
    "_call_gemini_video",
    "_call_ollama",
    "_call_openai_compat",
    "_dispatch_snapshot_call",
]


async def _dispatch_snapshot_call(
    images: list[bytes],
    prompt: str,
    provider: str,
    provider_cfg: dict,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    """Route a snapshot analysis call to the correct provider implementation.

    This is a pure dispatch helper — all error handling is done in the callers
    (``analyze_snapshots`` and ``analyze_video``).  Raises on any failure so
    the caller can log it and try the next provider.

    Args:
        images: List of raw JPEG bytes.
        prompt: Text instruction for the AI.
        provider: Provider name string (``gemini``, ``openai``, ``grok``,
            ``anthropic``, ``ollama``, ``custom``).
        provider_cfg: The raw config sub-dict for this provider (used to pull
            Gemini's full config and Ollama/custom host).
        api_key: Resolved API key string.
        model: Model identifier string.
        timeout: Request timeout in seconds.

    Returns:
        AI response text.

    Raises:
        ValueError: If ``provider`` is not recognised.
        Exception: Any network or API error from the underlying call.
    """
    if provider == "gemini":
        # _call_gemini_images reads the full config itself — pass a synthetic
        # config that preserves the structure it expects.
        synthetic_cfg = {"ai": {"primary": provider_cfg}}
        return await _call_gemini_images(images, prompt, synthetic_cfg)

    elif provider in ("openai", "grok"):
        base_url = (
            "https://api.openai.com/v1"
            if provider == "openai"
            else "https://api.x.ai/v1"
        )
        return await _call_openai_compat(images, prompt, api_key, model, base_url, timeout)

    elif provider == "anthropic":
        return await _call_anthropic(images, prompt, api_key, model, timeout)

    elif provider == "ollama":
        # Ollama handles only one image reliably — use the last (most recent) frame.
        best_image = images[-1]
        # _call_ollama reads fallback config by key — rebuild the expected shape.
        # When ollama is used as primary, we still need to pass the right section;
        # build a synthetic config that puts provider_cfg under "fallback" since
        # _call_ollama always reads from config["ai"]["fallback"].
        synthetic_cfg = {"ai": {"fallback": provider_cfg}}
        return await _call_ollama(best_image, prompt, synthetic_cfg)

    elif provider == "custom":
        host: str = provider_cfg.get("host", "http://localhost:8080/v1")
        return await _call_openai_compat(images, prompt, api_key, model, host, timeout)

    else:
        raise ValueError(f"Unknown AI provider: {provider!r}")
