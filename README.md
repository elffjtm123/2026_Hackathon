# 실시간 발표·면접 코치

브라우저의 카메라·마이크를 받아 **발표·면접 연습 중 시선, 발화 속도, 습관어, 대본 진행**을
실시간으로 분석하고 화면에 피드백을 띄우는 서비스입니다. 원본 영상·음성은 저장하지 않으며,
세션이 끝나면 집계된 리포트만 남깁니다.

- **백엔드**: FastAPI + SQLAlchemy(async) + WebSocket/WebRTC, 로컬 AI 추론
- **프론트엔드**: React 19 + Vite + TypeScript (단일 연습 화면)
- **AI**: MediaPipe Face Landmarker + MobileGaze(시선), Qwen3-ASR 0.6B(음성 인식), Qwen3.5-9B(대본 요약)
- **모드**: 발표(presentation) / 면접(interview)

---

## 1. 주요 기능

| 기능 | 내용 | 구현 위치 |
|---|---|---|
| 시선 피드백 | 얼굴 방향·눈 시선을 보정 기준과 비교해 `center/left/right/up/down/away` 표시. 정면 보정 후 시작 | `app/ai/uniface_gaze.py`, `app/modules/gaze/service.py` |
| 발화 속도 | VAD로 잘린 발화의 **한국어 음절 수 / 유성 시간**으로 분당 음절 계산, 느림·정상·빠름 판정 | `app/modules/speech/analysis.py` |
| 습관어 | 확정 전사에서 후보 단어(음·어·그 등)만 집계 | `app/modules/speech/analysis.py` |
| 대본 진행 | 확정 전사와 대본 문장을 정렬해 실제 진행률·목표 대비 편차 계산 | `app/modules/script_sync/service.py` |
| 대본 요약 힌트 | 문장 묶음별 한 줄 힌트를 로컬 LLM으로 생성하거나 직접 작성, 발표 중 현재 문장 힌트 표시 | `app/ai/script_summary.py` |
| 종료 리포트 | 세션 종료 시 집계 리포트 생성(시선 이탈, 속도, 습관어, 대본 일치도) 후 DB 저장 | `app/realtime/aggregator.py`, `app/services/session_service.py` |

프론트엔드는 **발표 모드**(대본 + 카메라 + 실시간 패널)와 **면접 모드**(카메라 + 피드백)를
한 화면에서 토글합니다.

---

## 2. 아키텍처

```
┌──────────────────────────── 브라우저 (React) ────────────────────────────┐
│  getUserMedia ─▶ AudioWorklet(16kHz PCM) ─┐                              │
│  canvas 8fps JPEG ───────────────────────┤                              │
│                                          ▼                              │
│  useFeedbackSocket ── WebSocket v2 ──▶ 미디어(26B 헤더 + payload)        │
│         ▲                                │ 제어(JSON)                   │
│         └──── feedback / script.progress / session.* ◀──┐               │
└─────────────────────────────────────────────────────────┼───────────────┘
                                                          │
┌──────────────────────── FastAPI (app/) ─────────────────┼───────────────┐
│  WS/WebRTC 진입점 ─▶ SessionPipeline                     │               │
│      ├ video_queue(최신 1장) ─▶ gaze worker ────────────┤               │
│      ├ audio_queue(32) ─▶ VAD 발화 분절 ─▶ speech worker┘               │
│      │                                    (STT + 속도/습관어)           │
│      ├ FeedbackAggregator ─▶ DB 리포트 / 이벤트 발행                    │
│      └ ModelExecution: 요약 모델 ↔ 실시간 모델 단일 소유권               │
│                                                                          │
│  자식 프로세스: RealtimeModelProcess (시선+STT) / llama-server (요약)     │
└──────────────────────────────────────────────────────────────────────────┘
```

설계상 중요한 두 가지:

1. **모델 단일 소유권** — 9B 요약 모델과 실시간 모델(시선+STT)이 동시에 메모리에 상주하지
   않습니다. 요약과 세션 시작은 하나의 실행권을 공유하고, 세션이 끝나면 자식 프로세스를 회수합니다.
2. **원본 미저장** — 영상·음성 payload, SDP, 토큰, 원문 전사는 로그·DB에 남기지 않습니다.

---

## 3. 저장소 구조

```
app/                    FastAPI 백엔드
  api/v1/               auth · sessions · scripts · websocket 라우터
  realtime/             파이프라인, 큐, WebRTC, 이벤트 스키마, 집계기
  ai/                   시선/STT/요약 어댑터, 자식 프로세스 IPC
  modules/              gaze · speech · pronunciation · script_sync 순수 로직
  db/                   SQLAlchemy 모델, 세션
  schemas/              요청·응답 스키마
  core/                 설정, 보안(JWT/해시), 로깅, 에러
src/                    React 프론트엔드
  features/practice/    연습 화면, 컴포넌트, 훅, 프로토콜 어댑터
  lib/                  미디어·실시간 프로토콜 직렬화
tests/                  pytest(백엔드) + node --test(프론트엔드)
docs/                   현장 확인 절차, WebRTC 계약, 설계 문서
scripts/                시선 벤치마크 도구
alembic/                DB 마이그레이션
```

---

## 4. 요구 사항

| 항목 | 버전 / 비고 |
|---|---|
| Python | 3.10 이상 (현재 검증 기준: macOS Apple Silicon, Metal) |
| Node.js | 20.19 이상 (Vite 7 요구사항, 개발 환경 확인: v22) |
| 브라우저 | Chrome/Edge 최신. `getUserMedia` + `AudioWorklet` 필요 (Safari 미검증) |
| OS | macOS 우선 검증. Linux/Windows는 STT 네이티브 라이브러리를 별도로 준비해야 함 |
| DB | SQLite(기본) 또는 PostgreSQL |
| Redis | 선택. 다중 인스턴스에서 세션 상태·레이트리밋을 공유할 때 사용 |

카메라·마이크는 **secure context**(`localhost` 또는 HTTPS)에서만 동작합니다.

---

## 5. 빠른 시작

### 5-1. 모델 준비 (최초 1회)

`.models/`는 Git에서 제외됩니다. 아래 세 가지를 준비해야 실제 분석이 동작합니다.

**① 시선: Face Landmarker**

```bash
mkdir -p .models
curl -fL -o .models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
shasum -a 256 .models/face_landmarker.task
# 기대값: 64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
```

MobileGaze 가중치는 첫 실행 시 내려받습니다. 절차와 한계는 [시선 확인 문서](docs/gaze-field-check.md)를 보세요.

**② 음성 인식: Qwen3-ASR 0.6B Q8_0 + speech.cpp**

```bash
mkdir -p .models/speech
curl -fL -o .models/speech-0.8.8-macos-arm64-metal.zip \
  https://github.com/nyosegawa/speech.cpp/releases/download/v0.8.8/speech-0.8.8-macos-arm64-metal.zip
unzip .models/speech-0.8.8-macos-arm64-metal.zip -d .models/speech

curl -fL -o .models/Qwen3-ASR-0.6B-Q8_0.gguf \
  https://huggingface.co/sakasegawa/Qwen3-ASR-0.6B-GGUF/resolve/ee78f8709547f39bea3b924a16c72403826cac92/Qwen3-ASR-0.6B-Q8_0.gguf
shasum -a 256 .models/Qwen3-ASR-0.6B-Q8_0.gguf
# 기대값: 416e10c15b4a3d9002bd337d18fc450233fdf68502b6e10d1379d2789838afd0
```

**③ 대본 요약: llama.cpp + Qwen3.5-9B** (요약 버튼을 쓸 때만 필요)

- `llama-server` 실행 파일과 라이브러리 → `.models/llama/`
- `Qwen3.5-9B-Q4_K_M.gguf` (5,680,522,464 bytes, SHA-256 `03b74727…2b7e8`) → `.models/`

모델·가중치·네이티브 바이너리는 저장소에 포함하지 않습니다.

### 5-2. 백엔드

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ai]'
cp .env.example .env          # 값 확인 후 수정
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/health/ready> (`modules`에 시선·음성 모델 상태 포함)

### 5-3. 프론트엔드

```bash
npm install
npm run dev            # http://localhost:5173
```

백엔드를 함께 띄우려면 터미널 두 개에서:

```bash
npm run dev:backend    # 내부적으로 .venv310/bin/python 사용 — 환경에 맞게 수정
npm run dev
```

프론트엔드는 기본적으로 `ws://127.0.0.1:8000/api/v1/ws/practice-demo`에 연결합니다.
다른 주소를 쓰려면 `.env.local`에 지정하세요.

```bash
VITE_FEEDBACK_WS_URL=ws://127.0.0.1:8000/api/v1/ws/practice-demo
```

> 이 데모 엔드포인트는 **개발 환경 + loopback 접속 + 허용된 Origin**에서만 열립니다.
> 공개 배포에서는 인증 세션 API(`/api/v1/sessions` + `/ws/sessions/{id}`)를 사용해야 하며,
> 현재 브라우저 UI에는 로그인 화면이 없습니다.

---

## 6. 환경 변수

`.env.example`이 기준입니다. 자주 건드리는 값만 정리했습니다.

**핵심**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_ENV` | `development` | `production`에서는 강한 `JWT_SECRET`(32자 이상)을 강제하고 개발용 엔드포인트가 닫힘 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./feedback.db` | PostgreSQL은 `postgresql+asyncpg://…` |
| `REDIS_URL` / `REDIS_REQUIRED` | 없음 / `false` | 세션 상태·레이트리밋 공유 |
| `CORS_ORIGINS` | localhost 목록 | WebSocket Origin 검증에도 사용 |
| `JWT_SECRET` | 개발용 기본값 | **운영에서는 반드시 교체** |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | 15 / 14 | 토큰 수명 |
| `AUTH_ATTEMPTS_PER_MINUTE` | 20 | 인증 엔드포인트 IP당 시도 제한 |
| `TRUST_PROXY_HEADERS` | `false` | 신뢰하는 리버스 프록시 뒤에서만 `true` |

**AI**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `AI_MODE` | `local` | `local`(자식 프로세스 추론) 또는 `http`(외부 AI 서버) |
| `VISION_PROVIDER` | `uniface` | `legacy`는 미지원(명시적 오류) |
| `FACE_LANDMARKER_PATH` | `.models/face_landmarker.task` | |
| `STT_MODEL` / `STT_LIBRARY_PATH` | `.models/Qwen3-ASR-0.6B-Q8_0.gguf` / `.models/speech/libspeech.dylib` | |
| `STT_DEVICE` | `auto` | `auto` / `mps` / `cpu` |
| `STT_SILENCE_RMS_THRESHOLD` | `0.003` | VAD 무음 기준 |
| `SUMMARY_SERVER_PATH` / `SUMMARY_MODEL_PATH` | `.models/llama/llama-server` / `.models/Qwen3.5-9B-Q4_K_M.gguf` | |
| `SUMMARY_TIMEOUT_SECONDS` | 600 | 요약 전체 제한 |

**실시간 처리**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `REALTIME_START_TIMEOUT_SECONDS` | 120 | 모델 로딩 대기 |
| `AUDIO_QUEUE_SIZE` / `VIDEO_QUEUE_SIZE` | 32 / 1 | 오디오는 순서 보존, 영상은 최신 1장만 |
| `PIPELINE_GRACE_SECONDS` | 30 | 종료 시 잔여 오디오 처리 |
| `MAX_MEDIA_MESSAGE_BYTES` | 2 MiB | 미디어 1건 상한 |
| `MAX_CONNECTIONS_PER_SESSION` | 2 | 세션당 WS/WebRTC 연결 상한 |
| `MAX_REALTIME_MESSAGES_PER_SECOND` | 30 | 사용자당 초당 메시지 |
| `MAX_SCRIPT_CHARS` | 20,000 | 대본 길이 |
| `TURN_URL` / `TURN_USERNAME` / `TURN_CREDENTIAL` | 없음 | WebRTC ICE(TURN) 설정 |

---

## 7. 세션 생명주기

```
session.start → session.ready → calibration.start → session.calibrating
             → session.running → (session.draining) → session.completed
```

| 단계 | 의미 |
|---|---|
| `preparing` | 모델 로딩. 이 구간에는 음성을 받지 않고 연습 시간도 세지 않음 |
| `calibrating` | 정면 응시 보정. 정면 head pose·품질·안정성 조건을 통과한 관찰 8개 이상 필요 |
| `running` | 실제 연습 구간. 이때부터 타이머와 분석 시작 |
| `draining` | 종료 후 남은 오디오 처리 |
| `completed` | 리포트 생성 완료 |

- 보정이 15초를 넘으면 연결은 유지한 채 오류를 보내고, 화면에서 **다시 보정**을 누를 수 있습니다.
- 시선 기능을 끄면 보정을 건너뛰고 바로 `running`으로 갑니다.
- 준비·보정 중에도 `session.end`로 취소할 수 있습니다.

---

## 8. 실시간 미디어 프로토콜 (v2)

브라우저가 보내는 바이너리 프레임은 **26바이트 big-endian 헤더 + payload**입니다.

| offset | size | 필드 | 의미 |
|---:|---:|---|---|
| 0 | 1 | `version` | 항상 `2` |
| 1 | 1 | `type` | `1`=JPEG, `2`=PCM16 |
| 2 | 4 | `sequence` | 1부터 증가, 갭·재전송 감지 |
| 6 | 8 | `timestamp_ms` | 세션 상대 시각 |
| 14 | 8 | `start_sample` | 오디오 샘플 인덱스 |
| 22 | 4 | `sample_count` | 오디오 샘플 수 |
| 26 | … | payload | JPEG 또는 mono 16 kHz PCM16 |

규칙:

- 오디오는 **200 ms(3,200 샘플)** 단위, `sample_count * 2 == payload 길이`
- 영상은 최대 너비 640, 초당 8프레임. 서버는 최신 1장만 유지하고 이전 프레임은 버립니다
- 순서 갭, 타임스탬프 역행, 재전송 내용 불일치는 세션을 **미완료**로 표시합니다
- `media.ack`는 큐 수신 확인일 뿐, 모델 분석 완료를 뜻하지 않습니다
- 제어 메시지는 JSON(`event`, `version`, `session_id`, `sequence`, `timestamp_ms`, `data`)이며
  클라이언트가 `transcript.partial/final`을 주입하는 것은 거부됩니다

WebRTC 경로(`POST /sessions/{id}/webrtc/offer`)도 같은 PCM 규격을 사용하며,
연결 후 30초 안에 붙지 않은 peer는 닫습니다. v1 9바이트 헤더는 인증 WS 호환 경로로만 남아 있습니다.

---

## 9. API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/v1/auth/register` | 가입 후 토큰 발급 |
| `POST` | `/api/v1/auth/login` | 로그인 |
| `POST` | `/api/v1/auth/refresh` | refresh token 회전(1회용) |
| `GET` | `/api/v1/users/me` | 내 정보 |
| `POST` | `/api/v1/sessions` | 세션 생성(대본·제한시간 선택) |
| `GET` | `/api/v1/sessions` | 내 세션 목록(페이지네이션) |
| `GET` | `/api/v1/sessions/{id}` | 세션 상세 |
| `DELETE` | `/api/v1/sessions/{id}` | 세션 삭제 |
| `POST` | `/api/v1/sessions/{id}/webrtc/offer` | WebRTC 협상 |
| `POST` | `/api/v1/sessions/{id}/complete` | 세션 종료 + 리포트 생성 |
| `GET` | `/api/v1/sessions/{id}/report` | 리포트 조회 |
| `POST` | `/api/v1/scripts/analyze` | 대본 분석(목표 타임라인) |
| `POST` | `/api/v1/scripts/summarize` | 문장 묶음 요약(NDJSON 스트리밍, 개발 전용) |
| `WS` | `/api/v1/ws/sessions/{id}?token=…` | 인증 실시간 세션 |
| `WS` | `/api/v1/ws/practice-demo?protocol=2` | 개발용 데모(loopback + dev 전용) |
| `GET` | `/health/live`, `/health/ready` | 상태 확인 |

모든 오류 응답은 `{"error": {"code", "message", "request_id", "details"}}` 형식입니다.

---

## 10. 분석 모듈

| 모듈 | 역할 | 핵심 아이디어 |
|---|---|---|
| `modules/gaze` | 시선 방향 안정화·보정·이탈 판정 | 중앙값 기반 각도 안정성, 정면 보정 기준과의 편차 |
| `modules/speech/segments` | PCM → 비중첩 발화 분절 | 20 ms 프레임 VAD, 샘플 인덱스 기반 발화 ID |
| `modules/speech/analysis` | 속도·습관어 | 음절 수 ÷ 유성 시간, 전사에 남은 후보 단어만 집계 |
| `modules/pronunciation` | 대본 대비 일치도 | 편집 거리 기반. **발음 정확도가 아닙니다** |
| `modules/script_sync` | 대본 정렬·진행률 | 확정 전사만 사용, 일치도·경쟁 구간 조건을 통과할 때만 전진 |

> `pronunciation_clarity_score`는 호환을 위해 이름만 유지한 필드로, 실제 의미는
> **대본과 인식 결과의 일치도**입니다. 음향학적 발음 진단이 아닙니다.

---

## 11. 데이터·프라이버시

- 원본 영상·음성, SDP, 토큰, 원문 전사는 **로그와 DB에 저장하지 않습니다**
- 세션 종료 후 DB에는 집계 리포트만 저장하며, `transcript` 필드는 `null`입니다
- 타임라인·지표는 숫자와 정해진 상태값만 허용해 원문이 섞이지 않게 합니다
- 실시간 파이프라인의 큐는 소비 즉시 폐기되고, 세션 객체와 함께 사라집니다
- 운영 배포 시 HTTPS/WSS, 강한 `JWT_SECRET`, 제한된 `CORS_ORIGINS`, TURN 서버가 필요합니다

---

## 12. 테스트와 품질 검사

```bash
# 백엔드
pytest
ruff check .
mypy app

# 프론트엔드 (node_modules 필요)
npm run typecheck
npm run lint
node --test tests/
```

- 백엔드 테스트는 실제 모델 없이 `tests/fake_ai.py`의 가짜 어댑터로 실행됩니다.
  서비스 코드는 이 가짜 구현을 절대 import하지 않습니다.
- 프론트엔드 테스트는 Vite SSR 로더로 컴포넌트·프로토콜 로직을 검증합니다.
- 모델 로딩·네이티브 프로세스가 필요한 일부 테스트는 실제 모델 파일이 있어야 통과합니다.

---

## 13. Docker

```bash
cp .env.example .env
docker compose up --build
```

- Postgres + Redis + API가 함께 뜨고, 시작 시 Alembic 마이그레이션이 적용됩니다
- Face Landmarker는 읽기 전용 볼륨으로 마운트되며, 없으면 시작을 거부합니다
- 컨테이너는 **비루트 사용자(uid 10001)** 로 실행됩니다
- Compose 예제는 Linux 기준이라 `libspeech.so`와 GGUF의 별도 준비·마운트가 필요합니다.
  현재 STT 검증은 **macOS 직접 실행** 기준입니다

---

## 14. 알려진 제한

- STT·시선의 **실제 정확도**는 현장 검증 전이며, 자동 테스트는 계약·로직만 검증합니다
- 감정·긴장 추론, 면접 질문 생성, 발음 진단은 구현 범위가 아닙니다
- 속도·음량 변화 감지는 세션 내부에서만 쓰이고 화면·DB·로그에 노출하지 않습니다
- CPU 전용·다중 사용자 동시 세션·공개 배포 튜닝은 범위 밖입니다
- 세션마다 모델을 다시 로딩하므로 시작 비용이 있습니다(메모리 회수를 위한 의도된 동작)
- 브라우저 UI에는 로그인 화면이 없어 개발용 데모 엔드포인트만 사용합니다

---

## 15. 관련 문서

- [시선 모델 준비·현장 확인](docs/gaze-field-check.md)
- [음성 파이프라인 현장 확인](docs/speech-field-check.md)
- [실시간 확인 항목](docs/realtime-field-check.md)
- [WebRTC·미디어 계약(v1 호환)](docs/webrtc-contract.md)
- [설계 문서](docs/superpowers/specs/) · [작업 계획](docs/superpowers/plans/)

## 라이선스

모델 가중치와 네이티브 실행 파일은 저장소에 포함되지 않으며 각 배포처의 라이선스를 따릅니다.
Qwen3-ASR·Qwen3.5는 Apache-2.0, MediaPipe Face Landmarker는 Apache-2.0입니다.
