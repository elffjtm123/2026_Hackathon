import struct
from uuid import UUID

from app.ai.base import MediaPayload

HEADER = struct.Struct(">BBIQQI")


def decode_media_v2(raw: bytes, session_id: UUID, audio_origin_ms: int) -> MediaPayload:
    if not HEADER.size < len(raw) <= 2 * 1024 * 1024:
        raise ValueError("INVALID_MEDIA_SIZE")
    version, kind, sequence, timestamp, start, count = HEADER.unpack_from(raw)
    if version != 2 or kind not in {1, 2} or sequence == 0:
        raise ValueError("INVALID_MEDIA_HEADER")
    payload = raw[HEADER.size :]
    if kind == 1:
        if start or count:
            raise ValueError("INVALID_VIDEO_SAMPLES")
    elif not 0 < count <= 16000 or len(payload) != count * 2:
        raise ValueError("INVALID_PCM_LENGTH")
    elif timestamp != audio_origin_ms + start * 1000 // 16000:
        raise ValueError("INVALID_AUDIO_TIMESTAMP")
    return MediaPayload(
        session_id, timestamp, payload, sequence, start, count, "jpeg" if kind == 1 else "pcm16"
    )
