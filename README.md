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

API 문서는 `http://localhost:8000/docs`, 상태 확인은
`http://localhost:8000/health/ready`에서 볼 수 있습니다. Docker 시작 시 Alembic
migration이 자동 적용됩니다.

로컬 Python 3.12 환경에서는 다음과 같이 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
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

WebSocket은 JSON 제어 메시지와 바이너리 미디어를 받습니다. 바이너리 헤더는
`payload type 1 byte + timestamp_ms 8 byte(big-endian)`이며 타입 `0x01`은 JPEG,
`0x02`는 mono PCM 16 kHz입니다. JSON `{"event":"ping"}`에는 `pong`으로
응답합니다. 개발 중에는 아래 메시지로 Mock 음성 분석을 바로 확인할 수 있습니다.

```json
{"event":"transcript.final","timestamp_ms":1000,"data":{"text":"음 저는 백엔드 개발자입니다"}}
```

AI 연동 계약과 모든 이벤트 schema는 `/docs` 및
[`app/realtime/events.py`](app/realtime/events.py)에 정의되어 있습니다.

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
