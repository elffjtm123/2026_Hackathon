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

현재 Mac 로컬 검증은 Python 3.10/MPS 기준입니다(패키지 지원 선언 >=3.10).
새 환경은 다음과 같이 실행하며, 기존 환경도 코드 갱신 후 `alembic upgrade head`를 적용합니다.

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

현재 브라우저는 `/api/v1/ws/practice-demo?protocol=2`를 사용합니다(개발 환경 + loopback 접속 전용).
공개 배포에서는 인증된 세션 API를 사용해야 하며 개발 데모는 차단됩니다.
브라우저 WebSocket의 Origin도 `CORS_ORIGINS`와 일치해야 합니다. 기존 `.env`에서는 사용하는 프론트 주소
(예: `http://localhost:9000`)를 추가하세요. Origin 없는 로컬 개발 도구 접속은 허용합니다.
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
PCM 패킷은 VAD로 비중첩 발화를 조립한 후 Qwen에서 최종 전사합니다.
짧은 종료 발화도 flush하고 발화 ID로 재전송만 중복 제거합니다. 실제 반복 문장은 보존합니다.
발화 속도는 한국어 음절 수 / VAD 발화 시간으로 계산하고, 습관어는 전사에 남은 후보만 검출합니다.
받아쓰기/습관어/속도/시선의 실제 정확도 개선 완료를 뜻하지 않습니다.
인증된 v1 WS/REST API는 유지합니다. 아래 9바이트 헤더는 v1 호환 경로 설명입니다.

## 주요 API (v1 호환)

### 로컬 대본 요약

발표 대본 옆 **요약 시작**을 누르면 Qwen3.5-0.8B Q8_0으로 문장별 요약을 만듭니다.
대본 아래 원문별 입력칸에서 결과를 확인·수정하거나 모델 없이 직접 작성할 수 있습니다.
**대본 요약 보기**를 켜면 발표 중 확정된 현재 문장 번호의 요약을 표시하며,
끄면 기존 대본 가이드로 돌아갑니다. 대본을 수정하면 요약을 초기화합니다.

실행 전에 플랫폼에 맞는 llama.cpp `llama-server`와 그 라이브러리를
`.models/llama/`에, `Qwen3.5-0.8B-Q8_0.gguf`를 `.models/`에 준비하세요.
다른 위치라면 `SUMMARY_SERVER_PATH`·`SUMMARY_MODEL_PATH`를 지정합니다.
이번 Mac 검증은 기존 llama.cpp b11429 및 다음 파일을 재사용했습니다.

- GGUF: `ggml-org/Qwen3.5-0.8B-GGUF`, revision `8fea620810c4afa23dd6443f999a48574c1611a3`
- 파일: `Qwen3.5-0.8B-Q8_0.gguf` (833,592,096 bytes)
- SHA-256: `37ae482d336108d23516fa35e8e0c4126688d81018b87178a18d752a1357814f`
- 모델 Apache-2.0. 가중치·네이티브 실행 파일은 Git에 포함하지 않습니다.

`POST /api/v1/scripts/summarize`는 인증 없는 현재 로컬 UI에 맞춘 개발 전용 API입니다.
development 환경, loopback 접속, 허용 목록의 필수 Origin을 모두 확인합니다.
실시간 세션이 진행 중이면 요약을 거절하고, 요약·모델 정리 중에는 WebSocket·WebRTC 세션 시작을 거절합니다.
프로세스는 요청마다 실행하고 전체 문장 처리가 끝난 뒤 종료·회수하며, 완료 응답은 종료 후 보냅니다.
GPU offload를 요청하되 실제 사용 장치는 설치된 llama.cpp 빌드·환경에 따릅니다.
STT·시선 모델 자체는 기존 서비스 수명주기를 유지합니다.

입력은 최대 20,000자·200문장·문장당 1,000자이며 원문 문장 분리는 기존 진행 가이드와 같습니다.
전체 처리 제한은 `SUMMARY_TIMEOUT_SECONDS`(기본 180초)입니다.
모델 누락·실행 실패·시간 초과·연결 종료 시 결과를 꾸미지 않고 자식 프로세스를 정리합니다.
출력 제한에 걸리거나 비어 있는 문장에는 요약 대신 오류를 표시하며 수동 입력할 수 있습니다.
원문과 요약은 로그나 DB에 저장하지 않고 현재 화면 상태로만 유지합니다. 새로고침하면 초기화됩니다.

요약은 의미 보존이 검증된 결과가 아닌 **AI 초안**입니다. 수치·부정·조건을 확인한 뒤 사용하세요.
화면의 소요 시간에는 모델 로딩·추론·종료가 모두 포함되므로 기존 순수 추론 비교표와 다릅니다.
CPU 전용·다중 사용자·공개 배포 대응은 이번 변경 범위가 아닙니다.

### 기존 API

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
만듭니다. 최종 전사만 정렬을 확정하며, 4자 이상·일치도 0.65 이상·경쟁 구간과 차이 0.10 이상일 때만
실제 위치를 전진시킵니다. 무관한 말·반복 구간은 마지막 위치를 유지합니다.

`pronunciation_clarity_score`는 호환 필드명이며 실제 의미는 **대본과 인식 결과 일치도**입니다.
확정된 정렬 구간만 비교하고 음향학적 발음 정확도·모델 확률을 점수로 만들지 않습니다.

발표 가이드는 목표 시간 진행과 실제 인식 진행을 구분합니다. 문장 요약 힌트는 설정 화면에서
직접 작성하거나 요약 버튼으로 생성·검토한 메모를 사용하며 미설정 시 임의 단어로 대체하지 않습니다.
대본 변경 시 힌트는 초기화됩니다. 요약 모델은 버튼을 누를 때만 실행합니다.

## 종료 리포트 v2와 저장 정책

최종 화면은 서버 집계만 사용하며 데이터 없음·비활성·검출 0회를 구분합니다.
시선은 관찰 간격 1초 이하만 적분하고 긴 공백은 판단 불가로 처리합니다.
마지막 관찰은 최대 1초만 유지하며 유효 관찰 중 이탈 비율과 전체 시간 대비 관찰 범위를 따로 표시합니다.
발화 속도는 유효 발화의 총 음절 수 / 총 발화 시간, 속도 경고는 경고 상태 진입 횟수입니다.
근거 없는 종합 점수는 `null`, 미완료 상태는 DB에도 보존합니다.

받아쓰기는 종료 화면에서 일시적으로 보여주지만 새 DB 리포트의 `transcript`는 `null`입니다.
타임라인·중첩 지표는 수치/정해진 상태값만 허용하여 대본 비교 원문도 저장하지 않습니다.
기존 v1 기록과 원문은 마이그레이션에서 삭제하지 않습니다. v2 nullable 변경은 안전한 다운그레이드를
지원하지 않으므로 되돌릴 때는 변경 전 DB 백업을 사용하세요.
현장 정성평가는 별도로 보류하며 [확인 항목](docs/realtime-field-check.md)을 참고하세요.

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
