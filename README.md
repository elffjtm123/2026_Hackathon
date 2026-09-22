# 실시간 발표·면접 피드백 백엔드

FastAPI, WebRTC, WebSocket 기반의 실시간 미디어 처리 백엔드입니다. 브라우저의
영상·음성을 세션별 bounded queue로 받은 뒤 서로 독립적인 AI worker에서
분석하며, 원본 미디어는 저장하지 않습니다. AI 서버 없이도 Mock AI로 전체
흐름을 실행할 수 있습니다.

## 빠른 실행

```bash
cp .env.example .env
docker compose up --build
```

## 서버 실행: 2개의 터미널에서 각각 실행
```bash
npm run dev:backend
npm run dev
```

프론트는 `http://localhost:5173`, 백엔드는 `http://127.0.0.1:8000`에서
실행된다. Qwen3-ASR과 UniFace를 처음 사용할 때는 각 모델 가중치 다운로드로
시작이 느려질 수 있다. 통신만 먼저 검사할 때는 `.env`의
`VISION_PROVIDER=mock`, `STT_PROVIDER=mock`을 사용한다. 모델 로드·추론 오류는
백엔드 터미널과 화면의 **최신 피드백** 패널에서 확인할 수 있다.

API 문서는 `http://localhost:8000/docs`, 상태 확인은
`http://localhost:8000/health/ready`에서 볼 수 있습니다. Docker 시작 시 Alembic
migration이 자동 적용됩니다.

로컬 Python 3.12 환경에서는 다음과 같이 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ai]'
alembic upgrade head
uvicorn app.main:app --reload
```

## 주요 API

- 인증: `POST /api/v1/auth/register`, `/login`, `/refresh`
- 사용자: `GET /api/v1/users/me`
- 세션: `POST/GET /api/v1/sessions`, `POST .../{id}/complete`
- WebRTC: `POST /api/v1/sessions/{id}/webrtc/offer`
- WebSocket: `WS /api/v1/ws/sessions/{id}?token=<access_token>`
- 리포트: `GET /api/v1/sessions/{id}/report`
- 대본 분석: `POST /api/v1/scripts/analyze`

발표 세션은 선택적으로 `script`와 `time_limit_seconds`를 함께 받을 수 있습니다.
대본이 있으면 문장부호의 쉼 가중치를 반영한 목표 타임라인과 목표 발화 속도를
계산합니다. 실시간 transcript는 대본 위치와 정렬되어 `script.progress` 이벤트를
만들고, final transcript는 문자 정렬 기반의 발음 명료도 추정에 사용됩니다.

발음 결과는 실제 음향학적 발음 정확도가 아니라 STT 결과와 예상 대본 구간의
일치도를 사용한 `pronunciation_clarity_score`입니다. 신호가 짧거나 신뢰도가 낮으면
점수를 0으로 만들지 않고 `insufficient_signal`로 반환합니다.

프론트의 발표 모드에서는 노래방식 진행 가이드와 주요 단어 힌트를 선택할 수
있습니다.

WebSocket은 JSON 제어 메시지와 바이너리 미디어를 받습니다. 바이너리 헤더는
`payload type 1 byte + timestamp_ms 8 byte(big-endian)`이며 타입 `0x01`은 JPEG,
`0x02`는 mono PCM 16 kHz입니다. JSON `{"event":"ping"}`에는 `pong`으로
응답합니다. 개발 중에는 아래 메시지로 Mock 음성 분석을 바로 확인할 수 있습니다.

```json
{"event":"transcript.final","timestamp_ms":1000,"data":{"text":"음 저는 백엔드 개발자입니다"}}
```

AI 연동 계약과 모든 이벤트 schema는 `/docs` 및
[`app/realtime/events.py`](app/realtime/events.py)에 정의되어 있습니다.

공통 이벤트에는 `version`, `module`, `level`, `trace_id`가 포함됩니다. 실시간
원본 영상·음성은 분석 큐에서 소비된 뒤 폐기되며 DB에 저장하지 않습니다.

## AI 모델과 라이선스

로컬 시선 분석의 기본값은 `VISION_PROVIDER=uniface`입니다. UniFace의
RetinaFace와 MobileGaze를 사용하며 Apple Silicon에서는 CoreML, 그 외에서는
CPU ONNX provider로 실행됩니다. 최초 실행 시 모델 가중치가 다운로드될 수
있습니다. 모델 없이 통신 흐름만 확인할 때는 `.env`에
`VISION_PROVIDER=mock`을 설정합니다. 설치나 로드에 실패하면 Mock으로 숨은
전환을 하지 않고 `GAZE_AI_UNAVAILABLE` 오류를 보냅니다.

L2CS-Net은 공식 실행 절차에서 별도의 가중치 파일을 요구하므로 현재 기본
의존성에서 제외했습니다. UniFace 역시 실제 카메라 환경에서 성능을 확인해야
하며, 저장소는 사전학습 모델 가중치나 평가 영상을 배포하지 않습니다.

라벨 CSV는 `frame,direction` 형식을 사용합니다. 평가 영상과 라벨을 로컬에
준비한 뒤 다음과 같이 실행하면 F1과 지연 시간 JSON을 만듭니다.

```bash
python scripts/benchmark_gaze.py \
  --provider uniface \
  --input /path/to/gaze-test.mov \
  --labels /path/to/gaze-labels.csv \
  --output /tmp/gaze-benchmark.json
```

참고: [UniFace quickstart](https://yakhyo.github.io/uniface/quickstart/),
[UniFace execution providers](https://yakhyo.github.io/uniface/concepts/execution-providers/),
[L2CS-Net 공식 저장소](https://github.com/Ahmednull/L2CS-Net)

## 개발 검증

```bash
pytest
ruff check .
mypy app
```

## 개인정보 원칙

영상·음성 payload와 SDP, 토큰, 원본 transcript는 로그 또는 DB에 기록하지
않습니다. DB에는 세션 종료 후 집계 리포트만 저장합니다. 운영 환경에서는 반드시
HTTPS/WSS, 강한 `JWT_SECRET`, 제한된 `CORS_ORIGINS`, TURN 서버를 사용해야 합니다.
