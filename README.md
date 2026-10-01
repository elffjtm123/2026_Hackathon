# 실시간 발표·면접 피드백 백엔드

FastAPI, WebRTC, WebSocket 기반의 실시간 미디어 처리 백엔드입니다. 브라우저의
영상·음성을 세션별 bounded queue로 받은 뒤 서로 독립적인 AI worker에서
분석하며, 원본 미디어는 저장하지 않습니다. 서비스는 실제 모델만 사용하며,
모델을 사용할 수 없으면 해당 분석을 오류로 표시합니다.

## 빠른 실행

먼저 [모델 준비 절차](docs/gaze-field-check.md)에 따라
`.models/face_landmarker.task`를 준비해야 합니다. Compose는 이 파일을 읽기 전용으로
연결하며, 없으면 시작을 거부합니다. Qwen과 MobileGaze 가중치는 첫 실행에
다운로드되므로 인터넷 연결과 모델용 메모리가 필요합니다.

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
시작이 느려질 수 있다. 모델 로드·추론 오류는
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

## 로컬 실시간 v2 (공통 처리 재설계 1단계)

`AI_MODE=local`은 실제 로컬 모델, `AI_MODE=http`은 외부 AI 서버 실행 방식입니다.
Mock 실행 모드와 provider는 제거되어 잘못된 설정으로 거부됩니다.
실제 모델 로드 실패는 `unavailable`로 표시하고 필요한 모델이 없으면 시작을 거절합니다.
실행 중 추론 실패는 분석 오류와 미완료 결과로 표시하며 가짜 결과를 생성하지 않습니다.
`/health/ready`의 기존 DB/Redis 준비 상태와 별도로 `modules`에 provider/model/device/status/reason을 반환합니다.
이번 로컬 경로에서 legacy 및 HTTP 시선 provider는 지원하지 않습니다.

현재 브라우저는 `/api/v1/ws/practice-demo?protocol=2`를 사용합니다(개발 전용).
`session.start → session.ready → calibration.start → session.calibrating → session.running`
이후에만 음성을 캡처하고 연습 시간을 셉니다. 시선 비활성화 시 보정을 건너뜁니다.
준비/보정 중 취소할 수 있고, 종료는 `session.draining → session.completed`로 진행됩니다.
시선 보정은 정면 head pose·품질·중앙값 기반 각도 안정성을 통과한 연속 8개 이상/0.75초 이상 관찰을 사용합니다.
보정 시간이 초과되면 연결을 유지하며 ‘다시 보정’으로 같은 세션에서 재시도할 수 있습니다.
얼굴 방향과 눈 시선은 별도이며 center는 카메라 응시가 아닌 **보정 기준 근처**입니다.
실제 사용자 방향 정확도는 현장 확인이 필요합니다. 모델 준비와 확인 절차는 [시선 체크 문서](docs/gaze-field-check.md)를 보세요.

v2 미디어는 big-endian `>BBIQQI` 26바이트 헤더(version=2, type, sequence,
timestamp_ms, start_sample, sample_count) 뒤에 JPEG 또는 little-endian PCM16 mono 16kHz가 붙습니다.
시각은 서버 ready를 기준으로 한 세션 상대 단조 시각, 음성은 sample index 기준입니다.
오디오는 200ms 단위로 전송하며 `media.ack`는 큐 수신 확인이지 모델 분석 완료가 아닙니다.
음성 갭/처리량 초과/ACK 5초 지연은 오류와 미완료 결과로 표시합니다.
영상은 비율을 유지한 최대 너비 640/8fps, 음성 큐는 32패킷입니다.
서버는 종료 후 최대 30초 오디오를 처리하고 화면은 최대 35초 완료를 기다립니다.
취소된 네이티브 추론이 실제로 끝나기 전 동일 모델의 다음 추론을 거절합니다.

AudioWorklet이 실제 장치 sample rate를 사용하며 필요 시 연속 FIR 저역통과 리샘플링합니다.
발화 구간 VAD 재설계 전까지는 비중첩 2초 PCM을 추론하고 마지막 짧은 잔여 음성도 전달합니다.
받아쓰기/습관어/속도/시선의 실제 정확도 개선 완료를 뜻하지 않습니다.
인증된 v1 WS/REST API는 유지합니다. 아래 9바이트 헤더는 v1 호환 경로 설명입니다.

## 주요 API (v1 호환)

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
응답합니다. 받아쓰기 결과는 서버의 STT 분석에서만 생성합니다.
클라이언트가 `transcript.partial` 또는 `transcript.final`을 보내는 전사 주입은 거부합니다.

AI 연동 계약과 모든 이벤트 schema는 `/docs` 및
[`app/realtime/events.py`](app/realtime/events.py)에 정의되어 있습니다.

공통 이벤트에는 `version`, `module`, `level`, `trace_id`가 포함됩니다. 실시간
원본 영상·음성은 분석 큐에서 소비된 뒤 폐기되며 DB에 저장하지 않습니다.

## AI 모델과 라이선스

로컬 시선 분석의 기본값은 `VISION_PROVIDER=uniface`입니다. UniFace의
MediaPipe Face Landmarker와 MobileGaze를 사용합니다. Face Landmarker는 공식
로컬 asset을 준비해야 하며 checksum을 검증합니다. MobileGaze는 Apple Silicon에서 CoreML, 그 외에서는
CPU ONNX provider로 실행됩니다. MobileGaze 최초 실행 시 모델 가중치가 다운로드될 수
있습니다. 설치나 로드에 실패하면 해당 모듈을 `unavailable`로 표시하고,
실행 중 시선 추론 실패는 `GAZE_AI_UNAVAILABLE` 오류를 보냅니다.

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

모델 로딩 없이 실행하는 자동 테스트의 가짜 분석기는 `tests/fake_ai.py`에만
있으며, 테스트에서 모델 생성 함수를 대체합니다. 서비스 코드에서는 불러오지 않습니다.

```bash
pytest
ruff check .
mypy app
```

## 개인정보 원칙

영상·음성 payload와 SDP, 토큰, 원본 transcript는 로그 또는 DB에 기록하지
않습니다. DB에는 세션 종료 후 집계 리포트만 저장합니다. 운영 환경에서는 반드시
HTTPS/WSS, 강한 `JWT_SECRET`, 제한된 `CORS_ORIGINS`, TURN 서버를 사용해야 합니다.
