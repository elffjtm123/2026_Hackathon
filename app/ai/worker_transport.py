"""Bounded private IPC: JSON metadata followed by unencoded media bytes."""

import asyncio
import json
import math
import struct
from dataclasses import fields
from typing import Any
from uuid import UUID

from app.ai.base import AIResult, MediaPayload

MAX_JSON_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
HEADER = struct.Struct(">II")
MODALITIES = {"gaze", "speech"}
MODEL_SETTINGS = {
    "vision_provider",
    "face_landmarker_path",
    "stt_provider",
    "stt_model",
    "stt_library_path",
    "stt_device",
    "stt_silence_rms_threshold",
}


class ProtocolError(ValueError):
    def __init__(self) -> None:
        super().__init__("INVALID_WORKER_FRAME")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError()
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ProtocolError()


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolError()
    return result


def encode_frame(metadata: dict[str, Any], payload: bytes = b"") -> bytes:
    raw = bytearray()
    try:
        for part in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(metadata):
            if len(part) > MAX_JSON_BYTES:
                raise ProtocolError()
            chunk = part.encode("utf-8")
            if len(raw) + len(chunk) > MAX_JSON_BYTES:
                raise ProtocolError()
            raw.extend(chunk)
    except (ValueError, TypeError, RecursionError):
        raise ProtocolError() from None
    if not 0 < len(raw) <= MAX_JSON_BYTES or len(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolError()
    return HEADER.pack(len(raw), len(payload)) + raw


async def read_frame(reader: asyncio.StreamReader) -> tuple[dict[str, Any], bytes]:
    json_size, payload_size = HEADER.unpack(await reader.readexactly(HEADER.size))
    if not 0 < json_size <= MAX_JSON_BYTES or payload_size > MAX_PAYLOAD_BYTES:
        raise ProtocolError()
    raw = await reader.readexactly(json_size)
    try:
        metadata = json.loads(
            raw,
            object_pairs_hook=_object,
            parse_constant=_nonfinite,
            parse_float=_float,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ProtocolError() from None
    if not isinstance(metadata, dict):
        raise ProtocolError()
    return metadata, await reader.readexactly(payload_size)


async def write_frame(
    writer: asyncio.StreamWriter, metadata: dict[str, Any], payload: bytes = b""
) -> None:
    writer.write(encode_frame(metadata, payload))
    await writer.drain()
    view = memoryview(payload)
    for offset in range(0, len(view), MAX_JSON_BYTES):
        writer.write(view[offset : offset + MAX_JSON_BYTES])
        await writer.drain()


def request_id(value: Any) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ProtocolError()
    return value


def media_metadata(media: MediaPayload) -> dict[str, Any]:
    metadata = {
        field.name: getattr(media, field.name) for field in fields(media) if field.name != "payload"
    }
    metadata["session_id"] = str(media.session_id)
    decode_media(metadata, media.payload)
    return metadata


def _integer(value: Any, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ProtocolError()


def decode_media(metadata: Any, payload: bytes) -> MediaPayload:
    names = {field.name for field in fields(MediaPayload)} - {"payload"}
    if not isinstance(metadata, dict) or metadata.keys() != names:
        raise ProtocolError()
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolError()
    for name in ("timestamp_ms", "sequence", "start_sample", "sample_count"):
        _integer(metadata[name])
    for name in ("end_ms", "voiced_ms"):
        _integer(metadata[name], optional=True)
    if not isinstance(metadata["format"], str) or not 0 < len(metadata["format"]) <= 64:
        raise ProtocolError()
    if metadata["cut_reason"] not in (None, "endpoint", "max_length", "flush"):
        raise ProtocolError()
    utterance = metadata["utterance_id"]
    if utterance is not None and (not isinstance(utterance, str) or len(utterance) > 256):
        raise ProtocolError()
    try:
        session_id = UUID(metadata["session_id"])
    except (ValueError, TypeError, AttributeError):
        raise ProtocolError() from None
    return MediaPayload(**{**metadata, "session_id": session_id, "payload": payload})


def result_metadata(result: AIResult) -> dict[str, Any]:
    metadata = {field.name: getattr(result, field.name) for field in fields(result)}
    decode_result(metadata)
    return metadata


def decode_result(metadata: Any) -> AIResult:
    if not isinstance(metadata, dict) or metadata.keys() != {f.name for f in fields(AIResult)}:
        raise ProtocolError()
    for name in ("source", "level", "message"):
        if not isinstance(metadata[name], str):
            raise ProtocolError()
    if metadata["source"] not in {"gaze", "speech_rate", "pronunciation", "script_sync"}:
        raise ProtocolError()
    if metadata["level"] not in {"info", "good", "warning", "critical"}:
        raise ProtocolError()
    if not isinstance(metadata["metrics"], dict):
        raise ProtocolError()
    if metadata["transcript"] is not None and not isinstance(metadata["transcript"], str):
        raise ProtocolError()
    if metadata["is_final"] is not None and type(metadata["is_final"]) is not bool:
        raise ProtocolError()
    _integer(metadata["timestamp_ms"])
    _integer(metadata["latency_ms"], optional=True)
    return AIResult(**metadata)
