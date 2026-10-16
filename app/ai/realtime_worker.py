"""The fresh interpreter that owns all local realtime model weights."""

import asyncio
import os
import sys
from collections.abc import Callable
from typing import Any

from app.ai.base import GazeAdapter, SpeechAdapter
from app.ai.worker_transport import (
    MAX_JSON_BYTES,
    MODALITIES,
    MODEL_SETTINGS,
    ProtocolError,
    decode_media,
    encode_frame,
    read_frame,
    request_id,
    result_metadata,
    write_frame,
)
from app.core.config import Settings

Factory = Callable[[Settings], GazeAdapter | SpeechAdapter]


def _gaze(settings: Settings) -> GazeAdapter:
    from app.main import create_local_gaze_adapter

    return create_local_gaze_adapter(settings)


def _speech(settings: Settings) -> SpeechAdapter:
    from app.ai.local_stt import create_local_qwen_speech_adapter

    return create_local_qwen_speech_adapter(
        settings.stt_model,
        settings.stt_device,
        settings.stt_context,
        settings.stt_silence_rms_threshold,
        settings.stt_library_path,
    )


async def serve(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    gaze_factory: Factory = _gaze,
    speech_factory: Factory = _speech,
) -> None:
    models: dict[str, GazeAdapter | SpeechAdapter] = {}
    active: dict[str, asyncio.Task[None]] = {}
    loading: asyncio.Task[dict[str, Any]] | None = None
    receive: asyncio.Task[tuple[dict[str, Any], bytes]] | None = None
    lock = asyncio.Lock()

    async def send(metadata: dict[str, Any]) -> None:
        async with lock:
            await write_frame(writer, metadata)

    async def infer(message: dict[str, Any], payload: bytes) -> None:
        modality, identity = message["module"], message["id"]
        try:
            try:
                result = await models[modality].infer(decode_media(message["media"], payload))
                response = {
                    "type": "result",
                    "id": identity,
                    "module": modality,
                    "result": result_metadata(result),
                }
                # Validate size before sending any header; oversized outputs fail safely.
                encode_frame(response)
            except Exception:
                response = {
                    "type": "error",
                    "id": identity,
                    "module": modality,
                    "reason": "INFERENCE_FAILED",
                }
            await send(response)
        except (ConnectionError, OSError):
            writer.close()
        finally:
            active.pop(modality, None)

    try:
        init, payload = await read_frame(reader)
        if init.keys() != {"type", "settings"} or init["type"] != "init" or payload:
            raise ProtocolError()
        if not isinstance(init["settings"], dict) or init["settings"].keys() != MODEL_SETTINGS:
            raise ProtocolError()
        settings = Settings(_env_file=None, **init["settings"])

        def load() -> dict[str, Any]:
            statuses = {}
            for modality, factory in (("gaze", gaze_factory), ("speech", speech_factory)):
                status: dict[str, Any] = {
                    "status": "unavailable",
                    "reason": "MODEL_LOAD_FAILED",
                    "device": None,
                }
                try:
                    model = factory(settings)
                    models[modality] = model
                    if not hasattr(model, "reason"):
                        device = getattr(model, "device", None)
                        status = {
                            "status": "ready",
                            "reason": None,
                            "device": device if device in {"cpu", "mps", "cuda"} else None,
                        }
                except Exception:
                    pass
                statuses[modality] = status
            return statuses

        # Keep watching EOF while model constructors run in a native thread.
        receive = asyncio.create_task(read_frame(reader))
        loading = asyncio.create_task(asyncio.to_thread(load))
        done, _ = await asyncio.wait((receive, loading), return_when=asyncio.FIRST_COMPLETED)
        if receive in done:
            return
        statuses = loading.result()
        await send({"type": "ready", "modules": statuses})
        last_id = 0
        while True:
            message, payload = await receive
            if message == {"type": "stop"} and not payload:
                return
            if message.keys() != {"type", "id", "module", "media"}:
                raise ProtocolError()
            modality = message["module"]
            if (
                message["type"] != "infer"
                or not isinstance(modality, str)
                or modality not in MODALITIES
                or modality in active
                or statuses[modality]["status"] != "ready"
            ):
                raise ProtocolError()
            identity = request_id(message["id"])
            if identity <= last_id:
                raise ProtocolError()
            decode_media(message["media"], payload)
            last_id = identity
            active[modality] = asyncio.create_task(infer(message, payload))
            receive = asyncio.create_task(read_frame(reader))
    except (Exception, asyncio.CancelledError):
        # Neither exception text nor raw media is ever returned or logged.
        pass
    finally:
        writer.close()
        tasks = [*active.values(), *([receive] if receive else []), *([loading] if loading else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for model in models.values():
            try:
                close = getattr(model, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass


async def run(
    socket_path: str,
    *,
    gaze_factory: Factory = _gaze,
    speech_factory: Factory = _speech,
) -> None:
    reader, writer = await asyncio.open_unix_connection(socket_path, limit=MAX_JSON_BYTES)
    await serve(reader, writer, gaze_factory=gaze_factory, speech_factory=speech_factory)


def main() -> None:
    loop = asyncio.new_event_loop()
    code = 0
    try:
        loop.run_until_complete(run(sys.argv[1]))
    except BaseException:
        code = 1
    finally:
        # asyncio.run waits for native executor threads; EOF must instead end their process.
        loop.close()
        os._exit(code)


if __name__ == "__main__":
    main()
