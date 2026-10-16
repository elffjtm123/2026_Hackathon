"""Sample-indexed, non-overlapping final utterances for 16 kHz mono PCM16."""

import math
import struct
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.ai.base import MediaPayload

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 320


@dataclass(frozen=True, slots=True)
class FinalUtterance:
    utterance_id: str
    start_ms: int
    end_ms: int
    voiced_ms: int
    text: str
    revision: int = 1


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    utterance_id: str
    start_ms: int
    end_ms: int
    voiced_ms: int
    pcm: bytes
    start_sample: int


@dataclass(frozen=True, slots=True)
class _Frame:
    start: int
    pcm: bytes
    voiced: bool

    @property
    def end(self) -> int:
        return self.start + len(self.pcm) // 2


class SpeechSegmenter:
    def __init__(
        self,
        is_speech: Callable[[bytes], bool] | None = None,
        *,
        silence_rms_threshold: float = 0.003,
        onset_ms: int = 100,
        pre_roll_ms: int = 200,
        endpoint_ms: int = 500,
        post_roll_ms: int = 100,
        max_ms: int = 8000,
        observe_frame: Callable[[int, int, float, bool], None] | None = None,
    ) -> None:
        if not (0 < onset_ms <= pre_roll_ms < max_ms and 0 <= post_roll_ms < endpoint_ms):
            raise ValueError("INVALID_SEGMENT_SETTINGS")
        if is_speech is None:
            import webrtcvad

            vad = webrtcvad.Vad(2)

            def is_speech(pcm: bytes) -> bool:
                padded = pcm.ljust(FRAME_SAMPLES * 2, b"\0")
                samples = [x[0] for x in struct.iter_unpack("<h", pcm)]
                rms = math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768
                return rms >= silence_rms_threshold and vad.is_speech(padded, SAMPLE_RATE)

        self.is_speech = is_speech
        self.observe_frame = observe_frame
        self.onset_samples = onset_ms * 16
        self.endpoint_samples = endpoint_ms * 16
        self.post_roll_samples = post_roll_ms * 16
        self.max_samples = max_ms * 16
        self.history: deque[_Frame] = deque(maxlen=math.ceil((pre_roll_ms + onset_ms) / 20))
        self.active: list[_Frame] | None = None
        self.pending = b""
        self.pending_start = 0
        self.next_sample = 0
        self.origin_ms: int | None = None
        self.session_id: object = None
        self.onset = self.voiced_samples = self.quiet_samples = self.last_voiced_end = 0
        self.counter = 0

    @property
    def speaking(self) -> bool:
        return self.active is not None and self.quiet_samples < self.endpoint_samples

    def feed(self, media: MediaPayload) -> list[SpeechSegment]:
        count = len(media.payload) // 2
        if media.format != "pcm16" or len(media.payload) % 2 or not count:
            raise ValueError("INVALID_PCM")
        if media.sample_count not in (0, count):
            raise ValueError("INVALID_PCM_LENGTH")
        if media.start_sample != self.next_sample:
            raise ValueError("PCM_SAMPLE_GAP")
        origin = media.timestamp_ms - media.start_sample * 1000 // SAMPLE_RATE
        if self.origin_ms is not None and (
            abs(origin - self.origin_ms) > 1 or media.session_id != self.session_id
        ):
            raise ValueError("PCM_CLOCK_MISMATCH")
        self.origin_ms, self.session_id = origin, media.session_id
        self.next_sample += count
        data = self.pending + media.payload
        outputs = []
        full_bytes = len(data) // (FRAME_SAMPLES * 2) * (FRAME_SAMPLES * 2)
        for offset in range(0, full_bytes, FRAME_SAMPLES * 2):
            pcm = data[offset : offset + FRAME_SAMPLES * 2]
            outputs.extend(self._frame(_Frame(self.pending_start, pcm, self.is_speech(pcm))))
            self.pending_start += FRAME_SAMPLES
        self.pending = data[full_bytes:]
        return outputs

    def flush(self) -> list[SpeechSegment]:
        outputs = []
        if self.pending:
            outputs.extend(
                self._frame(_Frame(self.pending_start, self.pending, self.is_speech(self.pending)))
            )
            self.pending_start += len(self.pending) // 2
            self.pending = b""
        if self.active:
            outputs.extend(self._finish(self.active[-1].end))
        self.active = None
        self.history.clear()
        self.onset = 0
        return outputs

    def _frame(self, frame: _Frame) -> list[SpeechSegment]:
        samples = frame.end - frame.start
        if self.observe_frame is not None:
            assert self.origin_ms is not None
            values = [x[0] for x in struct.iter_unpack("<h", frame.pcm)]
            rms = math.sqrt(sum(x * x for x in values) / len(values)) / 32768
            self.observe_frame(
                self.origin_ms + frame.start * 1000 // SAMPLE_RATE,
                self.origin_ms + frame.end * 1000 // SAMPLE_RATE,
                rms,
                frame.voiced,
            )
        if self.active is None:
            self.history.append(frame)
            self.onset = self.onset + samples if frame.voiced else 0
            if self.onset < self.onset_samples:
                return []
            self.active = list(self.history)
            self.history.clear()
            self.voiced_samples = sum(len(x.pcm) // 2 for x in self.active if x.voiced)
            self.last_voiced_end = frame.end
            self.quiet_samples = 0
        else:
            self.active.append(frame)
            if frame.voiced:
                self.voiced_samples += samples
                self.last_voiced_end = frame.end
                self.quiet_samples = 0
            else:
                self.quiet_samples += samples
        if self.quiet_samples >= self.endpoint_samples:
            return self._finish(self.last_voiced_end + self.post_roll_samples)
        if frame.end - self.active[0].start >= self.max_samples:
            # ponytail: hard maximum may cut a word; no overlap until revision-aware STT.
            outputs = self._finish(frame.end)
            self.active = []  # Continue confirmed speech at the very next sample.
            return outputs
        return []

    def _finish(self, end: int) -> list[SpeechSegment]:
        frames = self.active or []
        outputs = []
        if frames and self.voiced_samples:
            start = frames[0].start
            end = min(end, frames[-1].end)
            self.counter += 1
            assert self.origin_ms is not None
            outputs.append(
                SpeechSegment(
                    f"u{self.counter}",
                    self.origin_ms + start * 1000 // SAMPLE_RATE,
                    self.origin_ms + end * 1000 // SAMPLE_RATE,
                    self.voiced_samples * 1000 // SAMPLE_RATE,
                    b"".join(x.pcm for x in frames)[: (end - start) * 2],
                    start,
                )
            )
        for frame in frames:
            if frame.end > end:
                start = max(frame.start, end)
                self.history.append(_Frame(start, frame.pcm[(start - frame.start) * 2 :], False))
        self.active = None
        self.onset = self.voiced_samples = self.quiet_samples = self.last_voiced_end = 0
        return outputs
