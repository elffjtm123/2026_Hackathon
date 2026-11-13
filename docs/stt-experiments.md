# 로컬 CPU 받아쓰기 비교 실험

기존 발표·면접 서비스를 교체하지 않고, **같은 녹음**을 기존 서비스 STT와 네 후보에 순차 입력하는 실험 화면이다.

## 실행

프로젝트 루트에서 기존 `.venv`를 사용한다.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[stt-experiments]"
.venv\Scripts\python.exe -m scripts.prepare_stt_experiments --llama
npm run dev:backend
# 별도 터미널
npm run dev -- --host 127.0.0.1
```

현재 컴퓨터에는 패키지·네 후보의 가중치·Windows x64 CPU llama.cpp 실행 파일을 준비해 두었다. 다운로드는 최초 준비 단계에만 실행하며, API 요청 중에는 다운로드하거나 다른 모델로 대체하지 않는다. 기존 서비스의 Qwen 패키지·가중치도 정상 준비되어 있어야 한다.

화면: <http://127.0.0.1:5173/#stt-experiments> (연습 화면 상단에서도 이동 가능)

1. 마이크로 최대 60초 녹음하거나 음성 파일을 선택한다. 브라우저가 16kHz mono PCM16 WAV로 정규화한다.
2. 필요하면 실제 발화의 정답 전사를 입력한다. 정답은 **평가에만** 쓰며 모델 프롬프트로 전달하지 않는다. ‘어’, ‘음’, 실제 반복도 포함한다.
3. 다섯 모델을 선택하고 기본 2초 청크, 워밍업 ON으로 실행한다. 4초 청크도 별도 실행하여 문장 경계 영향을 비교할 수 있다.
4. 받아쓰기 원문, CER, RTF, 청크 처리 P95, 로딩·워밍업 시간, 백엔드 RSS를 확인한다.
5. 동일 음성 WAV, 상세 JSON, 비교표 CSV를 저장한다. 실험 메타데이터에는 음성 SHA-256, 패키지 버전, 가중치 revision과 llama.cpp 버전이 포함된다.

내장 브라우저에서 파일 다운로드가 제한되면 결과 아래의 ‘다운로드가 안 되면 결과 텍스트 복사’를 펼쳐 CSV/JSON 원문을 복사할 수 있다.

## 모델 구성

| 설정 | 실행 경로 | 정밀도 |
| --- | --- | --- |
| 현재 서비스 Qwen3-ASR-0.6B Q8_0 | speech.cpp 현재 서비스 어댑터 | Q8_0, 서비스 장치 설정 유지 |
| Qwen3-ASR-0.6B Q8 | llama.cpp CPU, 별도 loopback 자식 프로세스 | 본체 Q8_0 + 오디오 mmproj Q8_0 |
| Whisper small INT8 | faster-whisper / CTranslate2 CPU | 로딩 시 INT8 변환 |
| Whisper base INT8 | faster-whisper / CTranslate2 CPU | 로딩 시 INT8 변환 |
| 한국어 Zipformer INT8 | sherpa-onnx CPU | encoder·joiner INT8, decoder FP32 |

Whisper의 다운로드 파일은 FP16 가중치이며 **추론 시 INT8**로 변환된다. INT8 파일 크기를 측정하는 실험은 아니다. 모델 원본과 revision은 `.models/stt/manifest.json`에 기록된다.

가중치 출처:

- [Qwen GGUF](https://huggingface.co/ggml-org/Qwen3-ASR-0.6B-GGUF)
- [Whisper small 변환 모델](https://huggingface.co/Systran/faster-whisper-small), [Whisper base 변환 모델](https://huggingface.co/Systran/faster-whisper-base)
- [한국어 스트리밍 Zipformer](https://huggingface.co/k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16)
- [llama.cpp](https://github.com/ggml-org/llama.cpp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)

## 실험 해석

- 동일 PCM, 동일 청크, 공통 RMS/WebRTC VAD를 적용한다. 짧은 마지막 청크도 전달하고 실제 반복 발화는 삭제하지 않는다.
- CER은 NFC 정규화 후 공백·문장부호 제거, 영문 소문자화를 적용한다. 정답이 없으면 미측정이며 삽입 오류가 많으면 100%를 넘을 수 있다.
- RTF는 청크 추론 시간 합 / 전체 음성 길이이다. 로딩·워밍업은 별도이고 무음 청크는 건너뛴다. 무음이 많은 녹음과 발화 위주 녹음의 RTF를 직접 비교하지 않는다. P95도 전체 청크를 대상으로 하므로 건너뛴 청크가 포함된다.
- 공통 게이트 전처리는 시간에서 제외한다. 기존 어댑터의 내부 재검사와 음성 후처리는 포함된다. 따라서 완전히 동일한 커널 비용만 측정한 결과는 아니다.
- 현재 서비스는 실험 시작 시 공통 워커를 준비하고 실험 종료 시 회수한다. 워커 준비 이후의 로딩 표시 0ms는 콜드 스타트 비용 0이라는 뜻이 아니다.
- 후보는 설정된 CPU 스레드 수를 사용한다. 현재 서비스는 speech.cpp의 장치 설정을 유지하므로 GPU가 사용될 수 있다. 모든 모델이 CPU로 실행됐는지는 실제 장치 metadata를 확인한다.
- 현재 서비스도 Q8_0이므로 다른 Qwen Q8 후보와의 비교는 speech.cpp와 llama.cpp 등 **배포 설정 간 비교**이다. FP32 대비 양자화만의 인과 효과를 측정한 실험이 아니다.
- Zipformer는 서비스와 청크 조건을 맞추기 위해 매 청크마다 스트림을 초기화하고 오른쪽 문맥용 무음을 추가한다. 지속 스트리밍 구조의 최대 성능·정확도를 검증하는 실험은 아니다. 해당 효과는 연속 상태를 유지하는 별도 모드로 후속 평가해야 한다.
- RSS는 기존 Qwen·시선 모델을 포함한 백엔드와 자식 프로세스의 합계(50ms 표본)이다. 단독 모델 RAM이 아니며 할당 캐시·실행 순서의 영향도 있다. JSON에는 시작 대비 증가량도 기록된다. 경량화의 RAM 효과를 확정하려면 모델별 독립 프로세스 실험이 필요하다.
- 필러워드는 전사 기반 통계이다. 실제 검출 정확도나 음향학적 발음 명료도 점수로 해석하지 않는다.
- WebSocket 전송과 시선 분석 동시 실행은 측정 대상에서 제외된다. RTF < 1만으로 서비스 전체 실시간 동작을 보장하지 않는다.
- 모델 로딩·추론 실패는 해당 모델의 실패로 표시한다. 취소는 현재 네이티브 로딩/추론이 끝난 뒤 다음 청크에서 적용된다.

## 안전·보관

개발 환경의 loopback 접속에만 허용한다. `APP_ENV=production` 또는 `STT_EXPERIMENTS_ENABLED=false`에서는 API가 404를 반환한다. 기존 연습과 실험은 동시에 실행하지 않는다. 서버는 최근 10개 실험 결과를 메모리에 보관하며 재시작하면 사라진다. 원음은 실행 동안만 서버 메모리에서 처리하며 자동 파일 저장하지 않는다. 직접 저장한 WAV/CSV/JSON에는 발화 내용이 포함되므로 공유 전에 확인한다.

환경 변수: `STT_EXPERIMENT_MODEL_DIR=.models/stt`, `STT_EXPERIMENT_THREADS=4`, `STT_EXPERIMENTS_ENABLED=true`.

## 권장 평가

같은 화자가 같은 장비로 정상 발화, 기술 용어, 필러워드·반복, 중간 무음, 주변 소음을 포함한 여러 녹음을 만든다. 각 파일을 동일 설정으로 최소 3회 실행하고 실행 순서도 바꿔 기록한다. 음성별 CER과 RTF 분포를 비교하고, 실패 횟수와 청크 경계에서 누락된 표현을 함께 분석한다. 짧은 샘플 한 건의 성공은 품질 평가 완료를 의미하지 않는다.
