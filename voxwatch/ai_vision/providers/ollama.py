"""providers/ollama.py — Ollama local vision provider for VoxWatch AI Vision.

Implements:
    _call_ollama(image, prompt, config) -> str

Ollama exposes a REST API at POST /api/generate.  The image is sent as a
base64-encoded string in the ``images`` array.  Ollama/LLaVA handles one
image reliably; multi-image support is inconsistent so the caller always
passes exactly one image (the most recent frame).
"""

import base64
import logging

import aiohttp

from ..session import _get_session

logger = logging.getLogger("voxwatch.ai_vision")


async def _call_ollama(
    image: bytes,
    prompt: str,
    config: dict,
) -> str:
    """Call a local Ollama vision model with a single JPEG image.

    Ollama exposes a REST API at POST /api/generate.  We send the image as a
    base64-encoded string in the ``images`` array.  Ollama/LLaVA handles one
    image reliably; multi-image support is inconsistent so we always pass exactly
    one image.

    Uses the module-level shared aiohttp session (see ``_get_session``).

    Args:
        image: Raw JPEG bytes of the single image to analyse.
        prompt: Text instruction for the model.
        config: Full VoxWatch config dict.

    Returns:
        Model response text.

    Raises:
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds the configured timeout.
        ValueError: If the Ollama response cannot be parsed.
    """
    fallback_cfg = config.get("ai", {}).get("fallback", {})
    ollama_host: str = fallback_cfg.get("host", "http://localhost:11434")
    model_name: str = fallback_cfg.get("model", "llava:7b")
    timeout_seconds: int = fallback_cfg.get("timeout_seconds", 8)

    # Encode the image as base64 — Ollama's API requires a list of base64 strings.
    image_b64 = base64.b64encode(image).decode("utf-8")

    payload = {
        "model": model_name,
        "prompt": prompt,
        "images": [image_b64],  # List format required by Ollama REST API
        "stream": False,        # We want the full response in one JSON blob
    }

    generate_url = f"{ollama_host.rstrip('/')}/api/generate"
    http_timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    logger.debug("Calling Ollama at %s with model %s (%d-byte image)",
                 generate_url, model_name, len(image))

    session = await _get_session()
    try:
        async with session.post(generate_url, json=payload, timeout=http_timeout) as resp:
            if resp.status == 404:
                raise ValueError(
                    f"Ollama model {model_name!r} not found at {ollama_host} — "
                    f"run: ollama pull {model_name}"
                )
            if resp.status == 429:
                raise ValueError(
                    f"Ollama: Rate limit exceeded (HTTP 429) from {generate_url}"
                )
            if resp.status != 200:
                body = await resp.text()
                raise ValueError(
                    f"Ollama returned HTTP {resp.status}: {body[:200]}"
                )
            data = await resp.json()
    except aiohttp.ClientConnectorError as exc:
        raise ValueError(
            f"Ollama server at {ollama_host} is not reachable — is Ollama running? "
            f"({exc})"
        ) from exc
    except TimeoutError as exc:
        raise ValueError(
            f"Ollama: Request timed out after {timeout_seconds}s for model "
            f"{model_name!r} at {ollama_host}"
        ) from exc

    # Ollama's non-streaming response puts the full text in the "response" key.
    response_text: str = data.get("response", "").strip()
    if not response_text:
        raise ValueError(f"Ollama returned an empty response for model {model_name!r}")

    return response_text
