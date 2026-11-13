"""Spectral balance of one voiced 20 ms frame (eGeMAPS alpha ratio and Hammarberg index)."""

import numpy as np

from app.modules.delivery.f0 import SAMPLE_RATE

FFT_SIZE = 512
MIN_ENERGY = 1e-12


def spectral_balance(pcm: bytes) -> tuple[float, float] | None:
    """Return (alpha_ratio_db, hammarberg_db) for a PCM16 frame, or None for silence.

    Both are low-band over high-band, in dB, so a larger value means more low-frequency energy
    (softer, less tense voice) and a smaller value means more high-frequency energy:
    - alpha ratio = 10*log10(sum of power 50-1000 Hz / sum of power 1-5 kHz)
    - Hammarberg = 10*log10(strongest bin 0-2 kHz / strongest bin 2-5 kHz)
    The frame mean is removed, then a Hann window is applied; the Hammarberg low band starts
    at the first non-DC bin. Frames with no energy in 0-5 kHz return None.
    """
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float64) / 32768
    if samples.size < 2:
        return None
    samples = samples - samples.mean()
    power = np.abs(np.fft.rfft(samples * np.hanning(samples.size), n=FFT_SIZE)) ** 2
    freqs = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)

    def band(low: float, high: float) -> np.ndarray:
        return power[(freqs >= low) & (freqs < high)]

    low_sum, high_sum = band(50, 1000).sum(), band(1000, 5000).sum()
    low_peak, high_peak = band(1, 2000).max(), band(2000, 5000).max()
    if low_sum + high_sum < MIN_ENERGY:
        return None

    def db(numerator: float, denominator: float) -> float:
        return float(10 * np.log10(max(numerator, MIN_ENERGY) / max(denominator, MIN_ENERGY)))

    return db(low_sum, high_sum), db(low_peak, high_peak)
