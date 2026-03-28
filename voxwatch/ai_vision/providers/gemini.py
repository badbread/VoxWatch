"""providers/gemini.py — Google Gemini provider for VoxWatch AI Vision.

Implements:
    _call_gemini_images(images, prompt, config) -> str
    _call_gemini_video(video_bytes, prompt, config) -> str

Both functions call the Gemini REST API directly via aiohttp — no
google-generativeai SDK required.  The API key is passed as a query parameter
per-request so there is no global SDK state and no threading lock needed.

Safety filters are disabled via ``safetySettings`` because security camera
descriptions of people (clothing, build, actions, posture) can trigger
false positives on harassment and dangerous-content categories.  This is a
private security system, not user-facing content generation.
"""

import asyncio
import base64
import logging

import aiohttp

from ..session import _get_session

logger = logging.getLogger("voxwatch.ai_vision")


async def _call_gemini_images(
    images: list[bytes],
    prompt: str,
    config: dict,
) -> str:
    """Call Google Gemini with one or more JPEG images via the REST API.

    Uses the Gemini ``generateContent`` REST endpoint directly via the shared
    aiohttp session.  No google-generativeai SDK is required — the API key is
    passed as a query parameter per-request, so there is no global SDK state
    and no threading lock needed.

    Safety filters are disabled via ``safetySettings`` because security camera
    descriptions of people (clothing, build, actions, posture) can trigger
    false positives on harassment and dangerous-content categories.  This is a
    private security system, not user-facing content generation.

    Args:
        images: List of raw JPEG bytes to analyse.  All images are sent in a
            single request as ``inline_data`` content parts.
        prompt: Text instruction for the model.
        config: Full VoxWatch config dict.  Reads ``config["ai"]["primary"]``
            for ``api_key``, ``model``, and ``timeout_seconds``.

    Returns:
        Model response text.

    Raises:
        ValueError: On HTTP 400 (bad request / invalid key) or non-200 status,
            empty candidate list, or empty response text.
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the request exceeds ``timeout_seconds``.
    """
    primary_cfg = config["ai"]["primary"]
    api_key: str = primary_cfg["api_key"]
    model_name: str = primary_cfg.get("model", "gemini-2.5-flash")
    timeout_seconds: int = primary_cfg.get("timeout_seconds", 5)

    # Build multimodal content parts: text prompt first, then one inline_data
    # entry per image.  Gemini accepts multiple images in a single request,
    # giving the model cross-frame context for appearance comparison.
    parts: list[dict] = [{"text": prompt}]
    for idx, img_bytes in enumerate(images):
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("ascii"),
            }
        })
        logger.debug(
            "Gemini images: added image %d/%d to request (%d bytes)",
            idx + 1, len(images), len(img_bytes),
        )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": parts}],
        # Disable all safety filters — security camera descriptions regularly
        # trigger harassment / dangerous-content false positives without these.
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.3,
        },
    }

    logger.debug(
        "Calling Gemini REST API with model %r (%d image(s))",
        model_name, len(images),
    )

    session = await _get_session()
    try:
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
        ) as resp:
            if resp.status == 400:
                body = await resp.json()
                error = body.get("error", {}).get("message", "Unknown error")
                raise ValueError(f"Gemini API error (400): {error}")
            if resp.status in (401, 403):
                raise ValueError(
                    f"Gemini: Authentication failed (HTTP {resp.status}) — "
                    "check your API key"
                )
            if resp.status == 429:
                raise ValueError(
                    "Gemini: Rate limit exceeded (HTTP 429) — too many requests "
                    "or quota exhausted"
                )
            if resp.status != 200:
                body_text = await resp.text()
                raise ValueError(
                    f"Gemini API returned HTTP {resp.status}: {body_text[:200]}"
                )
            data = await resp.json()
    except aiohttp.ClientConnectorError as exc:
        raise ValueError(
            f"Gemini: Server unreachable — connection refused or DNS failure: {exc}"
        ) from exc
    except TimeoutError as exc:
        raise ValueError(
            f"Gemini: Request timed out after {timeout_seconds}s"
        ) from exc

    # Extract the generated text from the response structure:
    #   {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates in response")

    response_parts = candidates[0].get("content", {}).get("parts", [])
    text = " ".join(p.get("text", "") for p in response_parts).strip()
    if not text:
        raise ValueError("Gemini returned an empty text response")

    return text


async def _call_gemini_video(
    video_bytes: bytes,
    prompt: str,
    config: dict,
) -> str:
    """Upload an MP4 video to the Gemini Files API and analyse it via REST.

    The Gemini Files API requires a three-step flow:

    1. Upload the video bytes via a multipart POST to the upload endpoint.
       The response contains a ``file.name`` (e.g. ``"files/abc123"``).
    2. Poll the file metadata endpoint until ``state`` becomes ``"ACTIVE"``.
       Gemini typically processes a short security-camera clip in 2–5 seconds.
    3. Call ``generateContent`` referencing the uploaded file via its URI.
    4. Delete the uploaded file to avoid accumulating storage on the account.

    All network calls use the shared aiohttp session and pass the API key as a
    query parameter — no google-generativeai SDK required.

    Safety filters are disabled for the same reason as ``_call_gemini_images``:
    security camera footage of people in motion regularly triggers false
    positives on harassment and dangerous-content categories.

    Args:
        video_bytes: Raw MP4 bytes from ``grab_video_clip``.
        prompt: Text instruction for the model (e.g. STAGE3_PROMPT).
        config: Full VoxWatch config dict.  Reads ``config["ai"]["primary"]``
            for ``api_key``, ``model``, and ``timeout_seconds``.

    Returns:
        Model response text.

    Raises:
        ValueError: On non-200 HTTP responses, upload failure, processing
            timeout, empty candidate list, or empty response text.
        aiohttp.ClientError: On network-level failures.
        asyncio.TimeoutError: If the overall operation exceeds the timeout.
    """
    primary_cfg = config["ai"]["primary"]
    api_key: str = primary_cfg["api_key"]
    model_name: str = primary_cfg.get("model", "gemini-2.5-flash")
    # Video analysis takes longer than image analysis — triple the base timeout
    # to allow for upload time + Gemini processing latency.
    timeout_seconds: int = primary_cfg.get("timeout_seconds", 5) * 3

    session = await _get_session()

    # ── Step 1: Upload the video to the Gemini Files API ──────────────────────
    # The upload endpoint accepts a multipart POST with the video bytes.
    # The Content-Type header must declare the MIME type of the file being
    # uploaded so Gemini can identify it as a video for processing.
    logger.debug(
        "Uploading %d-byte video to Gemini Files API (model=%r)",
        len(video_bytes), model_name,
    )

    upload_url = (
        f"https://generativelanguage.googleapis.com/upload/v1beta/files"
        f"?key={api_key}"
    )

    # Build a minimal multipart body with the video bytes.
    # FormData handles the boundary encoding automatically.
    upload_data = aiohttp.FormData()
    upload_data.add_field(
        name="file",
        value=video_bytes,
        content_type="video/mp4",
        filename="clip.mp4",
    )

    http_timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with session.post(upload_url, data=upload_data, timeout=http_timeout) as resp:
        if resp.status != 200:
            body_text = await resp.text()
            raise ValueError(
                f"Gemini Files API upload returned HTTP {resp.status}: "
                f"{body_text[:200]}"
            )
        upload_data_resp = await resp.json()

    # The upload response nests the file metadata under the "file" key.
    file_meta: dict = upload_data_resp.get("file", {})
    file_name: str = file_meta.get("name", "")
    file_uri: str = file_meta.get("uri", "")

    if not file_name or not file_uri:
        raise ValueError(
            f"Gemini Files API upload response missing file name or URI: "
            f"{upload_data_resp}"
        )

    logger.debug("Gemini file uploaded: name=%r uri=%r", file_name, file_uri)

    # ── Step 2: Poll until the file state becomes ACTIVE ──────────────────────
    # Gemini processes the video asynchronously.  The file transitions from
    # PROCESSING → ACTIVE once Gemini has ingested it.  We poll the metadata
    # endpoint with a 1-second sleep between checks; typical processing time
    # for a short clip is 2–5 seconds.
    status_url = (
        f"https://generativelanguage.googleapis.com/v1beta/{file_name}"
        f"?key={api_key}"
    )
    poll_timeout = aiohttp.ClientTimeout(total=10)

    for attempt in range(30):  # Max 30 × 1 s = 30 s
        async with session.get(status_url, timeout=poll_timeout) as resp:
            if resp.status != 200:
                body_text = await resp.text()
                raise ValueError(
                    f"Gemini file status check returned HTTP {resp.status}: "
                    f"{body_text[:200]}"
                )
            status_data = await resp.json()

        state: str = status_data.get("state", "")
        if state == "ACTIVE":
            logger.debug(
                "Gemini file %r is ACTIVE after %d poll(s)", file_name, attempt + 1
            )
            break
        if state == "FAILED":
            raise ValueError(
                f"Gemini file {file_name!r} processing failed (state=FAILED)"
            )
        # Still PROCESSING — wait 1 second before the next poll.
        await asyncio.sleep(1)
    else:
        raise TimeoutError(
            f"Gemini file {file_name!r} did not become ACTIVE within 30 seconds"
        )

    # ── Step 3: Call generateContent with the uploaded file reference ─────────
    generate_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    generate_payload = {
        "contents": [{
            "parts": [
                # Reference the uploaded file by its URI.
                {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                {"text": prompt},
            ]
        }],
        # Disable safety filters — same rationale as _call_gemini_images.
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.3,
        },
    }

    logger.debug("Calling Gemini generateContent for video file %r", file_name)

    async with session.post(
        generate_url, json=generate_payload, timeout=http_timeout
    ) as resp:
        if resp.status == 400:
            body = await resp.json()
            error = body.get("error", {}).get("message", "Unknown error")
            raise ValueError(f"Gemini generateContent error (400): {error}")
        if resp.status != 200:
            body_text = await resp.text()
            raise ValueError(
                f"Gemini generateContent returned HTTP {resp.status}: "
                f"{body_text[:200]}"
            )
        gen_data = await resp.json()

    # ── Step 4: Delete the uploaded file to free Gemini storage ──────────────
    # Gemini's Files API has a per-account storage limit.  Always clean up
    # after a successful (or failed) generateContent call.
    delete_url = (
        f"https://generativelanguage.googleapis.com/v1beta/{file_name}"
        f"?key={api_key}"
    )
    try:
        async with session.delete(
            delete_url, timeout=aiohttp.ClientTimeout(total=5)
        ) as del_resp:
            if del_resp.status not in (200, 204):
                logger.debug(
                    "Gemini file delete returned HTTP %d for %r",
                    del_resp.status, file_name,
                )
            else:
                logger.debug("Gemini file %r deleted", file_name)
    except Exception as cleanup_exc:
        # Non-fatal — log and continue.
        logger.debug(
            "Could not delete Gemini file %r: %s", file_name, cleanup_exc
        )

    # ── Extract and return the response text ──────────────────────────────────
    candidates = gen_data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini video analysis returned no candidates")

    response_parts = candidates[0].get("content", {}).get("parts", [])
    text = " ".join(p.get("text", "") for p in response_parts).strip()
    if not text:
        raise ValueError("Gemini video analysis returned an empty text response")

    return text
