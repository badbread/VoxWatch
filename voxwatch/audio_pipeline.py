"""
audio_pipeline.py — Audio Generation and Push Module for VoxWatch

Handles all audio operations in the deterrent pipeline:
  - Text-to-speech generation via the multi-provider TTS factory
  - Audio format conversion via ffmpeg (to camera-compatible codec)
  - Audio push to camera speakers via go2rtc HTTP API
  - Pre-caching of Stage 1 warning audio at startup
  - Pre-generation of attention tones prepended before TTS speech

The go2rtc push method works by:
  1. Serving the audio file via a temporary HTTP server
  2. Telling go2rtc to fetch and play it: POST /api/streams?dst=CAMERA&src=URL
  3. go2rtc handles the backchannel negotiation with the camera

This method was proven working with Reolink CX410 (PCMU/8000 backchannel).

TTS is handled by ``voxwatch.tts.factory``, which selects a provider based on
``config["tts"]["provider"]`` and automatically walks the ``fallback_chain`` on
failure.  The factory exposes two callables used here:
  - ``get_provider(config)`` — returns the primary ``TTSProvider`` instance
  - ``generate_with_fallback(message, output_path, config)`` — runs the full
    chain and returns True on success

Attention tones:
  Pre-generated WAV files in the camera's codec (pcm_mulaw 8kHz mono by default)
  are prepended before TTS speech using ffmpeg's concat demuxer.  Three built-in
  tones are available:
    - ``short``  — 0.5s sharp 800 Hz beep
    - ``long``   — 1.0s two-tone alert (800 Hz + 1000 Hz alternating)
    - ``siren``  — 1.5s rising sweep (400 Hz to 1200 Hz)
  A path to a custom WAV file is also accepted.  ``"none"`` disables the tone.

Usage:
    from voxwatch.audio_pipeline import AudioPipeline
    pipeline = AudioPipeline(config)
    await pipeline.initialize()  # warms up TTS and generates cached Stage 1 audio
    await pipeline.play_audio("frontdoor", "/path/to/audio.wav")
"""

import asyncio
import http.server
import logging
import os
import time
import threading
import unicodedata
from typing import Optional

import aiohttp

from voxwatch.tts.factory import get_provider, generate_with_fallback

logger = logging.getLogger("voxwatch.audio")

# Timeout for ffmpeg/ffprobe subprocesses (seconds)
SUBPROCESS_TIMEOUT = 30

# Built-in attention tone names and their filenames in the serve directory.
# Values are used as keys in _attention_tone_paths and as config values.
_BUILTIN_TONES = ("short", "long", "siren")

# Silence gap (seconds) inserted between the attention tone and the TTS speech.
_TONE_GAP_SECONDS = 0.3


def _sanitize_tts_input(message: str) -> str:
    """Strip control characters from a TTS message string.

    Removes any Unicode code point whose general category begins with "C"
    (control, format, surrogate, private-use, and unassigned characters).
    Printable ASCII and Unicode letters, digits, punctuation, and whitespace
    (categories L, N, P, S, Z) are all preserved so the spoken output is not
    altered for well-formed messages.

    This prevents a crafted detection description from injecting shell control
    sequences or null bytes into the TTS subprocess call.

    Args:
        message: Raw TTS text, possibly containing untrusted content from AI
            model output or config values.

    Returns:
        Sanitized string with all control characters removed.

    Examples:
        >>> _sanitize_tts_input("Hello\\x00 world\\x1b[31m")
        'Hello world'
        >>> _sanitize_tts_input("Person in red hoodie near gate.")
        'Person in red hoodie near gate.'
    """
    return "".join(
        ch for ch in message
        if not unicodedata.category(ch).startswith("C")
    )


class AudioPipeline:
    """Manages TTS generation, audio conversion, and push to camera speakers.

    Maintains a background HTTP server so go2rtc can fetch audio files on demand.
    Handles pre-caching of Stage 1 audio and on-the-fly generation for Stages 2/3.

    Attributes:
        config: The full VoxWatch config dict.
        _http_server: Background HTTP server instance.
        _serve_dir: Directory where audio files are served from.
        _serve_port: Port the HTTP server listens on.
        _cached_stage1: Path to the pre-cached Stage 1 warning audio.
        _stage1_duration: Duration of Stage 1 audio in seconds.
        _tts_provider: The primary TTS provider instance, warmed up at startup.
        _attention_tone_paths: Maps tone name ("short", "long", "siren") to the
            absolute path of the pre-generated WAV file in the camera's codec.
            Populated by ``_generate_attention_tones()`` during ``initialize()``.
    """

    def __init__(self, config: dict):
        """Initialize the audio pipeline with config settings.

        Args:
            config: Full VoxWatch config dict from config.py.
        """
        self.config = config
        data_dir = config.get("logging", {}).get("data_dir", "/data")
        self._serve_dir = os.path.join(data_dir, "audio")
        push_cfg = config.get("audio_push", {})
        self._serve_port = push_cfg.get("serve_port", 8891)
        # Host IP that go2rtc's ffmpeg uses to fetch audio files from our HTTP server.
        # Must be a routable address — 127.0.0.1 does NOT work reliably because
        # go2rtc's ffmpeg may not resolve loopback the same way.
        # Defaults to the go2rtc host (works when VoxWatch and go2rtc share a host).
        # Override with audio_push.serve_host if they are on different machines.
        self._serve_host = push_cfg.get("serve_host", config.get("go2rtc", {}).get("host", "localhost"))
        self._http_server: Optional[http.server.HTTPServer] = None
        self._cached_stage1: Optional[str] = None
        self._stage1_duration: float = 0.0
        # Primary TTS provider — instantiated and warmed up in initialize()
        self._tts_provider = None
        # Pre-generated attention tone paths keyed by tone name.
        # Populated at startup by _generate_attention_tones().
        self._attention_tone_paths: dict[str, str] = {}
        # Lock to prevent simultaneous audio pushes to the same camera
        # go2rtc can handle one backchannel stream at a time per camera
        self._push_locks: dict[str, asyncio.Lock] = {}
        # Track which cameras have had their backchannel warmed up recently.
        # Warmup is only needed on the first push — subsequent pushes within
        # a short window reuse the established backchannel.
        self._warmed_up: dict[str, float] = {}
        # Backchannel stays active for ~30s after last push, so we re-warmup
        # if more than 25s have passed since the last successful push.
        self._warmup_ttl: float = 25.0

    async def initialize(self) -> None:
        """Start the HTTP server, warm up the TTS provider, and cache Stage 1 audio.

        Called once at service startup.  Instantiates the configured TTS provider
        via ``get_provider`` and calls ``provider.warmup()`` so any model loading
        or network preflight is done before the first detection event arrives.
        The Stage 1 audio is then pre-generated so it can play instantly when a
        detection occurs (zero runtime latency for the most critical path).
        """
        os.makedirs(self._serve_dir, exist_ok=True)

        # Start the background HTTP server
        self._start_http_server()

        # Pre-generate the built-in attention tone WAV files in the camera's
        # codec so they are ready to prepend to TTS output at event time.
        await self._generate_attention_tones()

        # Instantiate and warm up the primary TTS provider.
        # warmup() loads models / checks credentials so the first real TTS call
        # is fast.  Errors here are non-fatal — generate_with_fallback() will
        # try the fallback_chain at generation time.
        try:
            self._tts_provider = get_provider(self.config)
            await self._tts_provider.warmup()
            logger.info(
                "TTS provider '%s' warmed up successfully",
                self.config.get("tts", {}).get("provider", "piper"),
            )
        except Exception as exc:
            logger.warning(
                "TTS provider warmup failed (%s) — will rely on fallback_chain at generation time",
                exc,
            )
            self._tts_provider = None

        # Pre-generate and cache the Stage 1 warning audio
        stage1_message = self.config["messages"]["stage1"]
        self._cached_stage1 = os.path.join(self._serve_dir, "stage1_cached.wav")

        logger.info("Generating cached Stage 1 audio...")
        tts_path = os.path.join(self._serve_dir, "stage1_tts.wav")
        success = await self.generate_tts(stage1_message, tts_path)
        if not success:
            logger.error("Failed to generate Stage 1 cached audio — Stage 1 will be unavailable")
            return

        success = await self.convert_audio(tts_path, self._cached_stage1)
        if not success:
            logger.error("Failed to convert Stage 1 audio — Stage 1 will be unavailable")
            return

        self._stage1_duration = await self.get_audio_duration(self._cached_stage1)
        logger.info("Stage 1 audio cached: %s (%.1fs)", self._cached_stage1, self._stage1_duration)

    def _start_http_server(self) -> None:
        """Start a background HTTP server to serve audio files to go2rtc.

        go2rtc's play-audio feature fetches audio from a URL, so we serve
        local files over HTTP. The server runs in a daemon thread and
        automatically stops when the main process exits.
        """
        serve_dir = self._serve_dir

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            """HTTP handler that serves from the audio directory with minimal logging."""
            def __init__(self, *args, **kwargs):
                """Override directory to serve from the audio output dir."""
                super().__init__(*args, directory=serve_dir, **kwargs)
            def log_message(self, format, *args):
                """Only log errors, not every request."""
                pass

        try:
            # Security: bind to 127.0.0.1 (loopback) rather than 0.0.0.0 (all
            # interfaces).  The audio HTTP server is only accessed by go2rtc,
            # Bind to 0.0.0.0 so go2rtc's ffmpeg can reach this server.
            # go2rtc spawns ffmpeg which fetches audio via HTTP — it needs a
            # routable address.  Use firewall rules to restrict access to port
            # 8891 if the host is on an untrusted network.
            self._http_server = http.server.HTTPServer(("0.0.0.0", self._serve_port), QuietHandler)
            thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
            thread.start()
            logger.info("Audio HTTP server started on 0.0.0.0:%d", self._serve_port)
        except OSError as e:
            logger.error("Failed to start HTTP server on port %d: %s", self._serve_port, e)

    async def generate_tts(self, message: str, output_path: str) -> bool:
        """Generate speech audio from text using the configured TTS provider chain.

        Delegates to ``generate_with_fallback`` from ``voxwatch.tts.factory``,
        which tries the primary provider and then walks ``config["tts"]["fallback_chain"]``
        until one succeeds.  This replaces the former hard-coded Piper → espeak-ng
        logic and supports any provider registered in the factory (piper, espeak,
        kokoro, elevenlabs, cartesia, polly, openai).

        The ``message`` is sanitized with ``_sanitize_tts_input`` before being
        handed to any provider.  This strips Unicode control characters that could
        interfere with subprocess invocations or cloud API calls.

        Args:
            message: Text to convert to speech.  May contain AI-generated content
                from Gemini or Ollama — sanitized before use.
            output_path: Absolute path where the output WAV file should be written.
                The file is always WAV; callers are responsible for converting to
                the camera codec via ``convert_audio``.

        Returns:
            True if at least one provider in the chain succeeded and ``output_path``
            exists and is non-empty.
        """
        # Sanitize first so all downstream providers receive clean text.
        message = _sanitize_tts_input(message)

        success = await generate_with_fallback(message, output_path, self.config)
        if not success:
            logger.error("All TTS providers in fallback_chain exhausted — no audio generated")
        return success

    async def convert_audio(self, input_path: str, output_path: str) -> bool:
        """Convert audio to camera-compatible format via ffmpeg.

        Uses the codec, sample rate, and channel count from config.
        Default: pcm_mulaw, 8000 Hz, mono (proven working with Reolink CX410).

        Args:
            input_path: Path to the source audio file.
            output_path: Path for the converted output file.

        Returns:
            True if conversion succeeded.
        """
        audio_cfg = self.config.get("audio", {})
        codec = audio_cfg.get("codec", "pcm_mulaw")
        sample_rate = str(audio_cfg.get("sample_rate", 8000))
        channels = str(audio_cfg.get("channels", 1))

        # Pad 1.5s of silence at the end of the audio.  Some cameras
        # (notably Reolink E1 Zoom) drop the RTSP backchannel before the
        # last chunk of audio finishes playing.  The padding ensures real
        # speech finishes before the connection tears down.  Harmless on
        # cameras that don't need it.
        pad_filter = "apad=pad_dur=1.5"

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", input_path,
                "-af", pad_filter,
                "-acodec", codec,
                "-ar", sample_rate,
                "-ac", channels,
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=SUBPROCESS_TIMEOUT)
            if proc.returncode == 0 and os.path.exists(output_path):
                logger.debug("Audio converted (with 1.5s tail pad): %s -> %s",
                             input_path, output_path)
                return True
            logger.error("ffmpeg conversion failed (exit %d): %s", proc.returncode,
                         stderr.decode("utf-8", errors="replace")[-300:])
            return False
        except asyncio.TimeoutError:
            logger.error("ffmpeg conversion timed out after %ds", SUBPROCESS_TIMEOUT)
            return False
        except FileNotFoundError:
            logger.error("ffmpeg not found — install ffmpeg")
            return False

    async def get_audio_duration(self, file_path: str) -> float:
        """Get the duration of an audio file using ffprobe.

        Args:
            file_path: Path to the audio file.

        Returns:
            Duration in seconds, or 0.0 if ffprobe fails.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                duration = float(stdout.decode().strip())
                return duration
        except Exception as e:
            logger.warning("ffprobe failed for %s: %s", file_path, e)

        # Fallback: estimate from file size and codec
        # pcm_mulaw at 8kHz mono = 8000 bytes/sec
        try:
            size = os.path.getsize(file_path)
            return size / 8000.0
        except OSError:
            return 0.0

    async def push_audio(self, camera_stream: str, audio_path: str) -> bool:
        """Push an audio file to a camera speaker via go2rtc's HTTP API.

        Tells go2rtc to fetch the audio file from our HTTP server and stream
        it to the camera's backchannel. This is the proven working method
        for Reolink cameras.

        Args:
            camera_stream: go2rtc stream name (e.g., "frontdoor").
            audio_path: Path to the camera-compatible audio file.
                        Must be inside self._serve_dir to be accessible via HTTP.

        Returns:
            True if go2rtc accepted the audio push request.
        """
        # Ensure we don't overlap audio pushes to the same camera
        if camera_stream not in self._push_locks:
            self._push_locks[camera_stream] = asyncio.Lock()

        async with self._push_locks[camera_stream]:
            return await self._do_push(camera_stream, audio_path)

    async def _do_push(self, camera_stream: str, audio_path: str) -> bool:
        """Internal: perform the actual go2rtc API call to push audio.

        Uses go2rtc's /api/ffmpeg endpoint — the same one the go2rtc web UI
        "Play audio" feature uses.  This endpoint tells go2rtc to use its
        internal ffmpeg to read the audio file and push it through the camera's
        backchannel.

        The backchannel requires a "warmup" push to establish the RTP session
        with the camera.  The first push after idle opens the backchannel but
        audio may not play; the second push succeeds reliably.  We handle this
        transparently by pushing a short silent file first, waiting briefly,
        then pushing the real audio.

        This was discovered empirically with Reolink CX410: go2rtc's own web UI
        also fails on the first attempt and works on the second.

        Args:
            camera_stream: go2rtc stream name.
            audio_path: Path to the audio file.

        Returns:
            True if the push was accepted.
        """
        go2rtc_cfg = self.config["go2rtc"]
        host = go2rtc_cfg["host"]
        api_port = go2rtc_cfg.get("api_port", 1984)
        base_url = f"http://{host}:{api_port}"

        filename = os.path.basename(audio_path)
        audio_url = f"http://{self._serve_host}:{self._serve_port}/{filename}"

        # go2rtc's /api/ffmpeg endpoint — same as web UI "Play audio"
        api_url = f"{base_url}/api/ffmpeg?dst={camera_stream}&file={audio_url}"

        logger.info("Pushing audio to %s via /api/ffmpeg: %s", camera_stream, filename)


        duration = await self.get_audio_duration(audio_path)
        total_timeout = duration + 15.0

        # --- Warmup: only needed if backchannel hasn't been used recently ---
        needs_warmup = True
        last_warmup = self._warmed_up.get(camera_stream, 0)
        if (time.monotonic() - last_warmup) < self._warmup_ttl:
            needs_warmup = False
            logger.debug("Backchannel recently active, skipping warmup")

        try:
            async with aiohttp.ClientSession() as session:
                if needs_warmup:
                    warmup_path = os.path.join(self._serve_dir, "warmup_silent.wav")
                    if not os.path.exists(warmup_path):
                        await self._generate_silence(warmup_path)

                    warmup_url = f"http://{self._serve_host}:{self._serve_port}/warmup_silent.wav"
                    warmup_api = f"{base_url}/api/ffmpeg?dst={camera_stream}&file={warmup_url}"

                    logger.debug("Sending warmup push to establish backchannel...")
                    try:
                        async with session.post(warmup_api, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status == 200:
                                logger.debug("Warmup push accepted")
                            else:
                                logger.debug("Warmup push returned HTTP %d (continuing anyway)", resp.status)
                    except asyncio.TimeoutError:
                        logger.debug("Warmup push timed out (continuing anyway)")

                    # Wait for 0.1s silence to finish + backchannel establishment
                    await asyncio.sleep(2.0)
                    logger.debug("Backchannel established, pushing real audio...")

                # Push the real audio
                async with session.post(api_url, timeout=aiohttp.ClientTimeout(total=total_timeout)) as resp:
                    if resp.status == 200:
                        # /api/ffmpeg returns immediately — we must wait for
                        # the audio to finish playing before returning, so
                        # the caller knows when it's safe to push more audio
                        wait_time = duration + 2.0
                        logger.info("Audio push accepted, waiting %.1fs for playback on %s",
                                    wait_time, camera_stream)
                        await asyncio.sleep(wait_time)
                        # Record successful push time so next push skips warmup
                        self._warmed_up[camera_stream] = time.monotonic()
                        logger.info("Audio playback complete on %s (%.1fs)", camera_stream, duration)
                        # Monitor stale sender count — each /api/ffmpeg call
                        # leaves a sender entry in go2rtc that is never cleaned.
                        # Log a warning when the count gets high so operators
                        # know a Frigate restart will eventually be needed.
                        asyncio.create_task(
                            self._check_sender_count(camera_stream, base_url),
                            name=f"sender_check_{camera_stream}",
                        )
                        return True
                    else:
                        body = await resp.text()
                        # Reolink cameras can lock the speaker channel when
                        # another session is using it ("A user is using the
                        # speaker").  Retry once after a short delay.
                        if "using the speaker" in body.lower() or "speaker" in body.lower():
                            logger.warning(
                                "Camera speaker locked on %s — retrying in 3s",
                                camera_stream,
                            )
                            await asyncio.sleep(3.0)
                            async with session.post(
                                api_url,
                                timeout=aiohttp.ClientTimeout(total=total_timeout),
                            ) as retry_resp:
                                if retry_resp.status == 200:
                                    wait_time = duration + 2.0
                                    await asyncio.sleep(wait_time)
                                    self._warmed_up[camera_stream] = time.monotonic()
                                    logger.info(
                                        "Speaker retry succeeded on %s", camera_stream
                                    )
                                    return True
                                logger.error(
                                    "Speaker retry also failed (HTTP %d)",
                                    retry_resp.status,
                                )
                                return False
                        logger.error("go2rtc rejected audio push (HTTP %d): %s",
                                     resp.status, body[:200])
                        return False
        except asyncio.TimeoutError:
            logger.error("go2rtc audio push timed out after %.0fs", total_timeout)
            return False
        except Exception as e:
            logger.error("Audio push failed: %s", e)
            return False

    async def _check_sender_count(self, camera_stream: str, base_url: str) -> None:
        """Check how many stale backchannel senders exist for a camera stream.

        Each /api/ffmpeg push creates a sender entry in go2rtc that is never
        cleaned up.  This method queries the stream info and logs a warning
        when the count exceeds a threshold.  It does NOT take any corrective
        action (restarting Frigate/go2rtc is unacceptable during operation).

        This is purely observational — operators can schedule maintenance
        restarts based on these warnings.

        Args:
            camera_stream: go2rtc stream name to check.
            base_url: go2rtc base URL (e.g. http://localhost:1984).
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{base_url}/api/streams?src={camera_stream}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    for producer in data.get("producers", []):
                        senders = producer.get("senders", [])
                        count = len(senders)
                        if count >= 50:
                            logger.warning(
                                "Stream '%s' has %d stale backchannel senders. "
                                "Consider scheduling a Frigate restart during a "
                                "maintenance window to clear them.",
                                camera_stream, count,
                            )
                        elif count >= 20:
                            logger.info(
                                "Stream '%s' has %d backchannel senders",
                                camera_stream, count,
                            )
        except Exception:
            pass  # Best-effort monitoring, never block the pipeline

    async def _generate_silence(self, output_path: str) -> None:
        """Generate a very short silent WAV file for backchannel warmup.

        Creates a 0.1-second silent file in the camera's expected codec
        (PCMU/8000).  Kept as short as possible so go2rtc finishes playing
        it quickly and the backchannel is ready for the real audio.

        Args:
            output_path: Where to write the silent WAV file.
        """
        audio_cfg = self.config.get("audio", {})
        codec = audio_cfg.get("codec", "pcm_mulaw")
        sample_rate = str(audio_cfg.get("sample_rate", 8000))

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                "-t", "0.1",
                "-acodec", codec,
                "-ar", sample_rate,
                "-ac", "1",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                logger.info("Generated warmup silence file: %s", output_path)
            else:
                logger.warning("Failed to generate silence file (exit %d)", proc.returncode)
        except Exception as e:
            logger.warning("Could not generate silence file: %s", e)

    async def _generate_attention_tones(self) -> None:
        """Pre-generate built-in attention tone WAV files in the camera's codec.

        Creates three tone files in ``self._serve_dir`` converted to the
        camera's backchannel codec (default: pcm_mulaw, 8 kHz, mono):

        - ``attention_tone_short.wav``  — 0.5 s sharp 800 Hz beep
        - ``attention_tone_long.wav``   — 1.0 s two-tone alert (800/1000 Hz)
        - ``attention_tone_siren.wav``  — 1.5 s rising sweep (400–1200 Hz)

        Uses ffmpeg's ``lavfi`` source so no external audio files are needed.
        Generation errors are non-fatal — the missing tone is simply skipped at
        play time and a warning is logged.

        The generated paths are stored in ``self._attention_tone_paths`` keyed
        by the tone name (``"short"``, ``"long"``, ``"siren"``).
        """
        audio_cfg = self.config.get("audio", {})
        codec = audio_cfg.get("codec", "pcm_mulaw")
        sample_rate = str(audio_cfg.get("sample_rate", 8000))

        logger.info("Generating attention tone files (codec=%s, rate=%s Hz)...", codec, sample_rate)

        # Each entry: (tone_name, filename, ffmpeg_filter_chain)
        # The filter chain is passed to -filter_complex and the output is taken
        # from the [tone] output pad.
        tone_specs: list[tuple[str, str, str, float]] = [
            # short: single 800 Hz sine, 0.5 s
            (
                "short",
                "attention_tone_short.wav",
                "sine=frequency=800:duration=0.5",
                0.5,
            ),
            # long: two 0.5 s tones (800 Hz then 1000 Hz) concatenated
            (
                "long",
                "attention_tone_long.wav",
                "sine=frequency=800:duration=0.5[a];sine=frequency=1000:duration=0.5[b];[a][b]concat=n=2:v=0:a=1[tone]",
                1.0,
            ),
            # siren: 1.5 s sweep from 400 Hz to 1200 Hz using aevalsrc
            (
                "siren",
                "attention_tone_siren.wav",
                "aevalsrc=sin(2*PI*t*(400+800*t/1.5)):s=8000:d=1.5",
                1.5,
            ),
        ]

        for tone_name, filename, lavfi_filter, _duration in tone_specs:
            out_path = os.path.join(self._serve_dir, filename)
            # Skip regeneration if file already exists from a previous run.
            # During hot-reload of TTS the codec may have changed — but tone
            # files are keyed to the codec at service start, so we regenerate
            # only on a full service restart (when the serve_dir is fresh).
            if os.path.exists(out_path):
                logger.debug("Attention tone already exists, skipping: %s", filename)
                self._attention_tone_paths[tone_name] = out_path
                continue

            # The "long" tone uses a filter_complex with named pads; all others
            # use a simple -f lavfi -i <filter> source chain.
            if tone_name == "long":
                # Two inputs + concat: build with -filter_complex
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=800:duration=0.5",
                    "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.5",
                    "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[tone]",
                    "-map", "[tone]",
                    "-acodec", codec,
                    "-ar", sample_rate,
                    "-ac", "1",
                    out_path,
                ]
            else:
                # Single lavfi source (short and siren)
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", lavfi_filter,
                    "-acodec", codec,
                    "-ar", sample_rate,
                    "-ac", "1",
                    out_path,
                ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode == 0 and os.path.exists(out_path):
                    logger.info("Generated attention tone '%s': %s", tone_name, out_path)
                    self._attention_tone_paths[tone_name] = out_path
                else:
                    logger.warning(
                        "Failed to generate attention tone '%s' (exit %d): %s",
                        tone_name,
                        proc.returncode,
                        stderr.decode("utf-8", errors="replace")[-300:],
                    )
            except asyncio.TimeoutError:
                logger.warning("Attention tone generation timed out for '%s'", tone_name)
            except Exception as exc:
                logger.warning("Could not generate attention tone '%s': %s", tone_name, exc)

    def _resolve_tone_path(self, tone_name: str) -> Optional[str]:
        """Resolve an attention tone name or custom path to an absolute file path.

        Accepts:
          - ``"none"`` or empty string — returns ``None`` (no tone)
          - ``"short"``, ``"long"``, ``"siren"`` — returns the pre-generated path
          - Any other value — treated as an absolute path to a custom WAV file;
            returns the path if the file exists, otherwise ``None`` with a warning.

        Args:
            tone_name: Tone identifier from config (``audio.attention_tone`` or
                per-stage override such as ``messages.stage1_tone``).

        Returns:
            Absolute path to the tone WAV file, or ``None`` if no tone should
            be played or the file could not be resolved.
        """
        if not tone_name or tone_name.lower() == "none":
            return None

        if tone_name in _BUILTIN_TONES:
            path = self._attention_tone_paths.get(tone_name)
            if path and os.path.exists(path):
                return path
            logger.warning(
                "Built-in attention tone '%s' was not generated at startup — skipping tone",
                tone_name,
            )
            return None

        # Custom path
        if os.path.exists(tone_name):
            return tone_name
        logger.warning(
            "Custom attention tone file not found: '%s' — skipping tone",
            tone_name,
        )
        return None

    async def prepend_tone(self, audio_path: str, tone_name: str) -> str:
        """Prepend an attention tone to a TTS audio file using ffmpeg concat.

        Concatenates:  <tone> + <_TONE_GAP_SECONDS silence> + <speech>

        All segments must already be in the same codec and sample rate (the
        camera backchannel format).  The output file is written to the same
        directory as ``audio_path`` with a ``_toned`` suffix inserted before
        the extension.

        Args:
            audio_path: Absolute path to the converted TTS WAV file (already in
                camera codec).  This file is not modified.
            tone_name: Tone identifier (``"short"``, ``"long"``, ``"siren"``,
                ``"none"``, or path to a custom WAV file).

        Returns:
            Path to the combined WAV file if the tone was prepended, or
            ``audio_path`` unchanged if the tone is ``"none"`` / unavailable or
            if concatenation fails (the speech still plays, just without a tone).
        """
        tone_path = self._resolve_tone_path(tone_name)
        if tone_path is None:
            return audio_path

        audio_cfg = self.config.get("audio", {})
        codec = audio_cfg.get("codec", "pcm_mulaw")
        sample_rate = str(audio_cfg.get("sample_rate", 8000))

        # Derive output path: e.g. "stage2_ready.wav" -> "stage2_ready_toned.wav"
        base, ext = os.path.splitext(audio_path)
        toned_path = f"{base}_toned{ext}"

        # Build a temporary ffmpeg concat list file (concat demuxer format).
        # We use a concat list instead of the concat filter so we don't have to
        # worry about re-encoding intermediate formats — all inputs are already
        # in the same codec.
        gap_path = os.path.join(self._serve_dir, "tone_gap.wav")
        if not os.path.exists(gap_path):
            await self._generate_tone_gap(gap_path, sample_rate, codec)

        concat_list_path = f"{base}_concat.txt"
        try:
            with open(concat_list_path, "w") as fh:
                fh.write(f"file '{tone_path}'\n")
                if os.path.exists(gap_path):
                    fh.write(f"file '{gap_path}'\n")
                fh.write(f"file '{audio_path}'\n")
        except OSError as exc:
            logger.warning("Could not write concat list for tone prepend: %s", exc)
            return audio_path

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-acodec", codec,
                "-ar", sample_rate,
                "-ac", "1",
                toned_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=SUBPROCESS_TIMEOUT)
            if proc.returncode == 0 and os.path.exists(toned_path):
                logger.debug(
                    "Prepended attention tone '%s' to %s -> %s",
                    tone_name,
                    os.path.basename(audio_path),
                    os.path.basename(toned_path),
                )
                return toned_path
            logger.warning(
                "Tone prepend failed (exit %d): %s — playing speech without tone",
                proc.returncode,
                stderr.decode("utf-8", errors="replace")[-300:],
            )
            return audio_path
        except asyncio.TimeoutError:
            logger.warning("Tone prepend timed out — playing speech without tone")
            return audio_path
        except Exception as exc:
            logger.warning("Tone prepend error: %s — playing speech without tone", exc)
            return audio_path
        finally:
            # Clean up the temporary concat list regardless of outcome.
            try:
                os.remove(concat_list_path)
            except OSError:
                pass

    async def _apply_radio_effect(self, audio_path: str) -> None:
        """Apply police radio static effect to an audio file in-place.

        Uses ffmpeg to band-pass filter (300-3400Hz radio bandwidth), add slight
        overdrive distortion, and mix in low-volume white noise to simulate a
        police scanner broadcast.

        Non-fatal: if the effect fails, the clean audio is kept unchanged.

        Args:
            audio_path: Path to the WAV file to process (modified in-place).
        """
        radio_path = audio_path + ".radio.wav"
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", audio_path,
                "-f", "lavfi", "-i", "anoisesrc=d=60:c=white:a=0.015",
                "-filter_complex",
                "[0:a]bandpass=f=1800:width_type=h:w=3100,overdrive=gain=3:colour=20[voice];"
                "[1:a]volume=0.04[noise];"
                "[voice][noise]amix=inputs=2:duration=first:dropout_transition=0[mixed];"
                "[mixed]aformat=sample_rates=8000:channel_layouts=mono[out]",
                "-map", "[out]",
                "-acodec", "pcm_mulaw", "-f", "wav",
                radio_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
            if proc.returncode == 0 and os.path.exists(radio_path):
                os.replace(radio_path, audio_path)
                logger.debug("Applied police radio static effect to %s", audio_path)
            else:
                logger.debug("Radio effect ffmpeg failed (rc=%s), keeping clean audio",
                             proc.returncode)
        except Exception as exc:
            logger.debug("Radio effect failed: %s — keeping clean audio", exc)
        finally:
            if os.path.exists(radio_path):
                os.unlink(radio_path)

    async def _generate_tone_gap(self, output_path: str, sample_rate: str, codec: str) -> None:
        """Generate a short silent WAV used as the gap between tone and speech.

        The gap is ``_TONE_GAP_SECONDS`` long and encoded in the camera's codec
        so it can be losslessly concatenated with the tone and TTS files.

        Args:
            output_path: Where to write the gap WAV file.
            sample_rate: Sample rate string for ffmpeg (e.g. ``"8000"``).
            codec: ffmpeg codec name (e.g. ``"pcm_mulaw"``).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=mono",
                "-t", str(_TONE_GAP_SECONDS),
                "-acodec", codec,
                "-ar", sample_rate,
                "-ac", "1",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                logger.debug("Generated tone gap file: %s", output_path)
            else:
                logger.warning("Failed to generate tone gap file (exit %d)", proc.returncode)
        except Exception as exc:
            logger.warning("Could not generate tone gap file: %s", exc)

    def _get_stage_tone(self, stage_key: str) -> str:
        """Return the attention tone name for a given pipeline stage.

        Resolution priority (first non-empty wins):
          1. ``messages[stage_key]`` — legacy per-stage override
          2. ``pipeline.initial_response.attention_tone`` (for stage1_tone)
             ``pipeline.escalation.attention_tone`` (for stage2/3_tone)
          3. ``audio.attention_tone`` — global default
          4. ``"none"`` — hardcoded fallback

        Args:
            stage_key: Config key for the per-stage override, e.g.
                ``"stage1_tone"``, ``"stage2_tone"``, or ``"stage3_tone"``.

        Returns:
            Tone name string (``"none"``, ``"short"``, ``"long"``, ``"siren"``,
            or a custom file path).
        """
        messages_cfg = self.config.get("messages", {})
        audio_cfg = self.config.get("audio", {})
        pipeline_cfg = self.config.get("pipeline", {})

        # Priority 1: legacy messages.stageN_tone
        legacy = messages_cfg.get(stage_key)
        if legacy:
            return legacy

        # Priority 2: pipeline section (dashboard writes here)
        if stage_key == "stage1_tone":
            pipeline_tone = pipeline_cfg.get("initial_response", {}).get("attention_tone")
        else:
            pipeline_tone = pipeline_cfg.get("escalation", {}).get("attention_tone")
        if pipeline_tone:
            return pipeline_tone

        # Priority 3: global default
        return audio_cfg.get("attention_tone", "none")

    async def warmup_backchannel(self, camera_stream: str) -> None:
        """Send a silent warmup push to establish the go2rtc backchannel.

        The backchannel requires a throwaway push before real audio will play.
        This method sends a short silent file via /api/ffmpeg and waits for
        the backchannel to be established.  Designed to run concurrently with
        AI analysis so the warmup latency is hidden.

        Args:
            camera_stream: go2rtc stream name for the target camera.
        """
        go2rtc_cfg = self.config["go2rtc"]
        host = go2rtc_cfg["host"]
        api_port = go2rtc_cfg.get("api_port", 1984)
        base_url = f"http://{host}:{api_port}"

        warmup_path = os.path.join(self._serve_dir, "warmup_silent.wav")
        if not os.path.exists(warmup_path):
            await self._generate_silence(warmup_path)

        warmup_url = f"http://{self._serve_host}:{self._serve_port}/warmup_silent.wav"
        warmup_api = f"{base_url}/api/ffmpeg?dst={camera_stream}&file={warmup_url}"

        logger.info("Sending backchannel warmup push to %s...", camera_stream)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(warmup_api, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        logger.info("Warmup push accepted for %s", camera_stream)
                    else:
                        logger.warning("Warmup push returned HTTP %d", resp.status)
        except Exception as e:
            logger.warning("Warmup push failed: %s (continuing anyway)", e)

        # Wait for the backchannel to be fully established
        await asyncio.sleep(2.0)
        self._warmed_up[camera_stream] = time.monotonic()
        logger.info("Backchannel warmup complete for %s", camera_stream)

    async def play_cached_stage1(self, camera_stream: str) -> float:
        """Play the pre-cached Stage 1 warning audio on a camera.

        This is the fastest path — no TTS generation, no API calls, just
        push the pre-generated audio file. Returns the duration so the
        caller knows when it's safe to play Stage 2.

        If ``messages.stage1_tone`` (or the global ``audio.attention_tone``)
        is set to a value other than ``"none"``, the attention tone is prepended
        to the cached audio before pushing.  The toned file is a temporary copy
        that is cleaned up after the push.

        Args:
            camera_stream: go2rtc stream name for the target camera.

        Returns:
            Duration of the Stage 1 audio in seconds (0.0 if push failed).
        """
        if not self._cached_stage1 or not os.path.exists(self._cached_stage1):
            logger.error("Stage 1 cached audio not available")
            return 0.0

        tone_name = self._get_stage_tone("stage1_tone")
        audio_to_push = await self.prepend_tone(self._cached_stage1, tone_name)
        toned_is_temp = audio_to_push != self._cached_stage1

        try:
            success = await self.push_audio(camera_stream, audio_to_push)
        finally:
            # Remove the temporary toned file; the original cached file is kept.
            if toned_is_temp:
                try:
                    os.remove(audio_to_push)
                except OSError:
                    pass

        if success:
            # Return the duration of the file actually pushed so the caller
            # waits the right amount of time before playing Stage 2.
            # When a tone was prepended the temporary toned file has already
            # been deleted, so we compute: stage1 duration + tone gap + tone.
            # Rather than re-probing a deleted file, we use the stored stage1
            # duration and add the tone overhead from the gap constant.
            if toned_is_temp:
                tone_overhead = self._tone_duration(tone_name)
                return self._stage1_duration + tone_overhead + _TONE_GAP_SECONDS
            return self._stage1_duration
        return 0.0

    def _tone_duration(self, tone_name: str) -> float:
        """Return the pre-known duration in seconds for a built-in tone name.

        Used after the toned file has been cleaned up, so we cannot re-probe
        the file with ffprobe.  For custom WAV files we return a conservative
        estimate of 2.0 s rather than probing.

        Args:
            tone_name: Tone name (``"short"``, ``"long"``, ``"siren"``, or custom).

        Returns:
            Duration in seconds.
        """
        builtin_durations = {"short": 0.5, "long": 1.0, "siren": 1.5}
        return builtin_durations.get(tone_name, 2.0)

    async def generate_and_push(self, camera_stream: str, message: str,
                                 stage_label: str) -> bool:
        """Generate TTS, convert to camera format, optionally prepend a tone, and push.

        Full pipeline for Stage 2 and Stage 3:
          text -> TTS -> ffmpeg codec convert -> (tone prepend) -> go2rtc push

        The attention tone is controlled by ``messages.<stage_label>_tone``
        (e.g. ``messages.stage2_tone``) or, if that key is absent, by the
        global ``audio.attention_tone`` default.  Set to ``"none"`` to disable.

        Args:
            camera_stream: go2rtc stream name for the target camera.
            message: Text message to speak.
            stage_label: Label used for logging and temp file names.  Expected
                values are ``"stage2"`` and ``"stage3"``; the same string is
                used to look up the per-stage tone override key in config
                (e.g. ``stage_label="stage2"`` -> config key ``"stage2_tone"``).

        Returns:
            True if the full pipeline succeeded.
        """
        tts_path = os.path.join(self._serve_dir, f"{stage_label}_tts.wav")
        output_path = os.path.join(self._serve_dir, f"{stage_label}_ready.wav")

        # Step 1: Generate TTS
        logger.info("[%s] Generating TTS (%d chars)...", stage_label, len(message))
        if not await self.generate_tts(message, tts_path):
            logger.error("[%s] TTS generation failed", stage_label)
            return False

        # Step 2: Convert to camera-compatible format
        logger.info("[%s] Converting audio...", stage_label)
        if not await self.convert_audio(tts_path, output_path):
            logger.error("[%s] Audio conversion failed", stage_label)
            return False

        # Step 2.5: Apply radio static effect for police_dispatch persona.
        # Band-pass + noise overlay simulates a police scanner broadcast.
        persona = self.config.get("persona", {}).get("name", "standard")
        if persona == "police_dispatch":
            await self._apply_radio_effect(output_path)

        # Step 3: Prepend attention tone (if configured for this stage)
        # The tone key is e.g. "stage2_tone" or "stage3_tone".
        tone_name = self._get_stage_tone(f"{stage_label}_tone")
        audio_to_push = await self.prepend_tone(output_path, tone_name)
        toned_is_temp = audio_to_push != output_path
        if toned_is_temp:
            logger.debug("[%s] Attention tone '%s' prepended.", stage_label, tone_name)

        # Step 4: Push to camera
        logger.info("[%s] Pushing audio to %s...", stage_label, camera_stream)
        success = await self.push_audio(camera_stream, audio_to_push)

        if success:
            logger.info("[%s] Audio played successfully on %s", stage_label, camera_stream)
        else:
            logger.error("[%s] Audio push failed for %s", stage_label, camera_stream)

        # Clean up temp files to avoid filling disk
        cleanup_paths = [tts_path, output_path]
        if toned_is_temp:
            cleanup_paths.append(audio_to_push)
        for path in cleanup_paths:
            try:
                os.remove(path)
            except OSError:
                pass

        return success

    async def generate_natural_tts(
        self,
        phrases: list[str],
        output_path: str,
    ) -> bool:
        """Generate natural-sounding speech from a list of short phrases.

        Delegates to ``voxwatch.speech.natural_cadence.generate_natural_speech``
        to produce audio with human-like inter-phrase pauses and optional
        per-phrase speed variation.  Falls back to a single ``generate_tts``
        call with all phrases joined by spaces if natural cadence generation
        fails for any reason, ensuring the pipeline is always non-fatal.

        Natural cadence is only attempted when enabled in config
        (``speech.natural_cadence.enabled`` defaults to True).  When disabled,
        the fallback path runs immediately.

        Args:
            phrases: Ordered list of short spoken phrases.  Typically the result
                of ``voxwatch.speech.natural_cadence.parse_ai_response`` applied
                to the AI's structured JSON output.
            output_path: Absolute path where the output WAV should be written.
                The WAV is in the internal working format (44.1 kHz 16-bit mono)
                and must be converted to the camera codec by the caller via
                ``convert_audio``.

        Returns:
            True if audio was successfully written to ``output_path``, either
            via natural cadence or the flat-string fallback.
        """
        cadence_cfg = self.config.get("speech", {}).get("natural_cadence", {})
        enabled: bool = cadence_cfg.get("enabled", True)

        if enabled and phrases:
            try:
                from voxwatch.speech.natural_cadence import generate_natural_speech
                ok = await generate_natural_speech(
                    phrases=phrases,
                    audio_pipeline=self,
                    output_path=output_path,
                    config=self.config,
                )
                if ok:
                    logger.info(
                        "generate_natural_tts: natural cadence succeeded (%d phrases)",
                        len(phrases),
                    )
                    return True
                logger.warning(
                    "generate_natural_tts: natural cadence failed — falling back to flat TTS"
                )
            except Exception as exc:
                logger.warning(
                    "generate_natural_tts: natural cadence raised %s — falling back to flat TTS",
                    exc,
                )

        # Fallback: join all phrases into a single string and call standard TTS.
        fallback_text = " ".join(p.strip() for p in phrases if p.strip())
        if not fallback_text:
            logger.error("generate_natural_tts: no usable text in phrase list")
            return False

        logger.info(
            "generate_natural_tts: using flat-string fallback (%d chars)", len(fallback_text)
        )
        return await self.generate_tts(fallback_text, output_path)

    async def reload_tts(self, config: dict) -> None:
        """Reinitialise the TTS provider from an updated config dict.

        Called by the hot-reload watcher when ``config["tts"]`` has changed.
        Swaps ``self.config`` first so that ``generate_with_fallback`` picks up
        the new settings, then instantiates and warms up the new primary provider.
        If warmup fails, ``self._tts_provider`` is cleared so generation falls
        back to the chain at call time — the pipeline continues running.

        The Stage 1 cached audio is regenerated so the new TTS voice is used
        from the very next detection.

        Args:
            config: Fully resolved, validated config dict with the new TTS
                settings already applied.
        """
        new_provider_name = config.get("tts", {}).get("provider", "piper")
        logger.info("Reloading TTS provider: %s", new_provider_name)

        # Swap config so generate_with_fallback reads new settings immediately.
        self.config = config

        # Instantiate and warm up the new primary provider.
        try:
            provider = get_provider(config)
            await provider.warmup()
            self._tts_provider = provider
            logger.info("TTS provider '%s' reloaded and warmed up", new_provider_name)
        except Exception as exc:
            logger.warning(
                "New TTS provider '%s' warmup failed (%s) — "
                "will rely on fallback_chain at generation time",
                new_provider_name,
                exc,
            )
            self._tts_provider = None

        # Regenerate cached Stage 1 audio with the new provider / voice.
        stage1_message = config["messages"]["stage1"]
        tts_path = os.path.join(self._serve_dir, "stage1_tts.wav")
        cached_path = os.path.join(self._serve_dir, "stage1_cached.wav")

        logger.info("Regenerating cached Stage 1 audio for new TTS provider...")
        success = await self.generate_tts(stage1_message, tts_path)
        if not success:
            logger.error(
                "Stage 1 re-cache failed after TTS reload — "
                "old audio file will be used until next successful generation"
            )
            return

        success = await self.convert_audio(tts_path, cached_path)
        if not success:
            logger.error(
                "Stage 1 re-cache conversion failed — "
                "old audio file will be used until next successful generation"
            )
            return

        self._cached_stage1 = cached_path
        self._stage1_duration = await self.get_audio_duration(cached_path)
        logger.info(
            "Stage 1 audio re-cached with provider '%s' (%.1fs)",
            new_provider_name,
            self._stage1_duration,
        )

    async def recache_stage1(self, config: dict) -> None:
        """Regenerate the Stage 1 cached audio without changing the TTS provider.

        Called by the hot-reload watcher when ``config["messages"]["stage1"]``
        has changed but ``config["tts"]`` is unchanged.  Updates ``self.config``
        so the new message text is used by future calls, then regenerates the
        cached WAV so the very next detection plays the updated wording.

        Args:
            config: Fully resolved, validated config dict with updated messages.
        """
        self.config = config
        stage1_message = config["messages"]["stage1"]
        tts_path = os.path.join(self._serve_dir, "stage1_tts.wav")
        cached_path = os.path.join(self._serve_dir, "stage1_cached.wav")

        logger.info(
            "Regenerating Stage 1 cached audio with new message text: %.80s...",
            stage1_message,
        )
        success = await self.generate_tts(stage1_message, tts_path)
        if not success:
            logger.error(
                "Stage 1 re-cache failed after message change — "
                "old audio file will be used until next successful generation"
            )
            return

        success = await self.convert_audio(tts_path, cached_path)
        if not success:
            logger.error(
                "Stage 1 re-cache conversion failed after message change — "
                "old audio file will be used until next successful generation"
            )
            return

        self._cached_stage1 = cached_path
        self._stage1_duration = await self.get_audio_duration(cached_path)
        logger.info(
            "Stage 1 audio re-cached with updated message text (%.1fs)",
            self._stage1_duration,
        )

    def shutdown(self) -> None:
        """Stop the HTTP server. Called during service shutdown."""
        if self._http_server:
            self._http_server.shutdown()
            logger.info("Audio HTTP server stopped")
