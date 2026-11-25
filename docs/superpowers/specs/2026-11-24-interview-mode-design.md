# 면접 연습 기능 설계

- 작성일: 2026-11-24
- 계획: [`docs/superpowers/plans/2026-11-24-interview-mode.md`](../plans/2026-11-24-interview-mode.md) (결정 사항 §7)
- 조사: [`docs/research/2026-11-24-interview-question-references.md`](../../research/2026-11-24-interview-question-references.md)

서류와 지원 직무로 질문을 만들고, 시스템이 면접관처럼 질문을 내고 넘기며, 끝나면 질문별 평가와 종합 피드백을 보여 주는 기능이다. 질문 구성·평가 기준·결정의 이유는 계획 문서에 있고, 이 문서는 **모듈의 경계와 인터페이스, 데이터 흐름, 테스트 방법**을 정한다.

## 1. 전제와 제약

- 로컬 AI 모드 전용이다. 프론트는 로그인 없는 로컬 데모 경로(`/api/v1/ws/practice-demo`, 프로토콜 2)를 쓰며, 이 경로는 세션을 DB에 저장하지 않는다. 면접 기능도 같은 경로를 쓴다.
- **저장 방식(설계 중 확정)**: 면접 진행·평가 중의 기록은 서버 메모리에 두고, 최종 결과와 받은 질문 ID는 브라우저(localStorage)에 저장한다. DB 테이블과 마이그레이션은 만들지 않는다. 계획의 "새 테이블" 결정은 이것으로 바뀐다.
- 생성 모델(Qwen3.5-9B Q4_K_M, llama-server)과 실시간 모델(ASR·시선 프로세스)은 동시에 메모리에 올리지 않는다(16GB 맥북). 맥박 ONNX(약 9MB)만 예외다(§4.6 앞 7단계 구현 결과). 모델 점유는 `ModelExecution` 하나가 관리한다.
- 발화 분리는 서버의 `SpeechSegmenter`(`app/modules/speech/segments.py`, 끝점 500ms, 최대 8초)가 하고, 20ms 프레임마다 유성 여부를 알려 주는 관찰 지점(`observe_frame`)이 있다. 받아쓰기 최종 결과에는 `utterance_id`, `start_ms`, `end_ms`가 붙는다.
- 서류 전문은 질문 생성 뒤 버린다. 메모리에도 근거 문장만 남긴다.

## 2. 용어

| 용어 | 뜻 |
|---|---|
| 면접(interview) | 질문 생성부터 평가까지의 한 번. `interview_id`로 구별하며 실시간 세션 하나와 대응한다 |
| 면접 계획(plan) | 면접 전에 정해진 질문 목록과 구성. 생성 후 사용자가 고르고 순서를 바꾼 결과 |
| 질문 항목(item) | 질문 1개와 그 답변·시간·넘김 이유·평가를 묶은 단위. 추가 질문은 부모 항목에 딸린 항목 |
| 재료(material) | 서류에서 뽑은 질문 근거. 원문 인용(`quote`)이 서류에 실제로 있어야 한다 |
| 라운드(round) | 1라운드는 본 질문, 2라운드는 추가 질문. 같은 세션 안에서 진행한다 |
| 라운드 휴식(round break) | 1·2라운드 사이. 실시간 모델을 내리고 추가 질문을 만든 뒤 다시 올리는 구간 |
| 읽는 시간 | 질문을 보여 주는 시간. `3초 + 글자 수 ÷ 7초`, 최대 15초 |
| 답변 구간 | 한 질문에 대한 답으로 인정하는 시간 구간. 발화의 `start_ms`로 소속을 정한다 |
| 넘김 이유 | `silence`(침묵), `time_limit`(제한 시간), `no_response`(무응답), `stopped`(면접 중단) |
| 빠진 요소(gap) | 추가 질문이 묻는 답변의 빈 곳. 본인 역할, 판단 이유, 결과 확인, 배운 점, 협업 과정, 구체적 사례 등 |
| 평가 불가 | 무응답, 20음절 미만, 인식 실패. 0점이 아니며 평균에서 뺀다 |

## 3. 전체 흐름

```
[준비 화면]
  서류 업로드 ──POST /interview/documents──▶ 추출 텍스트(저장 안 함)
  사용자 수정 + 직무 입력
  질문 생성 ──POST /interview/plans (NDJSON 진행)──▶ interview_id + 질문 목록
             (생성 모델 로딩 → 재료 추출 → 질문 생성 → 생성 모델 정리, 서류 텍스트 폐기)
  질문 고르기·순서 바꾸기

[면접 화면]  WebSocket(practice-demo, v2)
  session.start {mode: interview, interview: {interview_id, question_ids}}
  ◀ interview.question / interview.question_hidden / interview.advanced ...   (1라운드)
  ◀ interview.round_break {stage}      실시간 모델 정리 → 추가 질문 생성 → 실시간 모델 재시작
  ◀ interview.question ...                                                    (2라운드)
  ◀ interview.finished
  session.end ─▶ ◀ session.completed {report}     (음성·시선 결과, 질문별 받아쓰기)

[결과 화면]
  GET /interview/{id}/evaluation (NDJSON 진행)──▶ 질문별 평가 + 종합 피드백
  결과·받은 질문 ID를 localStorage에 저장
```

## 4. 모듈 구성

새 코드는 순수 도메인 모듈(`app/modules/interview/`)과, 모델·입출력을 다루는 바깥 모듈로 나눈다. 판단 로직은 모두 도메인 쪽에 두어, 모델이나 소켓 없이 테스트할 수 있게 한다.

| 모듈 | 위치 | 역할 | 의존 |
|---|---|---|---|
| 면접 진행기 `InterviewConductor` | `app/modules/interview/conductor.py` | 질문 표시·숨김, 답변 종료 판단, 자동 넘김, 다시 보기, 답변 구간 배정 | 없음(순수, 시각 주입) |
| 질문 목록 `question_bank` | `app/modules/interview/question_bank.py` | 공통 질문 데이터와 고르기 | 없음 |
| 질문 규칙 `questions` | `app/modules/interview/questions.py` | 질문·재료 타입, 생성 결과 검증(길이·금지 주제·근거 인용), 중복 제거 | 없음 |
| 평가 기준 `rubric` | `app/modules/interview/rubric.py` | 평가 항목·등급 기준 데이터, 평가 가능 여부 판정, 점수 환산 | 없음 |
| 추가 질문 신호 `follow_ups` | `app/modules/interview/follow_ups.py` | 빠진 요소 규칙 신호("우리"만 있음 등), 질문 종류별 허용 빠진 요소, 고정 질문 문장, 우선순위 | 없음 |
| 구성 `composition` | `app/modules/interview/composition.py` | 면접 구성 설정(유형별 개수, 순서, 추가 질문 최대 수)과 진행 기준값 | 없음 |
| 로컬 LLM 실행기 `LocalLlm` | `app/ai/local_llm.py` | llama-server 띄우기·정리, JSON schema 응답 호출 | llama-server |
| 면접 생성기 `InterviewLlm` | `app/ai/interview_llm.py` | 재료 추출, 질문 생성, 추가 질문 생성, 답변 평가, 종합 피드백 | `LocalLlm`, 도메인 모듈 |
| 서류 추출기 `DocumentExtractor` | `app/modules/interview/documents.py` | PDF·DOCX·TXT → 텍스트 | pypdf, python-docx |
| 면접 저장소 `InterviewStore` | `app/services/interview_store.py` | 면접 계획·항목·평가 상태를 메모리에 보관, 만료 정리 | 없음 |
| 면접 실행 `InterviewRun` | `app/realtime/interview_run.py` | 세션 안에서 진행기를 구동하고 이벤트를 내보냄, 라운드 휴식 진행 | 진행기, 파이프라인, `ModelExecution`, `InterviewLlm` |
| API | `app/api/v1/interview.py` | 서류 추출, 계획 생성, 평가 진행·결과 | 위 모듈 |

### 4.1 면접 진행기 `InterviewConductor` (가장 중요한 모듈)

면접관의 판단을 모두 담는 순수 상태 기계다. 시각과 입력을 받아 할 일을 돌려준다. 소켓, 타이머, 모델을 모른다.

```python
class InterviewConductor:
    def __init__(self, questions: list[PlannedQuestion], rules: TurnRules) -> None: ...
    def start(self, now_ms: int) -> list[Action]: ...
    def on_frame(self, start_ms: int, end_ms: int, voiced: bool) -> list[Action]: ...
    def on_final(self, utterance: FinalUtterance) -> list[Action]: ...
    def on_replay(self, now_ms: int) -> list[Action]: ...
    def tick(self, now_ms: int, pending_finals: int) -> list[Action]: ...
    def add_questions(self, questions: list[PlannedQuestion], now_ms: int) -> list[Action]: ...  # 2라운드
    def items(self) -> list[ItemRecord]: ...
```

- `Action`은 `ShowQuestion(id, text, reading_ms, answer_limit_ms)`, `HideQuestion(id)`, `Advanced(id, reason)`, `RoundFinished(round)`, `ReplayRejected(id)` 중 하나다. `InterviewRun`이 이를 소켓 이벤트로 바꾼다.
- 시각은 모두 세션 시각(ms)이다. `tick`은 `InterviewRun`이 200ms마다 부른다.
- 규칙(값은 `TurnRules` 설정, 기본값은 계획 §7)
  - 읽는 시간이 끝나거나 첫 유성 프레임이 오면(먼저 오는 쪽) `HideQuestion`.
  - 침묵: 마지막 유성 프레임 뒤 4초가 지나고 답변 시작 후 10초가 지났으면 넘김 후보.
  - 제한 시간: 답변 시간이 2분(자기소개 1분 30초)을 넘으면, 진행 중인 발화가 끝나는 대로(마지막 유성 프레임 뒤 끝점 500ms) 넘김 후보.
  - 무응답: 읽는 시간이 끝난 뒤 15초 동안 유성 프레임이 없으면 넘김 후보.
  - 다시 보기: 질문당 1회. 받아들이면 `ShowQuestion`을 다시 내고, 읽는 시간 동안 답변 시간과 침묵·무응답 시계를 멈춘다. 말을 시작해도 다시 보여 준 질문은 `replay_min_visible_ms`(2초) 동안은 숨기지 않고, 그 뒤 또는 읽는 시간이 끝나면 숨긴다. 시계는 실제로 화면에 있던 시간만큼만 멈춘다. 두 번째는 `ReplayRejected`. (2026-11-25 사용자 결정: 다시 보기는 말을 시작해도 최소 2초 표시)
  - **넘김 확정**: 넘김 후보가 되면, 그 질문 구간에서 시작한 발화의 최종 받아쓰기가 모두 도착할 때까지(`pending_finals == 0`) 기다린 뒤 `Advanced`와 다음 `ShowQuestion`을 낸다. 최대 3초 기다리고, 넘으면 그대로 넘긴다(늦게 온 결과는 원래 질문에 붙인다).
- 답변 구간 배정: `on_final`로 들어온 발화는 `start_ms`가 속한 질문의 답변에 붙인다. 질문 전환 뒤에 시작한 발화만 다음 질문에 붙으므로, 경계에 걸친 발화가 다음 질문으로 넘어가지 않는다.
- 이 모듈의 테스트가 자동 넘김의 정확성을 책임진다(§8).

### 4.2 로컬 LLM 실행기 `LocalLlm`

`LocalScriptSummarizer`에 섞여 있는 llama-server 실행·정리와 스트리밍 호출을 떼어 낸다. 요약과 면접이 같은 실행기를 쓴다(어댑터가 둘이므로 실제 이음매다).

```python
class LocalLlm:
    def loaded(self) -> AsyncContextManager[LlmSession]: ...  # 서버를 띄우고, 블록을 나가면 반드시 정리

class LlmSession:
    async def complete_json(
        self, prompt: str, schema: dict, *, max_tokens: int,
        on_delta: Callable[[str], None] | None = None,
    ) -> Any: ...
```

- `loaded()` 블록 하나 안에서 여러 번 호출한다(질문 생성 2회, 평가 N회가 모델 로딩 한 번으로 끝난다).
- 생성 파라미터(temperature 0.2, seed 42, `enable_thinking: False`, `cache_prompt: False`), 출력 크기 제한, `finish_reason == "stop"` 확인은 실행기 안에 둔다.
- 요약기의 문장 묶음 단계별 진행 표시는 `on_delta`로 받은 텍스트를 요약기가 직접 파싱해 유지한다.
- 모델 점유(`ModelExecution` 예약)는 실행기가 아니라 호출하는 쪽이 맡는다. 질문 생성은 면접 전 예약, 추가 질문 생성과 평가는 세션 소유 안에서 빌려 쓰기 때문이다(§4.4).
- 요약 회귀 기준: `tests/test_script_summary.py`(20개), `tests/test_grouped_summary.py`(4개)를 분리 전후로 모두 통과해야 한다.

### 4.3 면접 생성기 `InterviewLlm`

```python
class InterviewLlm:
    async def plan(self, documents: list[DocumentText], job: str, composition: Composition,
                   exclude_common_ids: set[str], on_progress) -> InterviewPlan: ...
    async def follow_ups(self, items: list[ItemRecord], session: LlmSession) -> list[PlannedQuestion]: ...
    async def evaluate(self, items: list[ItemRecord], on_progress) -> InterviewEvaluation: ...
```

- `plan`: 공통 질문은 `question_bank`에서 고르고(LLM 없음), 서류 기반 질문은 한 번의 모델 로딩 안에서 재료 추출 → 질문 생성으로 만든다. 컨텍스트가 4096토큰이라 서류를 약 1,800자씩 나눠 조각마다 재료 추출을 1회 부르고(최대 8회, 조각당 재료 4개), 질문 생성은 1회 부른다. 제한 시간(300초)의 60%를 쓰면 추출을 멈추고 그때까지의 재료로 질문을 만든다. 시간이 모자라거나 재시도 후에도 실패하면 오류 대신 공통 질문으로 채우고 `document_questions_failed` 경고를 붙인다. 재시도는 다른 seed와 고칠 점을 덧붙인 프롬프트로 한다. 결과는 `questions` 모듈로 검증(근거 인용 존재, 금지 주제, 길이, 중복)하고, 서류 재료가 모자라면 공통 질문으로 채운다. 반환값에는 서류 텍스트가 없다.
- `follow_ups`: 라운드 휴식 중 호출. 평가 가능한 본 질문마다 `follow_ups` 규칙 신호를 먼저 계산하고, LLM은 허용된 `gap_type` 중 하나와 답변 인용(`answer_quote`), 질문 문장을 낸다. 인용이 답변에 없거나 실패하면 고정 문장을 쓴다. 빠진 요소가 많은 순으로 최대 2개.
- `evaluate`: 평가 불가 항목은 `rubric`으로 먼저 걸러 LLM을 부르지 않는다. 나머지는 질문당 1회 호출(추가 질문 답변을 묶어 입력)하고, 항목별 `{grade, evidence_quote, evidence_source, reason, improvement}`를 받는다. 근거 인용이 답변에 없으면 그 항목은 무효. 점수는 `rubric.score()`로 계산한다. 마지막에 종합 피드백을 1회 호출한다.
- 프롬프트와 JSON schema는 이 모듈 안의 상수로 두고, 각 호출의 검증 실패는 1회 재시도 후 실패로 처리한다.

### 4.4 모델 점유 `ModelExecution` 변경

현재: `owner`는 `None`, `"summary"`, 세션 UUID 중 하나이고, 세션이 소유하면 생성 작업이 들어올 수 없다.

추가하는 인터페이스:

```python
def reserve_offline(self, kind: Literal["summary", "interview_plan", "interview_evaluation"]) -> None
def release_offline(self, kind) -> None
async def suspend_session(self, session_id: UUID) -> None   # 실시간 모델 정리, 소유권 유지
async def resume_session(self, session_id: UUID) -> None    # 실시간 모델 재시작
def borrowing(self, session_id: UUID) -> AsyncContextManager[None]  # 일시 정지된 세션만 생성 모델 사용 허용
```

- `reserve_summary`/`release_summary`는 `reserve_offline("summary")`의 별칭으로 남겨 기존 호출과 테스트를 그대로 둔다.
- 불변식
  - 실시간 모델과 생성 모델은 동시에 올라가지 않는다. `borrowing`은 세션이 일시 정지 상태일 때만 들어갈 수 있다.
  - 일시 정지 중에도 소유자는 그 세션이다. 다른 세션 시작, 요약, 면접 계획 생성은 계속 거부된다.
  - `stop_session`은 일시 정지·빌려 쓰기 중에도 안전하게 정리한다(빌려 쓰는 작업을 취소하고 생성 모델 정리를 기다린 뒤 끝낸다).
- 면접 후 평가는 세션이 끝난(`stop_session` 이후) 뒤 `reserve_offline("interview_evaluation")`로 예약한다. 평가 도중 새 세션 시작은 거부된다.

### 4.5 파이프라인 일시 정지 `SessionPipeline.suspend()` / `resume()`

라운드 휴식을 위해 파이프라인에 두 동작을 더한다.

- `suspend()`: 새 미디어를 받지 않고, 받은 음성 꼬리까지 처리한 뒤(지금 `stop()`의 drain과 같은 방식) 작업자를 멈추고 `execution.suspend_session()`을 부른다. 집계기·상태·타임라인은 유지한다. `session.suspended` 이벤트를 낸다.
- `resume()`: `execution.resume_session()` → 작업자 재시작 → 미디어 수신 재개. `session.resumed` 이벤트를 낸다. 세션 시계는 휴식 시간을 포함해 계속 흐르고, 집계기는 휴식 구간을 관찰 구간에서 뺀다.
- `stop()`은 일시 정지 상태에서도 바로 끝낼 수 있어야 한다(휴식 중 면접 중단).
- **확인할 것**: 실시간 프로세스를 다시 띄운 뒤 시선 보정값이 유지되는지. 유지되지 않으면 2라운드 시작 전에 짧은 재보정을 넣는다. 첫 구현 전에 `RealtimeModelProcess.start/stop`과 시선 보정 저장 위치를 확인한다.
- 대안(일시 정지가 지나치게 침습적일 때): 라운드마다 파이프라인을 새로 만들고 면접 실행이 두 리포트를 합친다. 지금은 DB 저장이 없어 합치는 비용이 작다. 일시 정지 구현에서 기존 `stop()` 동작을 깨는 변경이 필요하면 이 대안으로 바꾸고 계획 문서에 기록한다.

- **구현 결과(7단계)**: 기존 파이프라인에 `suspend()/resume()`을 붙였다(라운드별 파이프라인은 쓰지 않음). 시선 보정 기준값은 서버의 `GazeStabilizer`에 있어 실시간 프로세스를 다시 띄워도 유지되고, 휴식 공백 때문에 보정이 풀리지 않게 `bridge_gap()`을 부른다. 휴식 구간은 집계기(`exclude`)와 전달력 분석(`mark_gap`)에서 뺀다. 맥박은 휴식 중에도 계속 측정한다(아래).
- **휴식 중 오디오 규약**: `audio_origin_ms`는 바뀌지 않고 `session.resumed`가 다시 알려 준다. 클라이언트의 `sequence`·`start_sample`은 세션 시계와 함께 휴식 중에도 계속 증가해야 한다(멈추거나 0으로 되돌리지 않음). 휴식 중 보낸 오디오는 확인 응답 후 버리고 영상은 조용히 버린다. 보내기를 멈췄던 클라이언트는 재개 후 첫 패킷에 한해 앞으로 건너뛸 수 있다.
- **재개 직후 오디오**: 휴식 중간 시각(짧은 휴식이면 `재개 시각 − 2.5초`)보다 먼저 찍힌 패킷은 오류 없이 확인 응답 후 버린다. 이런 패킷이 오면 규약을 어긴 클라이언트(휴식 중 샘플 카운터가 멈춤)로 보고 리포트를 `incomplete`로 표시하고 경고 로그를 한 번 남긴다. 그 시각 이후 첫 패킷은 보내지 않은 구간을 건너뛸 수 있지만 샘플 위치가 뒤로 갈 수는 없다. 녹음 시작이 늦은 정상 클라이언트(지연 0.5~6초)는 그대로 받는다.
- **맥박은 휴식 중에도 계속 측정한다(2026-11-25 결정)**: 맥박 ONNX(TS-CAN, 약 9MB)는 "실시간 모델과 생성 모델은 동시에 올리지 않는다"는 규칙의 예외로, 라운드 휴식과 생성 모델 빌려 쓰기 중에도 올라가 돌아갈 수 있다. `/pulse/infer`는 세션 없이 오프라인 작업(요약, 면접 계획·평가 생성)이 모델을 점유할 때만 거부한다. 휴식 구간에서 빼는 것은 발화 관련 값(발표 시간, 말 속도, 멈춤, 습관어)뿐이고, 시선은 휴식 중 데이터가 없다. 프론트는 맥박 기록에서 휴식 구간을 빼지 않고 그래프에 휴식 구간을 표시한다.
- 받아쓰기는 서비스 모델(Qwen3-ASR-0.6B, 실시간 프로세스) 하나만 쓴다. 실험용 받아쓰기 모델과 비교 기능은 2026-11-25에 삭제했다.

### 4.6 면접 실행 `InterviewRun`

세션 하나에 붙어 진행기를 구동한다. 파이프라인과 진행기 사이의 얇은 연결 고리이며, 판단은 하지 않는다.

- 파이프라인이 부르는 지점: 유성 프레임(`_observe_delivery_frame` 옆에 같은 관찰 지점 추가), 받아쓰기 최종 결과, 남은 최종 결과 수(음성 큐 크기).
- 200ms 주기 작업으로 `tick`을 부르고, `Action`을 `interview.*` 이벤트로 내보낸다.
- 진행기 시계는 오디오 시각을 따른다: `max(마지막으로 받은 프레임 끝, 서버 시각 − 1.5초)`이며 뒤로 가지 않는다. 음성 프레임은 오디오 시각으로 찍혀 늦게 도착하므로, 서버 시각을 그대로 쓰면 말하는 중에 제한 시간 넘김이 일어난다. 지연이 약 2초를 넘으면 경고 로그를 한 번 남긴다.
- 첫 질문은 `session.running`(시선 보정 뒤)에 오디오 시작 시각으로 띄운다. 면접이 붙은 세션은 피드백 설정과 관계없이 받아쓰기를 켠다. 질문 면접은 데모 경로에서만 지원한다.
- 계획은 한 세션에서만 쓴다(`INTERVIEW_ALREADY_STARTED`). 단, 첫 질문을 띄우기 전에 끝난 세션은 계획을 돌려놓아 다시 쓸 수 있다.
- 1라운드가 끝나면(`RoundFinished(1)`) 라운드 휴식을 진행한다: `pipeline.suspend()` → `execution.borrowing()` 안에서 `InterviewLlm.follow_ups()` → `pipeline.resume()` → `conductor.add_questions()`. 각 단계에서 `interview.round_break {stage}`를 낸다. 추가 질문이 0개거나 생성이 실패하면 2라운드를 건너뛰고 `interview.finished`를 낸다.
- 끝나면 항목 기록을 `InterviewStore`에 넘긴다.

### 4.7 면접 저장소 `InterviewStore`

```python
class InterviewStore:
    def create(self, plan: InterviewPlan) -> str: ...                 # interview_id
    def get(self, interview_id: str) -> InterviewState: ...
    def attach_session(self, interview_id: str, session_id: UUID, question_ids: list[str]) -> None
    def save_items(self, interview_id: str, items: list[ItemRecord]) -> None
    def set_evaluation(self, interview_id: str, evaluation: InterviewEvaluation) -> None
    def discard(self, interview_id: str) -> None
```

- 앱 상태(`app.state.interview_store`)에 하나 둔다. 면접 계획은 생성 후 2시간, 평가 결과는 처음 전달한 뒤 30분(`interview_evaluation_delivered_ttl_seconds`)에 지운다. 다시 받아가도 시간은 늘지 않는다. 서버를 재시작하면 사라진다.
- 진행 중인 세션이나 평가가 있는 항목은 만료·밀어내기 대상이 아니다. 상태에는 `items_saved`(세션이 항목을 넘겼는지), `evaluating`, `evaluation`, `delivered_at`이 있다. 진행 중인 평가 작업은 `app.state.interview_evaluations[id]`에 두어 `DELETE`가 취소한다.
- 계획 하나는 세션 하나에만 붙는다. 이미 세션이 붙은 계획으로 다시 시작하면 거부한다.

## 5. 인터페이스: HTTP와 실시간 이벤트

모든 면접 HTTP API는 요약 API와 같은 조건(로컬 AI 모드, 로컬 개발 화면 Origin)을 검사하고, 진행 중인 세션이 있으면 409를 돌려준다.

### 5.1 HTTP

| 요청 | 입력 | 출력 |
|---|---|---|
| `POST /api/v1/interview/documents` | multipart: 파일 1~3개(종류: 자기소개서·이력서·포트폴리오) | 파일별 `{kind, text, warnings}`. 서버에 남기지 않음 |
| `POST /api/v1/interview/plans` | `{documents: [{kind, text}] (0~3개), job?: str|null (30자 이하, 비우면 직무 없음), exclude_common_ids: []}`. `Accept: application/x-ndjson`이면 진행 상황을 줄 단위로 보냄 | `{interview_id, questions: [PlannedQuestion], warnings}`. NDJSON은 `{"event":"progress","data":{stage,…}}` 줄들 뒤에 마지막 줄 `{"event":"complete","data":{…}}` 또는 `{"event":"error","data":{code,message}}` |
| `GET /api/v1/interview/{id}/evaluation` | `Accept: application/x-ndjson`이면 진행 상황을 줄 단위로 보냄 | 일반 JSON은 `InterviewEvaluation`. NDJSON은 `{"event":"progress","data":{stage,…}}` 줄들(`loading`, `evaluating`+`index`/`total`, `summarizing`, `cleaning`) 뒤에 마지막 줄 `{"event":"complete","data":<InterviewEvaluation>}` 또는 `{"event":"error","data":{code,message}}` |
| `DELETE /api/v1/interview/{id}/evaluation` | — | 진행 중 평가를 취소하고 llama-server 정리가 끝난 뒤 204. 진행 중이 아니어도 204 |

- 상한(설정값): 파일당 10MB, 50쪽, 추출 텍스트 합계 30,000자(넘으면 앞 파일부터 채우고 나머지는 잘라 `truncated` 경고), DOCX 압축 해제 50MB, PDF 스트림 2MB, 요청당 추출 시간 10초. 추출은 한 번에 하나씩만 한다.
- 오류 코드
  - `INTERVIEW_DOCUMENT_REQUEST_INVALID`(422): multipart 형식 오류, 파일 0개·4개 이상, 종류 누락·중복·알 수 없음
  - `INTERVIEW_DOCUMENT_TOO_LARGE`(413): 요청·파일 크기, 쪽수, DOCX 압축 해제 크기 초과
  - `INTERVIEW_DOCUMENT_UNREADABLE`(422): 형식 불일치·알 수 없는 형식, 손상·암호화 파일, PDF 스트림 상한 초과, 추출 시간 초과
  - `INTERVIEW_PLAN_REQUEST_INVALID`(422): 서류 글자 수 합계 초과. 그 밖의 요청 형식 오류는 프레임워크 검증 오류(422, 입력 원문은 돌려주지 않음)
  - `INTERVIEW_MODEL_UNAVAILABLE`(503): 모델·실행 파일 없음
  - `INTERVIEW_PLAN_FAILED`(503 서버 시작 실패·예상 못 한 오류, 504 서버 준비 시간 초과). 모델 호출 실패나 생성 시간 초과는 오류가 아니라 공통 질문으로 채운 계획과 경고로 돌려준다
  - `INTERVIEW_PLAN_CANCELLED`(499): 일반 JSON 요청 중 연결 끊김
  - `INTERVIEW_NOT_FOUND`(404)
  - `INTERVIEW_NOT_READY`(409): 면접 세션이 아직 항목 기록을 저장하지 않았다(진행 중이거나 시작한 적 없음). "면접이 끝난 뒤 평가할 수 있습니다."
  - `INTERVIEW_EVALUATION_FAILED`(503 서버 시작 실패·예상 못 한 오류, 504 서버 준비 시간 초과). 질문 하나의 모델 호출 실패는 오류가 아니라 `failed` 항목과 경고로 돌려준다. 모델 없음은 `INTERVIEW_MODEL_UNAVAILABLE`
  - `INTERVIEW_EVALUATION_CANCELLED`(499): 일반 JSON 요청이 평가 중 연결 끊김·`DELETE`로 취소됨. NDJSON은 같은 코드의 `error` 줄로 끝난다
  - `PRACTICE_ACTIVE`, `SUMMARY_BUSY`, `INTERVIEW_BUSY`(면접 계획·평가 생성 중)
- 평가 요청(`GET .../evaluation`) 동작
  - 이미 평가 결과가 저장돼 있으면 모델을 쓰지 않고 마지막 `complete` 줄만 바로 돌려준다(일반 JSON이면 결과 JSON). 같은 면접의 평가가 진행 중이면 `INTERVIEW_BUSY`(409).
  - 그 밖에는 `reserve_offline("interview_evaluation")` 뒤 `LocalLlm.loaded()`를 한 번 열어 전체를 평가하고, llama-server 정리가 끝난 뒤에 예약을 푼다. 클라이언트 연결이 끊기거나 `DELETE`가 오면 취소하고 같은 순서로 정리한다.
  - 평가 제한 시간은 `interview_evaluation_timeout_seconds`(기본 600초, 모델이 준비된 뒤부터 센다). 넘으면 남은 질문은 `failed`, 경고 `evaluation_timeout`으로 결과를 만든다.
- 텍스트를 찾지 못한 파일(스캔 PDF 등)은 오류가 아니라 `text=""`와 `no_text` 경고로 돌려준다.
- 알려진 한계: 2MB를 넘는 PDF 개체(Form XObject) 안의 글자는 경고 없이 빠진다. 디자인 도구로 만든 포트폴리오에서 실제로 문제가 되면 상한을 다시 정한다.

### 5.2 세션 시작

`SessionStartData`에 면접 필드를 더한다.

```json
{"mode": "interview", "interview": {"interview_id": "…", "question_ids": ["q1", "q3", "q2"]}}
```

- `question_ids`는 계획의 질문 중 사용자가 고른 것과 그 순서다. 계획에 없는 ID나 빈 목록은 `INVALID_SETTINGS`.
- 면접 필드가 없는 `mode: "interview"`는 지금처럼 질문 없는 면접(받아쓰기·음성·시선만)으로 둔다.

### 5.3 서버 → 클라이언트 이벤트 (프로토콜 2, `module: "system"`)

| 이벤트 | 데이터 |
|---|---|
| `interview.question` | `{question_id, round, index, total, text, reading_ms, answer_limit_ms, replay_available}` |
| `interview.question_hidden` | `{question_id}` |
| `interview.advanced` | `{question_id, reason}` |
| `interview.replay_rejected` | `{question_id}` |
| `interview.round_break` | `{stage: "suspending" \| "generating" \| "resuming" \| "skipped", follow_up_count?}` |
| `interview.finished` | `{}` — 클라이언트는 받으면 `session.end`를 보낸다 |
| `session.suspended` / `session.resumed` | 파이프라인 일시 정지·재개 |

- `session.completed`의 리포트에 `interview_items`(질문별 받아쓰기·시간·넘김 이유·다시 보기 사용)를 더한다. 평가는 들어가지 않는다.

### 5.4 클라이언트 → 서버 이벤트

| 이벤트 | 데이터 |
|---|---|
| `interview.replay` | `{question_id}` |

질문을 넘기는 클라이언트 이벤트는 없다. 면접 중단은 기존 `session.end`(`incomplete: true`)를 쓴다.

## 6. 데이터 형식

```python
class PlannedQuestion:      # 계획 §4.4
    id: str
    kind: Literal["common", "document", "follow_up"]
    subtype: str            # 공통 분류, personality_behavioral/situational, job/experience, gap_type
    text: str
    intent: str
    source_quote: str | None
    rubric_items: list[RubricItem]   # 빈 목록이면 평가하지 않음(마무리)
    parent_id: str | None
    bank_id: str | None     # 공통 질문 목록 ID
    round: Literal[1, 2]

class ItemRecord:
    question: PlannedQuestion
    shown_ms: int; answer_started_ms: int | None; ended_ms: int
    advance_reason: Literal["silence", "time_limit", "no_response", "stopped"]
    replay_used: bool
    utterances: list[FinalUtterance]   # utterance_id, start_ms, end_ms, text, voiced_ms
    transcript: str

class ItemEvaluation:       # 본 질문 하나당 하나. 추가 질문 답변은 부모에 묶인다
    question_id: str
    status: Literal["evaluated", "not_evaluable", "not_scored", "failed"]
    not_evaluable_reason: Literal["no_response", "too_short", "recognition_failed"] | None
    grades: dict[RubricItem, Grade]    # Grade = {grade 0~4, evidence_quote, evidence_source: "main"|"follow_up", reason, improvement}
    excluded_items: list[RubricItem]   # 근거 인용이 무효라 빠진 적용 항목
    partial: bool                      # excluded_items가 있으면 true ("부분 평가")
    score: float | None                # 0~20
    follow_up_ids: list[str]           # 함께 평가한 추가 질문

class InterviewEvaluation:
    items: list[ItemEvaluation]
    overall_score: float | None        # evaluated 항목 점수의 평균
    summary: {strengths: [str], improvements: [str], next_goals: [str]}
    model: str; elapsed_seconds: float
    warnings: list[Literal["item_evaluation_failed", "summary_failed", "evaluation_timeout"]]
```

- `status`: `evaluated`(점수 있음), `not_evaluable`(rubric이 평가 불가로 본 답변), `not_scored`(`rubric_items`가 빈 질문, 마무리), `failed`(모델 호출이 재시도 후에도 실패했거나 적용 항목이 모두 무효이거나 제한 시간이 지남). `not_evaluable`·`not_scored`·`failed`는 점수가 없고 종합 점수에서 빠진다. `failed`는 경고 `item_evaluation_failed`(시간 초과는 `evaluation_timeout`)를 붙인다.
- 근거 인용 검사: 공백·문장부호를 뺀 부분 문자열로 `evidence_source`가 가리키는 답변(본 답변 또는 추가 질문 답변)에서 찾는다. 0~1등급은 인용이 비어도 유효하다(2026-11-25 사용자 확정. 일반론 답변에 모델이 빈 인용으로 1등급을 내서 평가 실패가 됐다). 2~4등급은 인용이 필요하고, 인용을 냈다면 1~4등급은 8자 이상으로 답변에 있어야 한다. 일부 항목만 무효면 재시도하지 않고 남은 항목으로 점수를 내며(`partial`), 모두 무효이거나 형식 오류면 다른 seed와 고칠 점을 덧붙여 1회 재시도한다.
- 종합 피드백 호출이 재시도 후에도 실패하면 빈 목록과 경고 `summary_failed`. 평가된 질문이 하나도 없으면 호출하지 않는다.

### 6.1 브라우저 저장(localStorage)

| 키 | 내용 | 보관 |
|---|---|---|
| `interview.history.v1` | 면접별 `{interview_id, date, common_bank_ids}` | 최근 10개 |
| `interview.results.v1` | 면접별 결과(질문·받아쓰기·평가·종합 피드백, 근거 문장) | 최근 10개, 사용자가 지울 수 있음 |

- 질문 생성 요청의 `exclude_common_ids`는 `interview.history.v1`의 최근 3개 면접에서 모은다.
- 서류 전문은 브라우저에도 저장하지 않는다(편집 중 상태는 화면 메모리에만 둔다).

## 7. 프론트엔드

| 모듈 | 위치 | 역할 |
|---|---|---|
| 면접 API | `src/features/interview/api.ts` | 서류 업로드, 계획 생성·평가 NDJSON 읽기, 취소 |
| 면접 기록 | `src/features/interview/storage.ts` | localStorage 읽기·쓰기, 제외 ID 계산 |
| 면접 진행 상태 | `src/features/interview/interviewState.ts` | `interview.*` 이벤트를 화면 상태로 바꾸는 순수 함수(리듀서) |
| 준비 화면 | `src/features/interview/InterviewSetup.tsx` | 업로드, 추출 결과 편집, 직무 입력, 생성 진행, 질문 고르기 |
| 진행 화면 | `InterviewContent.tsx` 수정 | 질문 표시·숨김(서버 이벤트 기준), 다시 보기 버튼, 남은 시간·질문 수, 라운드 휴식 화면 |
| 결과 화면 | `src/features/interview/InterviewReport.tsx` | 종합 피드백, 질문별 카드(추가 질문은 부모 카드 안), 평가 진행 표시, 기존 음성·시선 결과 |

- 질문 표시·숨김, 남은 답변 시간은 서버 이벤트가 기준이다. 클라이언트는 `reading_ms`, `answer_limit_ms`로 카운트다운만 그린다.
- 프론트는 `interview.finished`를 받으면 `session.end`를 보내고, `session.completed` 뒤 평가 NDJSON을 연다.

## 8. 테스트

TDD로 진행한다. 바깥 모듈은 가짜 어댑터로 대신하고, 판단 로직은 도메인 모듈의 인터페이스로 검증한다.

| 대상 | 방법 | 핵심 사례 |
|---|---|---|
| `InterviewConductor` | 가짜 시각으로 프레임·발화·tick을 넣고 `Action` 확인 | 읽는 시간 종료·말 시작 시 숨김 / 침묵 4초(10초 전에는 넘기지 않음) / 제한 시간 후 발화 끝에서 넘김 / 무응답 15초 / 다시 보기 1회·시계 정지·2회째 거부 / 최종 결과 대기와 3초 상한 / 경계에 걸친 발화 배정 / 2라운드 질문 추가 |
| `question_bank` | 고정 난수로 고르기 | 경험형·상황형 주제 겹치지 않음 / 제외 ID / 남은 질문 없을 때 오래된 것부터 / `{직무}` 치환 |
| `questions` | 생성 결과 예시 | 근거 인용 없음·금지 주제·두 가지 질문·길이 초과는 버림 / 같은 재료·같은 유형 중복 제거 |
| `rubric` | 값 계산 | 비적용 항목 제외 환산 / 평가 불가 세 경우 / 평균에서 제외 |
| `follow_ups` | 답변 예시 | "우리"만 있음 → 본인 역할 / 상황형에는 결과·배운 점 금지 / 우선순위 |
| `LocalLlm` | 가짜 llama-server(기존 요약 테스트 방식) | 블록 종료 시 정리 / 취소 시 정리 / 출력 크기 초과 / `finish_reason` 확인 / 요약 회귀 24개 |
| `InterviewLlm` | 가짜 `LlmSession`(정해진 JSON 반환) | 검증 실패 재시도 / 재료 부족 시 공통 질문 보충 / 근거 무효 처리 / 평가 불가 항목은 LLM 호출 안 함 |
| `ModelExecution` | 가짜 runtime | 일시 정지 중 다른 세션·요약 거부 / 빌려 쓰기는 일시 정지 중에만 / 빌려 쓰는 중 stop 정리 / 기존 동작 유지 |
| 파이프라인 | 기존 `tests/fake_ai.py` | suspend 시 음성 꼬리 처리 / resume 후 미디어 수신 / 휴식 중 stop |
| WebSocket 흐름 | TestClient + 가짜 모델 | 질문 3개 면접 → 자동 넘김 → 라운드 휴식 → 2라운드 → `interview.finished` → `session.completed`의 `interview_items` |
| 프론트 | 기존 `*.test.mjs`(node) | 이벤트 리듀서, 제외 ID 계산, 다시 보기 버튼 상태, `tests/interview-ui.test.mjs` 갱신 |

성능(생성·전환·평가 시간, 메모리, 자동 넘김 정확도)은 단위 테스트가 아니라 계획 단계 7의 데모 실험에서 확인한다.

## 9. 구현 순서와 파일

계획 단계와 맞춘다. 각 단계는 coder(TDD) → reviewer(code-review)로 진행한다.

1. 도메인 모듈: `composition`, `questions`, `rubric`, `follow_ups`, `question_bank`(초안 질문 포함), `conductor`
2. `LocalLlm` 분리와 요약기 전환(요약 회귀 24개 통과)
3. `ModelExecution` 확장(`reserve_offline`, `suspend/resume`, `borrowing`)
4. 서류 추출(`documents.py`, `POST /interview/documents`)과 샘플 서류(`tests/fixtures/interview/`)
5. `InterviewLlm.plan`, `InterviewStore`, `POST /interview/plans`
6. 실시간 연결: `SessionStartData` 확장, `InterviewRun`, 이벤트, `session.completed`의 `interview_items`
7. 파이프라인 `suspend/resume`와 라운드 휴식, `InterviewLlm.follow_ups`
8. `InterviewLlm.evaluate`, `GET/DELETE /interview/{id}/evaluation`
9. 프론트: API·저장·리듀서 → 준비 화면 → 진행 화면 → 결과 화면

단계 1과 2는 파일이 겹치지 않아 동시에 진행할 수 있다.

## 10. 남은 확인 사항

- 실시간 프로세스 재시작 후 시선 보정값 유지 여부(§4.5)
- 받아쓰기 최종 결과 지연: 침묵 4초 판단 시점에 최종 결과가 보통 도착해 있는지. 3초 대기 상한이 충분한지 데모 실험에서 확인
- 라운드 휴식 중 마이크·카메라 스트림 처리: 클라이언트는 미디어 전송을 멈추고 화면에 휴식 상태를 보여 준다. 재개 시 오디오 기준 시각(`audio_origin_ms`)이 그대로 유지되는지 확인
- 질문 생성 요청 중 브라우저를 닫았을 때 생성 모델 정리(요약 API의 연결 끊김 처리 방식을 따름)
- 면접 결과의 "이번 연습의 최종 피드백" 창: 지금은 발표용 창이 면접 결과에도 자동으로 뜬다. 면접에서도 띄우되 면접에 맞는 내용으로 바꾸는 작업은 다음 주(14주차)에 한다(2026-11-25 사용자 결정).
- 공통 질문 168개 문구는 사용자가 따로 검토 중이다. 검토 결과에 따라 `question_bank.py`를 고친다(기존 ID는 바꾸지 않는다).
