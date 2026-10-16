# 인접 의미 묶음 요약과 실제 진행도

사용자 승인: 2번(묶기와 요약 동시 생성), 추가 질문 없이 끝까지 구현. 현재 codex/local-script-summary 브랜치 유지, 기존 미커밋 변경 보존, 메인 병합/푸시 제외.

## 계약

- Qwen3.5-9B Q4_K_M 한 추론에서 인접 문장 범위와 메모를 함께 생성한다. 별도 경계 분류/검증 LLM/자동 재추론 없음.
- 결과 groups의 start_sentence/end_sentence는 0-based inclusive. 코드가 원문을 조합하며 원문 순서, 전체 포함, 무중복을 검증한다. 실패 구간은 hint=null, error 안내로 유지한다.
- 짧은 문장도 중요한 부정/조건/수치이면 보존. 같은 설명을 구성하는 인접 문장만 묶으며 멀리 떨어진 문장을 합치지 않는다. 의미 품질은 사용자 수정 가능.
- 긴 대본은 제한된 연속 청크로 나눈다. 청크 경계 간 재추론 병합은 하지 않는다. 컨텍스트 초과 방지는 실제 tokenizer로 확인하며 출력 공간을 확보한다.
- 기존 POST /scripts/summarize JSON 응답을 유지하되 payload는 groups로 전환. UI는 Accept: application/x-ndjson으로 progress/complete/error를 수신한다. 완료는 모델 회수 이후에만 전송한다.
- progress: preparing/generating/cleaning, completed_sentences/total_sentences/failed_sentences. 원문 처리 수이며 시간 추정 아님. 검증된 묶음 단위 갱신, 실패 구간 포함 처리 수 명시.
- UI는 묶인 원문과 하나의 편집 가능한 요약을 표시한다. 현재 원문 문장 번호가 범위 안이면 같은 힌트를 유지한다. 수동 입력은 기존처럼 가능, 대본 변경 시 초기화, 재요약 실패 시 기존 편집본 보존.
- STT/시선과 요약 모델의 배타 수명주기, timeout/취소/child 회수, 미디어 처리/보정 알고리즘은 변경하지 않는다. 새 의존성 없음.

## 검증

반복 문장 ID, 누락/중복/역순/범위 초과, 생성 잘림, 긴 입력 청크, 점진 스트림/깨진 스트림/중단, 오래된 대본 응답, 그룹 편집/오버레이/실제 진행률, 모델 자식 회수. 실제 9B 공통 대본과 짧은 문체 대본 실행 및 UI 확인. 카메라/마이크 접근 제외.
