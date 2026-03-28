"""preview_api.py — Lightweight HTTP API for audio preview generation.

Runs alongside the main VoxWatch MQTT service on a dedicated port (default
8892).  The dashboard proxies preview requests here so all audio generation
code — TTS, radio effects, dispatch composition — stays in one place and is
never duplicated.

Architecture::

    Browser → Dashboard (port 33344) → VoxWatch API (port 8892) → WAV response

Endpoints:
    POST /api/preview               — Generate a full audio preview using VoxWatch's actual
                                      TTS pipeline, response modes, and dispatch system.
                                      For dispatch modes the full experience is generated:
                                      channel intro → chatter → dispatch segments → officer.
                                      For all other modes, clean TTS is returned.
    POST /api/preview/generate-intro — Generate a dispatch channel intro from text using
                                      any configured TTS provider and optionally save it
                                      to /data/audio/dispatch_intro_cached.wav so it is
                                      reused by the dispatch pipeline automatically.
    GET  /api/health                — Simple health check ({"status": "ok", "version": ...}).

The server runs inside the same asyncio event loop as the main service so it
shares the AudioPipeline instance without any thread-safety concerns.  Every
generated preview is written to a temp file, read back, then deleted so the
serve directory is not polluted.

Non-fatal design:
    If the server fails to bind (port conflict, permissions), the failure is
    logged and the main service continues.  ``start()`` never raises; callers
    should check the return value of ``start()`` if they need to know whether
    the API is up.
"""

import contextlib
import json
import logging
import os
import tempfile
import time

from aiohttp import web

logger = logging.getLogger("voxwatch.preview_api")

# Service version — keep in sync with voxwatch_service.SERVICE_VERSION.
_VERSION = "0.2.0"

# Sample AI JSON used when generating dispatch previews.  These values produce
# a realistic 3-segment dispatch call that exercises the full pipeline.
_SAMPLE_DISPATCH_AI = json.dumps({
    "suspect_count": "one",
    "description": "male, dark hoodie, medium build, carrying a backpack",
    "location": "near the front entrance approaching from the driveway",
})

# Default preview message for non-dispatch modes when the caller sends no
# custom message.  Realistic enough to give a useful impression of the voice.
_DEFAULT_PREVIEW_MESSAGE = (
    "Attention — this property is under active surveillance. "
    "You have been identified on camera. Please leave the area immediately."
)


class PreviewAPI:
    """Small aiohttp HTTP server that generates audio previews on demand.

    The server reuses the live ``AudioPipeline`` instance so previews are
    synthesised with the exact same TTS provider, voices, and radio effects
    that are used during real detection events.

    Lifecycle:
        1. Construct with the running ``AudioPipeline`` and the current config.
        2. Await ``start(port)`` after the audio pipeline is initialised.
        3. Call ``update_config(new_config)`` on every hot-reload so previews
           always reflect the current dispatch address, agency, etc.
        4. Await ``stop()`` during graceful shutdown to release the port.

    Attributes:
        _audio: The shared ``AudioPipeline`` instance.
        _config: Current VoxWatch config dict (updated via ``update_config``).
        _app: The aiohttp ``web.Application`` instance.
        _runner: ``web.AppRunner`` created in ``start()``.
    """

    def __init__(self, audio_pipeline, config: dict) -> None:
        """Initialise the preview API.

        Args:
            audio_pipeline: Live ``AudioPipeline`` instance from the main
                service.  Used for TTS generation, audio conversion, and the
                radio effect.  Must already be initialised (``initialize()``
                called) before any preview requests arrive.
            config: The full VoxWatch config dict.  A reference is kept so
                that ``update_config`` can swap it atomically on hot-reload.
        """
        self._audio = audio_pipeline
        self._config = config

        self._app = web.Application()
        self._app.router.add_post("/api/preview", self._handle_preview)
        self._app.router.add_post("/api/preview/generate-intro", self._handle_generate_intro)
        self._app.router.add_post("/api/announce", self._handle_announce)
        self._app.router.add_get("/api/health", self._handle_health)
        self._app.router.add_delete("/api/piper-voices/{model_name}", self._handle_delete_piper_voice)

        self._runner: web.AppRunner | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, port: int = 8892) -> bool:
        """Bind the HTTP server and begin accepting requests.

        Binds to ``127.0.0.1`` so only the local host can reach it.  Both
        method is non-fatal: any ``OSError`` (port conflict, permission denied)
        is caught, logged, and ``False`` is returned so the main service can
        continue without the preview API.

        Args:
            port: TCP port to listen on.  Default 8892.

        Returns:
            ``True`` if the server bound and started successfully.
            ``False`` if startup failed (port conflict, etc.).
        """
        try:
            self._runner = web.AppRunner(self._app, access_log=None)
            await self._runner.setup()
            site = web.TCPSite(self._runner, "127.0.0.1", port)
            await site.start()
            logger.info("Preview API listening on 127.0.0.1:%d", port)
            return True
        except OSError as exc:
            logger.error(
                "Preview API failed to start on port %d: %s — "
                "preview functionality will be unavailable.",
                port,
                exc,
            )
            # Clean up the runner so stop() is a no-op.
            if self._runner:
                with contextlib.suppress(Exception):
                    await self._runner.cleanup()
                self._runner = None
            return False
        except Exception as exc:
            logger.error(
                "Preview API unexpected startup error: %s — "
                "preview functionality will be unavailable.",
                exc,
            )
            self._runner = None
            return False

    async def stop(self) -> None:
        """Release the server port and shut down the aiohttp runner.

        Safe to call even if ``start()`` failed or was never called.
        """
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            logger.info("Preview API stopped.")

    def update_config(self, config: dict) -> None:
        """Swap the config dict used for subsequent preview requests.

        Called by ``VoxWatchService._reload_config()`` after each hot-reload
        so previews always reflect the current dispatch address, agency,
        callsign, and TTS settings.

        Args:
            config: New VoxWatch config dict (already validated).
        """
        self._config = config
        logger.debug("Preview API config updated.")

    # ── Route handlers ────────────────────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /api/health — Return service health and version.

        Args:
            request: Incoming aiohttp request (body is not read).

        Returns:
            JSON response ``{"status": "ok", "version": "<version>"}``.
        """
        return web.json_response({"status": "ok", "version": _VERSION})

    async def _handle_preview(self, request: web.Request) -> web.Response:
        """POST /api/preview — Generate and return an audio preview as WAV.

        Reads a JSON body with the following optional fields:

        .. code-block:: json

            {
                "response_mode": "police_dispatch",
                "message": "optional custom text",
                "voice": "am_fenrir",
                "provider": "kokoro",
                "speed": 1.0
            }

        When ``response_mode`` names a dispatch mode the full dispatch
        sequence is generated (channel intro + chatter + dispatch segments +
        officer response).  For all other modes, clean TTS is returned.

        The ``voice``, ``provider``, and ``speed`` fields are applied to the
        active TTS config before generating so the preview reflects any
        pending changes the user has made in the UI but not yet saved.

        Args:
            request: Incoming aiohttp POST request with a JSON body.

        Returns:
            Raw WAV ``web.Response`` with ``Content-Type: audio/wav`` and
            ``X-Generation-Time-Ms`` header on success, or a JSON error
            response with status 400/500 on failure.
        """
        try:
            body: dict = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Request body must be valid JSON."},
                status=400,
            )

        response_mode: str = str(body.get("response_mode", "standard")).strip()
        custom_message: str = str(body.get("message", "")).strip()

        # Optional TTS overrides from the UI (voice / provider / speed).
        # We apply these to a shallow copy of the config so the live pipeline
        # is not mutated.  The TTS factory reads these keys at call time.
        tts_override: dict = {}
        if "voice" in body:
            tts_override["voice"] = str(body["voice"]).strip()
        if "provider" in body:
            tts_override["provider"] = str(body["provider"]).strip()
        if "speed" in body:
            with contextlib.suppress(TypeError, ValueError):
                tts_override["speed"] = float(body["speed"])

        # Build a config snapshot that includes any TTS overrides.
        preview_config = self._build_preview_config(tts_override)

        start_ts = time.monotonic()

        # Dispatch modes go through the full compose_dispatch_audio path.
        from voxwatch.radio_dispatch import DISPATCH_MODES

        if response_mode in DISPATCH_MODES:
            wav_path = await self._generate_dispatch_preview(
                preview_config, response_mode, custom_message
            )
        else:
            wav_path = await self._generate_tts_preview(
                preview_config, response_mode, custom_message
            )

        if not wav_path or not os.path.exists(wav_path):
            return web.json_response(
                {"error": "Preview generation failed. Check VoxWatch logs for details."},
                status=500,
            )

        elapsed_ms = int((time.monotonic() - start_ts) * 1000)

        # Determine which provider was actually used — may differ from what
        # was requested if the pipeline fell back (e.g. ElevenLabs → espeak).
        configured_provider = tts_override.get(
            "provider",
            preview_config.get("tts", {}).get("provider", "piper"),
        )
        actual_provider = configured_provider
        used_fallback = "false"
        fallback_reason = ""

        # The pipeline sets _last_fallback_reason when the primary provider
        # failed and a fallback succeeded.  This is the authoritative signal
        # for fallback detection — do NOT compare against _tts_provider.name
        # because that reflects the service's warmed-up provider, not the
        # preview's temporary provider override.
        if hasattr(self._audio, "_last_fallback_reason"):
            fallback_reason = self._audio._last_fallback_reason or ""
        if fallback_reason:
            used_fallback = "true"
            # Extract the actual provider name from the result if available.
            # The fallback chain's last successful provider wrote the file.
            # We can infer it from the fallback_chain config.
            chain = preview_config.get("tts", {}).get("fallback_chain", ["piper"])
            if chain:
                # The first chain entry that isn't the configured provider
                # is likely what succeeded.
                for name in chain:
                    if name != configured_provider:
                        actual_provider = name
                        break

        try:
            with open(wav_path, "rb") as fh:
                wav_bytes = fh.read()
        except OSError as exc:
            logger.error("Preview API: could not read output WAV: %s", exc)
            return web.json_response(
                {"error": "Could not read generated audio file."},
                status=500,
            )
        finally:
            # Always delete the temp file — callers never reuse it.
            with contextlib.suppress(OSError):
                os.unlink(wav_path)

        logger.info(
            "Preview generated: mode=%s provider=%s elapsed_ms=%d bytes=%d",
            response_mode,
            actual_provider,
            elapsed_ms,
            len(wav_bytes),
        )

        headers = {
            "X-Generation-Time-Ms": str(elapsed_ms),
            "X-TTS-Provider": actual_provider,
            "X-TTS-Configured": configured_provider,
            "X-TTS-Fallback": used_fallback,
        }
        if fallback_reason:
            # Sanitize: HTTP headers cannot contain newlines or carriage returns.
            safe_reason = fallback_reason.replace("\n", " ").replace("\r", "")
            headers["X-TTS-Fallback-Reason"] = safe_reason[:500]

        return web.Response(
            body=wav_bytes,
            content_type="audio/wav",
            headers=headers,
        )

    async def _handle_generate_intro(self, request: web.Request) -> web.Response:
        """POST /api/preview/generate-intro — Generate a dispatch channel intro WAV.

        Synthesises a custom dispatch intro phrase using the requested TTS
        provider/voice, streams the resulting WAV back to the caller for
        in-browser playback, and optionally persists it to
        ``/data/audio/dispatch_intro_cached.wav`` so the live dispatch
        pipeline reuses it automatically on the next detection event (Priority
        2 in ``generate_channel_intro``).

        Request body (JSON):

        .. code-block:: json

            {
                "text":     "Connecting to County Sheriff dispatch frequency.",
                "provider": "elevenlabs",
                "voice":    "pNInz6obpgDQGcFmaJgB",
                "speed":    1.0,
                "save":     true
            }

        ``text`` — the phrase to synthesise.  Supports the ``{agency}``
            template token which is substituted with the configured agency
            name from the current config.  Required.

        ``provider`` — TTS provider to use: ``"kokoro"``, ``"elevenlabs"``,
            ``"openai"``, ``"cartesia"``, ``"piper"``, ``"espeak"``.
            Defaults to the currently configured provider when omitted.

        ``voice`` — provider-specific voice identifier.  Defaults to the
            provider's currently configured voice when omitted.

        ``speed`` — speed multiplier (float, default 1.0).

        ``save`` — when ``true``, the generated audio is also written to
            ``/data/audio/dispatch_intro_cached.wav`` so it persists across
            requests and is used automatically by the dispatch pipeline.
            Defaults to ``false``.

        Response:
            Raw WAV bytes with ``Content-Type: audio/wav`` on success.  The
            ``X-Generation-Time-Ms`` header reports synthesis latency.  On
            failure a JSON error response is returned.

        Args:
            request: Incoming aiohttp POST request with JSON body.

        Returns:
            ``web.Response`` with WAV body on success or JSON error on
            failure.
        """
        try:
            body: dict = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Request body must be valid JSON."},
                status=400,
            )

        text: str = str(body.get("text", "")).strip()
        if not text:
            return web.json_response(
                {"error": "\"text\" field is required and must be non-empty."},
                status=400,
            )

        # Substitute {agency} token using the live config.
        dispatch_cfg: dict = (
            self._config.get("response_mode", self._config.get("persona", {}))
            .get("dispatch", {})
        )
        agency: str = dispatch_cfg.get("agency", "").strip()
        try:
            text = text.format(agency=agency)
        except (KeyError, ValueError):
            pass  # Malformed template — use verbatim.

        # TTS overrides from the request body.
        tts_override: dict = {}
        if "provider" in body:
            tts_override["provider"] = str(body["provider"]).strip()
        if "voice" in body:
            tts_override["voice"] = str(body["voice"]).strip()
        if "speed" in body:
            with contextlib.suppress(TypeError, ValueError):
                tts_override["speed"] = float(body["speed"])

        save: bool = bool(body.get("save", False))

        preview_config = self._build_preview_config(tts_override)

        start_ts = time.monotonic()

        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".wav", prefix="voxwatch_intro_gen_"
            )
            os.close(fd)
        except OSError as exc:
            logger.error("generate-intro: could not create temp file: %s", exc)
            return web.json_response(
                {"error": "Server error: could not create temp file."},
                status=500,
            )

        # Swap config so generate_tts picks up any voice/provider overrides.
        original_config = self._audio.config
        try:
            self._audio.config = preview_config
            success = await self._audio.generate_tts(text, tmp_path)
        finally:
            self._audio.config = original_config

        if not success or not os.path.exists(tmp_path):
            logger.error("generate-intro: TTS generation failed for text: %s", text[:80])
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            return web.json_response(
                {"error": "TTS generation failed. Check VoxWatch logs for details."},
                status=500,
            )

        # Optionally persist to the cached intro path for live pipeline reuse.
        if save:
            cached_intro_dir = "/data/audio"
            cached_intro_path = "/data/audio/dispatch_intro_cached.wav"
            try:
                os.makedirs(cached_intro_dir, exist_ok=True)
                import shutil as _shutil
                _shutil.copy2(tmp_path, cached_intro_path)
                logger.info(
                    "generate-intro: saved to %s (%d bytes)",
                    cached_intro_path,
                    os.path.getsize(cached_intro_path),
                )
            except OSError as exc:
                logger.warning(
                    "generate-intro: could not save cached intro to %s: %s "
                    "— preview still returned.",
                    cached_intro_path,
                    exc,
                )

        elapsed_ms = int((time.monotonic() - start_ts) * 1000)

        try:
            with open(tmp_path, "rb") as fh:
                wav_bytes = fh.read()
        except OSError as exc:
            logger.error("generate-intro: could not read output WAV: %s", exc)
            return web.json_response(
                {"error": "Could not read generated audio file."},
                status=500,
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

        logger.info(
            "generate-intro: synthesised %d bytes in %d ms (save=%s)",
            len(wav_bytes),
            elapsed_ms,
            save,
        )

        return web.Response(
            body=wav_bytes,
            content_type="audio/wav",
            headers={
                "X-Generation-Time-Ms": str(elapsed_ms),
                "X-Intro-Saved": "true" if save else "false",
            },
        )

    # ── Announce endpoint ──────────────────────────────────────────────────────

    async def _handle_announce(self, request: web.Request) -> web.Response:
        """POST /api/announce — Synthesise TTS and push audio to a camera speaker.

        Designed for Home Assistant automations and external integrations.
        Unlike the test endpoint, this does real TTS synthesis with the full
        pipeline (generate → convert → optional tone → push via go2rtc).

        Request body (JSON):

        .. code-block:: json

            {
                "camera": "front_door",
                "message": "Package delivered at front door",
                "voice": "af_heart",
                "provider": "kokoro",
                "speed": 1.0,
                "tone": "none",
                "cache_key": "pkg_delivered"
            }

        ``camera`` — Target camera name (required). Must match a go2rtc stream.

        ``message`` — Text to synthesise and play (required, max 1000 chars).

        ``voice`` — TTS voice override. Uses configured default when omitted.

        ``provider`` — TTS provider override. Uses configured default when omitted.

        ``speed`` — Speed multiplier (0.25–4.0, default 1.0).

        ``tone`` — Attention tone to prepend: ``"short"``, ``"long"``,
            ``"siren"``, or ``"none"`` (default ``"none"``).

        ``cache_key`` — Optional. When provided, the generated audio is cached
            under this key and reused on subsequent requests with the same key,
            skipping TTS generation entirely. Useful for HA automations that
            play the same message repeatedly (e.g. "goodnight", "doorbell").
            Clear cache by sending a request with ``"cache_clear": true``.

        Returns:
            JSON ``{"success": true, "camera": "...", "duration_ms": 1234}``
            on success, or a JSON error response on failure.

        Args:
            request: Incoming aiohttp POST request with JSON body.
        """
        try:
            body: dict = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Request body must be valid JSON."},
                status=400,
            )

        camera: str = str(body.get("camera", "")).strip()
        message: str = str(body.get("message", "")).strip()

        if not camera:
            return web.json_response(
                {"error": "\"camera\" field is required."},
                status=400,
            )

        # Validate camera name — same pattern as the dashboard test endpoint.
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", camera):
            return web.json_response(
                {"error": f"Invalid camera name {camera!r}. Only letters, digits, underscores, hyphens allowed."},
                status=400,
            )

        if not message:
            return web.json_response(
                {"error": "\"message\" field is required and must be non-empty."},
                status=400,
            )

        if len(message) > 1000:
            return web.json_response(
                {"error": f"Message too long ({len(message)} chars, max 1000)."},
                status=400,
            )

        # Optional TTS overrides.
        tts_override: dict = {}
        if "voice" in body:
            tts_override["voice"] = str(body["voice"]).strip()
        if "provider" in body:
            tts_override["provider"] = str(body["provider"]).strip()
        if "speed" in body:
            with contextlib.suppress(TypeError, ValueError):
                tts_override["speed"] = float(body["speed"])

        tone: str = str(body.get("tone", "none")).strip()
        if tone not in ("short", "long", "siren", "none"):
            tone = "none"

        announce_config = self._build_preview_config(tts_override)
        start_ts = time.monotonic()

        logger.info("Announce: camera=%s message_len=%d tone=%s", camera, len(message), tone)

        # Step 1: Generate TTS to a temp file.
        try:
            fd, tts_path = tempfile.mkstemp(suffix=".wav", prefix="voxwatch_announce_tts_")
            os.close(fd)
        except OSError as exc:
            logger.error("Announce: could not create temp file: %s", exc)
            return web.json_response(
                {"error": "Server error: could not create temp file."},
                status=500,
            )

        original_config = self._audio.config
        try:
            self._audio.config = announce_config
            tts_ok = await self._audio.generate_tts(message, tts_path)
        finally:
            self._audio.config = original_config

        if not tts_ok or not os.path.exists(tts_path):
            with contextlib.suppress(OSError):
                os.unlink(tts_path)
            logger.error("Announce: TTS generation failed for camera=%s", camera)
            return web.json_response(
                {"error": "TTS generation failed. Check VoxWatch logs."},
                status=500,
            )

        # Step 2: Convert to camera-compatible codec.
        try:
            fd2, output_path = tempfile.mkstemp(suffix=".wav", prefix="voxwatch_announce_out_")
            os.close(fd2)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tts_path)
            return web.json_response(
                {"error": "Server error: could not create temp file."},
                status=500,
            )

        convert_ok = await self._audio.convert_audio(tts_path, output_path)
        # Clean up TTS intermediate file.
        with contextlib.suppress(OSError):
            os.unlink(tts_path)

        if not convert_ok:
            with contextlib.suppress(OSError):
                os.unlink(output_path)
            logger.error("Announce: audio conversion failed for camera=%s", camera)
            return web.json_response(
                {"error": "Audio conversion failed."},
                status=500,
            )

        # Step 3: Optionally prepend attention tone.
        audio_to_push = output_path
        toned_path = None
        if tone != "none":
            toned = await self._audio.prepend_tone(output_path, tone)
            if toned != output_path:
                toned_path = toned
                audio_to_push = toned

        # Step 4: Copy to serve directory so go2rtc can fetch it via HTTP.
        import shutil
        serve_filename = f"announce_{camera}_{int(time.time())}.wav"
        serve_path = os.path.join(self._audio._serve_dir, serve_filename)
        try:
            shutil.copy2(audio_to_push, serve_path)
        except OSError as exc:
            logger.error("Announce: could not copy to serve dir: %s", exc)
            for p in [output_path, toned_path]:
                if p:
                    with contextlib.suppress(OSError):
                        os.unlink(p)
            return web.json_response(
                {"error": "Could not prepare audio for delivery."},
                status=500,
            )

        # Clean up temp files.
        for p in [output_path, toned_path]:
            if p:
                with contextlib.suppress(OSError):
                    os.unlink(p)

        # Step 5: Warmup backchannel + push.
        await self._audio.warmup_backchannel(camera)
        push_ok = await self._audio.push_audio(camera, serve_path)

        # Clean up the served file after a delay (go2rtc needs time to fetch it).
        async def _deferred_cleanup():
            import asyncio
            await asyncio.sleep(30)
            with contextlib.suppress(OSError):
                os.unlink(serve_path)

        import asyncio
        asyncio.create_task(_deferred_cleanup())

        elapsed_ms = int((time.monotonic() - start_ts) * 1000)

        if push_ok:
            logger.info("Announce: success camera=%s elapsed_ms=%d", camera, elapsed_ms)
            return web.json_response({
                "success": True,
                "camera": camera,
                "duration_ms": elapsed_ms,
            })
        else:
            logger.error("Announce: push failed for camera=%s", camera)
            return web.json_response(
                {"success": False, "camera": camera, "error": "Audio push to go2rtc failed."},
                status=502,
            )

    # ── Preview generators ────────────────────────────────────────────────────

    async def _generate_dispatch_preview(
        self,
        config: dict,
        response_mode: str,
        custom_message: str,
    ) -> str | None:
        """Generate the full dispatch audio sequence and return the WAV path.

        Calls the same ``segment_dispatch_message`` → ``compose_dispatch_audio``
        pipeline used during live detection events.  The generated segments use
        sample AI JSON so the preview demonstrates a realistic 3-segment
        dispatch call with the configured address, agency, and callsign.

        Steps performed:
          1. Build sample AI JSON describing a generic intruder.
          2. Call ``segment_dispatch_message(ai_json, "stage2", config)`` to
             produce the ordered list of dispatch phrases.
          3. Call ``compose_dispatch_audio(segments, output_path, audio_pipeline,
             config, "preview")`` which handles channel intro generation,
             per-segment TTS + radio effect, squelch pauses, and officer
             response — identical to the live pipeline.
          4. Return the path to the final WAV, or ``None`` on failure.

        Args:
            config: Preview config snapshot (may contain TTS overrides).
            response_mode: Active dispatch mode name (e.g. "police_dispatch").
            custom_message: Caller-supplied text.  When non-empty, used as a
                single dispatch segment instead of the sample AI JSON so the
                user can hear their exact wording through the radio effect.

        Returns:
            Absolute path to the composed WAV file, or ``None`` if composition
            failed.  The caller is responsible for deleting the file.
        """
        from voxwatch.radio_dispatch import (
            compose_dispatch_audio,
            segment_dispatch_message,
        )

        # Always use the sample AI JSON for dispatch previews.  The frontend
        # sends the persona example text as custom_message, but that text is a
        # display-only sentence — not structured AI JSON.  Stuffing it into the
        # description field produced nonsensical dispatch output ("Suspect
        # described as... All units, 10-97 at...").  The sample JSON gives a
        # realistic 3-segment dispatch with proper suspect description.
        ai_json = _SAMPLE_DISPATCH_AI

        segments = segment_dispatch_message(ai_json, stage="stage2", config=config)
        if not segments:
            logger.error("Preview API: segment_dispatch_message returned empty list")
            return None

        logger.debug(
            "Preview API: dispatch preview — %d segment(s) for mode '%s'",
            len(segments),
            response_mode,
        )

        # Write to a named temp file so compose_dispatch_audio has a stable path.
        # We do not use TemporaryDirectory here because compose_dispatch_audio
        # manages its own internal temp files; we only need the final output path.
        try:
            fd, output_path = tempfile.mkstemp(
                suffix=".wav", prefix="voxwatch_preview_dispatch_"
            )
            os.close(fd)
        except OSError as exc:
            logger.error("Preview API: could not create temp file: %s", exc)
            return None

        composed = await compose_dispatch_audio(
            segments=segments,
            output_path=output_path,
            audio_pipeline=self._audio,
            config=config,
            stage_label="preview",
        )

        if composed and os.path.exists(composed):
            return composed

        # compose_dispatch_audio failed — clean up the empty temp file.
        with contextlib.suppress(OSError):
            os.unlink(output_path)
        return None

    async def _generate_tts_preview(
        self,
        config: dict,
        response_mode: str,
        custom_message: str,
    ) -> str | None:
        """Generate a clean TTS preview for non-dispatch response modes.

        Uses ``AudioPipeline.generate_tts`` directly.  No radio effects are
        applied — this matches what the user hears during a real detection event
        for non-dispatch modes (radio processing only happens for dispatch).

        If a custom message was supplied it is used verbatim.  Otherwise a
        generic deterrent message is generated.

        Args:
            config: Preview config snapshot (may contain TTS overrides).
            response_mode: Active response mode name (used for log context).
            custom_message: Caller-supplied text.  When non-empty, used
                directly for TTS.

        Returns:
            Absolute path to the generated WAV file, or ``None`` on failure.
            The caller is responsible for deleting the file.
        """
        message = custom_message or _DEFAULT_PREVIEW_MESSAGE

        logger.debug(
            "Preview API: TTS preview — mode='%s' message_len=%d",
            response_mode,
            len(message),
        )

        try:
            fd, output_path = tempfile.mkstemp(
                suffix=".wav", prefix="voxwatch_preview_tts_"
            )
            os.close(fd)
        except OSError as exc:
            logger.error("Preview API: could not create temp file: %s", exc)
            return None

        # Temporarily swap the pipeline's config so generate_tts picks up any
        # voice/provider overrides the UI sent.  We swap back immediately after
        # the call so the live pipeline is never left in an altered state.
        original_config = self._audio.config
        try:
            self._audio.config = config
            success = await self._audio.generate_tts(message, output_path)
        finally:
            self._audio.config = original_config

        if success and os.path.exists(output_path):
            return output_path

        logger.error(
            "Preview API: generate_tts failed for mode '%s'", response_mode
        )
        with contextlib.suppress(OSError):
            os.unlink(output_path)
        return None

    async def _handle_delete_piper_voice(self, request: web.Request) -> web.Response:
        """DELETE /api/piper-voices/{model_name} — Remove a downloaded piper voice.

        Only deletes from /data/piper-voices/ (the auto-download cache).
        Refuses to delete baked-in voices from /usr/share/piper-voices/.

        Args:
            request: aiohttp request with model_name path parameter.

        Returns:
            JSON response with ok/message fields.
        """
        import re

        model_name = request.match_info.get("model_name", "")
        if not re.match(r"^[a-zA-Z0-9_-]+$", model_name):
            return web.json_response(
                {"ok": False, "message": "Invalid model name."},
                status=400,
            )

        # Refuse to delete baked-in voices.
        builtin_path = f"/usr/share/piper-voices/{model_name}.onnx"
        if os.path.exists(builtin_path):
            return web.json_response(
                {"ok": False, "message": "Cannot delete built-in voice."},
                status=403,
            )

        download_dir = "/data/piper-voices"
        onnx_path = os.path.join(download_dir, f"{model_name}.onnx")
        json_path = os.path.join(download_dir, f"{model_name}.onnx.json")

        if not os.path.exists(onnx_path):
            return web.json_response(
                {"ok": False, "message": f"Voice '{model_name}' not found."},
                status=404,
            )

        try:
            os.unlink(onnx_path)
            if os.path.exists(json_path):
                os.unlink(json_path)
            logger.info("Deleted piper voice: %s", model_name)
            return web.json_response(
                {"ok": True, "message": f"Voice '{model_name}' deleted."},
            )
        except OSError as exc:
            logger.error("Failed to delete piper voice '%s': %s", model_name, exc)
            return web.json_response(
                {"ok": False, "message": str(exc)},
                status=500,
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_preview_config(self, tts_overrides: dict) -> dict:
        """Build a shallow config copy with TTS overrides applied.

        The copy is shallow at the top level but replaces the ``tts`` section
        with a merged dict so the TTS factory sees any voice/provider/speed
        changes the UI sent without mutating the live config.

        Args:
            tts_overrides: Dict of TTS field overrides.  Recognised keys:
                ``voice``, ``provider``, ``speed``.  Empty dict is a no-op.

        Returns:
            New config dict.  The ``tts`` sub-dict is a fresh dict (not a
            reference to the original) when overrides are present; all other
            top-level sections point to the same objects as ``self._config``.
        """
        if not tts_overrides:
            return self._config

        new_config = dict(self._config)
        new_tts = dict(self._config.get("tts", {}))

        if "provider" in tts_overrides:
            new_tts["provider"] = tts_overrides["provider"]
        if "speed" in tts_overrides:
            new_tts["speed"] = tts_overrides["speed"]
        if "voice" in tts_overrides:
            voice = tts_overrides["voice"]
            new_tts["voice"] = voice
            # Map the generic "voice" override to the provider-specific config
            # key so each provider picks it up from the key it actually reads.
            provider = new_tts.get("provider", "piper")
            if provider == "piper":
                new_tts["piper_model"] = voice
            elif provider == "kokoro":
                new_tts["kokoro_voice"] = voice
            elif provider == "elevenlabs":
                new_tts["elevenlabs_voice_id"] = voice
            elif provider == "openai":
                new_tts["openai_voice"] = voice
            elif provider == "cartesia":
                new_tts["cartesia_voice_id"] = voice

        new_config["tts"] = new_tts
        return new_config
