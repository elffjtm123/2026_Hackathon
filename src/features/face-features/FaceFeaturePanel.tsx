import { useEffect, useState } from 'react';
import { blendshapeNames, type FaceFeatures } from './features';
import './face-features.css';

const movements = [
  ['왼쪽 눈 감김', ['eyeBlinkLeft']], ['오른쪽 눈 감김', ['eyeBlinkRight']],
  ['눈썹 내림', ['browDownLeft', 'browDownRight']], ['안쪽 눈썹 올림', ['browInnerUp']],
  ['입꼬리 올림', ['mouthSmileLeft', 'mouthSmileRight']], ['입술 누름', ['mouthPressLeft', 'mouthPressRight']],
  ['턱 벌어짐', ['jawOpen']],
] as const;
const number = (v: number | null | undefined, digits = 2) => v == null ? '—' : v.toFixed(digits);
const average = (values: Record<string, number> | null, keys: readonly string[]) =>
  values && keys.every(k => values[k] !== undefined) ? keys.reduce((sum, k) => sum + values[k], 0) / keys.length : null;

export function FaceFeaturePanel({result, enabled, active, onEnabledChange, snapshot}: {
  result: FaceFeatures; enabled: boolean; active: boolean; onEnabledChange: (enabled: boolean) => void;
  snapshot?: () => unknown;
}) {
  const [baseline, setBaseline] = useState<Record<string, number> | null>(null);
  useEffect(() => { setBaseline(null); }, [active, enabled]);
  const live = active && result.status === 'observed';
  const w = result.window;
  const status = !enabled ? '꺼짐' : !active && result.status !== 'ended' ? '시작 대기'
    : ({waiting: '모델 준비 중', observed: '관찰 중', unavailable: '관찰 보류', stale: '갱신 중단', ended: '관찰 종료', off: '꺼짐'})[result.status];
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot?.() ?? result, null, 2)], {type: 'application/json'}));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'presentation-face-features.json';
    anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="face-feature-panel" aria-label="발표 표정 특징 추출">
    <header className="face-feature-heading"><div><p className="eyebrow">FACE MOVEMENT · MEDIAPIPE</p>
      <h2>발표 중 표정 특징</h2><p>눈·눈썹·입 움직임을 수치로 관찰합니다.</p></div>
      <label><input type="checkbox" checked={enabled} onChange={e => onEnabledChange(e.target.checked)} />표정 특징 추출</label>
    </header>
    <div className={`face-feature-status face-feature-status--${live ? 'live' : 'idle'}`}>
      <strong>{status}</strong><span>{result.reason}</span>
    </div>
    <div className="face-feature-summary">
      <div><span>관찰된 깜빡임</span><strong>{enabled && w.sampleCount ? result.totalBlinks : '—'}<small>회 · 관찰 시작 이후</small></strong></div>
      <div><span>최근 구간 눈 감김 비율</span><strong>{enabled ? number(w.closedEyeRatio == null ? null : w.closedEyeRatio * 100, 1) : '—'}<small>% · 유효 시간 기준</small></strong></div>
      <div><span>유효 관찰</span><strong>{enabled && w.durationSeconds ? number(w.coverage * 100, 0) : '—'}<small>% · 최근 {number(w.durationSeconds, 1)}초</small></strong></div>
      <div><span>표정 분석 속도</span><strong>{live ? number(w.observedFps, 1) : '—'}<small>회/초</small></strong></div>
    </div>
    <div className="face-feature-movements">
      {movements.map(([label, keys]) => {
        const value = live ? average(result.coefficients, keys) : null;
        const currentMean = average(w.mean, keys), reference = average(baseline, keys);
        const delta = currentMean !== null && reference !== null ? Math.round((currentMean - reference) * 100) / 100 : null;
        return <div className="face-feature-movement" key={label}><div><span>{label}</span><strong>{number(value)}</strong></div>
          <meter aria-label={`${label} 계수`} min={0} max={1} value={value ?? 0} />
          <small>구간 평균 {enabled ? number(currentMean) : '—'}{baseline && delta !== null ? ` · 기준 대비 ${delta >= 0 ? '+' : ''}${delta.toFixed(2)}` : ''}</small>
        </div>;
      })}
    </div>
    <div className="face-feature-actions"><button className="secondary-button" disabled={!live || w.validSeconds < 1}
      onClick={() => setBaseline({...w.mean})}>현재 표정을 비교 기준으로</button>
      {baseline && <button className="secondary-button" onClick={() => setBaseline(null)}>기준 초기화</button>}
      <button className="secondary-button" disabled={!enabled || !w.sampleCount} onClick={download}>특징 JSON 내려받기</button>
    </div>
    <p className="face-feature-note">계수는 0~1의 얼굴 움직임 값입니다. 감정 확률이나 긴장 점수는 아닙니다. 좌우는 사용자 얼굴 기준이며, 말하기에 따른 입 움직임도 포함됩니다.</p>
    {w.observedFps > 0 && w.observedFps < 10 && <p className="face-feature-note">표정 분석이 초당 10회 미만입니다. 짧은 깜빡임이 누락될 수 있습니다.</p>}
    <details><summary>52개 원시 특징과 최근 구간 통계</summary>
      <p>478개 랜드마크와 얼굴 변환 행렬을 이용합니다. 아래에는 52개 표정 계수를 표시하며, 표준편차·구간 처음과 끝의 차이는 관찰된 프레임으로 계산합니다.</p>
      <p>얼굴 {result.faceCount}명 · 마지막 관찰 시각 {number(result.timestampMs == null ? null : result.timestampMs / 1000, 2)}초 · 유효 {number(w.validSeconds, 1)}초 · 고개 움직임 {number(w.headMotionDegreesPerSecond, 1)}도/초 · {result.delegate ?? '준비 중'} delegate</p>
      <div className="face-feature-table"><table><thead><tr><th>특징</th><th>현재</th><th>평균</th><th>표준편차</th><th>변화량</th></tr></thead>
        <tbody>{blendshapeNames.map(name => <tr key={name}><th scope="row">{name}</th><td>{number(live ? result.coefficients?.[name] : null, 3)}</td>
          <td>{number(w.mean[name], 3)}</td><td>{number(w.std[name], 3)}</td><td>{number(w.change[name], 3)}</td></tr>)}</tbody></table></div>
    </details>
    <p className="face-feature-note">같은 발표 카메라와 얼굴 모델을 공유합니다. 표정 특징은 브라우저 메모리에서 처리하며 자동 저장·전송하지 않습니다. JSON은 버튼을 누를 때만 내려받습니다. <a href="https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker" target="_blank" rel="noreferrer">MediaPipe 공식 자료</a></p>
  </section>;
}
