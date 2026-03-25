"""
system.py — System Information and Health API Router

Endpoints:
    GET /api/system/health    — Minimal health check for container probes
    GET /api/system/info      — Static system information
    GET /api/system/frigate   — Frigate NVR status probe
    GET /api/system/go2rtc    — go2rtc status probe

The /health endpoint is intentionally fast and dependency-free — it only
checks in-process state so container orchestrators can use it as a liveness
probe without causing cascading load on Frigate or go2rtc.

The /frigate and /go2rtc endpoints do live HTTP probes on each call. They
are intended for the system settings page, not for polling.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend import config as cfg_module
from backend.models.status_models import (
    FrigateStatus,
    Go2rtcStatus,
    HealthStatus,
    SystemInfo,
)
from backend.services import frigate_client as fc_module
from backend.services import go2rtc_client as g2rtc_module
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.system")

router = APIRouter(prefix="/system", tags=["System"])

# Record the dashboard startup time for uptime calculation
_STARTUP_TIME: float = time.monotonic()


@router.get(
    "/health",
    response_model=HealthStatus,
    summary="Health check",
    description=(
        "Fast in-process health check. Returns 200 with status='ok' when the "
        "dashboard backend is running and config.yaml is present. Does not probe "
        "Frigate or go2rtc. Use /api/system/frigate and /api/system/go2rtc for those."
    ),
)
async def health_check() -> HealthStatus:
    """Return a minimal health check response.

    This endpoint is designed to be called frequently by container health
    checks and load balancers. It only inspects in-process state — no
    outbound HTTP requests or file I/O beyond a path existence check.

    Returns:
        HealthStatus with overall status, uptime, and config_loaded flag.
    """
    uptime = time.monotonic() - _STARTUP_TIME
    config_ok = Path(cfg_module.VOXWATCH_CONFIG_PATH).exists()

    overall = "ok" if config_ok else "degraded"

    return HealthStatus(
        status=overall,
        dashboard_uptime_seconds=round(uptime, 1),
        config_loaded=config_ok,
    )


@router.get(
    "/info",
    response_model=SystemInfo,
    summary="Get system information",
    description=(
        "Returns static information about the host running VoxWatch: "
        "hostname, platform, Python version, and configured file paths."
    ),
)
async def get_system_info() -> SystemInfo:
    """Return static system information collected at startup.

    Returns:
        SystemInfo with hostname, platform, paths, and Python version.
    """
    return SystemInfo(
        hostname=cfg_module.SYSTEM_HOSTNAME,
        platform=cfg_module.SYSTEM_PLATFORM,
        python_version=cfg_module.PYTHON_VERSION,
        config_path=cfg_module.VOXWATCH_CONFIG_PATH,
        data_dir=cfg_module.DATA_DIR,
        events_file=cfg_module.EVENTS_FILE,
    )


@router.get(
    "/frigate",
    response_model=FrigateStatus,
    summary="Probe Frigate NVR",
    description=(
        "Makes a live HTTP request to the Frigate API to check reachability, "
        "version, and camera count. Response time reflects actual network latency "
        "to Frigate — expect up to 5 seconds on timeout."
    ),
)
async def get_frigate_status() -> FrigateStatus:
    """Probe the Frigate NVR API and return its status.

    Returns:
        FrigateStatus with reachable flag, version, camera count, and uptime.
    """
    if fc_module.frigate_client is None:
        return FrigateStatus(
            reachable=False,
            error="Frigate client not initialized. Check config.yaml frigate section.",
        )
    return await fc_module.frigate_client.probe_status()


@router.get(
    "/go2rtc",
    response_model=Go2rtcStatus,
    summary="Probe go2rtc relay",
    description=(
        "Makes a live HTTP request to the go2rtc API to check reachability, "
        "version, and stream count. Response time reflects actual network latency."
    ),
)
async def get_go2rtc_status() -> Go2rtcStatus:
    """Probe the go2rtc API and return its status.

    Returns:
        Go2rtcStatus with reachable flag, version, and stream count.
    """
    if g2rtc_module.go2rtc_client is None:
        return Go2rtcStatus(
            reachable=False,
            error="go2rtc client not initialized. Check config.yaml go2rtc section.",
        )
    return await g2rtc_module.go2rtc_client.probe_status()


# ── AI Provider Test ─────────────────────────────────────────────────────────


class AiTestRequest(BaseModel):
    """Request body for POST /api/system/test-ai."""

    provider: str = Field(description="AI provider to test (gemini, openai, anthropic, grok, ollama)")
    model: str = Field(description="Model name to test (e.g. gemini-2.0-flash)")
    api_key: Optional[str] = Field(default=None, description="API key (not needed for ollama)")
    host: Optional[str] = Field(default=None, description="Host URL for self-hosted providers")


class AiTestResponse(BaseModel):
    """Response from POST /api/system/test-ai."""

    success: bool = Field(description="Whether the AI provider responded successfully")
    provider: str = Field(description="Provider that was tested")
    model: str = Field(description="Model that was tested")
    message: str = Field(description="Human-readable result or error message")
    response_time_ms: Optional[int] = Field(default=None, description="Response time in milliseconds")


@router.post(
    "/test-ai",
    response_model=AiTestResponse,
    summary="Test AI provider connection",
    description=(
        "Sends a minimal test prompt to the specified AI provider to verify "
        "API key validity, model availability, and network connectivity."
    ),
)
async def test_ai_provider(request: AiTestRequest) -> AiTestResponse:
    """Test connectivity to an AI vision provider.

    Sends a trivial prompt ('Respond with OK') to verify the provider is
    reachable, the API key is valid, and the model exists.

    Args:
        request: Provider, model, API key, and optional host URL.

    Returns:
        AiTestResponse with success flag, response time, and error details.
    """
    start = time.monotonic()

    # Resolve the real API key when the dashboard sends a masked placeholder.
    # The dashboard masks secrets as '***MASKED***', and the raw config may
    # contain '${ENV_VAR}' tokens. We need to resolve both to the actual key.
    api_key = request.api_key
    if not api_key or api_key.startswith("***") or not api_key.strip():
        # Masked or empty — read from raw config and resolve env vars
        try:
            cfg = await config_service.get_raw_config()
            raw_key = None
            if request.provider == cfg.get("ai", {}).get("primary", {}).get("provider"):
                raw_key = cfg.get("ai", {}).get("primary", {}).get("api_key", "")
            elif request.provider == cfg.get("ai", {}).get("fallback", {}).get("provider"):
                raw_key = cfg.get("ai", {}).get("fallback", {}).get("api_key", "")

            if raw_key:
                # Resolve ${ENV_VAR} tokens to actual values
                import re
                env_pattern = re.compile(r"\$\{(\w+)\}")
                match = env_pattern.match(raw_key)
                if match:
                    import os
                    api_key = os.environ.get(match.group(1), "")
                    if not api_key:
                        return AiTestResponse(
                            success=False,
                            provider=request.provider,
                            model=request.model,
                            message=f"Environment variable {match.group(1)} is not set",
                        )
                else:
                    api_key = raw_key
        except Exception as exc:
            logger.warning("Could not resolve API key from config: %s", exc)

    try:
        if request.provider == "gemini":
            result = await _test_gemini(api_key or "", request.model)
        elif request.provider == "openai":
            result = await _test_openai(api_key or "", request.model)
        elif request.provider == "anthropic":
            result = await _test_anthropic(api_key or "", request.model)
        elif request.provider == "grok":
            result = await _test_openai_compat(api_key or "", request.model, "https://api.x.ai/v1")
        elif request.provider == "ollama":
            host = request.host or "http://localhost:11434"
            result = await _test_ollama(host, request.model)
        elif request.provider == "custom":
            host = request.host or "http://localhost:8080/v1"
            result = await _test_openai_compat(api_key or "", request.model, host)
        else:
            result = f"Unknown provider: {request.provider}"

        elapsed = int((time.monotonic() - start) * 1000)

        if result is None:
            return AiTestResponse(
                success=True,
                provider=request.provider,
                model=request.model,
                message=f"Connected successfully ({elapsed}ms)",
                response_time_ms=elapsed,
            )
        else:
            return AiTestResponse(
                success=False,
                provider=request.provider,
                model=request.model,
                message=result,
            )
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return AiTestResponse(
            success=False,
            provider=request.provider,
            model=request.model,
            message=f"Error: {exc}",
            response_time_ms=elapsed,
        )


async def _test_gemini(api_key: str, model: str) -> Optional[str]:
    """Test Gemini API. Returns None on success, error string on failure."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": "Respond with just the word OK"}]}]}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return None
            body = await resp.text()
            if resp.status == 400 and "API_KEY" in body:
                return "Invalid API key"
            if resp.status == 404:
                return f"Model '{model}' not found"
            return f"HTTP {resp.status}: {body[:200]}"


async def _test_openai(api_key: str, model: str) -> Optional[str]:
    """Test OpenAI API. Returns None on success, error string on failure."""
    return await _test_openai_compat(api_key, model, "https://api.openai.com/v1")


async def _test_anthropic(api_key: str, model: str) -> Optional[str]:
    """Test Anthropic API. Returns None on success, error string on failure."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "Respond with just OK"}],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return None
            body = await resp.text()
            if resp.status == 401:
                return "Invalid API key"
            if resp.status == 404:
                return f"Model '{model}' not found"
            return f"HTTP {resp.status}: {body[:200]}"


async def _test_openai_compat(api_key: str, model: str, base_url: str) -> Optional[str]:
    """Test OpenAI-compatible API (OpenAI, Grok, custom). Returns None on success."""
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "Respond with just OK"}],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return None
            body = await resp.text()
            if resp.status == 401:
                return "Invalid API key"
            if resp.status == 404:
                return f"Model '{model}' not found"
            return f"HTTP {resp.status}: {body[:200]}"


async def _test_ollama(host: str, model: str) -> Optional[str]:
    """Test Ollama API. Returns None on success, error string on failure."""
    url = f"{host}/api/tags"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return f"Ollama unreachable (HTTP {resp.status})"
                data = await resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if requested model is available (with or without :latest tag)
                model_base = model.split(":")[0]
                if any(model_base in m for m in models):
                    return None
                return f"Model '{model}' not found. Available: {', '.join(models[:5])}"
    except aiohttp.ClientError as exc:
        return f"Cannot reach Ollama at {host}: {exc}"


# ── TTS Provider Test ──────────────────────────────────────────────────────


class TtsTestRequest(BaseModel):
    """Request body for POST /api/system/test-tts."""

    engine: str = Field(description="TTS engine to test (kokoro, piper, espeak, elevenlabs, etc.)")
    text: Optional[str] = Field(default=None, description="Sample text to synthesize")
    config: dict = Field(default_factory=dict, description="Provider-specific config (API keys, voice, host, etc.)")


class TtsTestResponse(BaseModel):
    """Response from POST /api/system/test-tts."""

    success: bool = Field(description="Whether the TTS provider responded successfully")
    engine: str = Field(description="Engine that was tested")
    message: str = Field(description="Human-readable result or error message")
    synthesis_ms: Optional[int] = Field(default=None, description="Synthesis time in milliseconds")


@router.post(
    "/test-tts",
    response_model=TtsTestResponse,
    summary="Test TTS provider connection",
    description=(
        "Verifies that a TTS provider is reachable and can synthesize audio. "
        "For cloud providers, tests the API key. For local providers, checks binary availability."
    ),
)
async def test_tts_provider(request: TtsTestRequest) -> TtsTestResponse:
    """Test connectivity and functionality of a TTS provider.

    For cloud providers (elevenlabs, cartesia, polly, openai): verifies API key.
    For remote providers (kokoro): tests the HTTP server health endpoint.
    For local providers (piper, espeak): checks if the binary exists.

    Args:
        request: Engine name and provider-specific config.

    Returns:
        TtsTestResponse with success flag and timing.
    """
    start = time.monotonic()
    engine = request.engine
    cfg = request.config

    try:
        if engine == "kokoro":
            host = cfg.get("kokoro_host") or cfg.get("host") or "http://localhost:8880"
            result = await _test_kokoro_tts(str(host))

        elif engine == "elevenlabs":
            api_key = await _resolve_tts_key(cfg, "elevenlabs_api_key", "tts.elevenlabs_api_key")
            result = await _test_elevenlabs_tts(api_key)

        elif engine == "openai":
            api_key = await _resolve_tts_key(cfg, "openai_api_key", "tts.openai_api_key")
            result = await _test_openai_tts(api_key)

        elif engine == "cartesia":
            api_key = await _resolve_tts_key(cfg, "cartesia_api_key", "tts.cartesia_api_key")
            result = await _test_cartesia_tts(api_key)

        elif engine == "polly":
            result = "AWS Polly test: configure AWS credentials and test via the preview button"

        elif engine == "piper":
            result = await _test_local_binary("piper")

        elif engine == "espeak":
            result = await _test_local_binary("espeak-ng")

        else:
            result = f"Unknown TTS engine: {engine}"

        elapsed = int((time.monotonic() - start) * 1000)

        if result is None:
            return TtsTestResponse(
                success=True, engine=engine,
                message=f"Connected ({elapsed}ms)",
                synthesis_ms=elapsed,
            )
        return TtsTestResponse(success=False, engine=engine, message=result)

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return TtsTestResponse(
            success=False, engine=engine,
            message=f"Error: {exc}", synthesis_ms=elapsed,
        )


async def _resolve_tts_key(cfg: dict, cfg_key: str, config_path: str) -> str:
    """Resolve a TTS API key from the request config or the saved config file.

    Handles masked keys (***MASKED***) and ${ENV_VAR} tokens.

    Args:
        cfg: Request config dict.
        cfg_key: Key name in the request config.
        config_path: Dot-separated path in the VoxWatch config file.

    Returns:
        The resolved API key string.
    """
    import os
    import re

    key = str(cfg.get(cfg_key, "") or "")
    # Use the key directly if it's a real value (not masked or empty)
    if key and not key.startswith("***") and key != "None":
        return key

    # Resolve from saved config — try the specific path first,
    # then scan all TTS provider sections for a matching key
    try:
        raw_cfg = await config_service.get_raw_config()

        # Try the explicit config path
        parts = config_path.split(".")
        val = raw_cfg
        for p in parts:
            val = val.get(p, {}) if isinstance(val, dict) else ""
        if isinstance(val, str) and val:
            env_match = re.match(r"\$\{(\w+)\}", val)
            if env_match:
                resolved = os.environ.get(env_match.group(1), "")
                if resolved:
                    return resolved
            elif not val.startswith("***"):
                return val

        # Fallback: scan the TTS section for any api_key field
        tts_cfg = raw_cfg.get("tts", {})
        for section_name, section in tts_cfg.items():
            if isinstance(section, dict) and "api_key" in section:
                raw_key = section["api_key"]
                if isinstance(raw_key, str) and raw_key:
                    env_match = re.match(r"\$\{(\w+)\}", raw_key)
                    if env_match:
                        resolved = os.environ.get(env_match.group(1), "")
                        if resolved:
                            return resolved
                    elif not raw_key.startswith("***"):
                        return raw_key
    except Exception:
        pass
    return ""


async def _test_kokoro_tts(host: str) -> Optional[str]:
    """Test Kokoro TTS server health. Returns None on success."""
    url = f"{host.rstrip('/')}/health"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return None
                return f"Kokoro server returned HTTP {resp.status}"
    except aiohttp.ClientError as exc:
        return f"Cannot reach Kokoro at {host}: {exc}"


async def _test_elevenlabs_tts(api_key: str) -> Optional[str]:
    """Test ElevenLabs API key validity. Returns None on success."""
    if not api_key:
        return "No API key configured"
    url = "https://api.elevenlabs.io/v1/user"
    headers = {"xi-api-key": api_key}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return None
                if resp.status == 401:
                    return "Invalid API key"
                return f"ElevenLabs returned HTTP {resp.status}"
    except aiohttp.ClientError as exc:
        return f"Cannot reach ElevenLabs: {exc}"


async def _test_openai_tts(api_key: str) -> Optional[str]:
    """Test OpenAI API key for TTS access. Returns None on success."""
    if not api_key:
        return "No API key configured"
    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return None
                if resp.status == 401:
                    return "Invalid API key"
                return f"OpenAI returned HTTP {resp.status}"
    except aiohttp.ClientError as exc:
        return f"Cannot reach OpenAI: {exc}"


async def _test_cartesia_tts(api_key: str) -> Optional[str]:
    """Test Cartesia API key validity. Returns None on success."""
    if not api_key:
        return "No API key configured"
    url = "https://api.cartesia.ai/voices"
    headers = {"X-API-Key": api_key, "Cartesia-Version": "2024-06-10"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return None
                if resp.status in (401, 403):
                    return "Invalid API key"
                return f"Cartesia returned HTTP {resp.status}"
    except aiohttp.ClientError as exc:
        return f"Cannot reach Cartesia: {exc}"


async def _test_local_binary(name: str) -> Optional[str]:
    """Test if a local binary exists. Returns None if found."""
    import shutil
    if shutil.which(name):
        return None
    return f"{name} not installed in this container"
