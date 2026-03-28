"""providers/openai_compat.py — OpenAI-compatible provider for VoxWatch AI Vision.

Implements:
    _call_openai_compat(images, prompt, api_key, model, base_url, timeout) -> str

Works with OpenAI (gpt-4o, gpt-4-vision-preview, etc.), xAI Grok
(grok-2-vision, grok-vision-beta, etc.), and any third-party API that
implements the OpenAI chat completions format.

Does NOT use the openai SDK — raw aiohttp is used to keep the Docker image
small and avoid an extra transitive dependency.
"""

import base64
import logging

import aiohttp

from ..session import _get_session

logger = logging.getLogger("voxwatch.ai_vision")


async def _call_openai_compat(
    images: list[bytes],
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    timeout: int,
) -> str:
    """Call any OpenAI-compatible chat completions endpoint with vision images.

    Works with OpenAI (gpt-4o, gpt-4-vision-preview, etc.), xAI Grok
    (grok-2-vision, grok-vision-beta, etc.), and any third-party API that
    implements the OpenAI chat completions format.

    Images are encoded as base64 data URIs and supplied as ``image_url``
    content parts inside the user message.  The OpenAI vision format accepts
    multiple images in a single request so all captured frames are sent.

    Uses the module-level shared aiohttp session (see ``_get_session``).
    Does NOT use the openai SDK — raw aiohttp is used to keep the Docker
    image small and avoid an extra transitive dependency.

    Default base URLs:
      - OpenAI: ``https://api.openai.com/v1``
      - Grok:   ``https://api.x.ai/v1``
      - Custom: controlled by the caller via the ``base_url`` argument.

    Args:
        images: List of raw JPEG bytes to analyse.  All images are sent in
            a single API call as separate ``image_url`` content parts.
        prompt: Text instruction for the model.
        api_key: Bearer token (OpenAI API key or equivalent).
        model: Model identifier string (e.g. ``"gpt-4o"`` or
            ``"grok-vision-beta"``).
        base_url: Root URL of the API endpoint, without a trailing slash
            (e.g. ``"https://api.openai.com/v1"``).
        timeout: Request timeout in seconds.

    Returns:
        Model response text from ``choices[0].message.content``.

    Raises:
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds ``timeout`` seconds.
        ValueError: On HTTP 401 (invalid key), HTTP 404 (model not found),
            other non-200 status codes, or an empty/unparseable response.
    """
    # Build the list of content parts: one image_url entry per image.
    # The OpenAI vision spec uses data URIs: "data:image/jpeg;base64,<b64>".
    content_parts: list[dict] = []
    for idx, img_bytes in enumerate(images):
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        logger.debug(
            "OpenAI-compat: added image %d/%d to request (%d bytes)",
            idx + 1, len(images), len(img_bytes),
        )

    # Append the text instruction after all images.
    content_parts.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content_parts}],
        # max_tokens guards against runaway generation; the prompts request a
        # single short sentence so 150 tokens is more than sufficient.
        "max_tokens": 150,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    completions_url = f"{base_url.rstrip('/')}/chat/completions"
    http_timeout = aiohttp.ClientTimeout(total=timeout)

    logger.debug(
        "Calling OpenAI-compat endpoint %s with model %r (%d image(s))",
        completions_url, model, len(images),
    )

    session = await _get_session()
    try:
        async with session.post(
            completions_url, json=payload, headers=headers, timeout=http_timeout
        ) as resp:
            if resp.status == 401:
                raise ValueError(
                    f"OpenAI-compat: Authentication failed (HTTP 401) from "
                    f"{completions_url} — Invalid API key"
                )
            if resp.status == 403:
                raise ValueError(
                    f"OpenAI-compat: Authentication failed (HTTP 403) from "
                    f"{completions_url} — check your API key or account permissions"
                )
            if resp.status == 404:
                raise ValueError(
                    f"OpenAI-compat: HTTP 404 from {completions_url} — "
                    f"model {model!r} not found"
                )
            if resp.status == 429:
                raise ValueError(
                    f"OpenAI-compat: Rate limit exceeded (HTTP 429) from "
                    f"{completions_url} — too many requests or quota exhausted"
                )
            if resp.status != 200:
                body = await resp.text()
                raise ValueError(
                    f"OpenAI-compat: HTTP {resp.status} from {completions_url}: "
                    f"{body[:200]}"
                )
            data = await resp.json()
    except aiohttp.ClientConnectorError as exc:
        raise ValueError(
            f"OpenAI-compat: Connection refused or server unreachable at "
            f"{completions_url}: {exc}"
        ) from exc
    except TimeoutError as exc:
        raise ValueError(
            f"OpenAI-compat: Request timed out after {timeout}s for "
            f"{completions_url}"
        ) from exc

    # Navigate the standard OpenAI response structure.
    try:
        response_text: str = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"OpenAI-compat: could not parse response from {completions_url}: "
            f"{exc} — raw response: {str(data)[:200]}"
        ) from exc

    if not response_text:
        raise ValueError(
            f"OpenAI-compat: empty response from model {model!r} "
            f"at {completions_url}"
        )

    return response_text
