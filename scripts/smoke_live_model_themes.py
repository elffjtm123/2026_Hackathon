"""Opt-in localhost check using public samples, never user's camera/microphone.

Requires an already-running local server and prepared model files. This checks
real inference integration, not model accuracy or directional gaze accuracy.
Portrait: https://storage.googleapis.com/mediapipe-assets/portrait.jpg
Audio: Korean sherpa-onnx public test_wavs/0.wav from the prepared smoke assets.
"""

import asyncio
import json
import struct
import time
import wave
from pathlib import Path

import cv2
import httpx
import websockets

from app.ai.experimental_stt import MODEL_IDS


async def run_model(model_id, jpeg, pcm):
    async with websockets.connect(
        "ws://127.0.0.1:8000/api/v1/ws/practice-demo?protocol=2", max_size=2097152
    ) as socket:
        identity = None
        sequence = 0
        received = []
        reference = "그는 괜찮은 척하려고 애쓰는 것 같았다"
        clock = time.monotonic()
        offset = 0

        def elapsed():
            return offset + round((time.monotonic() - clock) * 1000)

        async def control(event, data=None):
            nonlocal sequence
            sequence += 1
            await socket.send(
                json.dumps(
                    {
                        "event": event,
                        "version": 2,
                        "module": "system",
                        "level": "info",
                        "session_id": identity,
                        "sequence": sequence,
                        "timestamp_ms": elapsed(),
                        "data": data or {},
                    }
                )
            )

        async def until(event):
            for _ in range(100):
                result = json.loads(await asyncio.wait_for(socket.recv(), 240))
                received.append(result)
                if result["event"] == "error":
                    raise RuntimeError(result["data"])
                if result["event"] == event:
                    return result
            raise RuntimeError(f"Missing {event}")

        await control(
            "session.start",
            {
                "mode": "presentation",
                "stt_model_id": model_id,
                "script": reference,
                "time_limit_seconds": 180,
            },
        )
        ready = await until("session.ready")
        assert ready["data"]["comparison"]["model_id"] == model_id
        identity, clock, offset = ready["session_id"], time.monotonic(), ready["timestamp_ms"]
        await control("calibration.start")
        calibration = await until("session.calibrating")
        clock, offset = time.monotonic(), calibration["timestamp_ms"]
        video_sequence = 0
        for _ in range(16):
            video_sequence += 1
            await socket.send(struct.pack(">BBIQQI", 2, 1, video_sequence, elapsed(), 0, 0) + jpeg)
            gaze = await until("feedback")
            if gaze["data"]["metrics"].get("calibrated"):
                break
            await asyncio.sleep(0.12)
        else:
            await control("session.end")
            await until("session.completed")
            raise RuntimeError(f"Public portrait did not calibrate: {gaze['data']['metrics']}")
        running = await until("session.running")
        origin = running["data"]["audio_origin_ms"]

        async def send_video():
            nonlocal video_sequence
            while True:
                video_sequence += 1
                await socket.send(
                    struct.pack(">BBIQQI", 2, 1, video_sequence, elapsed(), 0, 0) + jpeg
                )
                await asyncio.sleep(0.35)

        video = asyncio.create_task(send_video())
        try:
            for start in range(0, len(pcm) // 2, 3200):
                target = origin + start // 16
                await asyncio.sleep(max(0, (target - elapsed()) / 1000))
                payload = pcm[start * 2 : (start + 3200) * 2]
                await socket.send(
                    struct.pack(
                        ">BBIQQI", 2, 2, start // 3200 + 1, target, start, len(payload) // 2
                    )
                    + payload
                )
                await until("media.ack")
            # Keep the vision loop active during the accepted final packet.
            await asyncio.sleep(0.2)
        finally:
            video.cancel()
            await asyncio.gather(video, return_exceptions=True)
        await control("session.end")
        report = (await until("session.completed"))["data"]["report"]
        assert not report["incomplete"], report["comparison"]["errors"]
        assert report["transcript"], "no actual transcription"
        assert report["comparison"]["performance"]["gaze"]["observations"] > 0
        return {
            "model_id": model_id,
            "report": report,
            "feedback_sources": sorted(
                {e["data"]["source"] for e in received if e["event"] == "feedback"}
            ),
        }


async def main():
    root = Path(".models/stt/smoke-audio")
    frame = cv2.imread(str(root / "portrait.jpg"))
    if frame is None:
        raise RuntimeError("Official public portrait sample is not prepared")
    scale = min(1, 640 / max(frame.shape[:2]))
    frame = cv2.resize(frame, None, fx=scale, fy=scale)
    ok, jpeg = cv2.imencode(".jpg", frame)
    assert ok
    with wave.open(str(root / "test_wavs/0.wav")) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
        pcm = audio.readframes(audio.getnframes())
    results = []
    async with httpx.AsyncClient() as client:
        for model in MODEL_IDS:
            for _ in range(100):
                state = (
                    await client.get("http://127.0.0.1:8000/api/v1/stt-experiments/models")
                ).json()
                if not state["busy"]:
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Another session is active; smoke check did not start")
            result = await run_model(model, jpeg.tobytes(), pcm)
            results.append(result)
            report = result["report"]
            print(
                json.dumps(
                    {
                        "model_id": model,
                        "incomplete": report["incomplete"],
                        "transcript": report["transcript"],
                        "comparison": report["comparison"],
                        "feedback_sources": result["feedback_sources"],
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
    print(f"Completed {len(results)} real model + vision integration checks", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
