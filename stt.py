"""
실시간 음성 AI 분석 시스템 — 발표/면접 피드백 엔진
====================================================

설치:
    python -m pip install openai-whisper sounddevice numpy
    python -m pip install faster-whisper          # 권장: 더 빠른 STT
    python -m pip install sentence-transformers   # 맥락 분석 고품질 (선택)

실행:
    python stt.py                                        # 데이터셋 데모 (3개)
    python stt.py --mic                                  # 마이크 실시간 분석
    python stt.py --mic --question "자기소개 해주세요."
    python stt.py --demo --demo-n 5
    python stt.py --enrich --whisper-model small         # CSV STT 컬럼 추가

API 사용:
    engine = RealTimeAudioFeedbackEngine(stt_model_size="small")
    result = engine.analyze_audio_chunk(
        audio_path="chunk.wav",
        interview_question="프로젝트 경험을 설명해주세요.",
    )
    print(result)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

# ── 선택적 패키지 ──────────────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel as _FasterWhisper
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False

try:
    import whisper as _openai_whisper
    HAS_OPENAI_WHISPER = True
except ImportError:
    HAS_OPENAI_WHISPER = False

HAS_WHISPER = HAS_FASTER_WHISPER or HAS_OPENAI_WHISPER

try:
    import sounddevice as _sd
    HAS_MIC = True
except ImportError:
    HAS_MIC = False

try:
    from sentence_transformers import SentenceTransformer as _ST
    from sentence_transformers.util import cos_sim as _cos_sim
    HAS_SBERT = True
except ImportError:
    HAS_SBERT = False

# ── 경로 ──────────────────────────────────────────────────────────────────────
LABEL_ROOT = Path(__file__).resolve().parent
SAMPLE_ROOT = LABEL_ROOT.parent
AUDIO_ROOT = SAMPLE_ROOT / "01.원천데이터"
DEFAULT_OUTPUT_DIR = LABEL_ROOT / "features"

# ══════════════════════════════════════════════════════════════════════════════
# 기준값 — 상단에서 쉽게 조정 가능
# 데이터셋 기반 (AI Hub 채용면접, n=1302): p25=294 p50=332 p75=395 p90=443
# ══════════════════════════════════════════════════════════════════════════════
CPM_SLOW_THRESHOLD   = 200   # 이하 → SLOW
CPM_FAST_THRESHOLD   = 420   # 이상 → FAST
WPM_SLOW_THRESHOLD   = 50    # 어절/분 이하 → SLOW
WPM_FAST_THRESHOLD   = 110   # 어절/분 이상 → FAST

FILLER_HIGH_RATIO    = 0.12  # 전체 어절 대비 12% 초과 → HIGH
FILLER_MEDIUM_RATIO  = 0.05  # 5~12% → MEDIUM

CLARITY_LOW_LOGPROB  = -1.0  # avg_logprob 이하 → 낮은 신뢰도
CLARITY_HIGH_NSP     = 0.5   # no_speech_prob 이상 → 발화 없음 의심

RELEVANCE_ON_TOPIC   = 55    # 이상 → ON_TOPIC  (keyword 방식은 자연히 낮으므로 보수적 기준)
RELEVANCE_PARTIAL    = 28    # 이상 → PARTIALLY_OFF_TOPIC

MIC_SAMPLE_RATE = 16000
CHUNK_DURATION  = 5          # 초, 기본 청크 길이

# ── 습관어 목록 ────────────────────────────────────────────────────────────────
_SINGLE_FILLERS = [
    "어", "음", "아", "에", "으", "응", "흠",   # 주저 소리·변이형
    "뭐", "좀", "막", "약간", "그냥",
    "이제", "인제", "저기", "그", "일단", "사실",
    "뭔가", "아무튼", "어쨌든", "뭐냐", "자",
]
_MULTI_FILLERS = [
    "그러니까", "그니까", "그러니까요",
    "사실은", "기본적으로", "솔직히",
    "말하자면", "뭐랄까", "어떻게 보면",
    "있잖아요", "있잖아", "그래가지고",
    "다시 말해서", "솔직히 말해서",
    "어떻게 말하면", "그렇게 말하자면",
    "그러다 보니까", "뭔가 좀",
]

# ── 한국어 불용어 (맥락 키워드 추출용) ──────────────────────────────────────
_KO_STOPWORDS = {
    "이", "그", "저", "것", "수", "등", "및", "또", "를", "을", "가",
    "은", "는", "의", "에", "서", "와", "과", "도", "로", "으로", "하다",
    "있다", "되다", "하고", "에서", "부터", "까지", "라고",
}


# ══════════════════════════════════════════════════════════════════════════════
# 유틸리티
# ══════════════════════════════════════════════════════════════════════════════

def _load_wav_as_float32(audio_path: str) -> tuple[np.ndarray, int]:
    """WAV 파일 → (float32 배열 @16kHz, sample_rate). ffmpeg 불필요."""
    with wave.open(audio_path, "rb") as wf:
        channels    = wf.getnchannels()
        sample_rate = wf.getframerate()
        frames      = wf.readframes(wf.getnframes())

    audio = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        audio = audio[::channels]

    audio_f32 = audio.astype(np.float32) / 32768.0
    if sample_rate != 16000:
        ratio  = 16000 / sample_rate
        n_out  = int(len(audio_f32) * ratio)
        idxs   = np.linspace(0, len(audio_f32) - 1, n_out)
        audio_f32 = np.interp(idxs, np.arange(len(audio_f32)), audio_f32).astype(np.float32)
        sample_rate = 16000

    return audio_f32, sample_rate


def _int16_to_float32(audio_int16: np.ndarray, sample_rate: int) -> np.ndarray:
    audio_f32 = audio_int16.astype(np.float32) / 32768.0
    if sample_rate != 16000:
        ratio  = 16000 / sample_rate
        n_out  = int(len(audio_f32) * ratio)
        idxs   = np.linspace(0, len(audio_f32) - 1, n_out)
        audio_f32 = np.interp(idxs, np.arange(len(audio_f32)), audio_f32).astype(np.float32)
    return audio_f32


def _cer(ref: str, hyp: str) -> float:
    """Character Error Rate (edit distance / len(ref))."""
    r, h = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i, rc in enumerate(r):
        nd = [i + 1]
        for j, hc in enumerate(h):
            nd.append(d[j] if rc == hc else 1 + min(d[j], d[j + 1], nd[j]))
        d = nd
    return d[len(h)] / len(r)


_KO_PARTICLES = re.compile(
    r"(을|를|이|가|은|는|의|에서|에게|으로|로|과|와|도|만|부터|까지|라고|이라고"
    r"|께서|에서|한테|보다|처럼|마다|이나|나|이든|든|조차|서|게)$"
)



_KO_VERB_ENDINGS = re.compile(
    r"(했고|했습니다|했어요|합니다|해요|했다|한다|하는|하고|하여|해서|할|하면"
    r"|됩니다|됐고|됐습니다|되어|되고|되는|되면|됩니다"
    r"|입니다|이에요|이라|라고|이고|있고|있습니다|없습니다"
    r"|습니다|세요|주세요|겠습니다|겠어요|었습니다|았습니다)$"
)


def _normalize_token(w: str) -> str:
    """조사·어미 제거 후 어근 반환."""
    w = _KO_VERB_ENDINGS.sub("", w)
    for _ in range(2):
        m = _KO_PARTICLES.search(w)
        if m and len(w) - len(m.group()) >= 1:
            w = w[:m.start()]
        else:
            break
    return w


def _extract_keywords(text: str) -> set[str]:
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    result = set()
    for w in tokens:
        stem = _normalize_token(w)
        if len(stem) > 1 and stem not in _KO_STOPWORDS:
            result.add(stem)
    return result


def _keyword_overlap(question: str, answer: str) -> float:
    """
    질문 키워드가 답변에 얼마나 커버되는지 (recall 방식).
    질문이 짧고 답변이 길어도 공정하게 측정한다.
    """
    kq = _extract_keywords(question)
    ka = _extract_keywords(answer)
    if not kq:
        return _extract_keywords(answer) and 0.5 or 0.0
    overlap = len(kq & ka) / len(kq)  # recall
    topic_bonus = min(len(ka) / 10, 0.3)  # 답변이 충분히 길면 보너스
    return min(1.0, overlap + topic_bonus)


# ══════════════════════════════════════════════════════════════════════════════
# AudioStreamRecorder
# ══════════════════════════════════════════════════════════════════════════════

class AudioStreamRecorder:
    """마이크 녹음 — sounddevice 래퍼."""

    def __init__(self, sample_rate: int = MIC_SAMPLE_RATE):
        if not HAS_MIC:
            raise RuntimeError(
                "sounddevice가 없습니다.\n"
                "  설치: python -m pip install sounddevice"
            )
        self.sample_rate = sample_rate

    def record_until_enter(self) -> tuple[np.ndarray, float]:
        """
        Enter를 누를 때까지 녹음 (길이 제한 없음).
        반환: (int16 배열, 녹음 시간(초))
        """
        chunks: list[np.ndarray] = []
        start_time = [0.0]

        def _callback(indata, *_):
            chunks.append(indata.copy())

        with _sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            callback=_callback,
        ):
            start_time[0] = time.time()
            input("  [●] 녹음 중... 말이 끝나면 Enter ↵\n")

        duration = time.time() - start_time[0]
        print(f"  [■] 녹음 완료  ({duration:.1f}초)")
        if not chunks:
            return np.zeros(1, dtype=np.int16), 0.0
        return np.concatenate(chunks, axis=0).flatten(), duration


# ══════════════════════════════════════════════════════════════════════════════
# STTEngine
# ══════════════════════════════════════════════════════════════════════════════

class STTEngine:
    """
    Whisper 기반 STT 엔진.
    faster-whisper 우선, 없으면 openai-whisper 사용.
    """

    def __init__(self, model_size: str = "small", language: str = "ko"):
        self.language   = language
        self.model_size = model_size
        self._model     = None
        self._backend   = None

    def _load(self):
        if self._model is not None:
            return
        print(f"  Whisper 모델 로딩 ({self.model_size})...", end="", flush=True)
        if HAS_FASTER_WHISPER:
            self._model   = _FasterWhisper(
                self.model_size, device="cpu", compute_type="int8"
            )
            self._backend = "faster"
        elif HAS_OPENAI_WHISPER:
            self._model   = _openai_whisper.load_model(self.model_size)
            self._backend = "openai"
        else:
            raise RuntimeError(
                "Whisper가 없습니다.\n"
                "  설치: python -m pip install faster-whisper\n"
                "  또는: python -m pip install openai-whisper"
            )
        print(" 완료")

    def transcribe(self, audio_f32: np.ndarray) -> dict[str, Any]:
        """
        float32 배열(16kHz) → STT 결과 dict.
        반환: transcript, segments, avg_logprob, no_speech_prob, duration
        """
        self._load()

        # Korean context prompt — 모델이 한국어 발화 맥락을 인식하도록 유도한다.
        # 이 prompt 없이는 base/small 모델이 잡음·침묵 구간에서
        # 영어나 엉뚱한 단어를 생성하는 경향이 있다.
        ko_prompt = "다음은 한국어 면접 또는 발표 내용입니다."

        if self._backend == "faster":
            segments_gen, _ = self._model.transcribe(
                audio_f32,
                language=self.language,
                beam_size=5,
                temperature=0,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
                initial_prompt=ko_prompt,
            )
            segments = list(segments_gen)
            transcript = "".join(s.text for s in segments).strip()
            avg_logprob = (
                float(np.mean([s.avg_logprob for s in segments])) if segments else -1.0
            )
            no_speech_prob = (
                float(np.mean([s.no_speech_prob for s in segments])) if segments else 1.0
            )
            seg_list = [
                {
                    "start": round(s.start, 2),
                    "end":   round(s.end,   2),
                    "text":  s.text.strip(),
                    "avg_logprob":    round(s.avg_logprob,    4),
                    "no_speech_prob": round(s.no_speech_prob, 4),
                }
                for s in segments
            ]
        else:
            result = self._model.transcribe(
                audio_f32,
                language=self.language,
                beam_size=5,
                best_of=5,
                temperature=0,
                condition_on_previous_text=False,
                initial_prompt=ko_prompt,
            )
            transcript  = result["text"].strip()
            segs        = result.get("segments", [])
            avg_logprob    = float(np.mean([s["avg_logprob"]    for s in segs])) if segs else -1.0
            no_speech_prob = float(np.mean([s["no_speech_prob"] for s in segs])) if segs else 1.0
            seg_list = [
                {
                    "start": round(s["start"], 2),
                    "end":   round(s["end"],   2),
                    "text":  s["text"].strip(),
                    "avg_logprob":    round(s["avg_logprob"],    4),
                    "no_speech_prob": round(s["no_speech_prob"], 4),
                }
                for s in segs
            ]

        duration = float(len(audio_f32)) / 16000

        return {
            "transcript":     transcript,
            "segments":       seg_list,
            "avg_logprob":    round(avg_logprob,    4),
            "no_speech_prob": round(no_speech_prob, 4),
            "duration":       round(duration,       3),
        }

    def transcribe_file(self, audio_path: str) -> dict[str, Any]:
        audio_f32, _ = _load_wav_as_float32(audio_path)
        return self.transcribe(audio_f32)


# ══════════════════════════════════════════════════════════════════════════════
# SpeechRateAnalyzer
# ══════════════════════════════════════════════════════════════════════════════

class SpeechRateAnalyzer:
    """
    발화 속도 분석.
    CPM(분당 글자수), WPM_like(분당 어절수) 기반 SLOW/NORMAL/FAST 분류.
    """

    def analyze(self, transcript: str, duration_sec: float) -> dict[str, Any]:
        if duration_sec <= 0:
            return self._empty("음성 길이 정보 없음")

        # 공백·문장부호 제거 후 글자 수
        chars  = len(re.sub(r"[\s\W]", "", transcript))
        words  = len(transcript.split())
        cpm    = round(chars  / duration_sec * 60)
        wpm    = round(words  / duration_sec * 60)

        if cpm < CPM_SLOW_THRESHOLD:
            level    = "SLOW"
            feedback = (
                f"발화 속도가 느립니다 (분당 {cpm}자·{wpm}어절). "
                "자신감 있게 일정한 속도로 말해보세요."
            )
        elif cpm > CPM_FAST_THRESHOLD:
            level    = "FAST"
            feedback = (
                f"발화 속도가 빠릅니다 (분당 {cpm}자·{wpm}어절). "
                "문장 사이 짧은 pause를 두면 전달력이 높아집니다."
            )
        else:
            level    = "NORMAL"
            feedback = f"발화 속도가 적절합니다 (분당 {cpm}자·{wpm}어절)."

        return {
            "cpm":      cpm,
            "wpm_like": wpm,
            "level":    level,
            "feedback": feedback,
        }

    @staticmethod
    def _empty(reason: str) -> dict[str, Any]:
        return {"cpm": 0, "wpm_like": 0, "level": "UNKNOWN", "feedback": reason}


# ══════════════════════════════════════════════════════════════════════════════
# FillerWordAnalyzer
# ══════════════════════════════════════════════════════════════════════════════

class FillerWordAnalyzer:
    """
    습관어 감지 — 정규식 + 토큰 단위 매칭 혼합.
    단순 substring 방식은 오탐이 많으므로 단어 경계를 활용한다.
    """

    def analyze(self, transcript: str) -> dict[str, Any]:
        cleaned = re.sub(r"[^\w\s]", " ", transcript)
        tokens  = cleaned.split()
        counts: dict[str, int] = {}

        # 음절 반복 허용(어어어→어로 취급) + 단어 경계 매칭
        for f in _SINGLE_FILLERS:
            pat = re.compile(r'(?<!\w)' + re.escape(f) + r'+(?!\w)', re.UNICODE)
            n = len(pat.findall(cleaned))
            if n:
                counts[f] = n

        # STT 공백 오차 흡수: "그러 니까" / "그러니까" 모두 매칭
        for f in _MULTI_FILLERS:
            parts = f.split()
            pat = re.compile(r'\s+'.join(re.escape(p) for p in parts), re.UNICODE)
            n = len(pat.findall(transcript))
            if n:
                counts[f] = n

        # 연속 동일 단어 반복 감지 (말더듬: "그 그 그", "어 어")
        repeat_count = sum(
            1 for i in range(len(tokens) - 1)
            if tokens[i] == tokens[i + 1]
        )
        if repeat_count:
            counts["(말더듬)"] = repeat_count

        total      = sum(counts.values())
        word_count = len(tokens)
        ratio      = total / word_count if word_count else 0.0

        if ratio >= FILLER_HIGH_RATIO:
            level    = "HIGH"
            feedback = (
                "습관어 사용이 많습니다. "
                "답변 시작 전 1~2초 생각하고 말하면 자연스러워집니다."
            )
        elif ratio >= FILLER_MEDIUM_RATIO:
            level    = "MEDIUM"
            feedback = "습관어가 다소 나타납니다. 의식적으로 줄여보세요."
        else:
            level    = "LOW"
            feedback = "습관어 사용이 적절합니다."

        return {
            "total_count":  total,
            "counts":       counts,
            "word_count":   word_count,
            "filler_ratio": round(ratio, 4),
            "level":        level,
            "feedback":     feedback,
        }


# ══════════════════════════════════════════════════════════════════════════════
# ClarityAnalyzer
# ══════════════════════════════════════════════════════════════════════════════

class ClarityAnalyzer:
    """
    발음/전달 명확도 추정.

    [중요] STT 텍스트만으로는 실제 발음 정확도를 완벽히 판단할 수 없다.
    정확한 발음 평가는 phoneme-level forced alignment 또는 reference script가 필요하다.
    여기서는 두 가지 proxy를 사용한다:
      1) reference_text가 있으면 → CER 기반 유사도
      2) 없으면 → Whisper avg_logprob + no_speech_prob 기반 추정
    """

    def analyze(
        self,
        transcript:     str,
        stt_result:     dict[str, Any],
        reference_text: str | None = None,
    ) -> dict[str, Any]:

        if reference_text:
            cer   = _cer(reference_text, transcript)
            score = max(0, round((1 - cer) * 100))
            method = "cer"
        else:
            avg_logprob    = stt_result.get("avg_logprob",    -0.5)
            no_speech_prob = stt_result.get("no_speech_prob", 0.1)
            transcript_len = len(transcript.strip())

            # 실제 발화 avg_logprob 분포: 맑은 발화 -0.3~-0.7, 불명확 -1.0~-1.5
            # [-1.5, 0] → [0, 100] 매핑으로 실용 구간 감도 향상
            logprob_score  = min(100, max(0, round((avg_logprob + 1.5) / 1.5 * 100)))
            nsp_penalty    = round(no_speech_prob * 50)
            length_penalty = 30 if transcript_len < 3 else (10 if transcript_len < 10 else 0)

            score  = max(0, min(100, logprob_score - nsp_penalty - length_penalty))
            method = "proxy"

        if score >= 80:
            level    = "HIGH"
            feedback = "전달이 명확합니다."
        elif score >= 55:
            level    = "NORMAL"
            feedback = (
                "대체로 전달은 가능하지만 "
                "일부 구간의 인식 신뢰도가 낮습니다."
            )
        else:
            level    = "LOW"
            feedback = (
                "발음 또는 전달이 불명확할 가능성이 있습니다. "
                "더 천천히, 또렷하게 말해보세요."
            )

        return {
            "score":   score,
            "level":   level,
            "method":  method,
            "feedback": feedback,
        }


# ══════════════════════════════════════════════════════════════════════════════
# RelevanceAnalyzer
# ══════════════════════════════════════════════════════════════════════════════

class RelevanceAnalyzer:
    """
    맥락 이탈 감지.

    baseline: sentence-transformers 코사인 유사도 (없으면 키워드 Jaccard).
    추후 LLM API로 교체 가능하도록 analyze_relevance()를 독립 함수로도 제공한다.
    """

    _sbert_model = None

    def _get_sbert(self):
        if not HAS_SBERT:
            return None
        if RelevanceAnalyzer._sbert_model is None:
            print("  SentenceTransformer 로딩...", end="", flush=True)
            RelevanceAnalyzer._sbert_model = _ST(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
            print(" 완료")
        return RelevanceAnalyzer._sbert_model

    def analyze(
        self,
        transcript: str,
        context:    str | None,     # interview_question or presentation_topic
    ) -> dict[str, Any]:

        if not context or not transcript.strip():
            return {
                "score":         -1,
                "level":         "UNKNOWN",
                "feedback":      "질문 또는 주제가 제공되지 않아 분석을 건너뜁니다.",
                "method":        "none",
            }

        sbert = self._get_sbert()
        if sbert is not None:
            emb_q = sbert.encode(context,    convert_to_tensor=True)
            emb_a = sbert.encode(transcript, convert_to_tensor=True)
            sim   = float(_cos_sim(emb_q, emb_a)[0][0])
            score = round(max(0, min(100, (sim + 1) / 2 * 100)))
            method = "sbert"
        else:
            jaccard = _keyword_overlap(context, transcript)
            score   = round(jaccard * 100)
            method  = "keyword"

        if score >= RELEVANCE_ON_TOPIC:
            level    = "ON_TOPIC"
            feedback = "질문 맥락에서 크게 벗어나지 않고 답변하고 있습니다."
        elif score >= RELEVANCE_PARTIAL:
            level    = "PARTIALLY_OFF_TOPIC"
            feedback = "일부 내용이 질문과 연관성이 낮습니다. 답변을 좀 더 핵심에 집중해보세요."
        else:
            level    = "OFF_TOPIC"
            feedback = "답변이 질문 주제에서 많이 벗어난 것 같습니다. 질문을 다시 확인해보세요."

        return {
            
            "score":   score,
            "level":   level,
            "feedback": feedback,
            "method":  method,
        }


def analyze_relevance(
    transcript: str,
    context:    str | None,
    use_llm:    bool = False,
    llm_fn=None,
) -> dict[str, Any]:
    """
    독립 함수 버전 — 추후 LLM으로 교체 가능.
    use_llm=True이면 llm_fn(transcript, context) → dict 를 호출한다.
    """
    if use_llm and llm_fn is not None:
        return llm_fn(transcript, context)
    return RelevanceAnalyzer().analyze(transcript, context)


# ══════════════════════════════════════════════════════════════════════════════
# RealTimeAudioFeedbackEngine  (메인 오케스트레이터)
# ══════════════════════════════════════════════════════════════════════════════

class RealTimeAudioFeedbackEngine:
    """
    실시간 오디오 피드백 엔진.

    engine = RealTimeAudioFeedbackEngine(stt_model_size="small", language="ko")
    result = engine.analyze_audio_chunk(
        audio_path="chunk.wav",
        interview_question="본인의 프로젝트 경험을 설명해주세요.",
        reference_text=None,
    )
    """

    def __init__(
        self,
        stt_model_size: str = "small",
        language:        str = "ko",
    ):
        self.stt       = STTEngine(model_size=stt_model_size, language=language)
        self.rate      = SpeechRateAnalyzer()
        self.filler    = FillerWordAnalyzer()
        self.clarity   = ClarityAnalyzer()
        self.relevance = RelevanceAnalyzer()

    def analyze_audio_chunk(
        self,
        audio_path:         str | None      = None,
        audio_array:        np.ndarray | None = None,
        interview_question: str | None      = None,
        presentation_topic: str | None      = None,
        reference_text:     str | None      = None,
    ) -> dict[str, Any]:
        """
        WAV 파일 경로 또는 int16/float32 배열을 입력받아 분석 결과 JSON을 반환한다.

        입력:
            audio_path         : WAV 파일 경로 (audio_array와 둘 중 하나)
            audio_array        : numpy int16 배열 (MIC_SAMPLE_RATE Hz)
            interview_question : 면접 질문 (맥락 분석용)
            presentation_topic : 발표 주제 (맥락 분석용)
            reference_text     : 기준 답변 (발음 정확도 계산용, 없으면 proxy 사용)

        반환:
            { "audio": { transcript, speech_rate, fillers, clarity, relevance,
                         overall_feedback } }
        """
        # 1) STT
        if audio_path is not None:
            stt_result = self.stt.transcribe_file(audio_path)
        elif audio_array is not None:
            arr = _int16_to_float32(audio_array, MIC_SAMPLE_RATE) \
                  if audio_array.dtype == np.int16 else audio_array
            stt_result = self.stt.transcribe(arr)
        else:
            raise ValueError("audio_path 또는 audio_array 중 하나는 필수입니다.")

        transcript = stt_result["transcript"]
        duration   = stt_result["duration"]

        # 2) 각 분석기 실행
        sr  = self.rate.analyze(transcript, duration)
        fw  = self.filler.analyze(transcript)
        cl  = self.clarity.analyze(transcript, stt_result, reference_text)
        ctx = interview_question or presentation_topic
        rv  = self.relevance.analyze(transcript, ctx)

        # 3) 종합 피드백
        issues: list[str] = []
        if sr["level"] == "FAST":
            issues.append("발화 속도가 조금 빠릅니다.")
        elif sr["level"] == "SLOW":
            issues.append("발화 속도가 다소 느립니다.")
        if fw["level"] == "HIGH":
            issues.append("습관어가 반복됩니다.")
        elif fw["level"] == "MEDIUM":
            issues.append("습관어가 다소 나타납니다.")
        if cl["level"] == "LOW":
            issues.append("발음/전달 명확도를 높여보세요.")
        if rv["level"] == "OFF_TOPIC":
            issues.append("답변이 주제에서 벗어났습니다.")

        if issues:
            overall = " ".join(issues) + (
                " 답변 속도를 낮추고 문장 사이에 짧은 pause를 두세요."
                if sr["level"] == "FAST" else ""
            )
        else:
            overall = "전반적으로 발화 품질이 양호합니다. 계속 유지하세요."

        return {
            "audio": {
                "transcript":  transcript,
                "speech_rate": sr,
                "fillers":     fw,
                "clarity":     cl,
                "relevance":   rv,
                "overall_feedback": overall,
                "_meta": {
                    "duration_sec":    round(duration, 2),
                    "avg_logprob":     stt_result["avg_logprob"],
                    "no_speech_prob":  stt_result["no_speech_prob"],
                    "stt_backend":     self.stt._backend,
                    "stt_model":       self.stt.model_size,
                },
            }
        }


# ══════════════════════════════════════════════════════════════════════════════
# 데이터셋 전처리 함수 뼈대
# (AI Hub 채용면접 / 자유대화 데이터를 나중에 붙일 때 사용)
# ══════════════════════════════════════════════════════════════════════════════

def dataset_collect_wav_paths(root: Path) -> list[Path]:
    """데이터셋 루트에서 모든 WAV 파일 경로를 수집한다."""
    return sorted(root.rglob("*.wav"))


def dataset_load_label(label_path: Path) -> dict[str, Any]:
    """JSON 전사 라벨을 로드한다."""
    with label_path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def dataset_extract_transcript(label: dict[str, Any], audio_type: str = "answer") -> str:
    """라벨에서 transcript를 추출한다."""
    return label.get("dataSet", {}).get(audio_type, {}).get("raw", {}).get("text", "")


def dataset_calc_duration(wav_path: Path) -> float:
    """WAV 파일의 재생 시간(초)을 반환한다."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def dataset_filler_stats(transcripts: list[str]) -> dict[str, Any]:
    """
    여러 transcript에 대한 습관어 통계를 집계한다.
    STT 결과 검증, 습관어 사전 구축, 발화 속도 기준값 산출에 활용한다.
    """
    analyzer = FillerWordAnalyzer()
    total_counts: dict[str, int] = {}
    ratios: list[float] = []

    for t in transcripts:
        r = analyzer.analyze(t)
        ratios.append(r["filler_ratio"])
        for word, cnt in r["counts"].items():
            total_counts[word] = total_counts.get(word, 0) + cnt

    return {
        "total_fillers":       sum(total_counts.values()),
        "per_word":            dict(sorted(total_counts.items(), key=lambda x: -x[1])),
        "avg_filler_ratio":    round(sum(ratios) / len(ratios), 4) if ratios else 0,
        "sample_count":        len(transcripts),
    }


def dataset_speech_rate_stats(
    transcripts: list[str],
    durations:   list[float],
) -> dict[str, Any]:
    """
    발화 속도 기준값을 데이터셋에서 산출한다.
    CPM 분포를 기반으로 SLOW/NORMAL/FAST 임계값을 제안한다.
    """
    cpms = []
    for t, d in zip(transcripts, durations, strict=False):
        if d > 0:
            chars = len(re.sub(r"[\s\W]", "", t))
            cpms.append(chars / d * 60)

    if not cpms:
        return {}

    cpms_arr = np.array(cpms)
    return {
        "n":     len(cpms),
        "mean":  round(float(np.mean(cpms_arr))),
        "p25":   round(float(np.percentile(cpms_arr, 25))),
        "p50":   round(float(np.percentile(cpms_arr, 50))),
        "p75":   round(float(np.percentile(cpms_arr, 75))),
        "p90":   round(float(np.percentile(cpms_arr, 90))),
        "suggested_slow_threshold": round(float(np.percentile(cpms_arr, 15))),
        "suggested_fast_threshold": round(float(np.percentile(cpms_arr, 85))),
    }


def dataset_build_stats_from_csv(csv_path: Path) -> dict[str, Any]:
    """
    features/stt_audio_features.csv에서 전사 텍스트와 duration을 읽어
    습관어·발화속도 통계를 산출한다.
    """
    with csv_path.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("audio_type") == "answer"]

    transcripts = [r["text"] for r in rows if r.get("text")]
    durations   = [float(r["duration_sec"]) for r in rows if r.get("duration_sec")]

    return {
        "filler_stats":      dataset_filler_stats(transcripts),
        "speech_rate_stats": dataset_speech_rate_stats(transcripts, durations),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 레거시 함수 — 기존 CSV 추출 워크플로우 호환
# ══════════════════════════════════════════════════════════════════════════════

def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def normalize_audio_path(audio_path: str) -> Path:
    parts = [p for p in audio_path.replace("\\", "/").split("/") if p]
    if parts and parts[0].lower() == "mock":
        parts = parts[1:]
    return AUDIO_ROOT.joinpath(*parts)


def iter_label_files(label_root: Path) -> list[Path]:
    return sorted(
        p for p in label_root.rglob("*.json")
        if DEFAULT_OUTPUT_DIR not in p.parents
    )


def extract_wav_features(path: Path, frame_ms: int = 20) -> dict[str, Any]:
    if not path.exists():
        return {"audio_exists": False, "error": "missing_audio"}
    try:
        with wave.open(str(path), "rb") as wav:
            channels     = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate  = wav.getframerate()
            frame_count  = wav.getnframes()
            raw_frames   = wav.readframes(frame_count)
    except wave.Error as exc:
        return {"audio_exists": True, "error": f"wave_error:{exc}"}

    if sample_width != 2:
        return {
            "audio_exists": True, "channels": channels,
            "sample_width": sample_width, "sample_rate": sample_rate,
            "frame_count": frame_count,
            "duration_sec": frame_count / sample_rate if sample_rate else 0,
            "error": "unsupported_sample_width",
        }

    samples  = np.frombuffer(raw_frames, dtype=np.int16)
    if channels > 1:
        samples = samples[::channels]

    total       = len(samples)
    duration_sec= total / sample_rate if sample_rate else 0.0
    if total == 0:
        return {
            "audio_exists": True, "channels": channels,
            "sample_width": sample_width, "sample_rate": sample_rate,
            "frame_count": frame_count, "duration_sec": duration_sec,
            "error": "empty_audio",
        }

    s    = samples.astype(np.float32)
    peak = int(np.max(np.abs(samples)))
    rms  = float(np.sqrt(np.mean(s ** 2)))
    zcr  = float(np.sum(np.diff(np.sign(samples)) != 0)) / max(total - 1, 1)

    frame_size = max(int(sample_rate * frame_ms / 1000), 1)
    n_frames   = total // frame_size
    if n_frames > 0:
        frame_rms = np.sqrt(np.mean(
            s[:n_frames * frame_size].reshape(n_frames, frame_size) ** 2, axis=1
        ))
    else:
        frame_rms = np.array([rms], dtype=np.float32)

    silence_ratio = float(np.sum(frame_rms < max(300.0, rms * 0.20))) / len(frame_rms)

    return {
        "audio_exists": True, "error": "",
        "channels": channels, "sample_width": sample_width,
        "sample_rate": sample_rate, "frame_count": frame_count,
        "duration_sec":         round(duration_sec, 3),
        "rms":                  round(rms, 3),
        "mean_abs":             round(float(np.mean(np.abs(s))), 3),
        "dc_offset":            round(float(np.mean(s)), 3),
        "peak":                 peak,
        "peak_dbfs":            round(20 * math.log10(max(peak, 1) / 32768), 3),
        "rms_dbfs":             round(20 * math.log10(max(rms, 1e-9) / 32768), 3),
        "zero_crossing_rate":   round(zcr, 6),
        "silence_ratio":        round(silence_ratio, 6),
        "frame_rms_mean":       round(float(np.mean(frame_rms)), 3),
        "frame_rms_min":        round(float(np.min(frame_rms)), 3),
        "frame_rms_max":        round(float(np.max(frame_rms)), 3),
    }


def _detect_fillers_legacy(text: str) -> dict[str, Any]:
    return FillerWordAnalyzer().analyze(text)


def build_rows(label_path: Path, stt_engine: STTEngine | None = None) -> list[dict[str, Any]]:
    label    = read_json(label_path)
    data_set = label["dataSet"]
    info     = data_set.get("info", {})
    raw_data = label.get("rawDataInfo", {})
    rows: list[dict[str, Any]] = []

    for audio_type in ("question", "answer"):
        text_info   = data_set.get(audio_type, {}).get("raw", {})
        audio_info  = raw_data.get(audio_type, {})
        local_path  = normalize_audio_path(audio_info.get("audioPath", ""))
        text        = text_info.get("text", "")
        features    = extract_wav_features(local_path)

        row: dict[str, Any] = {
            "label_path": str(label_path), "audio_type": audio_type,
            "audio_path": str(local_path), "file_id": local_path.stem,
            "occupation": info.get("occupation", ""), "channel": info.get("channel", ""),
            "place": info.get("place", ""), "gender": info.get("gender", ""),
            "age_range": info.get("ageRange", ""), "experience": info.get("experience", ""),
            "text": text, "text_char_count": len(text),
            "text_word_count_json": text_info.get("wordCount", ""),
            "duration_ms_json": audio_info.get("duration", ""),
            "sampling_rate_json": audio_info.get("samplingRate", ""),
            "file_size_json": audio_info.get("fileSize", ""),
        }
        row.update(features)

        if audio_type == "answer" and stt_engine and features.get("audio_exists"):
            try:
                stt_res    = stt_engine.transcribe_file(str(local_path))
                stt_text   = stt_res["transcript"]
                fw         = FillerWordAnalyzer().analyze(stt_text)
                row["stt_text"]          = stt_text
                row["stt_filler_counts"] = json.dumps(fw["counts"], ensure_ascii=False)
                row["stt_total_fillers"] = fw["total_count"]
                row["stt_word_count"]    = fw["word_count"]
                row["stt_filler_ratio"]  = fw["filler_ratio"]
            except Exception as exc:
                row["stt_text"] = f"ERROR:{exc}"
                for k in ("stt_filler_counts", "stt_total_fillers",
                          "stt_word_count", "stt_filler_ratio"):
                    row[k] = ""
        else:
            row["stt_text"] = ""
            for k in ("stt_filler_counts", "stt_total_fillers",
                      "stt_word_count", "stt_filler_ratio"):
                row[k] = ""

        rows.append(row)
    return rows


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r.get("audio_exists") and not r.get("error")]
    durs  = [float(r["duration_sec"]) for r in valid]
    return {
        "total_rows": len(rows),
        "valid_audio_rows": len(valid),
        "total_audio_hours": round(sum(durs) / 3600, 3),
        "avg_duration_sec":  round(sum(durs) / len(durs), 3) if durs else 0,
    }


def enrich_csv(input_csv: Path, output_csv: Path, stt_engine: STTEngine) -> None:
    with input_csv.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    for i, row in enumerate(rows):
        is_answer  = row.get("audio_type") == "answer"
        audio_path = row.get("audio_path", "")
        print(f"  [{i+1}/{len(rows)}] {row.get('file_id', '')}  ({row.get('audio_type', '')})")

        if is_answer and audio_path and Path(audio_path).exists():
            stt_res  = stt_engine.transcribe_file(audio_path)
            stt_text = stt_res["transcript"]
            fw       = FillerWordAnalyzer().analyze(stt_text)
            row["stt_text"]          = stt_text
            row["stt_filler_counts"] = json.dumps(fw["counts"], ensure_ascii=False)
            row["stt_total_fillers"] = fw["total_count"]
            row["stt_word_count"]    = fw["word_count"]
            row["stt_filler_ratio"]  = fw["filler_ratio"]
        else:
            for k in ("stt_text", "stt_filler_counts", "stt_total_fillers",
                      "stt_word_count", "stt_filler_ratio"):
                row.setdefault(k, "")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n저장: {output_csv}")


# ══════════════════════════════════════════════════════════════════════════════
# 실행 모드
# ══════════════════════════════════════════════════════════════════════════════

def _print_result(result: dict[str, Any]) -> None:
    """분석 결과를 콘솔에 보기 좋게 출력한다."""
    audio = result["audio"]
    print("\n  [전사 텍스트]")
    t = audio["transcript"]
    print(f"    {t[:120]}{'...' if len(t)>120 else ''}")

    sr = audio["speech_rate"]
    print(f"\n  [발화 속도]  CPM {sr['cpm']}  /  어절/분 {sr['wpm_like']}"
          f"  →  {sr['level']}")
    print(f"    {sr['feedback']}")

    fw = audio["fillers"]
    counts_str = "  |  ".join(
        f"'{w}' {c}회" for w, c in sorted(fw["counts"].items(), key=lambda x: -x[1])
    ) if fw["counts"] else "없음"
    print(f"\n  [습관어]  총 {fw['total_count']}개 ({fw['filler_ratio']:.1%})"
          f"  →  {fw['level']}")
    print(f"    {counts_str}")
    print(f"    {fw['feedback']}")

    cl = audio["clarity"]
    print(f"\n  [전달 명확도]  {cl['score']}점  →  {cl['level']}")
    print(f"    {cl['feedback']}")

    rv = audio["relevance"]
    if rv["level"] != "UNKNOWN":
        print(f"\n  [맥락 관련성]  {rv['score']}점  →  {rv['level']}")
        print(f"    {rv['feedback']}")

    print("\n  [종합 피드백]")
    print(f"    {audio['overall_feedback']}")

    m = audio["_meta"]
    print(f"\n  [메타]  {m['duration_sec']}초  /  "
          f"logprob {m['avg_logprob']}  /  nsp {m['no_speech_prob']}  /  "
          f"STT: {m['stt_backend']} ({m['stt_model']})")


def run_mic_mode(engine: RealTimeAudioFeedbackEngine, question: str | None) -> None:
    if not HAS_MIC:
        print("[오류] sounddevice 없음. 설치: python -m pip install sounddevice")
        return

    recorder = AudioStreamRecorder()

    print("\n" + "=" * 60)
    print("  실시간 발화 AI 분석  (Ctrl+C로 종료)")
    print("=" * 60)

    # 질문이 없으면 입력받기
    if not question:
        print("  면접 질문 또는 발표 주제를 입력하세요.")
        print("  (없으면 Enter만 누르면 됩니다)")
        question = input("  > ").strip() or None

    if question:
        print(f"\n  [질문/주제] {question}")

    print("\n  말을 시작하면 녹음됩니다. 다 말한 뒤 Enter를 누르면 분석합니다.")
    print("  종료: Ctrl+C\n")

    session = 0
    try:
        while True:
            session += 1
            if session > 1:
                cmd = input("  [ 계속: Enter  |  질문 변경: c  |  종료: q ] > ").strip().lower()
                if cmd == "q":
                    break
                if cmd == "c":
                    question = input("  새 질문/주제 > ").strip() or None
                    print(f"  [질문 변경] {question or '(없음)'}\n")

            audio, rec_duration = recorder.record_until_enter()

            if rec_duration < 1.0:
                print("  (녹음이 너무 짧습니다. 다시 시도하세요.)\n")
                session -= 1
                continue

            print("  AI 분석 중...", end="", flush=True)
            result = engine.analyze_audio_chunk(
                audio_array=audio,
                interview_question=question,
            )
            print("\r" + " " * 25 + "\r", end="")
            print(f"\n{'─' * 60}  세션 #{session}  ({rec_duration:.1f}초 발화)")
            _print_result(result)
            print()

    except KeyboardInterrupt:
        pass
    print("\n종료.")


def run_demo_mode(
    engine: RealTimeAudioFeedbackEngine,
    n: int,
    question: str | None,
    as_json: bool = False,
) -> None:
    csv_path = DEFAULT_OUTPUT_DIR / "stt_audio_features.csv"
    if not csv_path.exists():
        print("[오류] features/stt_audio_features.csv 없음. 먼저 python stt.py --extract 실행")
        return

    with csv_path.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r.get("audio_type") == "answer"
                and r.get("audio_exists", "").lower() in ("true", "1")][:n]

    if not rows:
        print("[오류] 유효한 오디오 행이 없습니다.")
        return

    print("\n" + "=" * 60)
    print(f"  데모: 오디오 파일 {len(rows)}개 AI 분석")
    print("=" * 60)

    for i, row in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] {row.get('file_id','')}  "
              f"({row.get('occupation','')} / {row.get('gender','')} / {row.get('experience','')})")
        print(f"  음성 길이: {float(row.get('duration_sec',0)):.1f}초")
        print(f"  [원문]  {row.get('text','')[:80]}...")
        print("  분석 중...", end="", flush=True)

        result = engine.analyze_audio_chunk(
            audio_path=row["audio_path"],
            interview_question=question,
        )
        print("\r" + " " * 20 + "\r", end="")
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_result(result)
        print()


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="실시간 음성 AI 분석 시스템 (발표/면접 피드백)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mic",           action="store_true", help="마이크 실시간 분석")
    p.add_argument("--mic-duration",  type=int, default=CHUNK_DURATION,
                   help=f"마이크 녹음 시간(초) (기본: {CHUNK_DURATION})")
    p.add_argument("--demo",          action="store_true", help="데이터셋 파일 N개 분석 데모")
    p.add_argument("--demo-n",        type=int, default=3, help="데모 파일 수 (기본: 3)")
    p.add_argument("--question",      type=str, default=None, help="면접 질문 / 발표 주제")
    p.add_argument("--extract",       action="store_true", help="WAV 피처 추출 → CSV 저장")
    p.add_argument("--enrich",        action="store_true", help="기존 CSV에 STT 컬럼 추가")
    p.add_argument(
        "--stats",
        action="store_true",
        help="데이터셋 습관어/발화속도 통계 출력",
    )
    p.add_argument("--whisper-model", default="small",
                   choices=["tiny", "base", "small", "medium", "large"],
                   help="Whisper 모델 크기 (기본: base)")
    p.add_argument("--limit",         type=int, default=0, help="처리할 JSON 수 (0=전체)")
    p.add_argument("--json",          action="store_true", help="분석 결과를 JSON으로 출력")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    engine = RealTimeAudioFeedbackEngine(stt_model_size=args.whisper_model)

    # 아무 옵션 없음 → 마이크 모드
    if not any([args.mic, args.demo, args.extract, args.enrich, args.stats]):
        run_mic_mode(engine, question=args.question)
        return

    if args.stats:
        csv_path = DEFAULT_OUTPUT_DIR / "stt_audio_features.csv"
        print("데이터셋 통계 산출 중...")
        stats = dataset_build_stats_from_csv(csv_path)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    if args.mic:
        run_mic_mode(engine, question=args.question)
        return

    if args.demo:
        run_demo_mode(engine, n=args.demo_n, question=args.question, as_json=args.json)
        return

    if args.enrich:
        input_csv  = DEFAULT_OUTPUT_DIR / "stt_audio_features.csv"
        output_csv = DEFAULT_OUTPUT_DIR / "stt_audio_features_enriched.csv"
        print(f"STT 컬럼 추가: {input_csv}")
        enrich_csv(input_csv, output_csv, engine.stt)
        return

    if args.extract:
        label_files = iter_label_files(LABEL_ROOT)
        if args.limit > 0:
            label_files = label_files[:args.limit]
        rows: list[dict[str, Any]] = []
        for lp in label_files:
            rows.extend(build_rows(lp))
        output_csv = DEFAULT_OUTPUT_DIR / "stt_audio_features.csv"
        write_csv(rows, output_csv)
        s = summarize(rows)
        print(f"labels: {len(label_files)}")
        print(f"rows: {s['total_rows']}")
        print(f"valid audio rows: {s['valid_audio_rows']}")
        print(f"total audio hours: {s['total_audio_hours']}")
        print(f"csv: {output_csv}")


if __name__ == "__main__":
    main()
