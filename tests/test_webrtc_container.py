"""Test WebRTC audio push from inside the Docker container (localhost to go2rtc)."""
import asyncio
import json
import time
import os

async def main():
    import websockets
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer

    # Generate test audio at 48kHz for Opus
    os.system(
        "ffmpeg -y -f lavfi -i sine=frequency=800:duration=3:sample_rate=48000 "
        "-af volume=5.0 -ar 48000 -ac 1 -acodec pcm_s16le "
        "-f wav /tmp/webrtc_test.wav 2>/dev/null"
    )
    print("Generated 48kHz test audio")

    pc = RTCPeerConnection()
    player = MediaPlayer("/tmp/webrtc_test.wav")

    if player.audio:
        pc.addTrack(player.audio)
        print("Audio track added")
    else:
        print("No audio track!")
        return

    @pc.on("connectionstatechange")
    async def on_conn():
        print(f"  conn={pc.connectionState}")

    @pc.on("iceconnectionstatechange")
    async def on_ice():
        print(f"  ice={pc.iceConnectionState}")

    # Connect to go2rtc on localhost (same container host)
    ws_url = "ws://localhost:1984/api/ws?dst=frontdoor"
    print(f"Connecting to {ws_url}")

    async with websockets.connect(ws_url, open_timeout=5) as ws:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        # Wait for ICE gathering
        while pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)

        sdp = pc.localDescription.sdp
        print(f"Sending offer ({len(sdp)} bytes)")

        await ws.send(json.dumps({
            "type": "webrtc/offer",
            "value": sdp,
        }))

        # Get answer
        connected = False
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mtype = data.get("type", "")
                if mtype == "webrtc/answer":
                    answer_sdp = data["value"]
                    answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
                    await pc.setRemoteDescription(answer)
                    connected = True
                    print("Got answer")
                    for line in answer_sdp.split("\r\n"):
                        if "rtpmap" in line:
                            print(f"  {line}")
            except asyncio.TimeoutError:
                break

        if not connected:
            print("FAILED")
            await pc.close()
            return

        print("Waiting 6s for audio to play...")
        await asyncio.sleep(6)

        # Check stats
        stats = await pc.getStats()
        for s in stats.values():
            if hasattr(s, "bytesSent") and s.bytesSent > 0:
                print(f"  RTP sent: {s.bytesSent} bytes, {s.packetsSent} packets")

        print(f"Final: conn={pc.connectionState} ice={pc.iceConnectionState}")

    await pc.close()
    player.audio.stop()
    print("Done")

asyncio.run(main())
