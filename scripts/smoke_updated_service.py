"""Opt-in end-to-end check with a public fixture, never camera/microphone input."""

import asyncio
import json
import struct
import time
import wave
from pathlib import Path

import httpx
import websockets


async def main() -> None:
    with wave.open(".models/stt/smoke-audio/test_wavs/0.wav", "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
        pcm = audio.readframes(audio.getnframes())
    async with websockets.connect(
        "ws://127.0.0.1:8000/api/v1/ws/practice-demo?protocol=2"
    ) as socket:
        identity = None

        async def control(
            event: str, sequence: int, timestamp: int = 0, data: dict | None = None
        ) -> None:
            await socket.send(
                json.dumps(
                    {
                        "event": event,
                        "version": 2,
                        "session_id": identity,
                        "sequence": sequence,
                        "module": "system",
                        "level": "info",
                        "timestamp_ms": timestamp,
                        "data": data or {},
                    }
                )
            )

        async def until(event: str, timeout: float = 130) -> dict:
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout))
                if message["event"] == "error":
                    raise RuntimeError(message["data"])
                if message["event"] == event:
                    return message

        await control(
            "session.start",
            1,
            data={
                "mode": "interview",
                "settings": {"gaze_enabled": False},
                "stt_model_id": "service_qwen",
            },
        )
        ready = await until("session.ready")
        identity = ready["session_id"]
        print(json.dumps({"modules": ready["data"]["modules"]}, ensure_ascii=False), flush=True)
        offset, started = ready["timestamp_ms"], time.monotonic()
        await control("session.audio_settings", 2, offset, {"audio_settings": {"autoGainControl": False}})
        await control("calibration.start", 3, offset)
        running = await until("session.running")
        origin = running["data"]["audio_origin_ms"]
        for sequence, start in enumerate(range(0, len(pcm), 6400), 1):
            block = pcm[start : start + 6400]
            await socket.send(
                struct.pack(
                    ">BBIQQI", 2, 2, sequence, origin + start // 32, start // 2, len(block) // 2
                )
                + block
            )
            await until("media.ack", 10)
            await asyncio.sleep(len(block) / 32000)
        await control("session.end", 4, offset + round((time.monotonic() - started) * 1000))
        report = (await until("session.completed", 45))["data"]["report"]
        assert not report["incomplete"], report
        assert report["transcript"], report
        delivery = report["delivery_metrics"]
        assert delivery["status"] in {"observed", "unavailable"}, delivery
        assert delivery["agc_on"] is False
        assert delivery["report"]["total_voiced_ms"] > 0
        assert any(row["f0_median_hz"] is not None for row in delivery["windows"]["windows"]), delivery
        Path(".logs/voice-delivery-public-smoke.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        print(
            json.dumps(
                {
                    "completed": True,
                    "public_sample_transcript": report["transcript"],
                    "speech_rate_metrics": report["speech_rate_metrics"],
                    "voice_feature_windows": len(delivery["windows"]["windows"]),
                    "voiced_ms": delivery["report"]["total_voiced_ms"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    async with httpx.AsyncClient() as client:
        status = (await client.get("http://127.0.0.1:8000/health/ready")).json()
        assert all(module["status"] == "idle" for module in status["modules"].values()), status
        print("Real model processes released after completion.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
