# Exclusive Model Processes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qwen3.5-9B Q4_K_M 문장 요약과 STT·시선 가중치의 메모리 상주를 분리한다.
**Architecture:** 서버는 가중치를 로드하지 않고, 요약 llama-server 또는 실시간 AI 자식 중 하나만 실행한다. 단일 소유 관리자가 모든 세션의 실행권을 예약하고 자식 회수 후 해제한다. 기존 미디어 큐와 분석·리포트 계약을 유지한다.
**Tech Stack:** Python 3.10+, asyncio subprocess/Unix socket, FastAPI, 기존 Qwen ASR·MediaPipe·MobileGaze·llama.cpp, React/TypeScript.
**Spec:** ../specs/2026-10-14-exclusive-model-processes-design.md

## Global Constraints

- 브랜치 codex/local-script-summary, 로컬 단일 사용자, 새 제품 의존성 없음.
- 부모에서 가중치 미로드. 요약 자식과 실시간 자식의 생존 구간 배타적.
- 시작 120초, 프론트 준비 130초, 요약 전체 600초, 정상 종료 대기 5초 후 강제 회수.
- 기존 모델 알고리즘·미디어·AIResult 필드 보존, fake는 tests에만 허용.
- 원본 미디어·전사 로그/파일 미기록, 가중치 Git 제외, main 병합·원격 푸시 제외.

## Review Focus

1. 자식 생성 중 연속 취소: 핸들을 확보하고 종료 후에만 실행권 해제.
2. 추론 waiter 취소: 실제 네이티브 실행이 끝나기 전 슬롯 재사용 금지.
3. worker 죽음/잘못된 응답: 모든 대기자 실패와 재시도 복구, 임의 결과 없음.
4. 세션 종료와 요약 동시 요청: drain·프로세스 회수 구간에도 배타성 유지.
5. 로딩 실패·부모 종료: 부분 로드 자식/소켓/세션 소유권 누락 없음.

### Task 1: Real-time child and IPC

**Files:** app/ai/worker_transport.py, app/ai/realtime_worker.py, app/ai/realtime_process.py; tests/test_realtime_process.py, tests/model_worker_fixture.py.
**Interfaces:** RealtimeModelProcess(settings) exposes gaze/speech infer(MediaPayload)->AIResult proxies, mutable modules dict, process handle, async start()/stop(). Child uses existing model factories and independent inference gates. Tests may inject a child command, never a runtime fake setting.
- [x] Write RED tests for idle no-child, full payload/result round-trip, concurrent modalities, malformed/oversized frames, cancellation and child crash, repeated start/stop and parent EOF.
- [x] Run targeted tests and record expected failures.
- [x] Implement bounded length-prefixed JSON + raw bytes, private Unix socket, fresh Python subprocess, startup handshake, protected spawn/reap and module statuses.
- [x] Run targeted tests, Ruff and mypy; verify child PIDs gone.

### Task 2: Exclusive ownership and all session paths

**Files:** app/ai/model_execution.py, app/main.py, app/realtime/pipeline.py, app/realtime/registry.py, app/api/v1/websocket.py, app/api/v1/scripts.py, app/ai/script_summary.py; tests/conftest.py, tests/fake_ai.py, tests/test_provider_startup.py, tests/test_model_execution.py, tests/test_script_summary.py.
**Interfaces:** ModelExecution(runtime) provides reserve_summary()/release_summary(), async start_session(UUID)/stop_session(UUID)/close(), with synchronous ownership reservation before awaits. Pipelines accept optional internal execution dependency; all service-created pipelines receive the one app manager. Main exposes module statuses from runtime without startup model loading.
- [x] RED tests for every v1/v2/WebRTC entry point, same-session transports, other-session rejection, summary reservation while loading/stopping, repeated cancellation and failed rollback.
- [x] Implement lifecycle integration and finally-based app shutdown. Move no analysis algorithms.
- [x] Preserve drain, release real-time child before session.completed, and summary child before unlock. Reject summary in ai_mode=http.
- [x] Run Python full suite and inspect task/process leak diagnostics.

### Task 3: Qwen 9B and UI contract

**Files:** app/core/config.py, .env.example, app/realtime/events.py, src/lib/realtimeProtocol.ts, src/features/practice/hooks/useFeedbackSocket.ts, src/features/practice/PracticePage.tsx, src/features/practice/components/PresentationSetup.tsx, README.md; tests/interview-ui.test.mjs, tests/script_summary.test.mjs.
- [x] RED checks for idle/loading/ready/unavailable labels, model Qwen3.5-9B Q4_K_M, 130s ready wait and completion wait including teardown.
- [x] Change default model path/name and summary timeout600, copy/hash-check existing ignored 9B asset, retain context4096/thinking off and sentence mapping.
- [x] Show model preparing/idle states and preserve editable hints/toggle. Document memory/OS cache distinction and cold start.
- [x] Run Node tests, ESLint and production build.

### Task 4: Whole-service verification

- [x] Full pytest + Node + Ruff + mypy + lint + build + diff check.
- [x] Fresh-context whole-branch review while running real-model checks; fix material findings with regressions.
- [x] Actual 9B summary, process exit, then actual STT/gaze start/stop; record PID intervals, RSS/swap observations and observed startup times. No camera/mic permission without user confirmation; synthetic media permitted.
- [x] Leave local branch/server usable, report unchecked microphone/camera quality separately; do not merge/push.

## Execution ledger

- 2026-10-14: User requested end-to-end implementation of the approved written design. Execute continuously, with no unrelated features.
- Ruling: 기존 독립 모델 실행기를 자식 안에서 재사용하고, 모델별 새 서버나 제품 의존성은 추가하지 않는다. 메모리 소유권은 프로세스 종료로 분리한다.
- Task 1–3 implementation and regression gates passed. Native worker 30 tests; all API entry paths exercised through actual test child processes.
- Review fixes: rejected duplicate connections cannot release another pipeline's execution or peer; failed initial WebRTC rolls back only unconnected new pipelines; startup accepts cancel/disconnect before ready; stale failure permits retry; final standalone WebRTC disconnect reaps the worker; draining pipelines reject new attachment; intentional cancellation returns idle.
- Actual models: 9B two sentences 7.80s (web 6.71s), real-time initialization 8.99s (network 12.92s), all three observed child PIDs reaped with no overlap. Real PCM ACK/final report and network startup cancellation also passed. No microphone/camera permission used.
- Full verification before final review completion: pytest 214, Node 37, Ruff, mypy, ESLint, build and diff check passed. Review follow-up remains the final gate.
- Memory ruling: process exit proves release of owned model memory, not a return of OS cache/swap to baseline. Actual global swap rose; report this limitation rather than claim zero burden.
- 2026-10-15 final gate: pytest 218 + Node 37 passed; Ruff, mypy (63 files), ESLint, production build and diff check passed. HTTP disconnect regressions preserve existing peers and reap only a newly abandoned session.
- Final review fix: never-connected WebRTC peers expire 30s after answer creation. Native regression reproduced indefinite ownership RED; expiry now reaps the worker GREEN. A second RED test reproduced cancellation of yielding peer cleanup; clearing the deadline reference before closing fixes it. All 14 lifecycle regressions passed.
- Review limitation: the independent reviewer identified the final timer issue and recommended the exact fix, but usage limits prevented their last follow-up. The implementer inspected that fix and verified it with the failing-then-passing regression and full suite; no clean independent re-review is claimed.
- Final actual-network check: real models ready in 12.28s, silent PCM ACK and final report succeeded, preparation cancellation 0.016s, both paths returned to idle. Implementation remains uncommitted on codex/local-script-summary; main and remote unchanged.
