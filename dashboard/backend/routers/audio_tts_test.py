"""
audio_tts_test.py — TTS Provider Credential Testing Sub-Router

Handles POST /api/audio/test-tts-provider — validates cloud TTS provider
API credentials by making a lightweight authenticated request (e.g. listing
voices or fetching account info).  No audio is synthesized.

Used by the TTS settings page "Test API Access" button in the dashboard UI.

Supported providers: elevenlabs, openai, cartesia, kokoro.
"""

import logging
import time

import aiohttp
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from backend.routers._audio_utils import _resolve_cloud_tts_key
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.audio.tts_test")

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────


class TestTtsProviderRequest(BaseModel):
    """Request body for POST /api/audio/test-tts-provider."""

    provider: str = Field(
        description=(
            "Cloud TTS provider to test: 'elevenlabs', 'openai', or 'cartesia'. "
            "The provider name is case-insensitive."
        )
    )
    api_key: str | None = Field(
        default=None,
        description=(
            "API key to test.  If omitted the key is read from the saved config "
            "(tts.<provider>_api_key in config.yaml).  Pass this field explicitly "
            "to test a new key before saving it to config."
        ),
    )
    voice_id: str | None = Field(
        default=None,
        description=(
            "Optional voice identifier to validate.  Currently unused for the "
            "lightweight connectivity check but reserved for future expansion."
        ),
    )


class TestTtsProviderResult(BaseModel):
    """Result of a TTS provider API connectivity test."""

    ok: bool = Field(description="True if the API key is valid and the provider is reachable")
    message: str = Field(description="Human-readable result or error description")
    latency_ms: int = Field(description="Round-trip time to the provider's API in milliseconds")


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post(
    "/test-tts-provider",
    response_model=TestTtsProviderResult,
    summary="Test cloud TTS provider credentials",
    description=(
        "Validates API key access for a cloud TTS provider by making a lightweight "
        "authenticated request (e.g. listing voices or fetching account info). "
        "No audio is synthesized — this is purely a connectivity and auth check. "
        "Supported providers: elevenlabs, openai, cartesia, kokoro. "
        "If api_key is omitted, the key from tts.<provider>_api_key in config.yaml is used."
    ),
    status_code=status.HTTP_200_OK,
)
async def test_tts_provider(request: TestTtsProviderRequest) -> TestTtsProviderResult:
    """Test connectivity and authentication for a cloud TTS provider.

    Makes the lightest available authenticated API call for each provider:
    - ElevenLabs: GET /v1/user (returns subscription tier and character quota)
    - OpenAI: GET /v1/models (confirms Bearer token is accepted)
    - Cartesia: GET /voices (confirms X-API-Key header is accepted)

    The api_key field is optional: if omitted, the key is resolved from the
    saved config via ``_resolve_cloud_tts_key``, which handles ``${ENV_VAR}``
    token expansion and masked (``***``) values.  Pass api_key explicitly to
    test a new key before persisting it to config.

    Args:
        request: TestTtsProviderRequest with provider name and optional key.

    Returns:
        TestTtsProviderResult with ok, message, and latency_ms fields.
        Always returns HTTP 200 — the ``ok`` field indicates pass/fail so the
        frontend can display a consistent result regardless of auth outcome.
    """
    start = time.monotonic()
    provider = request.provider.lower()

    # Resolve the API key: prefer the explicit field, then fall back to config.
    # If the frontend sends a masked placeholder (e.g. "***MASKED***"), ignore
    # it and resolve from the raw config instead.
    api_key = request.api_key
    if not api_key or api_key.startswith("***"):
        key_name_map = {
            "elevenlabs": "elevenlabs_api_key",
            "openai": "openai_api_key",
            "cartesia": "cartesia_api_key",
        }
        key_name = key_name_map.get(provider)
        if key_name:
            api_key = await _resolve_cloud_tts_key(key_name)

    if not api_key:
        return TestTtsProviderResult(
            ok=False,
            message=f"No API key configured for {provider}. "
                    f"Set tts.{provider}_api_key in config.yaml or pass api_key in the request.",
            latency_ms=0,
        )

    try:
        if provider == "elevenlabs":
            # GET /v1/user returns subscription tier and character quota — a
            # lightweight call that confirms both auth and account status.
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.elevenlabs.io/v1/user",
                    headers={"xi-api-key": api_key},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    if resp.status == 401:
                        return TestTtsProviderResult(
                            ok=False,
                            message="Invalid ElevenLabs API key (401 Unauthorized).",
                            latency_ms=latency_ms,
                        )
                    if resp.status != 200:
                        return TestTtsProviderResult(
                            ok=False,
                            message=f"ElevenLabs API returned HTTP {resp.status}.",
                            latency_ms=latency_ms,
                        )
                    data = await resp.json()
                    subscription = data.get("subscription", {})
                    tier = subscription.get("tier", "unknown")
                    chars_used = subscription.get("character_count", 0)
                    chars_limit = subscription.get("character_limit", 0)
                    return TestTtsProviderResult(
                        ok=True,
                        message=(
                            f"Connected. Plan: {tier}. "
                            f"Characters: {chars_used:,}/{chars_limit:,} used."
                        ),
                        latency_ms=latency_ms,
                    )

        elif provider == "openai":
            # GET /v1/models confirms the Bearer token is accepted without
            # actually running an inference request.
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    if resp.status == 401:
                        return TestTtsProviderResult(
                            ok=False,
                            message="Invalid OpenAI API key (401 Unauthorized).",
                            latency_ms=latency_ms,
                        )
                    if resp.status != 200:
                        return TestTtsProviderResult(
                            ok=False,
                            message=f"OpenAI API returned HTTP {resp.status}.",
                            latency_ms=latency_ms,
                        )
                    return TestTtsProviderResult(
                        ok=True,
                        message="API key valid. OpenAI connected.",
                        latency_ms=latency_ms,
                    )

        elif provider == "cartesia":
            # GET /voices confirms the X-API-Key header is accepted without
            # triggering a billable synthesis call.
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.cartesia.ai/voices",
                    headers={
                        "X-API-Key": api_key,
                        "Cartesia-Version": "2024-06-10",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    if resp.status in (401, 403):
                        return TestTtsProviderResult(
                            ok=False,
                            message=f"Invalid Cartesia API key (HTTP {resp.status}).",
                            latency_ms=latency_ms,
                        )
                    if resp.status != 200:
                        return TestTtsProviderResult(
                            ok=False,
                            message=f"Cartesia API returned HTTP {resp.status}.",
                            latency_ms=latency_ms,
                        )
                    return TestTtsProviderResult(
                        ok=True,
                        message="API key valid. Cartesia connected.",
                        latency_ms=latency_ms,
                    )

        elif provider == "kokoro":
            # Ping the Kokoro server's health or voices endpoint to confirm
            # it is reachable and responding.
            raw_cfg = await config_service.get_raw_config()
            tts_cfg = raw_cfg.get("tts", {})
            kokoro_cfg = tts_cfg.get("kokoro", {})
            host = (
                request.api_key  # frontend sends the host URL in the api_key field
                or kokoro_cfg.get("host")
                or tts_cfg.get("kokoro_host")
                or "http://localhost:8880"
            )
            host = host.rstrip("/")
            async with aiohttp.ClientSession() as session:
                # Try /voices first (Kokoro native), fall back to /v1/audio/voices
                # (OpenAI-compatible wrapper) if not found.
                for endpoint in (f"{host}/voices", f"{host}/v1/audio/voices"):
                    async with session.get(
                        endpoint,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 404:
                            continue
                        latency_ms = int((time.monotonic() - start) * 1000)
                        if resp.status != 200:
                            return TestTtsProviderResult(
                                ok=False,
                                message=f"Kokoro server returned HTTP {resp.status}.",
                                latency_ms=latency_ms,
                            )
                        data = await resp.json()
                        # /voices returns {"voices": {"lang": [...]}}
                        # /v1/audio/voices returns a flat list
                        if isinstance(data, dict) and "voices" in data:
                            voice_count = sum(
                                len(v) for v in data["voices"].values()
                                if isinstance(v, list)
                            )
                        elif isinstance(data, list):
                            voice_count = len(data)
                        else:
                            voice_count = 0
                        return TestTtsProviderResult(
                            ok=True,
                            message=f"Kokoro server reachable. {voice_count} voices available.",
                            latency_ms=latency_ms,
                        )
                # Both endpoints returned 404
                latency_ms = int((time.monotonic() - start) * 1000)
                return TestTtsProviderResult(
                    ok=False,
                    message=f"Kokoro server at {host} responded but no voices endpoint found.",
                    latency_ms=latency_ms,
                )

        else:
            return TestTtsProviderResult(
                ok=False,
                message=(
                    f"Unknown provider: '{provider}'. "
                    "Supported values: elevenlabs, openai, cartesia, kokoro."
                ),
                latency_ms=0,
            )

    except aiohttp.ClientConnectorError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("test-tts-provider: network error for %s: %s", provider, exc)
        return TestTtsProviderResult(
            ok=False,
            message=f"Network error reaching {provider} API: {exc}",
            latency_ms=latency_ms,
        )
    except TimeoutError:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("test-tts-provider: timeout for %s", provider)
        return TestTtsProviderResult(
            ok=False,
            message=f"{provider} API did not respond within 10 seconds.",
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.exception("test-tts-provider: unexpected error for %s", provider)
        return TestTtsProviderResult(
            ok=False,
            message=str(exc),
            latency_ms=latency_ms,
        )
