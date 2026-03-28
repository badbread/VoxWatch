"""providers/anthropic.py — Anthropic Claude provider for VoxWatch AI Vision.

Implements:
    _call_anthropic(images, prompt, api_key, model, timeout) -> str

Uses the Anthropic ``/v1/messages`` endpoint directly via aiohttp rather
than the anthropic SDK, keeping the Docker image small.

Images are encoded as base64 and supplied as ``image`` content blocks of
type ``"base64"``.  Anthropic's vision models accept multiple images in a
single message, so all captured frames are sent together.

Supported models include ``claude-3-5-sonnet-20241022``,
``claude-3-5-haiku-20241022``, ``claude-3-opus-20240229``, etc.
"""

import base64
import logging

import aiohttp

from ..session import _get_session

logger = logging.getLogger("voxwatch.ai_vision")


async def _call_anthropic(
    images: list[bytes],
    prompt: str,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    """Call the Anthropic Messages API with one or more JPEG images.

    Uses the Anthropic ``/v1/messages`` endpoint directly via aiohttp rather
    than the anthropic SDK, keeping the Docker image small.

    Images are encoded as base64 and supplied as ``image`` content blocks of
    type ``"base64"``.  Anthropic's vision models accept multiple images in a
    single message, so all captured frames are sent together.

    Supported models include ``claude-3-5-sonnet-20241022``,
    ``claude-3-5-haiku-20241022``, ``claude-3-opus-20240229``, etc.

    Uses the module-level shared aiohttp session (see ``_get_session``).
    Does NOT use the anthropic SDK.

    Args:
        images: List of raw JPEG bytes to analyse.  All images are sent in
            a single API call as separate image content blocks.
        prompt: Text instruction for the model.
        api_key: Anthropic API key (starts with ``"sk-ant-"``).
        model: Anthropic model identifier string
            (e.g. ``"claude-3-5-haiku-20241022"``).
        timeout: Request timeout in seconds.

    Returns:
        Model response text from ``content[0].text``.

    Raises:
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds ``timeout`` seconds.
        ValueError: On HTTP 401 (invalid key), HTTP 404 (model not found),
            other non-200 status codes, or an empty/unparseable response.
    """
    # Build the list of content blocks: one image block per image, then text.
    # Anthropic's vision format uses a structured "source" object with base64 data.
    content_blocks: list[dict] = []
    for idx, img_bytes in enumerate(images):
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64,
            },
        })
        logger.debug(
            "Anthropic: added image %d/%d to request (%d bytes)",
            idx + 1, len(images), len(img_bytes),
        )

    # Append the text instruction after all images.
    content_blocks.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
        "max_tokens": 150,
        "messages": [{"role": "user", "content": content_blocks}],
    }

    headers = {
        "x-api-key": api_key,
        # anthropic-version is required; this value enables all current features.
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    messages_url = "https://api.anthropic.com/v1/messages"
    http_timeout = aiohttp.ClientTimeout(total=timeout)

    logger.debug(
        "Calling Anthropic API with model %r (%d image(s))",
        model, len(images),
    )

    session = await _get_session()
    try:
        async with session.post(
            messages_url, json=payload, headers=headers, timeout=http_timeout
        ) as resp:
            if resp.status == 401:
                raise ValueError(
                    "Anthropic: Authentication failed (HTTP 401) — Invalid API key"
                )
            if resp.status == 403:
                raise ValueError(
                    "Anthropic: Authentication failed (HTTP 403) — check your API key "
                    "or account permissions"
                )
            if resp.status == 404:
                raise ValueError(
                    f"Anthropic: HTTP 404 — model {model!r} not found"
                )
            if resp.status == 429:
                raise ValueError(
                    "Anthropic: Rate limit exceeded (HTTP 429) — too many requests "
                    "or quota exhausted"
                )
            if resp.status != 200:
                body = await resp.text()
                raise ValueError(
                    f"Anthropic: HTTP {resp.status}: {body[:200]}"
                )
            data = await resp.json()
    except aiohttp.ClientConnectorError as exc:
        raise ValueError(
            f"Anthropic: Connection refused or server unreachable at "
            f"{messages_url}: {exc}"
        ) from exc
    except TimeoutError as exc:
        raise ValueError(
            f"Anthropic: Request timed out after {timeout}s"
        ) from exc

    # Anthropic's response puts the text in content[0].text.
    try:
        response_text: str = data["content"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"Anthropic: could not parse response: {exc} — "
            f"raw response: {str(data)[:200]}"
        ) from exc

    if not response_text:
        raise ValueError(
            f"Anthropic: empty response from model {model!r}"
        )

    return response_text
