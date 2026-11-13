import { useEffect, useState } from 'react';
import type { PracticeSummary } from '../../lib/realtimeProtocol';
import { storeRun, summaryForUser } from './runHistory';

function ms(value: number | null | undefined) { return value == null ? '미측정' : `${Math.round(value)} ms`; }

export function LiveComparisonPanel({summary}: {summary: PracticeSummary | null}) {
  const [note, setNote] = useState('');
  const [storageWarning, setStorageWarning] = useState('');
  const [createdAt] = useState(() => new Date().toISOString());
  const comparison = summary?.comparison;
  useEffect(() => {
    if (!summary || !comparison) return;
    try {
      storeRun(sessionStorage, {id: summary.sessionId, createdAt, note, summary});
      setStorageWarning('');
    } catch { setStorageWarning('브라우저 저장 공간이 없어 기록을 보관하지 못했습니다. JSON을 직접 저장하거나 복사해 주세요.'); }
  }, [summary, comparison, note, createdAt]);
  if (!summary || !comparison) return null;
  const shown = summaryForUser(summary);
  const data = JSON.stringify({created_at: createdAt, note, summary: shown, report: shown.backendReport}, null, 2);
  const errors = Object.entries(comparison.errors ?? {});
  function download() {
    const blob = new Blob([data], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url;
    link.download = `live-${comparison!.model_id}-${summary!.sessionId}.json`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="live-comparison-panel" aria-label="통합 모델 비교 기록">
    <h2>통합 연습 비교 기록 · {comparison.label}</h2>
    <p>얼굴·시선과 음성을 함께 실행한 결과입니다. 상태: {summary.incomplete ? '미완료 — 오류 포함' : '완료'}</p>
    <dl className="summary-grid">
      <div><dt>음성 평균 추론</dt><dd>{ms(comparison.performance?.speech_rate?.average_inference_ms)}</dd></div>
      <div><dt>시선 평균 추론</dt><dd>{ms(comparison.performance?.gaze?.average_inference_ms)}</dd></div>
      <div><dt>음성 최대 결과 지연</dt><dd>{ms(comparison.performance?.speech_rate?.max_result_age_ms)}</dd></div>
      <div><dt>최대 음성 큐 대기</dt><dd>{comparison.audio_queue_peak ?? '미측정'} 패킷</dd></div>
      <div><dt>교체된 영상 프레임</dt><dd>{comparison.dropped_video_frames ?? '미측정'}개</dd></div>
      <div><dt>음성 모델 준비 시간</dt><dd>{ms(comparison.load_ms)}{comparison.already_loaded ? ' · 기존 상주 모델' : ''}</dd></div>
    </dl>
    <p>오류: {errors.length ? errors.map(([code, count]) => `${code} ${count}회`).join(' / ') : '보고된 오류 없음'}</p>
    <p>음성 결과 지연은 청크 시작 기준으로 조립·큐·추론 시간을 포함합니다. 네트워크 왕복 시간이나 자막 표시 시간은 아닙니다.</p>
    <label className="live-comparison-note">정성평가 메모<textarea value={note} rows={3}
      placeholder="예: 왼쪽을 봤을 때 반응이 늦음 / 기술 용어 누락 / 자막 지연 / 발화 속도 표시 안정적"
      onChange={event => setNote(event.target.value.slice(0, 3000))} /></label>
    <p>종료 결과와 메모는 이 탭의 세션 저장소에 최신 20개까지 보관합니다. 녹음·영상 파일은 저장하지 않습니다.</p>
    {storageWarning && <p className="error-banner" role="alert">{storageWarning}</p>}
    <div className="live-comparison-actions"><button className="secondary-button" onClick={download}>통합 결과 JSON 저장</button>
      <a href="#themes" className="secondary-button theme-link">다른 테마와 비교하기</a></div>
    <details><summary>저장이 안 되면 결과 원문 복사</summary><textarea aria-label="통합 결과 JSON 원문" readOnly rows={8} value={data} /></details>
    <details><summary>실행 설정 및 해석 주의</summary><ul>{comparison.notes.map(text => <li key={text}>{text}</li>)}</ul>
      <pre>{JSON.stringify(comparison, null, 2)}</pre></details>
  </section>;
}
