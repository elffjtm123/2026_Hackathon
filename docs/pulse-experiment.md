# Camera pulse experiment / 카메라 색 변화 기반 맥박 실험

> 최신: 발표 화면에는 EfficientPhys 사전학습 모델이 연결되었다.
> 기존 `#pulse-experiment`도 통합 발표 화면으로 이동하며, 이 문서의 POS
> 비교 기준선은 `#pulse-pos-experiment`에 남아 있다.
> 현재 연결 구조는 [pretrained-presentation-pulse.md](pretrained-presentation-pulse.md) 참고.

## 무엇을 추가했는가

- `#pulse-experiment`: 카메라만 사용하는 단독 실험. 마이크·STT·시선 서버 없이 실행.
- 모든 `#practice/<model>`: 동일한 카메라 스트림을 선택적으로 재사용하는 맥박 패널.
- 기본 OFF. 카메라 권한은 사용자가 시작 버튼을 누를 때만 요청.
- MediaPipe Tasks Vision 1.2.0의 Face Landmarker WASM으로 이마·양 볼 영역 추적.
- POS 논문의 RGB 정규화·투영·겹침 합산 원리를 TypeScript로 독립 구현.
- 실측 프레임 시각으로 30Hz 보간, 15~20초 창, 45~180 BPM 탐색, 부위 간 일치도 검사.
- FPS 부족, 얼굴 미검출/복수 얼굴, 큰 움직임, 과노출·저조도, 조명 변동,
  신호 부족이면 수치를 숨김. 1.5초 영상 중단·탭 숨김 시 이전 수치 폐기.
- 신호 품질은 개발용 휴리스틱이며, 검증된 정확도 확률이 아님.
- 수동 비교 기준·상대 변화 표시. 임상적인 안정 시 심박수로 간주하지 않음.

이것은 감정/긴장 분류기, HRV 측정기, 혈압계 또는 의료기기가 아니다.
맥박 증가에는 움직임·환경·기저 상태 등 여러 요인이 있으므로 원인을 단정하지 않는다.
면접 합격/불합격이나 부정행위 점수에 연결하지 않는다.

## 개인정보와 실행 구조

맥박 전용 프레임은 `createImageBitmap`으로 브라우저의 classic Worker에만 전달된다.
프레임 처리가 끝나면 bitmap을 닫으며, 한 번에 한 프레임만 전송한다.
원본 영상·RGB·맥파·BPM은 서버/외부 서비스/저장소로 보내지 않는다.
최대 20초의 RGB만 메모리에 유지하고 OFF/종료/이동 시 워커를 종료한다.
기존 발표·면접 영상/음성의 로컬 백엔드 전송 정책은 변경하지 않았다.

실행 시 CDN에 접속하지 않도록 패키지 WASM과 기존 `.models/face_landmarker.task`를
`npm run prepare:pulse-assets`가 `public/pulse-assets/`에 준비한다.
`predev`와 `prebuild`에서도 실행한다. 해당 생성 디렉터리는 Git에서 제외된다.
다른 PC는 공식 모델을 `.models/face_landmarker.task`에 준비해야 한다:
<https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker#models>

## 데이터셋 (자동 다운로드·학습하지 않았음)

| 데이터셋 | 목적 | 접근/제약 |
| --- | --- | --- |
| [UBFC-rPPG](https://sites.google.com/view/ybenezeth/ubfcrppg) | 얼굴 영상과 기준 맥파로 기본 BPM 검증 | 공식 연구용 배포·인용 조건 확인 |
| [PURE](https://www.tu-ilmenau.de/en/university/departments/department-of-computer-science-and-automation/profile/institutes-and-groups/institute-of-computer-and-systems-engineering/group-for-neuroinformatics-and-cognitive-robotics/data-sets-code/pulse-rate-detection-dataset-pure) | 정지·말하기·이동·회전 오차 | 학술기관 소속 이메일로 신청, 기업 신청 불가 안내 |
| [MMPD](https://github.com/THU-CS-PI/MMPD_rPPG_dataset) | 피부톤·조명·움직임 조건별 성능과 편향 | 연구용, 상업 사용 금지, 기관 신청·동의서 필요 |
| [UBFC-Phys](https://sites.google.com/view/ybenezeth/ubfc-phys) | 휴식·발표·암산과 영상/BVP/EDA/불안 자기보고 | 공식 서버·데이터포트의 접근·이용 조건 확인 |

단순한 피부색 분류 데이터셋이 아니라 **동기화된 얼굴 영상 + 기준 생리 신호**가
필요하다. 피부톤 자체를 감정의 근거로 쓰거나 인종을 추정하지 않는다.
UBFC-Phys에서도 실험 과제와 자기보고를 개인의 실제 긴장 감정과 동일시하지 않는다.

## 연결한 오픈소스 / 후속 후보 구분

- **현재 연결**: [MediaPipe](https://github.com/google-ai-edge/mediapipe) / Apache-2.0 코드,
  [Web API 문서](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/web_js).
  npm 패키지의 버전·integrity는 package-lock에 고정.
- **현재 별도 구현한 원리**: Wang et al.,
  [Algorithmic Principles of Remote PPG](https://doi.org/10.1109/TBME.2016.2609282),
  IEEE TBME 2017. 학습 가중치가 없는 POS 기준선.
- **아직 미연결**: [rPPG-Toolbox](https://github.com/ubicomplab/rPPG-Toolbox),
  POS·TS-CAN·EfficientPhys·PhysFormer 등 비교용. 코드의 Responsible AI/RAIL 조건과
  개별 모델·가중치 및 데이터셋 이용 조건은 각각 확인 필요.
- **아직 미연결**: [pyVHR](https://github.com/phuselab/pyVHR), GPL-3.0,
  전통 신호 처리와 ROI 비교용. 서비스 코드에 복사/번들하지 않음.
- **아직 미연결**: [yarPPG](https://github.com/SamProell/yarppg), MIT,
  Python 데모·실시간 처리 참고. 서비스 코드에 복사/번들하지 않음.

설치 가능한 공개 코드와 사용 제한이 없는 데이터는 다른 개념이다.
연구용 데이터셋을 서비스 사용자 영상으로 대체 수집하지 않는다.

## 다음 검증

1. 기준 센서와 동시 측정한 허가된 영상으로 동일한 시간창·사람 단위 분할을 적용.
2. BPM MAE/RMSE, 측정 가능 비율, 잘못된 수치 표시율, 처리 시간·FPS를 함께 기록.
   게이트가 거부한 영상을 제외한 오차만으로 성능을 과장하지 않음.
3. 피부톤·조명·카메라·말하기·움직임별로 분리 평가. 합성 RGB 통과는 이 검증을 대체하지 않음.
4. POS 기준선과 학습형 후보를 같은 입력/ROI/창에서 비교한 뒤 적용 여부 결정.
5. 긴장 연구는 별도 동의와 자기보고·실험 조건을 갖춘 후 수행. 현재 맥박 기능을
   스트레스 점수나 HRV로 재해석하지 않음.

## 재현 가능한 개발 검사

`npm run build`, `node --test tests/pulse_signal.test.mjs`.
개발 서버의 `/tests/pulse-browser-smoke.html`에서 실제 MediaPipe 로드 및 얼굴 없는
영상 거부를 검사할 수 있다. 카메라/마이크를 사용하지 않는 개발용 화면이며
배포 빌드에는 포함되지 않는다. 실제 사용자 맥박 정확도는 별도 검증이 필요하다.

2026-10-29 개발 검증: 합성 RGB 54/72/96/120/150 BPM 복원 및 무효 입력
거부 테스트 통과. 실제 브라우저의 MediaPipe WASM·모델 로드 성공.
합성 canvas 영상 → 실제 video 프레임 콜백 → Worker → React 패널 연결에서
얼굴 미검출을 측정 보류로 표시함을 확인했다. 실제 카메라 권한을 승인하거나
사용자 생체 신호를 수집한 검사는 수행하지 않았다.

## 2026-10-30 얼굴 영역 회귀 수정

실제 사용에서 얼굴이 보이는데도 `얼굴 영역이 너무 작거나 화면 밖` 오류가
지속되는 문제가 보고되었다. 공개 얼굴 사진을 일반 웹캠 크기로 잘라
기존 코드에 입력하자 20프레임 연속 거부됨을 재현했다.
기존 이마 랜드마크의 좁은 bounding box가 최소 높이 검사에 걸렸으며,
세 부위 중 하나만 실패해도 전체 버퍼를 비우는 구조가 문제를 확대했다.

눈 사이 거리에 비례하는 이마·볼 면적과 해부학적 중심점으로 변경했다.
최소 면적·화면 경계 검사는 유지한다. 250ms 이내 단발성 품질 실패는
잘못된 샘플을 넣지 않고 건너뛰며, 얼굴 없음/복수 얼굴은 즉시 버퍼를 비운다.
수집 창이 초기화되면 이전 BPM을 다시 표시하지 않는다.

패널에 미러 좌표로 맞춘 ROI 상자, 처리 FPS, 유효 프레임 수, 밝기,
수집 단계 및 실제 녹색 채널 변화 그래프를 추가했다.
ROI 상자의 녹색은 면적 조건 충족을 뜻하며 맥파 정확도 인증이 아니다.

`/tests/pulse-face-regression.html` 개발용 검사에서 공식 공개 얼굴 영상에
72 BPM 색 변화를 합성하여 실제 모델 → ROI → RGB → POS를 검사했다.
수정 후 457/457프레임을 수집하고 15.2초 창에서 72 BPM을 산출했다.
이는 **알려진 합성 신호의 처리 경로 검증**이고 실제 생체 맥박 정확도와 다르다.
추가로 실제 canvas MediaStream → video 프레임 콜백 → Worker → UI에서도
영역 3/3, 약 20fps 수집, 합성 72 BPM 산출을 확인했다. 얼굴 랜드마크 추론은
약 10Hz로 분리하고 RGB 샘플링은 매 캡처 프레임마다 수행하여 부하를 줄였다.
프론트엔드 회귀 테스트 59개와 빌드를 통과했다.
사진 출처: <https://storage.googleapis.com/mediapipe-assets/portrait.jpg>.
테스트 사진은 tests/fixtures에만 있으며 배포 public 자산에 넣지 않는다.
