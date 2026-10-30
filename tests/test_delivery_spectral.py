import math

import numpy as np

from app.modules.delivery.spectral import spectral_balance

RATE = 16_000
FRAME = 320


def frame(samples) -> bytes:
    return (np.asarray(samples) * 32767).astype("<i2").tobytes()


def sine(freq: float, amplitude: float = 0.3) -> bytes:
    return frame(amplitude * np.sin(2 * math.pi * freq * np.arange(FRAME) / RATE))


def noise(scale: float = 0.1, seed: int = 0) -> bytes:
    return frame(np.random.default_rng(seed).normal(scale=scale, size=FRAME))


def test_low_sine_has_clearly_higher_alpha_ratio_than_noise_or_high_sine():
    low, _ = spectral_balance(sine(300))
    white, _ = spectral_balance(noise())
    high, _ = spectral_balance(sine(3000))
    assert low > white + 15
    assert low > high + 15
    assert -12 < white < 0  # roughly 10*log10(950/4000)


def test_hammarberg_is_high_for_low_sine_and_low_for_high_sine():
    _, low = spectral_balance(sine(300))
    _, white = spectral_balance(noise())
    _, high = spectral_balance(sine(3000))
    assert low > white + 15
    assert high < white - 15


def test_level_does_not_change_the_balance():
    quiet = spectral_balance(noise(0.02))
    loud = spectral_balance(noise(0.2))
    assert quiet and loud
    assert abs(quiet[0] - loud[0]) < 0.5
    assert abs(quiet[1] - loud[1]) < 0.5


def test_silence_and_short_frames_have_no_balance():
    assert spectral_balance(frame(np.zeros(FRAME))) is None
    assert spectral_balance(b"\0\0" * 10) is None


def test_dc_offset_does_not_change_hammarberg():
    clean = spectral_balance(sine(300, 0.01))
    offset = spectral_balance(
        frame(0.01 * np.sin(2 * math.pi * 300 * np.arange(FRAME) / RATE) + 0.2)
    )
    assert clean and offset
    assert abs(clean[1] - offset[1]) < 5  # about 34 dB off while DC sat in the low band
