"""
Test persistent RTSP backchannel connection.

Opens a direct RTSP connection to the camera, negotiates backchannel,
then streams continuous silence with occasional audio injection.
Bypasses go2rtc entirely for the audio path.

This is the "live microphone" approach — the RTSP session stays open
and we inject audio into the continuous stream.

Usage:
    python tests/test_persistent_backchannel.py --camera 192.168.1.100
"""
import argparse
import asyncio
import os
import struct
import subprocess
import sys
import time
import wave


async def test_persistent(camera_ip: str, username: str, password: str):
    """Test persistent backchannel by connecting directly to camera RTSP."""

    print(f"Camera: {camera_ip}")
    print(f"Connecting via ffmpeg as RTSP client...\n")

    # Approach: ffmpeg reads from pipe (continuous PCM), outputs to RTSP
    # The -re flag ensures real-time pacing
    # The camera URL with backchannel negotiation
    rtsp_url = f"rtsp://{username}:{password}@{camera_ip}/Preview_01_sub"

    # Step 1: Test if ffmpeg can connect and hold the backchannel
    # Use -stream_loop -1 on a silence file to keep streaming forever
    silence_path = "/tmp/persistent_silence.wav"

    # Generate 10s of silence (will loop)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
        "-t", "10",
        "-acodec", "pcm_mulaw", "-ar", "8000", "-ac", "1",
        "-f", "wav", silence_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    print(f"[OK] Silence file: {os.path.getsize(silence_path)} bytes")

    # Step 2: Start ffmpeg that loops silence to camera backchannel
    # Using -stream_loop -1 for infinite looping
    # -f rtsp output with the camera as destination
    print("\nStarting persistent ffmpeg connection...")
    print("(This will stream silence to keep backchannel alive)")

    ffmpeg_proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-re",  # Real-time pacing
        "-stream_loop", "-1",  # Loop forever
        "-i", silence_path,
        "-acodec", "pcm_mulaw",
        "-ar", "8000", "-ac", "1",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        rtsp_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Wait 5s and check if it's still running
    await asyncio.sleep(5)

    if ffmpeg_proc.returncode is not None:
        stderr = await ffmpeg_proc.stderr.read()
        print(f"[FAIL] ffmpeg exited (rc={ffmpeg_proc.returncode})")
        print(f"  stderr: {stderr.decode()[-500:]}")
        return

    print("[OK] ffmpeg still running after 5s")
    print("     Backchannel should be streaming silence")
    print("     >>> Can you hear anything from the camera? (should be silent) <<<\n")

    # Step 3: Now inject real audio by stopping the silence and playing a file
    # Kill the silence ffmpeg and immediately start a new one with audio
    print("Injecting test audio...")
    ffmpeg_proc.terminate()
    await asyncio.sleep(0.5)

    # Generate test audio
    test_path = "/tmp/persistent_test.wav"
    test_proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=800:duration=3:sample_rate=8000",
        "-af", "volume=5.0",
        "-acodec", "pcm_mulaw", "-ar", "8000", "-ac", "1",
        "-f", "wav", test_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await test_proc.wait()

    # Push via go2rtc (backchannel should be warm from the persistent connection)
    start = time.monotonic()
    push_proc = await asyncio.create_subprocess_exec(
        "curl", "-s", "-X", "POST",
        f"http://localhost:1984/api/ffmpeg?dst=frontdoor&file=http://localhost:8891/stage1_cached.wav",
        "-o", "/dev/null", "-w", "%{http_code}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await push_proc.communicate()
    elapsed = time.monotonic() - start
    print(f"  Push after persistent connection: {elapsed:.3f}s (HTTP {stdout.decode()})")
    print("  >>> Did you hear audio? <<<")


async def test_pipe_approach(camera_ip: str, username: str, password: str):
    """Test the pipe-based persistent stream approach.

    Keeps ffmpeg running with stdin as input, writes silence continuously,
    and injects real audio when needed.
    """
    print(f"\n{'='*50}")
    print(f"  Pipe-based Persistent Stream Test")
    print(f"{'='*50}\n")

    # ffmpeg reads raw PCMU from pipe, outputs to... what?
    # Problem: ffmpeg can't output to RTSP backchannel as a client
    # It can only ANNOUNCE to an RTSP server (which cameras reject)

    # Alternative: output to go2rtc via exec source
    # But go2rtc rejected exec: via API

    # Alternative: output RTP directly to go2rtc's backchannel port
    # go2rtc forwards it to the camera

    # Let's find go2rtc's backchannel RTP port for frontdoor
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:1984/api/streams?src=frontdoor") as resp:
            import json
            data = await resp.json()
            for p in data.get("producers", []):
                for s in p.get("senders", []):
                    print(f"  Sender: id={s.get('id')} codec={s.get('codec',{}).get('codec_name')}")
                    # Can we find the RTP port?
                    parent = s.get("parent")
                    print(f"    parent={parent}")

    print("\n  The pipe approach needs a destination port.")
    print("  go2rtc doesn't expose the backchannel RTP port.")
    print("  This approach requires go2rtc source code modification.")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", default="192.168.1.100")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="YOUR_CAMERA_PASSWORD")
    args = parser.parse_args()

    await test_persistent(args.camera, args.user, args.password)
    await test_pipe_approach(args.camera, args.user, args.password)


if __name__ == "__main__":
    asyncio.run(main())
