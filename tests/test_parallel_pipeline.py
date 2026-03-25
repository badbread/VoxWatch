"""Test parallel pipeline: warmup + AI + TTS run concurrently."""
import asyncio
import aiohttp
import time
import os
import subprocess

CAMERA = "frontdoor"
GO2RTC = "http://localhost:1984"
KOKORO = "http://localhost:8880"
AUDIO_DIR = "/data/audio"
SERVE_HOST = "localhost"
SERVE_PORT = 8891
MESSAGE = "Attention. Individual in dark clothing detected near front door. You are being recorded."

async def warmup():
    """Send warmup push to prime the backchannel."""
    start = time.monotonic()
    url = f"{GO2RTC}/api/ffmpeg?dst={CAMERA}&file=http://{SERVE_HOST}:{SERVE_PORT}/warmup_silent.wav"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = time.monotonic() - start
            print(f"  Warmup: {elapsed:.3f}s (HTTP {resp.status})")
            return elapsed

async def generate_tts():
    """Generate TTS via Kokoro and convert to PCMU."""
    start = time.monotonic()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{KOKORO}/tts",
            json={"text": MESSAGE, "voice": "am_fenrir", "speed": 1.0},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.read()
            tts_path = os.path.join(AUDIO_DIR, "parallel_tts.wav")
            with open(tts_path, "wb") as f:
                f.write(data)
            tts_time = time.monotonic() - start
            print(f"  TTS: {tts_time:.3f}s ({len(data)} bytes)")

    # Convert to PCMU
    ready_path = os.path.join(AUDIO_DIR, "parallel_ready.wav")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", tts_path,
        "-ar", "8000", "-ac", "1", "-acodec", "pcm_mulaw",
        "-f", "wav", ready_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    convert_time = time.monotonic() - start - tts_time
    print(f"  Convert: {convert_time:.3f}s")
    return time.monotonic() - start

async def push_audio():
    """Push the generated audio."""
    start = time.monotonic()
    url = f"{GO2RTC}/api/ffmpeg?dst={CAMERA}&file=http://{SERVE_HOST}:{SERVE_PORT}/parallel_ready.wav"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = time.monotonic() - start
            print(f"  Push: {elapsed:.3f}s (HTTP {resp.status})")
            return elapsed

async def main():
    print("=" * 50)
    print("  Parallel Pipeline Test")
    print("=" * 50)

    pipeline_start = time.monotonic()

    # Phase 1: Warmup + TTS in parallel
    print("\nPhase 1: Warmup + TTS (parallel)")
    warmup_task = asyncio.create_task(warmup())
    tts_task = asyncio.create_task(generate_tts())

    warmup_time = await warmup_task
    tts_time = await tts_task
    phase1 = time.monotonic() - pipeline_start
    print(f"  Phase 1 total: {phase1:.3f}s")

    # Phase 2: Push (backchannel should be warm)
    print("\nPhase 2: Push audio")
    push_time = await push_audio()

    total = time.monotonic() - pipeline_start
    print(f"\n{'=' * 50}")
    print(f"  TOTAL: {total:.3f}s")
    print(f"  Warmup: {warmup_time:.3f}s (parallel)")
    print(f"  TTS+Convert: {tts_time:.3f}s (parallel)")
    print(f"  Push: {push_time:.3f}s (serial)")
    print(f"  Overhead hidden by parallelism: {max(0, warmup_time - tts_time):.3f}s")
    print(f"{'=' * 50}")

asyncio.run(main())
