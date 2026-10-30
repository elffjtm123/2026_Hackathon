import struct
from uuid import uuid4

import pytest

from app.ai.base import MediaPayload


def segmenter():
    from app.modules.speech.segments import SpeechSegmenter

    # Deterministic VAD boundary; the real segment state machine is under test.
    return SpeechSegmenter(is_speech=lambda pcm: struct.unpack_from("<h", pcm)[0] > 0)


def frames(voiced: int, quiet: int = 0) -> bytes:
    return struct.pack("<h", 1000) * (voiced * 320) + b"\0\0" * (quiet * 320)


def test_silence_and_sub_onset_noise_do_not_create_segments():
    s = segmenter()
    media = MediaPayload(uuid4(), 0, frames(0, 20) + frames(4, 30), format="pcm16")
    assert s.feed(media) == []
    assert s.flush() == []


def test_100ms_voiced_tail_flushes_once():
    s = segmenter()
    data = frames(5)
    assert s.feed(MediaPayload(uuid4(), 0, data, format="pcm16")) == []
    results = s.flush()
    assert len(results) == 1
    assert (results[0].start_ms, results[0].end_ms, results[0].voiced_ms) == (0, 100, 100)
    assert results[0].pcm == data
    assert s.flush() == []


def test_endpoint_keeps_context_without_overlapping_next_utterance():
    s = segmenter()
    session = uuid4()
    first = frames(0, 5) + frames(10, 25)
    result = s.feed(MediaPayload(session, 0, first, format="pcm16"))
    assert len(result) == 1
    assert (result[0].start_ms, result[0].end_ms, result[0].voiced_ms) == (0, 400, 200)
    second = frames(10)
    assert s.feed(MediaPayload(session, 800, second, start_sample=12800, format="pcm16")) == []
    tail = s.flush()[0]
    assert (tail.start_ms, tail.end_ms, tail.voiced_ms) == (600, 1000, 200)
    assert tail.start_ms >= result[0].end_ms
    assert tail.utterance_id != result[0].utterance_id
    assert result[0].pcm == first[:12800]
    assert tail.pcm == first[19200:] + second


def test_max_8_second_split_preserves_each_sample_once():
    s = segmenter()
    data = b"".join(struct.pack("<h", 1000 + index) * 320 for index in range(450))
    outputs = s.feed(MediaPayload(uuid4(), 0, data, format="pcm16")) + s.flush()
    assert [(x.start_ms, x.end_ms, x.voiced_ms) for x in outputs] == [
        (0, 8000, 8000),
        (8000, 9000, 1000),
    ]
    assert b"".join(x.pcm for x in outputs) == data


def test_partial_frame_and_packet_boundaries_preserve_tail():
    s = segmenter()
    session = uuid4()
    data = frames(5) + struct.pack("<h", 1000) * 123
    assert s.feed(MediaPayload(session, 200, data[:1000], format="pcm16")) == []
    assert s.feed(MediaPayload(session, 231, data[1000:], start_sample=500, format="pcm16")) == []
    tail = s.flush()[0]
    assert tail.pcm == data
    assert tail.start_ms == 200
    assert tail.end_ms == 307
    assert tail.voiced_ms == 107


def test_pcm_gap_is_reported_without_mutating_accepted_samples():
    s = segmenter()
    session = uuid4()
    s.feed(MediaPayload(session, 0, frames(5), format="pcm16"))
    with pytest.raises(ValueError, match="PCM_SAMPLE_GAP"):
        s.feed(MediaPayload(session, 120, frames(5), start_sample=1920, format="pcm16"))
    assert s.flush()[0].pcm == frames(5)


def test_real_vad_rejects_silence_and_seeded_microphone_noise():
    import numpy as np

    from app.modules.speech.segments import SpeechSegmenter

    for data in [
        b"\0\0" * 32000,
        (np.random.default_rng(7).normal(0, 0.005, 32000) * 32767).astype("<i2").tobytes(),
    ]:
        s = SpeechSegmenter()
        assert s.feed(MediaPayload(uuid4(), 0, data, format="pcm16")) + s.flush() == []


def test_cut_reason_distinguishes_endpoint_max_length_and_flush():
    s = segmenter()
    session = uuid4()
    endpoint = s.feed(MediaPayload(session, 0, frames(10, 30), format="pcm16"))
    assert [x.cut_reason for x in endpoint] == ["endpoint"]
    s = segmenter()
    data = frames(450)
    outputs = s.feed(MediaPayload(uuid4(), 0, data, format="pcm16")) + s.flush()
    assert [x.cut_reason for x in outputs] == ["max_length", "flush"]
