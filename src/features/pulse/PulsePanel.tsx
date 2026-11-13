import { useEffect, useState, type RefObject } from 'react';
import { usePulse, type FaceFeatureOptions } from './usePulse';
import './pulse.css';
import { VideoPreview } from '../practice/components/VideoPreview';
import { emptyPulse, type PulseResult } from './signal';
import { pulseModels, type PulseModelId } from './models';

export function PulsePanel({stream, showPreview = false, mode = 'pos', embedded = false, videoRef, onResult, faceFeatures}: {
  stream: MediaStream | null; showPreview?: boolean; mode?: 'pos' | 'efficientphys'; embedded?: boolean;
  videoRef?: RefObject<HTMLVideoElement | null>; onResult?: (result: PulseResult) => void;
  faceFeatures?: FaceFeatureOptions;
}) {
  const [enabled, setEnabled] = useState(mode === 'efficientphys');
  const [baseline, setBaseline] = useState<number | null>(null);
  const [modelId, setModelId] = useState<PulseModelId>('ma_ubfc_tscan');
  const model = pulseModels.find(v=>v.id===modelId)!;
  useEffect(() => { setBaseline(null); }, [stream]);
  const result = usePulse(stream, enabled, mode, videoRef, modelId, faceFeatures);
  useEffect(() => { onResult?.(enabled && (stream || result.ended) ? result : emptyPulse(enabled ? '발표 시작 대기' : '맥박 분석 꺼짐')); }, [result, enabled, stream, onResult]);
  const observed = enabled && !!stream && !result.held && result.status === 'observed' && result.bpm !== null;
  const numeric = enabled && (!!stream || result.ended) && result.bpm !== null;
  const provisional = (result.readingStatus ?? result.status) === 'provisional';
  const delta = observed && baseline !== null ? result.bpm! - baseline : null;
  const diagnostics = enabled && stream ? result.diagnostics : undefined;
  const regions = diagnostics?.regions ?? [];
  const trackSettings = stream?.getVideoTracks()[0]?.getSettings();
  const aspect = trackSettings?.width && trackSettings?.height ? trackSettings.width / trackSettings.height : 4 / 3;
  const green = diagnostics?.green ?? [];
  const minGreen = Math.min(...green), rangeGreen = Math.max(0.01, Math.max(...green) - minGreen);
  return <section className="pulse-panel" aria-label="실험용 카메라 맥박 추정">
    <div className="pulse-heading"><div><p className="eyebrow">CAMERA PHYSIOLOGY · EXPERIMENT</p>
      <h2>{mode === 'efficientphys' ? '발표 영상 맥박 추정 · 사전학습 모델' : '얼굴 색 변화로 보는 맥박'}</h2></div>
      <label className="pulse-toggle"><input type="checkbox" checked={enabled}
        onChange={e => { setEnabled(e.target.checked); setBaseline(null); }} />{mode === 'efficientphys' ? '발표 중 맥박 분석' : '실험용 분석 켜기'}</label></div>
    <p>{mode === 'efficientphys' ? `${model.name} 사전학습 가중치 · ONNX Runtime · 발표 카메라의 같은 영상을 분석합니다.` : 'MediaPipe 얼굴 추적 + POS 신호 분석 · 기존 시선·음성 기능과 별도로 실행합니다.'}</p>
    {mode === 'efficientphys' && <div className="pulse-model-picker"><label>맥박 추정 모델 <select aria-label="맥박 추정 모델" value={modelId} disabled={!!stream}
      onChange={e=>{setModelId(e.target.value as PulseModelId);setBaseline(null);}}>
      {pulseModels.map(v=><option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
      <span className="pulse-meta">{model.note} · 모델 변경은 발표 종료 후 가능합니다.</span></div>}
    <p className="pulse-meta">{mode === 'efficientphys' ? '얼굴이 보이는 한 명·일정한 조명·15fps 이상이 필요합니다. 보통의 고개 기울임과 작은 움직임은 분석을 계속하며, 탐색 대역은 45~180 BPM입니다. 신호가 약하면 이전 값과 경과시간을 구분해 표시합니다.' : '일정한 조명·정면·한 명·15fps 이상이 필요합니다. POS 비교 실험은 움직임·각도 조건을 엄격하게 검사합니다. 탐색 대역은 45~180 BPM입니다.'}</p>
    {mode === 'efficientphys' && <p className="pulse-meta">실제 모델 신호 6초부터 잠정 BPM을 계산하고, 15초 이상에서 주기성을 검사합니다. 약 1초 간격으로 최신 영상 구간을 분석하며, 처리 중에는 요청을 쌓지 않습니다. 영상·모델 속도에 따라 갱신은 늦어질 수 있습니다.</p>}
    {!embedded && (showPreview || enabled && stream) && <div className="pulse-camera" style={{aspectRatio: aspect}}>
      <VideoPreview stream={stream} />
      {enabled && stream && <svg className="pulse-roi-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="이마와 양 볼의 실제 분석 영역">
        {regions.map(region => <g key={region.name}>
          <rect x={region.x * 100} y={region.y * 100} width={region.width * 100} height={region.height * 100}
            fill={region.valid ? '#3bdcb133' : '#f5787833'} stroke={region.valid ? '#3bdcb1' : '#f57878'} strokeWidth="0.4" />
        </g>)}
      </svg>}
      <span className="pulse-camera-badge">{!stream ? '카메라 꺼짐' : !enabled ? '분석 꺼짐 · 위 토글을 켜 주세요' : `분석 영역 ${regions.filter(r => r.valid).length}/3 · 거울 표시`}</span>
    </div>}
    {enabled && stream && <>
      <div className="pulse-stages" aria-label="맥박 분석 진행 단계">
        <span>① 얼굴 영역 {regions.filter(r => r.valid).length}/3</span>
        <span>② 모델 맥파 {result.seconds.toFixed(1)}/15초</span>
        <span>③ 맥박 {result.held ? '이전 값 유지' : observed ? '주기성 양호' : numeric ? '잠정값 산출' : result.seconds >= 6 ? '신호 부족' : '첫 값 준비'}</span>
      </div>
      <p className="pulse-meta">처리 영상 {diagnostics?.inputFps ? diagnostics.inputFps.toFixed(1) + 'fps' : '확인 중'} ·
        유효 프레임 {diagnostics?.acceptedFrames ?? 0}/{diagnostics?.totalFrames ?? 0} ·
        영역 평균 밝기 {diagnostics?.light == null ? '미측정' : diagnostics.light.toFixed(0)}</p>
      {mode === 'efficientphys' && <p className="pulse-meta">완료된 실제 모델 추론 {result.modelWindows ?? 0}회 · 추론 시간 {result.inferenceMs == null ? '미측정' : `${result.inferenceMs.toFixed(0)}ms`} · 입력 시각 기준 30Hz 보간</p>}
      {mode === 'efficientphys' && <p className="pulse-meta">실제 갱신 간격 {diagnostics?.updateSeconds == null ? '첫 결과 대기' : `${diagnostics.updateSeconds.toFixed(1)}초`} · 결과 영상 지연 {diagnostics?.resultAgeSeconds == null ? '미측정' : `${diagnostics.resultAgeSeconds.toFixed(1)}초`} · 수집 재시작 {diagnostics?.resets ?? 0}회{diagnostics?.resetReason ? ` · 마지막 원인: ${diagnostics.resetReason}` : ''}</p>}
      {diagnostics?.faceAssessment && <p className="pulse-meta">얼굴 크기 {diagnostics.faceAssessment.faceWidth.toFixed(0)}×{diagnostics.faceAssessment.faceHeight.toFixed(0)}px · 눈 사이 {diagnostics.faceAssessment.eyePixels.toFixed(0)}px{diagnostics.faceAssessment.warning ? ` · ${diagnostics.faceAssessment.warning}` : ''}</p>}
      {green.length > 3 && <div><p className="pulse-meta">수집 중인 녹색 채널 변화 · 아직 맥파로 확정된 신호는 아닙니다.</p>
        <svg className="pulse-wave" viewBox="0 0 300 60" role="img" aria-label="실제 얼굴 영역의 녹색 채널 변화">
          <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={green.map((v,i) => `${i*300/(green.length-1)},${52-(v-minGreen)/rangeGreen*44}`).join(' ')} />
        </svg></div>}
    </>}
    <div className={`pulse-readout ${numeric && (provisional || result.held) ? 'pulse-provisional' : ''}`}><div><span>{result.ended ? '발표 종료 · 마지막 추정값' : result.held ? `이전 추정값 · ${(result.ageSeconds??0).toFixed(1)}초 전` : provisional ? '잠정 추정 맥박수' : '추정 맥박수'}</span><strong>{numeric ? result.bpm : '—'} <small>BPM</small></strong>
      {numeric && <small>{result.held ? '현재값 아님 · 새 추정값을 기다리는 중' : provisional ? '잠정값 · 신호 품질 추가 확인 필요' : '주기성 검사 통과 · 센서 정확도 미검증'}{result.rawBpm !== undefined ? ` · 평활화 전 ${result.rawBpm} BPM` : ''}</small>}</div>
      <div><span>현재 상태</span><b>{!enabled ? '꺼짐' : result.ended ? `측정 종료${provisional ? ' · 마지막 값은 잠정' : ''}` : !stream ? '카메라 대기' : result.held ? '이전 값 유지 · 갱신 대기' : observed ? '주기성 양호' : numeric ? '잠정 추정' : result.status === 'unreliable' ? '측정 보류' : '수집 중'}</b></div></div>
    <p role="status">{!enabled ? '분석을 켜고 연습을 시작해 주세요.' : result.ended ? '전체 평균이 아니라 발표 중 마지막으로 산출한 값입니다. 현재 측정값이 아니며 새 발표를 시작하면 초기화됩니다.' : !stream ? mode === 'efficientphys' ? '위 시작 버튼으로 발표를 시작하면 같은 카메라 영상에서 자동 분석합니다.' : '카메라 대기 중입니다. 카메라를 시작해 주세요.' : result.held ? `마지막 산출 후 ${(result.ageSeconds??0).toFixed(1)}초 · ${result.reason}` : result.reason}</p>
    {enabled && stream && <>
      <progress aria-label="안정된 영상 수집" max={15} value={Math.min(15, result.seconds)} />
      <p className="pulse-meta">수집 {result.seconds.toFixed(1)}초 / 최소 15초 · {mode === 'efficientphys' ? '모델 기준 30Hz (시간 보간)' : `유효 샘플링 ${result.fps > 0 ? result.fps.toFixed(1)+'fps' : '미측정'}`} ·
        스펙트럼 품질 {result.snr === null ? '미측정' : `${result.snr} dB (정확도 확률 아님)`}</p>
    </>}
    {numeric && <svg className="pulse-wave" viewBox="0 0 300 70" role="img" aria-label={result.held || result.ended ? '마지막 추정값 당시의 상대 맥파 · 현재 신호 아님' : '상대 맥파 추정 신호 · 원시 혈압 파형 아님'}>
      <polyline fill="none" stroke="currentColor" strokeWidth="2" points={result.waveform.map((v, i) => `${i * 300 / Math.max(1, result.waveform.length - 1)},${35 - v * 28}`).join(' ')} />
    </svg>}
    <div className="pulse-actions"><button className="secondary-button" disabled={!observed} onClick={() => setBaseline(result.bpm)}>현재값을 비교 기준으로</button>
      <span>{baseline === null ? '기준값 미설정' : `기준 ${baseline} BPM · 현재 변화 ${delta === null ? '미측정' : `${delta > 0 ? '+' : ''}${delta} BPM`}`}</span></div>
    <p className="pulse-caution">연구용 추정치입니다. 맥박 상승을 긴장·감정으로 판정하지 않으며, 의료 진단이나 면접 평가 점수에 사용하지 않습니다. 기준값은 수동 비교용이지 안정 시 심박수로 검증된 값이 아닙니다.</p>
    <p className="pulse-meta">{mode === 'efficientphys' ? `${model.size}×${model.size} RGB 얼굴 크롭은 이 컴퓨터의 로컬 백엔드에서만 추론합니다. 영상·맥파·BPM을 파일이나 DB에 저장하지 않고, 종료 시 마지막 값만 이 화면 메모리에 남깁니다. 인터넷 서버로 보내지 않습니다.` : '본 맥박 기능의 프레임·RGB 신호·생체 추정값은 브라우저 메모리에서만 처리하며 저장·외부 전송하지 않습니다.'} 기존 연습의 영상·음성은 원래처럼 로컬 백엔드로 전송됩니다.</p>
    <details><summary>맥박 추정으로 무엇을 확인하나요?</summary><ul>
      <li>현재 추정 BPM과 발표 중 변화: 얼굴 영상의 주기적 신호로 분당 맥박수를 추정합니다.</li>
      <li>개인 기준과의 차이: 주기성이 양호할 때 설정한 수동 기준과 현재값을 비교합니다. 상승 원인을 긴장으로 단정하지 않습니다.</li>
      <li>측정 가능 조건: 영상 속도·누락·신호 품질로 수치를 해석할 수 있는 구간을 확인합니다.</li>
      <li>아직 제공하지 않는 정보: HRV·스트레스 점수·혈압·산소포화도. 현재 BPM 값만으로 계산하거나 판정하지 않습니다.</li>
    </ul><p>후속 검증은 기준 센서와의 BPM 오차와 측정 가능 비율을 함께 비교합니다. 발표 말하기·조명·피부톤·카메라 조건에 따른 오차를 별도로 확인해야 합니다.</p></details>
    <details><summary>데이터셋·오픈소스와 검증 계획</summary><PulseResources pretrained={mode === 'efficientphys'} /></details>
    {!embedded && <a href="#practice/service_qwen">발표·음성·시선·맥박 함께 사용하기 →</a>}
  </section>;
}

export function PulseResources({pretrained = false}: {pretrained?: boolean}) {
  return <div className="pulse-resources">
    <h3>검증에 사용할 데이터셋</h3><ul>
      <li><a href="https://sites.google.com/view/ybenezeth/ubfcrppg" target="_blank" rel="noreferrer">UBFC-rPPG</a> — 얼굴 영상과 기준 맥파. 기본 BPM 오차 확인.</li>
      <li><a href="https://www.tu-ilmenau.de/en/university/departments/department-of-computer-science-and-automation/profile/institutes-and-groups/institute-of-computer-and-systems-engineering/group-for-neuroinformatics-and-cognitive-robotics/data-sets-code/pulse-rate-detection-dataset-pure" target="_blank" rel="noreferrer">PURE</a> — 정지·말하기·고개 움직임. 학술 기관 신청 필요.</li>
      <li><a href="https://github.com/THU-CS-PI/MMPD_rPPG_dataset" target="_blank" rel="noreferrer">MMPD</a> — 피부톤·조명·움직임 조건별 평가. 연구용 신청·이용 제한 확인 필요.</li>
      <li><a href="https://sites.google.com/view/ybenezeth/ubfc-phys" target="_blank" rel="noreferrer">UBFC-Phys</a> — 휴식·발표·암산 영상과 BVP·EDA·불안 자기보고. 긴장 연구의 후속 후보.</li>
    </ul><h3>연결한 기술 / 후속 비교 도구</h3><ul>
      <li><a href="https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/web_js" target="_blank" rel="noreferrer">MediaPipe Face Landmarker</a> — 현재 연결: 로컬 WASM 얼굴 영역 추적. Apache-2.0 계열 코드.</li>
      <li><a href="https://doi.org/10.1109/TBME.2016.2609282" target="_blank" rel="noreferrer">POS 원 논문</a> — {pretrained ? '별도 실험실의 비교 기준선. 발표 모드의 EfficientPhys 결과를 대체하지 않음.' : '현재 연결: 논문의 투영 원리를 별도 구현. 학습 가중치 미사용.'}</li>
      <li><a href="https://github.com/ubicomplab/rPPG-Toolbox" target="_blank" rel="noreferrer">rPPG-Toolbox</a> — {pretrained ? '현재 연결: 움직임 증강 MA-UBFC TS-CAN, UBFC-rPPG 학습 EfficientPhys·TS-CAN·PhysFormer 및 기존 PURE EfficientPhys. 공식 구조와 가중치를 ONNX로 변환.' : '후속 비교: POS·TS-CAN·PhysFormer 등. RAIL 이용 조건 확인. 아직 학습 모델 미연결.'} {pretrained && <a href="/pulse-licenses/EfficientPhys-RAIL1.1.txt" target="_blank" rel="noreferrer">RAIL 1.1 이용 제한</a>}</li>
      {pretrained && <li><a href="https://motion-matters.github.io/" target="_blank" rel="noreferrer">Motion Matters</a> — 기본 모델의 움직임 증강 학습 출처. 실제 발표 중 오차 개선 여부는 기준 센서와 추가 검증이 필요합니다.</li>}
      <li><a href="https://github.com/phuselab/pyVHR" target="_blank" rel="noreferrer">pyVHR</a> — 후속 비교: ROI·전통 신호 처리. GPL-3.0, 현재 번들에 포함하지 않음.</li>
      <li><a href="https://github.com/SamProell/yarppg" target="_blank" rel="noreferrer">yarPPG</a> — Python 실시간 실험 참고. MIT, 현재 번들에 포함하지 않음.</li>
    </ul><p>아직 위 데이터셋의 다운로드·학습·성능평가는 수행하지 않았습니다. 동일한 참가자가 학습·시험에 섞이지 않게 나누고, BPM MAE·RMSE와 측정 가능 비율을 함께 비교할 계획입니다. 피부톤·조명별 결과도 별도로 확인해야 합니다.</p>
  </div>;
}
