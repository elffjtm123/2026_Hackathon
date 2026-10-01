import importlib.util
import struct
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.realtime import events


def decoder():
    assert importlib.util.find_spec("app.realtime.media") is not None, "v2 media decoder missing"
    from app.realtime.media import decode_media_v2

    return decode_media_v2


def test_pcm_printable_bytes_remain_audio():
    media = decoder()(struct.pack(">BBIQQI", 2, 2, 1, 0, 0, 8) + b"AB" * 8, uuid4(), 0)
    assert media.payload == b"AB" * 8
    assert media.sample_count == 8
    assert media.format == "pcm16"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        struct.pack(">BBIQQI", 2, 2, 1, 0, 0, 8) + b"AB",
        struct.pack(">BBIQQI", 2, 2, 1, 1, 0, 8) + b"AB" * 8,
        struct.pack(">BBIQQI", 2, 1, 1, 0, 1, 0) + b"jpeg",
        b"x" * (2 * 1024 * 1024 + 1),
    ],
    ids=["empty", "length", "time", "video", "oversize"],
)
def test_pcm_length_and_header_limits(raw):
    decode = decoder()
    with pytest.raises(ValueError):
        decode(raw, uuid4(), 0)


@pytest.mark.parametrize(
    "data",
    [
        {"timeLimitSeconds": 0},
        {"timeLimitSeconds": float("nan")},
        {"script": "x" * 20001, "timeLimitSeconds": 180},
        {"script": "hello"},
    ],
)
def test_start_rejects_invalid_settings(data):
    dto = getattr(events, "SessionStartData", None)
    assert dto is not None, "shared start validator missing"
    with pytest.raises(ValidationError):
        dto.model_validate(data)
