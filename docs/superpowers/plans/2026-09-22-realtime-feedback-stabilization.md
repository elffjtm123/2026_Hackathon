# Realtime Feedback Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 세션 종료 직전 오디오까지 처리하고, 시선·발화·습관어 상태를 독립적으로 표시하며, Qwen3-ASR와 시선 분석 결과를 검증 가능한 형태로 안정화한다.

**Architecture:** 브라우저가 16 kHz mono 오디오와 640×480 JPEG를 하나의 WebSocket으로 보내고, 백엔드가 source별 worker와 집계기를 통해 결과를 반환한다. 종료는 `flush media → session.end → queue drain → session.completed → socket close` 순서로 수행하며, 프론트는 source별 상태와 서버 최종 report를 보관한다. 시선 모델은 파이프라인별 안정화 계층 뒤에 두고, Apple Silicon에서는 UniFace MobileGaze를 우선 어댑터로 사용하되 품질 부족 시 `unknown`을 반환한다.

**Tech Stack:** React 19, TypeScript 5.8, Web Audio API, WebSocket, FastAPI, asyncio, Qwen3-ASR 0.6B, NumPy, ONNX Runtime/UniFace 4.x, pytest, Node test runner

**Spec:** `docs/superpowers/specs/2026-09-22-realtime-feedback-stabilization-design.md`

## Global Constraints

- 단일 localhost 사용자와 Apple Silicon MacBook 실행을 기준으로 한다.
- 원본 영상·음성을 파일이나 DB에 저장하지 않는다.
- 새 npm 의존성은 추가하지 않는다.
- 오디오 전송 규격은 16 kHz mono PCM WAV, 기본 청크 2초, 중첩 250 ms다.
- 비디오 전송 규격은 JPEG 640×480, 최대 8 FPS, 서버 queue size 1이다.
- 감정 판정, 얼굴 색 변화, Laya/Jev, LLM 질문·피드백, 다중 사용자 최적화는 구현하지 않는다.
- 없는 측정값을 정상값으로 채우지 않으며 품질이 부족하면 `unknown` 또는 `null`을 반환한다.
- 모든 동작 변경은 실패하는 테스트를 먼저 작성하고 최소 구현으로 통과시킨다.

## Review Focus

- 세션 시작 직후 0.5초 이내에 종료해도 짧은 오디오가 유실되지 않고 완료 report가 한 번만 와야 한다.
- `session.end`를 연속 두 번 호출해도 파이프라인 종료와 완료 이벤트가 중복되지 않아야 한다.
- STT가 실패해도 시선 worker와 WebSocket 연결은 계속 동작하며 음성 모듈 오류만 표시해야 한다.
- 얼굴이 없거나 프레임 디코딩이 실패하면 시선 이탈로 잘못 집계하지 않고 `unknown`으로 남아야 한다.
- 48 kHz가 아닌 44.1 kHz 장치 입력도 정확히 16 kHz로 변환되고 종료 순서가 유지되어야 한다.

---

### Task 1: 종료 프로토콜과 서버 최종 report

**Files:**
- Modify: `app/realtime/events.py`
- Modify: `app/realtime/pipeline.py`
- Modify: `app/api/v1/websocket.py`
- Modify: `src/lib/realtimeProtocol.ts`
- Modify: `src/features/practice/hooks/useFeedbackSocket.ts`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_session_flow.py`

**Interfaces:**
- Consumes: 기존 `SessionPipeline.stop() -> dict[str, Any]`, `FeedbackAggregator.report()`
- Produces: `ClientEvent.event == "session.end"`, `SessionCompletionMessage`, `useFeedbackSocket.finish(sessionId) -> Promise<SessionCompletionReport>`

- [ ] **Step 1: 파이프라인 종료의 배수성과 timeout report 테스트 작성**

`tests/test_pipeline.py`에 worker가 마지막 오디오를 처리한 뒤 완료 이벤트가 한 번만 발생하는 테스트를 추가한다.

```python
@pytest.mark.asyncio
async def test_stop_drains_audio_and_emits_completion_once() -> None:
    settings = Settings(
        jwt_secret="test-secret-that-is-definitely-long-enough",
        redis_url=None,
        pipeline_grace_seconds=1,
    )
    pipeline = SessionPipeline(
        uuid4(), settings, SessionStateStore(None), object(), MockSpeechAdapter(),
        {"speech_rate_enabled": True},
    )
    events = []

    async def collect(event: object) -> None:
        events.append(event)

    pipeline.subscribe("test", collect)  # type: ignore[arg-type]
    await pipeline.start()
    await pipeline.push_audio(100, "마지막 문장입니다".encode())
    first = await pipeline.stop()
    second = await pipeline.stop()

    assert first["transcript"] == "마지막 문장입니다"
    assert second == first
    assert [event.event for event in events].count("session.completed") == 1
    assert events[-1].data["report"]["incomplete"] is False
```

- [ ] **Step 2: 테스트가 현재 완료 payload와 배수성 캐시 부재로 실패하는지 확인**

Run: `.venv310/bin/python -m pytest tests/test_pipeline.py::test_stop_drains_audio_and_emits_completion_once -v`

Expected: FAIL because `incomplete` and the cached completed report are absent.

- [ ] **Step 3: `SessionPipeline.stop()`이 report를 캐시하고 timeout 여부를 포함하도록 구현**

`app/realtime/pipeline.py`에 `self.completed_report: dict[str, Any] | None = None`과 `self._stop_lock = asyncio.Lock()`을 추가하고 다음 형태로 종료를 직렬화한다.

```python
async def stop(self) -> dict[str, Any]:
    async with self._stop_lock:
        if self.completed_report is not None:
            return self.completed_report
        self.accepting = False
        incomplete = False
        try:
            await asyncio.wait_for(
                asyncio.gather(self.video_queue.queue.join(), self.audio_queue.join()),
                timeout=self.settings.pipeline_grace_seconds,
            )
        except TimeoutError:
            incomplete = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self.running = False
        report = {**self.aggregator.report(), "incomplete": incomplete}
        self.completed_report = report
        await self.state_store.set(self.session_id, {"status": "completed", **self.metrics()})
        await self.emit("session.completed", self.elapsed_ms(), {"report": report})
        return report
```

- [ ] **Step 4: WebSocket `session.end` 통합 테스트 작성**

`tests/test_session_flow.py`의 연결 안에서 transcript를 보낸 후 아래 검증을 추가한다.

```python
websocket.send_json({"event": "session.end", "timestamp_ms": 1100, "data": {}})
completed = websocket.receive_json()
assert completed["event"] == "session.completed"
assert completed["data"]["report"]["transcript"] == "음 저는 백엔드 개발자입니다"
assert completed["data"]["report"]["incomplete"] is False
```

- [ ] **Step 5: 통합 테스트가 `ClientEvent` validation에서 실패하는지 확인**

Run: `.venv310/bin/python -m pytest tests/test_session_flow.py::test_websocket_feedback_complete_and_report -v`

Expected: FAIL with `INVALID_MESSAGE` because `session.end` is not accepted.

- [ ] **Step 6: 두 WebSocket endpoint에 종료 처리를 구현**

`app/realtime/events.py`의 `ClientEvent` literal에 `session.end`를 추가한다. `practice_demo_websocket`은 subscriber를 유지한 채 `await pipeline.stop()` 후 loop를 끝내고, 인증 endpoint는 `await websocket.app.state.pipelines.stop(session_id)` 후 loop를 끝낸다. `finally`의 두 번째 stop은 캐시된 report만 반환하므로 이벤트를 다시 내보내지 않는다.

- [ ] **Step 7: 프론트 종료 이벤트와 완료 메시지 타입을 추가**

`src/lib/realtimeProtocol.ts`에 다음 타입을 추가하고 `BackendClientEvent`에 `session.end`를 포함한다.

```typescript
export type SessionCompletionReport = {
  transcript: string | null;
  gaze: { awayCount: number; awayDurationMs: number };
  speech: { averageSyllablesPerMinute: number };
  filler: { counts: Record<string, number> };
  incomplete: boolean;
};

export type SessionCompletionMessage = {
  type: "session.completed";
  sessionId: string;
  timestamp: number;
  report: SessionCompletionReport;
};
```

`toBackendEvent`에서 `session.end`를 그대로 변환하고, 백엔드 demo 변환 함수가 aggregator의 flat report를 위 nested 타입으로 바꿔 `session.completed`를 보낸다. `useFeedbackSocket`은 completion resolver를 ref에 저장하고 10초 timeout을 두는 `finish`를 반환한다.

- [ ] **Step 8: Task 1 테스트와 정적 검사를 실행**

Run: `.venv310/bin/python -m pytest tests/test_pipeline.py tests/test_session_flow.py -v`

Run: `npm run typecheck`

Expected: all PASS.

- [ ] **Step 9: Task 1 커밋**

```bash
git add app/realtime/events.py app/realtime/pipeline.py app/api/v1/websocket.py src/lib/realtimeProtocol.ts src/features/practice/hooks/useFeedbackSocket.ts tests/test_pipeline.py tests/test_session_flow.py
git commit -m "Fix realtime session completion protocol"
```

### Task 2: source별 피드백 상태 분리

**Files:**
- Create: `src/features/practice/feedbackState.ts`
- Modify: `src/lib/realtimeProtocol.ts`
- Modify: `src/features/practice/hooks/usePracticeSession.ts`
- Modify: `src/features/practice/components/FeedbackPanel.tsx`
- Modify: `src/features/practice/components/FeedbackOverlay.tsx`
- Modify: `src/features/practice/PracticePage.tsx`
- Modify: `app/api/v1/websocket.py`
- Test: `tests/frontend_tools.test.mjs`

**Interfaces:**
- Consumes: `RealtimeFeedback.source`, `SessionCompletionReport`
- Produces: `FeedbackState`, `reduceFeedback(state, event) -> FeedbackState`, `completeSession(report)`

- [ ] **Step 1: source가 다른 이벤트가 상태를 덮지 않는 테스트 작성**

`tests/frontend_tools.test.mjs`에 다음 테스트를 추가한다.

```javascript
import * as feedbackState from "../src/features/practice/feedbackState.ts";

test("발화 피드백이 마지막 시선 상태를 덮어쓰지 않는다", () => {
  const gaze = {
    type: "feedback", sessionId: "s", source: "gaze", timestamp: 1,
    severity: "warning", gaze: { status: "left", message: "왼쪽" },
  };
  const speech = {
    type: "feedback", sessionId: "s", source: "speech_rate", timestamp: 2,
    severity: "info", speech: { pace: "normal", message: "적절" },
    filler: { totalCount: 0, counts: {} },
  };
  const afterGaze = feedbackState.reduceFeedback(feedbackState.emptyFeedbackState, gaze);
  const afterSpeech = feedbackState.reduceFeedback(afterGaze, speech);
  assert.equal(afterSpeech.gaze?.gaze?.status, "left");
  assert.equal(afterSpeech.speech?.speech?.pace, "normal");
});
```

- [ ] **Step 2: 테스트가 모듈 부재로 실패하는지 확인**

Run: `node --test --experimental-strip-types tests/frontend_tools.test.mjs`

Expected: FAIL with module not found.

- [ ] **Step 3: 최소 reducer와 source별 타입 구현**

`RealtimeFeedback`의 `gaze`, `speech`, `filler`, `pronunciation`을 optional로 바꾸고 `feedbackState.ts`를 만든다.

```typescript
export type FeedbackState = {
  gaze: RealtimeFeedback | null;
  speech: RealtimeFeedback | null;
  pronunciation: RealtimeFeedback | null;
};

export const emptyFeedbackState: FeedbackState = {
  gaze: null,
  speech: null,
  pronunciation: null,
};

export function reduceFeedback(
  state: FeedbackState,
  feedback: RealtimeFeedback
): FeedbackState {
  if (feedback.source === "gaze") return { ...state, gaze: feedback };
  if (feedback.source === "speech_rate") return { ...state, speech: feedback };
  if (feedback.source === "pronunciation") return { ...state, pronunciation: feedback };
  return state;
}
```

- [ ] **Step 4: 백엔드가 source 외 정상값을 만들지 않도록 수정**

`app/api/v1/websocket.py`의 demo feedback 변환에서 gaze source는 `gaze`만, speech source는 `speech`와 `filler`만, pronunciation source는 `pronunciation`만 채운다. 다른 source 필드는 응답에서 생략한다.

- [ ] **Step 5: 훅과 컴포넌트를 source별 상태로 연결**

`usePracticeSession`은 `feedbackState`를 reducer로 갱신하고, transcript만 별도로 누적한다. `FeedbackPanel`과 `FeedbackOverlay`는 `FeedbackState`를 받아 마지막 시선과 발화 상태를 각각 렌더링한다. optional 필드는 optional chaining으로 접근하며 값이 없으면 `분석 대기`를 표시한다.

- [ ] **Step 6: 서버 report가 세션 요약의 최종 기준이 되도록 구현**

`completeSession(report)`에서 종료 시각과 report를 함께 저장한다. `PracticeSummary`의 transcript, 시선 이탈 시간/비율, 평균 발화 속도, 습관어는 각각 `report.transcript`, `report.gaze`, `report.speech`, `report.filler` 값을 사용하고, `report.incomplete`를 화면에 표시한다. report가 timeout으로 오지 않은 경우에만 현재 로컬 누적값을 fallback으로 사용하고 `incomplete=true`로 표시한다.

- [ ] **Step 7: Task 2 검증**

Run: `node --test --experimental-strip-types tests/frontend_tools.test.mjs`

Run: `npm run lint`

Run: `npm run typecheck`

Expected: all PASS.

- [ ] **Step 8: Task 2 커밋**

```bash
git add src/features/practice/feedbackState.ts src/lib/realtimeProtocol.ts src/features/practice/hooks/usePracticeSession.ts src/features/practice/components/FeedbackPanel.tsx src/features/practice/components/FeedbackOverlay.tsx src/features/practice/PracticePage.tsx app/api/v1/websocket.py tests/frontend_tools.test.mjs
git commit -m "Separate realtime feedback by source"
```

### Task 3: 16 kHz 오디오 청크와 안전한 종료 순서

**Files:**
- Create: `src/features/practice/audioTools.ts`
- Create: `src/features/practice/sessionLifecycle.ts`
- Modify: `src/features/practice/hooks/useBackendStreaming.ts`
- Modify: `src/features/practice/hooks/useFeedbackSocket.ts`
- Modify: `src/features/practice/PracticePage.tsx`
- Modify: `app/core/config.py`
- Test: `tests/frontend_tools.test.mjs`

**Interfaces:**
- Consumes: `sendAudioChunk(payload: Blob) -> Promise<boolean>`, `finish(sessionId)` from Task 1
- Produces: `downsampleLinear`, `encodePcm16Wav`, `takeNextAudioChunk`, `completePracticeSession`, `useBackendStreaming().stopStreaming()`

- [ ] **Step 1: 44.1/48 kHz 변환과 WAV 헤더 테스트 작성**

```javascript
import * as audioTools from "../src/features/practice/audioTools.ts";

test("48 kHz mono 입력을 16 kHz WAV로 변환한다", async () => {
  const input = Float32Array.from({ length: 48_000 }, (_, i) => Math.sin(i / 20));
  const output = audioTools.downsampleLinear(input, 48_000, 16_000);
  const wav = audioTools.encodePcm16Wav(output, 16_000);
  const view = new DataView(await wav.arrayBuffer());
  assert.equal(output.length, 16_000);
  assert.equal(view.getUint32(24, true), 16_000);
  assert.equal(view.getUint16(22, true), 1);
});

test("44.1 kHz 입력도 16 kHz 길이로 변환한다", () => {
  const output = audioTools.downsampleLinear(new Float32Array(44_100), 44_100, 16_000);
  assert.equal(output.length, 16_000);
});

test("종료 flush는 2초보다 짧은 마지막 샘플도 청크로 반환한다", () => {
  const input = new Float32Array(12_000);
  const { chunk, remainder } = audioTools.takeNextAudioChunk(
    input, 96_000, 12_000, true
  );
  assert.equal(chunk?.length, 12_000);
  assert.equal(remainder.length, 0);
});
```

- [ ] **Step 2: 테스트가 export 부재로 실패하는지 확인**

Run: `node --test --experimental-strip-types tests/frontend_tools.test.mjs`

Expected: FAIL with module not found.

- [ ] **Step 3: 선형 보간 다운샘플링과 WAV encoder 구현**

`audioTools.ts`는 DOM 외부에서도 테스트 가능한 순수 함수만 둔다.

```typescript
export function downsampleLinear(
  input: Float32Array,
  sourceRate: number,
  targetRate = 16_000
): Float32Array {
  if (sourceRate === targetRate) return input.slice();
  const length = Math.round(input.length * targetRate / sourceRate);
  const output = new Float32Array(length);
  const ratio = sourceRate / targetRate;
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, input.length - 1);
    const weight = position - left;
    output[i] = input[left] * (1 - weight) + input[right] * weight;
  }
  return output;
}
```

`encodePcm16Wav`는 기존 WAV header 로직을 이동하되 sample rate를 항상 명시적으로 받는다. `takeNextAudioChunk(input, chunkSize, overlapSize, flush)`는 평상시에는 완성된 2초 청크와 overlap을 포함한 remainder를 반환하고, `flush=true`일 때는 짧은 마지막 샘플도 반환한다.

- [ ] **Step 4: 종료 호출 순서 테스트 작성**

```javascript
import * as lifecycle from "../src/features/practice/sessionLifecycle.ts";

test("오디오 flush 후 session.end를 보내고 완료 report를 기다린다", async () => {
  const calls = [];
  const report = { transcript: "마지막", incomplete: false };
  const result = await lifecycle.completePracticeSession({
    flushMedia: async () => { calls.push("flush"); },
    requestCompletion: async () => { calls.push("end"); return report; },
    closeMedia: () => { calls.push("close-media"); },
    closeSocket: () => { calls.push("close-socket"); },
  });
  assert.deepEqual(calls, ["flush", "close-media", "end", "close-socket"]);
  assert.equal(result, report);
});
```

- [ ] **Step 5: 테스트가 lifecycle 모듈 부재로 실패하는지 확인**

Run: `node --test --experimental-strip-types tests/frontend_tools.test.mjs`

Expected: FAIL with module not found.

- [ ] **Step 6: 종료 orchestration과 스트리밍 controller 구현**

`completePracticeSession`은 위 테스트 순서만 담당한다. `useBackendStreaming`은 내부 audio/video cleanup을 ref에 저장하고 `stopStreaming(): Promise<void>`를 반환한다. audio cleanup은 마지막 새 샘플이 있으면 250 ms overlap을 포함해 flush하며 `sendAudioChunk`의 Promise를 기다린다. 2초 청크를 보낸 뒤 원본 rate 기준 마지막 250 ms를 다음 청크 시작에 남긴다.

비디오 canvas는 640×480으로 바꾸고 interval을 125 ms로 설정한다. 서버 `video_queue_size` 기본값은 1로 바꿔 처리 지연이 생기면 오래된 frame을 버리고 최신 frame만 분석한다.

- [ ] **Step 7: 소켓 binary 전송을 await 가능하게 변경**

`sendAudioChunk`와 `sendVideoFrame`은 `payload.arrayBuffer()` 완료 후 `WebSocket.send()` 호출 여부를 boolean으로 반환한다. 같은 WebSocket에서 audio binary 전송 Promise가 끝난 뒤 `session.end` JSON을 보내므로 browser send queue 순서가 보장된다.

- [ ] **Step 8: `PracticePage.handleEnd`를 lifecycle 함수에 연결**

중복 클릭 방지를 위해 `isStopping` 상태를 두고, 종료 버튼을 비활성화한다. 성공 시 `session.completeSession(report)`, 실패/timeout 시 로컬 transcript를 보존한 incomplete summary를 만든다.

- [ ] **Step 9: Task 3 검증과 커밋**

Run: `node --test --experimental-strip-types tests/frontend_tools.test.mjs`

Run: `npm run lint && npm run typecheck && npm run build`

Expected: all PASS.

```bash
git add src/features/practice/audioTools.ts src/features/practice/sessionLifecycle.ts src/features/practice/hooks/useBackendStreaming.ts src/features/practice/hooks/useFeedbackSocket.ts src/features/practice/PracticePage.tsx app/core/config.py tests/frontend_tools.test.mjs
git commit -m "Flush 16 kHz audio before session completion"
```

### Task 4: STT 발화 구간과 중복 없는 집계

**Files:**
- Create: `app/modules/speech/__init__.py`
- Create: `app/modules/speech/text.py`
- Modify: `app/ai/local_stt.py`
- Modify: `app/realtime/aggregator.py`
- Test: `tests/test_local_stt.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Qwen transcript, 16 kHz mono samples, 250 ms overlap
- Produces: `active_speech_duration(audio, sample_rate, threshold) -> float`, `merge_transcript(existing, incoming) -> tuple[str, str]`

- [ ] **Step 1: 실제 발화 구간 시간 테스트 작성**

```python
def test_active_speech_duration_excludes_silence() -> None:
    silence = np.zeros(16_000, dtype=np.float32)
    speech = np.full(16_000, 0.1, dtype=np.float32)
    audio = np.concatenate([silence, speech, silence])
    duration = active_speech_duration(audio, 16_000, 0.003)
    assert 0.9 <= duration <= 1.1
```

- [ ] **Step 2: 중첩 transcript와 습관어 중복 집계 테스트 작성**

```python
def test_overlapping_final_transcripts_are_merged_once() -> None:
    aggregator = FeedbackAggregator()
    aggregator.add(AIResult(
        "speech_rate", 1000, "info", "ok",
        {"syllables_per_minute": 200, "duration_sec": 2},
        "음 저는 백엔드", True,
    ))
    aggregator.add(AIResult(
        "speech_rate", 2750, "info", "ok",
        {"syllables_per_minute": 220, "duration_sec": 2},
        "백엔드 개발자입니다", True,
    ))
    report = aggregator.report()
    assert report["transcript"] == "음 저는 백엔드 개발자입니다"
    assert report["filler_word_counts"] == {"음": 1}
```

- [ ] **Step 3: 두 테스트가 함수 부재와 transcript 중복으로 실패하는지 확인**

Run: `.venv310/bin/python -m pytest tests/test_local_stt.py::test_active_speech_duration_excludes_silence tests/test_pipeline.py::test_overlapping_final_transcripts_are_merged_once -v`

Expected: both FAIL for the intended missing behavior.

- [ ] **Step 4: speech text 도구 구현**

`app/modules/speech/text.py`에 공백 단위 최대 접미/접두 중첩을 찾는 함수를 구현한다.

```python
def merge_transcript(existing: str, incoming: str) -> tuple[str, str]:
    current = existing.strip()
    next_text = incoming.strip()
    if not next_text or next_text in current:
        return current, ""
    if not current:
        return next_text, next_text
    left = current.split()
    right = next_text.split()
    overlap = 0
    for size in range(min(len(left), len(right)), 0, -1):
        if left[-size:] == right[:size]:
            overlap = size
            break
    novel = " ".join(right[overlap:])
    return " ".join([current, novel]).strip(), novel
```

- [ ] **Step 5: frame RMS 기반 발화 시간을 구현하고 Qwen 분석에 사용**

`active_speech_duration`은 30 ms frame의 RMS가 threshold 이상인 frame 시간만 합산하고 최소 0.5초로 clamp한다. 전체 chunk RMS가 threshold 미만이면 기존대로 Qwen 호출을 생략한다. 발화 속도 분석에는 chunk 전체 길이 대신 이 값을 전달한다.

- [ ] **Step 6: aggregator가 final의 novel text만 누적하도록 수정**

`transcript_parts`를 `transcript` 문자열로 바꾸고 `merge_transcript`의 novel text에서만 `어|음|그|저기|그러니까`를 집계한다. partial 결과는 transcript·습관어·평균 속도 집계에서 제외한다.

- [ ] **Step 7: STT 실패 격리 테스트 추가**

기존 `test_slow_failing_gaze_does_not_stop_speech`의 반대 방향으로 failing speech와 정상 gaze를 넣고, `SPEECH_AI_UNAVAILABLE` error 뒤에도 gaze feedback이 도착하는지 검증한다.

- [ ] **Step 8: Task 4 검증과 커밋**

Run: `.venv310/bin/python -m pytest tests/test_local_stt.py tests/test_pipeline.py -v`

Run: `.venv310/bin/python -m ruff check app tests`

Run: `.venv310/bin/python -m mypy app`

Expected: all PASS.

```bash
git add app/modules/speech app/ai/local_stt.py app/realtime/aggregator.py tests/test_local_stt.py tests/test_pipeline.py
git commit -m "Stabilize streaming speech aggregation"
```

### Task 5: 시선 관찰값 계약과 시간 기반 안정화

**Files:**
- Create: `app/modules/gaze/__init__.py`
- Create: `app/modules/gaze/service.py`
- Modify: `app/realtime/pipeline.py`
- Modify: `app/realtime/aggregator.py`
- Modify: `app/api/v1/websocket.py`
- Modify: `src/lib/realtimeProtocol.ts`
- Test: `tests/test_gaze_service.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: gaze `AIResult.metrics`
- Produces: `GazeObservation`, `GazeStabilizer.update(result) -> AIResult`, 실제 timestamp 기반 gaze duration

- [ ] **Step 1: 얼굴 미검출과 이탈을 분리하는 테스트 작성**

```python
def gaze_result(timestamp_ms: int, face_detected: bool, direction: str) -> AIResult:
    return AIResult(
        source="gaze",
        timestamp_ms=timestamp_ms,
        level="info",
        message="",
        metrics={
            "face_detected": face_detected,
            "gaze_direction": direction,
            "attention_state": "camera" if direction == "center" else "away",
            "quality": 0.9 if face_detected else 0.0,
            "confidence": 0.9 if face_detected else 0.0,
            "calibrated": True,
            "head_pose": {
                "yaw": 0.0 if face_detected else None,
                "pitch": 0.0 if face_detected else None,
                "roll": 0.0 if face_detected else None,
            },
            "away": face_detected and direction != "center",
        },
    )


def test_no_face_is_unknown_not_gaze_away() -> None:
    stabilizer = GazeStabilizer(warning_after_ms=2000)
    result = gaze_result(1000, face_detected=False, direction="unknown")
    stabilized = stabilizer.update(result)
    assert stabilized.metrics["attention_state"] == "unknown"
    assert stabilized.metrics["away"] is False
    assert "얼굴이 화면에서 벗어났습니다" not in stabilized.message


def test_calibration_requires_sixteen_good_center_frames() -> None:
    stabilizer = GazeStabilizer(calibration_frames=16)
    for index in range(15):
        current = stabilizer.update(gaze_result(index * 125, True, "center"))
        assert current.metrics["calibrated"] is False
    calibrated = stabilizer.update(gaze_result(15 * 125, True, "center"))
    assert calibrated.metrics["calibrated"] is True
```

- [ ] **Step 2: 2초 미만 흔들림과 지속 이탈 테스트 작성**

```python
def test_gaze_warning_requires_sustained_away_state() -> None:
    stabilizer = GazeStabilizer(warning_after_ms=2000)
    first = stabilizer.update(gaze_result(1000, True, "left"))
    transient = stabilizer.update(gaze_result(2500, True, "left"))
    sustained = stabilizer.update(gaze_result(3100, True, "left"))
    assert first.level == "info"
    assert transient.level == "info"
    assert sustained.level == "warning"
    assert "왼쪽" in sustained.message
```

- [ ] **Step 3: 테스트가 모듈 부재로 실패하는지 확인**

Run: `.venv310/bin/python -m pytest tests/test_gaze_service.py -v`

Expected: FAIL with module not found.

- [ ] **Step 4: `GazeObservation`과 `GazeStabilizer` 구현**

```python
@dataclass(frozen=True, slots=True)
class GazeObservation:
    face_detected: bool
    head_pose: dict[str, float | None]
    gaze_direction: str
    attention_state: str
    quality: float
    confidence: float
    calibrated: bool
```

stabilizer는 보정 frame의 yaw/pitch 중앙값을 baseline으로 저장하고, 이후 raw 각도에서 baseline을 뺀 뒤 기본 12도 threshold로 `center|left|right|up|down`을 만든다. 또한 `unknown`, `camera`, `screen`, `away` 상태의 시작 timestamp를 보관한다. `away`가 2000 ms 이상 유지될 때만 warning을 만들고, 같은 메시지는 5000 ms 이내에 반복하지 않는다. 얼굴 미검출은 1000 ms 후 안내하되 aggregator의 gaze-away 시간에는 포함하지 않는다.

세션 시작 후 품질 기준을 통과한 정면 frame 16개를 baseline으로 모으는 명시적 보정 단계를 둔다. 보정이 끝나기 전 결과는 `calibrated=false`, `attention_state=unknown`이며 이탈 집계와 경고를 만들지 않는다. 프론트 패널은 사용자에게 `카메라를 바라보며 보정 중 (n/16)`을 표시한다.

- [ ] **Step 5: 파이프라인별 stabilizer 적용**

`SessionPipeline.__init__`에서 인스턴스를 만들고 gaze `AIResult`를 aggregator와 emit에 넘기기 전에 안정화한다. 어댑터가 필드를 생략하면 `unknown`, `0.0`, `False`로 정규화하며 정면으로 추측하지 않는다.

- [ ] **Step 6: 실제 timestamp 기반 집계 테스트 작성**

```python
def test_gaze_away_duration_uses_sample_timestamps() -> None:
    aggregator = FeedbackAggregator()
    aggregator.add(gaze_result(1000, True, "left"))
    aggregator.add(gaze_result(1750, True, "left"))
    aggregator.add(gaze_result(2500, True, "center"))
    assert aggregator.report()["gaze_away_duration_ms"] == 1500
```

- [ ] **Step 7: aggregator의 고정 333 ms 제거**

마지막 gaze timestamp와 상태를 저장하고 다음 gaze sample timestamp와의 차이만 이전 상태에 더한다. timestamp가 역행하면 0으로 처리하고, 얼굴 미검출/품질 부족은 sample 수에는 포함하되 away 시간에는 포함하지 않는다.

- [ ] **Step 8: 프론트 gaze 계약 연결**

`RealtimeFeedback.gaze`에 `faceDetected`, `headPose`, `direction`, `attentionState`, `quality`, `confidence`, `calibrated`를 추가하고 패널에 상태·신뢰도·안내 문장을 표시한다. 보정 전에는 `보정 중`, quality 부족은 `판단 어려움`으로 표시한다.

- [ ] **Step 9: Task 5 검증과 커밋**

Run: `.venv310/bin/python -m pytest tests/test_gaze_service.py tests/test_pipeline.py -v`

Run: `npm run typecheck`

Expected: all PASS.

```bash
git add app/modules/gaze app/realtime/pipeline.py app/realtime/aggregator.py app/api/v1/websocket.py src/lib/realtimeProtocol.ts tests/test_gaze_service.py tests/test_pipeline.py
git commit -m "Add stable gaze observation contract"
```

### Task 6: UniFace MobileGaze 어댑터와 MacBook 평가

**Files:**
- Create: `app/ai/uniface_gaze.py`
- Create: `scripts/benchmark_gaze.py`
- Modify: `app/api/v1/websocket.py`
- Modify: `app/core/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_uniface_gaze.py`

**Interfaces:**
- Consumes: JPEG bytes, UniFace `RetinaFace.detect(image)`, `MobileGaze.estimate(face_crop)`
- Produces: `UniFaceGazeAdapter.infer(media) -> AIResult`, JSON benchmark summary

- [ ] **Step 1: 외부 모델 없이 adapter mapping을 검증하는 테스트 작성**

```python
class FakeFace:
    bbox = np.array([20, 10, 180, 190], dtype=np.float32)
    confidence = 0.95


class FakeDetector:
    def detect(self, _frame: np.ndarray) -> list[FakeFace]:
        return [FakeFace()]


class FakeEstimate:
    pitch = 0.02
    yaw = -0.35


class FakeEstimator:
    def estimate(self, _face_crop: np.ndarray) -> FakeEstimate:
        return FakeEstimate()


@pytest.mark.asyncio
async def test_uniface_adapter_maps_angles_to_contract() -> None:
    adapter = UniFaceGazeAdapter(
        detector=FakeDetector(),
        estimator=FakeEstimator(),
        decoder=lambda _payload: np.zeros((200, 200, 3), dtype=np.uint8),
    )
    result = await adapter.infer(MediaPayload(uuid4(), 1000, b"jpeg"))
    assert result.metrics["face_detected"] is True
    assert result.metrics["gaze_direction"] == "unknown"
    assert round(result.metrics["head_pose"]["yaw"]) == -20
    assert result.metrics["quality"] > 0
```

- [ ] **Step 2: 테스트가 adapter 부재로 실패하는지 확인**

Run: `.venv310/bin/python -m pytest tests/test_uniface_gaze.py -v`

Expected: FAIL with module not found.

- [ ] **Step 3: UniFace 의존성과 설정 추가**

`pyproject.toml`의 `ai` extra에 `uniface[cpu]>=4,<5`를 추가한다. `Settings.vision_provider`는 `Literal["legacy", "uniface", "mock"]`로 제한하고 기본값을 `uniface`로 바꾼다. `.env.example`에 `VISION_PROVIDER=uniface`를 넣는다.

- [ ] **Step 4: ONNX 기반 adapter 구현**

`UniFaceGazeAdapter.__init__(detector=None, estimator=None, decoder=None)`로 테스트 주입점을 두되 기본값은 공식 quickstart와 동일한 `RetinaFace`, `MobileGaze`, OpenCV decoder다. Apple Silicon에서는 `CoreMLExecutionProvider`, `CPUExecutionProvider` 순서를 사용한다. 얼굴 bbox 면적과 detector confidence로 quality를 계산하며 bbox가 프레임의 5% 미만이면 direction을 `unknown`으로 둔다. adapter는 raw pitch/yaw만 반환하고, 방향 threshold와 개인 정면 baseline은 Task 5의 파이프라인별 stabilizer가 적용한다.

- [ ] **Step 5: L2CS runtime 채택 여부를 호환성 gate로 기록**

공식 L2CS repository의 현재 package/weight 설치와 Apple Silicon CPU 추론을 별도 임시 환경에서 확인한다. 다음 중 하나라도 해당하면 제품 의존성에 추가하지 않고 benchmark 결과에 `rejected`와 이유를 기록한다.

- 별도 수동 weight 파일 없이는 실행 불가
- pitch/yaw 순서가 공개 API와 일치하지 않음
- 640×480 단일 얼굴 P95가 125 ms를 넘음
- 얼굴 미검출을 정상 결과와 구분하지 못함

UniFace는 공식 문서상 Apple Silicon용 CPU extra와 ONNX provider를 지원하고, MobileGaze 결과를 pitch/yaw radians로 제공한다. 참고: `https://yakhyo.github.io/uniface/quickstart/`, `https://yakhyo.github.io/uniface/models/`, `https://github.com/ahmednull/L2CS-Net`.

- [ ] **Step 6: 재현 가능한 benchmark CLI 구현**

`scripts/benchmark_gaze.py`는 `--provider`, `--input`, `--labels`, `--output`을 받고 각 frame의 ground-truth direction, prediction, latency를 수집한다. stdout과 JSON에 `binary_f1`, `macro_f1`, `mean_latency_ms`, `p95_latency_ms`, `no_face_rate`를 기록한다. 입력 영상은 저장소에 커밋하지 않고 사용자가 지정한 로컬 경로만 읽는다.

- [ ] **Step 7: demo endpoint가 설정된 adapter를 사용하도록 변경**

매 연결마다 대형 모델을 다시 로딩하지 않는다. 앱 시작 시 registry와 동일한 gaze adapter를 생성하고 demo endpoint도 `websocket.app.state.gaze`를 사용한다. 모델 로드 실패 시 silent Mock fallback을 제거하고 명시적인 `GAZE_AI_UNAVAILABLE` 오류를 보낸다. `legacy`는 문제 비교용 설정으로만 유지한다.

- [ ] **Step 8: 자동 검증과 3분 사용자 검증 준비**

Run: `.venv310/bin/python -m pytest tests/test_uniface_gaze.py tests/test_gaze_service.py -v`

Run: `.venv310/bin/python -m ruff check app tests scripts`

Run: `.venv310/bin/python -m mypy app`

Expected: all PASS.

사용자 검증은 정면/좌/우/상/하 각 10초와 얼굴 미검출 10초를 녹화하지 않고 실시간 집계한다. 목표는 binary F1 ≥ 0.90, 5방향 macro F1 ≥ 0.80, P95 ≤ 125 ms(8 FPS 처리 가능), 정면 오경고 ≤ 1회/분이다. 기준 미달이면 threshold와 정면 baseline만 조정하고 새 모델을 추가하지 않는다.

- [ ] **Step 9: Task 6 커밋**

```bash
git add app/ai/uniface_gaze.py scripts/benchmark_gaze.py app/api/v1/websocket.py app/core/config.py pyproject.toml .env.example README.md tests/test_uniface_gaze.py
git commit -m "Replace legacy gaze inference with UniFace"
```

### Task 7: 전체 회귀 검증과 실행 문서

**Files:**
- Modify: `docs/webrtc-contract.md`
- Modify: `README.md`
- Modify: `tests/frontend_tools.test.mjs`
- Modify: `tests/test_session_flow.py`

**Interfaces:**
- Consumes: Tasks 1–6의 최종 WebSocket/event/audio/gaze 계약
- Produces: 재현 가능한 localhost 실행·검증 절차

- [ ] **Step 1: 짧은 세션과 source 독립성을 포함한 end-to-end 테스트 완성**

인증 WebSocket 통합 테스트에서 gaze feedback, transcript final, `session.end`, `session.completed`를 순서대로 검증한다. 완료 report의 transcript, filler count, gaze duration과 incomplete flag를 단언한다.

- [ ] **Step 2: 계약 문서 갱신**

`docs/webrtc-contract.md`에 9-byte binary header, 16 kHz WAV, `session.end`, source별 feedback, `session.completed` payload와 종료 순서를 실제 타입 이름 그대로 기록한다. `README.md`에 Qwen/UniFace 최초 weight 다운로드, localhost 실행, 오류 확인 위치를 추가한다.

- [ ] **Step 3: 전체 자동 검증**

Run: `.venv310/bin/python -m pytest`

Run: `.venv310/bin/python -m ruff check .`

Run: `.venv310/bin/python -m mypy app`

Run: `node --test --experimental-strip-types tests/frontend_tools.test.mjs`

Run: `npm run lint`

Run: `npm run typecheck`

Run: `npm run build`

Expected: every command exits 0. Existing third-party deprecation warning may be reported but no new warning is accepted.

- [ ] **Step 4: localhost 자동 smoke test**

백엔드 `/health/ready`가 200인지 확인하고, 프론트 Vite build를 localhost에서 열어 콘솔 error가 없는지 확인한다. 카메라·마이크 권한이 없어도 UI가 명시적인 권한 오류를 보여야 한다.

- [ ] **Step 5: 사용자 카메라·마이크 검증 요청**

자동 검증이 모두 통과한 뒤에만 사용자에게 다음 한 번의 수동 테스트를 요청한다.

1. 정면/좌/우/상/하 각 10초
2. 정상/빠름/느림 문장 각 1회
3. `음`, `어`, `그`를 포함한 문장 1회
4. 마지막 문장 도중 종료 1회

최종 transcript와 benchmark summary만 남기고 원본 영상·음성은 저장하지 않는다.

- [ ] **Step 6: 최종 커밋**

```bash
git add docs/webrtc-contract.md README.md tests/frontend_tools.test.mjs tests/test_session_flow.py
git commit -m "Document stabilized realtime pipeline"
```

- [ ] **Step 7: 완료 전 branch 검토**

`superpowers:verification-before-completion`으로 전체 검증 결과를 다시 확인하고 `superpowers:requesting-code-review`로 branch 전체 review를 수행한다. 발견된 correctness 문제만 수정하고 범위 밖 감정/LLM 기능은 추가하지 않는다.
