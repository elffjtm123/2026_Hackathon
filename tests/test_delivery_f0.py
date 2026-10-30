import math
import struct

import pytest

pytest.importorskip("parselmouth")

from app.modules.delivery.f0 import parselmouth_f0  # noqa: E402
from app.modules.delivery.features import pvq  # noqa: E402


def pcm(freq_at, seconds=1.0, rate=16_000):
    phase, out = 0.0, []
    for n in range(int(seconds * rate)):
        phase += 2 * math.pi * freq_at(n / rate) / rate
        out.append(int(8000 * math.sin(phase)))
    return struct.pack(f"<{len(out)}h", *out)


def hz_of(pairs):
    return [hz for _, hz in pairs]


def test_steady_200hz_sine_has_f0_near_200_and_tiny_pvq():
    pairs = parselmouth_f0(pcm(lambda t: 200.0))
    values = hz_of(pairs)
    assert len(values) > 50
    assert sum(values) / len(values) == pytest.approx(200, abs=3)
    assert (pvq(values) or 0) < 0.02
    times = [t for t, _ in pairs]
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    assert 0 <= times[0] and times[-1] <= 1000


def test_f0_offsets_follow_the_voiced_part_of_the_signal():
    tone = pcm(lambda t: 200.0, 1.0)
    pairs = parselmouth_f0(b"\0\0" * 16000 + tone)
    assert pairs
    assert min(t for t, _ in pairs) >= 900
    assert max(t for t, _ in pairs) <= 2000


def test_pitch_modulation_raises_pvq():
    values = hz_of(parselmouth_f0(pcm(lambda t: 200 + 40 * math.sin(2 * math.pi * 3 * t), 2.0)))
    assert sum(values) / len(values) == pytest.approx(200, abs=10)
    assert (pvq(values) or 0) > 0.08


def test_silence_and_too_short_audio_have_no_f0():
    assert parselmouth_f0(b"\0\0" * 16000) == []
    assert parselmouth_f0(b"\0\0" * 100) == []
