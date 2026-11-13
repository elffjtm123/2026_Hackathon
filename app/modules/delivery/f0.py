"""F0 extraction seam: PCM16 bytes to voiced (offset_ms, Hz) pairs, offset from the PCM start."""

from collections.abc import Callable, Sequence

F0Extractor = Callable[[bytes], Sequence[tuple[int, float]]]

SAMPLE_RATE = 16_000
PITCH_FLOOR_HZ = 75.0
PITCH_CEILING_HZ = 500.0
MIN_SAMPLES = SAMPLE_RATE // 10


def parselmouth_f0(pcm: bytes) -> list[tuple[int, float]]:
    import numpy as np
    import parselmouth

    if len(pcm) // 2 < MIN_SAMPLES:
        return []
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float64) / 32768
    pitch = parselmouth.Sound(samples, sampling_frequency=SAMPLE_RATE).to_pitch(
        pitch_floor=PITCH_FLOOR_HZ, pitch_ceiling=PITCH_CEILING_HZ
    )
    hz = pitch.selected_array["frequency"]
    times = pitch.xs()
    voiced = hz > 0
    return [
        (round(float(t) * 1000), float(f)) for t, f in zip(times[voiced], hz[voiced], strict=True)
    ]
