# Grouped Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. User explicitly requested no further questions.

**Goal:** 의미 묶음 요약과 실제 처리 진행도를 끝까지 연결한다.
**Architecture:** 기존 단기 llama-server에 묶음+요약 구조화 스트리밍 요청, 코드 검증, 동일 POST의 NDJSON 진행 이벤트, 묶음 편집 후 기존 문장 위치 오버레이에 연결.
**Tech Stack:** 기존 Python/FastAPI/httpx/llama.cpp/React/TypeScript. 새 의존성 없음.
**Spec:** ../specs/2026-10-15-grouped-summary-design.md

## Global Constraints
- codex/local-script-summary 유지, 기존 미커밋 작업 보존, commit/merge/push 제외.
- 200문장/문장당1000자/기존 max_script_chars 제한, context4096, 요약600초, 모델 회수 후 완료.
- 원문 index는 0-based inclusive, groups는 전체 원문을 정확히 한 번 순서대로 포함.
- 프로세스 배타성/취소/준비 시선 보정은 기존대로 유지.

## Review Focus
- 스트리밍이 끊겨도 자식/실행권이 남지 않음.
- 누락/중복/역순/잘림을 정상 요약으로 표시하지 않음.
- 덮어쓰기 실패와 오래된 대본 응답은 수동 편집본 보존.
- 진행률은 실제 원문 처리 수, 생성 묶음 수나 가짜 시간 비율 아님.
- 긴 입력은 tokenizer 확인 후 연속 청크, 추론 자동 반복 없음.

### Task 1: Model grouped output
Files: app/ai/script_summary.py, tests/test_script_summary.py, tests/test_grouped_summary.py.
- [x] RED: 묶음 범위/원문/중복 문장/출력 잘림/진행/청크/native exit.
- [x] Implement grouping+summary single-pass streaming, bounded parser, coverage validation, context check and failed-range handling.
- [x] GREEN targeted backend tests.

### Task 2: API and UI
Files: app/api/v1/scripts.py, src/features/practice/{scriptTools.ts,scriptSummary.ts,PracticePage.tsx,components/PresentationSetup.tsx}; tests/{script_summary.test.mjs,interview-ui.test.mjs,test_grouped_summary.py}.
- [x] RED: NDJSON progress before completion, cancel cleanup, decoder fragmentation and error, mapping/group editor/overlay.
- [x] Implement streaming response, incremental client progress, grouped editing and same hint through range.
- [x] GREEN Node and Python tests, lint/build.

### Task 3: Final verification
- [x] Full pytest/Node/Ruff/mypy/ESLint/build/diff check, focused fresh review if available.
- [x] Actual 9B sample and browser progress/result/edit/toggle. Record speed, group ranges and process exit.
- [x] Restart own backend, leave localhost9000 usable; no merge/push.

## Ledger
- 2026-10-15: User waived further clarification/design approval questions and authorized inline end-to-end execution. Written design/plan record the chosen contract without another pause.
- Pre-flight: model group ranges feed API groups; client validates them then derives the existing sentence-index hint map. No change to STT or script alignment contract.
- Task 1 complete: native grouped fixtures/coverage/truncation/token-budget split/progress pass. Short context input has one inference; only oversized inputs split, never a separate grouping pass.
- Ruling: candidate batch increased from 8 to16 sentences, still tokenizer<=2304 plus output1536 and template reserve256 within4096. This avoids unnecessary second inference for a 12-sentence script and permits meaningful grouping across its earlier 8-sentence boundary.
- Task 2 complete: NDJSON reader handles UTF-8 fragmentation, progress and early close. Actual stream disconnect regression confirms child exit. Existing sentence-index overlay receives same hint through grouped range.
- Review finding fixed RED→GREEN: any failed regenerated group with existing nonempty hints rejects replacement and preserves the whole edited draft. Initial blank drafts may accept error placeholders. Independent reviewer follow-up found no actionable remaining issue in this fix.
- Task 3 complete: pytest230, Node41, Ruff, mypy63, ESLint, build, diff check passed. Actual 9B final samples: 5 sentences→2 groups6.61s;12 sentences→7 groups12.11s. Each sample uses one grouping+summary inference. Includes model load/inference/teardown, not isolated token-generation time.
- Browser: actual button5 sentences→2 groups5.29s; captured3/5 processing before completion, start disabled until cleanup, grouped edit/toggle verified. No camera/mic access. Screenshots/results in chat outputs/grouped-summary-20261015/.
- Remaining limits: cross-context-batch grouping not implemented, no additional LLM pass. No10-minute full draft or CPU-only hardware run, no quantitative meaning-quality guarantee. Model loading cost persists. All observed model children gone after validation. Current branch stays uncommitted; no merge/push.
