# 발표 영상의 사전학습 맥박 추정

> 이 문서는 최초 PURE 모델 연결 기록이다. 현재 기본값은 MA-UBFC TS-CAN이며,
> 세 모델 선택·1초 갱신·잠정 BPM·종료 후 표시를 포함한 최신 구조는
> [ubfc-pulse-update.md](ubfc-pulse-update.md)를 따른다.

## 실제 연결 상태

- 발표 화면: `http://127.0.0.1:5173/#practice/service_qwen`.
- EfficientPhys / PURE 사전학습 가중치를 사용하며, 새 학습은 하지 않았다.
- 카메라와 마이크는 기존 연습 시작 버튼으로만 요청한다. 맥박용 새 카메라 없음.
- VideoPreview의 **동일한 HTMLVideoElement와 MediaStream**을 시선 전송과 맥박
  수집이 공유한다. 발표 카메라 우측 상단에 맥박/수집/실패 상태가 표시된다.
- 발표 중 맥박 분석은 기본 ON, 패널 토글로 OFF 가능. 숫자는 충분한 신호가
  있을 때만 표시하며 실패 시 POS나 예시 결과로 대체하지 않는다.
- 이전 `#pulse-experiment` 링크도 이제 발표 화면으로 연결한다.
  POS 기준선 비교는 별도 `#pulse-pos-experiment`에만 남긴다.

## 출처와 준비

공식 저장소: <https://github.com/ubicomplab/rPPG-Toolbox>
고정 revision: `b7500b848f84ad7f86e277b4612563b69f4f88f9`.
공식 구조 `neural_methods/model/EfficientPhys.py`, 가중치
`final_model_release/PURE_EfficientPhys.pth` 사용.
RAIL 1.1 라이선스 및 제한 조건 사본은
`public/pulse-licenses/EfficientPhys-RAIL1.1.txt`에 포함한다.
상업화·배포 시 가중치/훈련 데이터셋 조건까지 별도 확인해야 한다.

다른 PC의 준비 절차:

```powershell
.venv/Scripts/python.exe -m pip install -e ".[ai,pulse]"
# 변환에만 필요. 기존 MediaPipe protobuf와 호환되는 버전 유지.
.venv/Scripts/python.exe -m pip install onnx==1.17.0 --no-deps
.venv/Scripts/python.exe scripts/prepare_pretrained_pulse.py --download
npm run prepare:pulse-assets
```

준비 스크립트는 공식 코드/가중치의 고정 SHA-256을 확인하고, `weights_only=True`로
로드한다. ONNX로 바꿀 때 diff를 인접 차분으로, TSM scatter를 동등한 concat으로
표현하여 불필요한 상수를 줄였다. 원본 PyTorch 출력과 allclose 검증한다.
현재 변환 모델은 8,681,596바이트이고 검증 입력의 최대 절대 오차는 약 5.96e-7.
실행 중 다운로드나 임의 코드 로드는 하지 않는다. 런타임은 ONNX Runtime CPU만 사용.
검증된 로컬 개발 측정: 3초 창의 추론 약 0.24~0.25초. 모든 PC의 성능 보장은 아니다.

## 처리 흐름과 한계

1. 실제 비디오 프레임 시각으로 수집하고, 얼굴 추적은 약 5Hz로 분리한다.
   한 번에 한 프레임만 처리하며 늦은 프레임의 무한 적재를 하지 않는다.
2. 얼굴 경계의 1.5배 영역을 잘라 RGB 72×72로 축소한다. 한 명·면적·조명·큰
   움직임 조건을 검사한다. 말하기에 따른 정상 미세 움직임을 무조건 정지로 취급하지 않는다.
3. 약 3초의 실제 크롭과 촬영 시각을 로컬 API로 전송한다. 최소 15fps, 최대
   프레임 간격 250ms 조건을 검사하고 공식 30fps 기준으로 시간 보간한다.
   보간한 프레임은 추가로 촬영한 데이터가 아니며 낮은 FPS의 정보를 복원하지 않는다.
4. 공식 Standardized 전처리를 적용한다. 입력 `[91,3,72,72]`, 출력 90개
   DiffNormalized 맥파 값을 얻는다. 모델의 frame_depth는 10이다.
5. 실제 모델 출력만 누적/적분·추세 제거하고, 주기성/전후반 일치도를 검사한다.
   최소 약 15초의 모델 출력을 모으므로 첫 BPM은 보통 18~20초 이상 필요하다.
   45~180 BPM 탐색, 경계/약한 신호는 미측정이다. 품질 값은 정확도 확률이 아니다.
6. 얼굴 이탈·누락·탭 숨김·종료 시 오래된 결과와 늦은 HTTP 응답을 배제한다.
   사용자 영상·신호는 학습하지 않으며 맥박은 종합 점수나 종료 보고서에 저장하지 않는다.

카메라 30fps를 요청하더라도 조명·드라이버·다른 탭·PC 부하 때문에 실제 수집률이
낮아질 수 있다. 다른 카메라 탭을 닫고 전면 조명을 일정하게 유지해야 한다.
말하기·움직임에 대한 실제 정확도는 기준 센서와 함께 별도 검증해야 한다.

## 개인정보와 API

POS와 달리 EfficientPhys 모드는 **작은 얼굴 크롭을 로컬 백엔드로 전송**한다.
브라우저에서 loopback 목적지만 허용하고, API는 development + loopback + 허용 Origin
검사 후 처리한다. 요청 최대 2MiB, 동시 요청 1개, 업로드 제한 10초이다.
추론은 비동기 스레드에서 ORT 2스레드로 실행하여 FastAPI/음성 WebSocket을 막지 않는다.
연결 취소 시 실제 추론 종료 전 슬롯을 다시 열지 않는다. 사용하지 않으면
30~40초 내 ORT 모델 세션을 회수한다. 원본 영상·맥파·BPM을 파일/DB/로그에 저장하지 않는다.
외부 서버나 클라우드 API로 보내지 않는다.

맥박 상승을 긴장·감정·건강 상태로 단정하지 않으며, 의료 진단·면접 평가/선발에
사용하지 않는다. 현재 기능은 본인의 발표 연습용 연구 프로토타입이다.

## 검증

- 모델 변환의 원본 출력 비교, 실제 ONNX 추론, 입력/시각/Origin/크기 검사,
  취소 슬롯 처리, 발표 화면의 단일 video 공유를 테스트한다.
- `/tests/pretrained-presentation-smoke.html`은 공개 얼굴 예제와 합성 색 변화로
  실제 모델 API/공유 비디오/UI를 검사하는 개발용 화면이다. 사람의 카메라나
  마이크를 요청하지 않는다. 합성 시험 통과는 실제 맥박 정확도를 보장하지 않는다.
- 실제 사용자 발표 중 정확도, 조명/피부톤/카메라별 오차, 측정 가능 비율은
  기준 센서가 포함된 허가된 데이터로 후속 검증이 필요하다.

현재 확인 결과: 프론트엔드 61개, 백엔드 321개 테스트 통과(Windows에서 POSIX 전용
3개 제외). 공개 얼굴 + 합성 색 변화의 공유 video 시험에서 실제 모델이 반복
호출되고 카메라 오버레이/패널에 결과가 표시됨을 확인했다. 같은 시점에 실제
Qwen WebSocket 공개 음성 전사·종료·모델 회수도 통과했다. 사용자 카메라/마이크
권한은 테스트에서 승인하지 않았다. 시선 모듈 로드 성공이 방향 정확도 검증은 아니다.

STT 테마 비교 시에는 맥박 ON/OFF도 동일하게 맞춰야 한다. 맥박 ON 상태의
추가 CPU/RAM 부하가 있으며 별도 맥박 추론 시간은 기존 STT 비교 기록에 포함되지 않는다.
