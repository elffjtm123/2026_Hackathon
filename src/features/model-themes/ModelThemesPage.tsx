import { useCallback, useEffect, useState, type CSSProperties } from 'react';
import { modelThemes, readModelAvailability, type ModelAvailability } from './modelThemes';
import './themes.css';
import { readRuns, type SavedRun } from './runHistory';

export function ModelThemesPage() {
  const [models, setModels] = useState<ModelAvailability[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [runs] = useState<SavedRun[]>(() => { try { return readRuns(sessionStorage); } catch { return []; } });
  const refresh = useCallback(async (isDisposed: () => boolean = () => false) => {
    setChecking(true);
    try {
      const body = await readModelAvailability();
      if (!isDisposed()) { setModels(body.models); setBusy(body.busy); setError(null); }
    } catch (cause) {
      if (!isDisposed()) setError(cause instanceof Error ? cause.message : '백엔드 연결 실패');
    } finally { if (!isDisposed()) setChecking(false); }
  }, []);
  useEffect(() => {
    let disposed = false; void refresh(() => disposed);
    return () => { disposed = true; };
  }, [refresh]);
  return <main className="practice-shell model-hub">
    <header className="practice-header"><div><p className="eyebrow">REALTIME COACH · MODEL STUDIO</p>
      <h1>같은 연습, 다른 음성 모델</h1></div>
      <nav className="theme-nav"><a href="#stt-experiments" className="secondary-button theme-link">동일 음성 파일 비교</a>
      <a href="#practice/service_qwen" className="secondary-button theme-link">발표·시선·맥박 함께 사용</a></nav></header>
    <section className="theme-hero"><span className="theme-pill">얼굴·시선 기능 포함</span>
      <h2>테마를 고르고, 실제 서비스로 비교하세요.</h2>
      <p>카메라 보정부터 얼굴 방향·눈 시선, 받아쓰기, 발화 속도, 필러워드와 종료 리포트까지.
        기존 기능은 함께 사용하고, 선택한 테마의 STT 모델만 바뀝니다.</p>
      <div className="theme-feature-list"><span>얼굴 방향 + 눈 시선</span><span>발표 / 면접</span>
        <span>대본 가이드 + 자막</span><span>음성 후처리 + 결과</span></div>
    </section>
    <div className="theme-status-row"><p>실시간 통합 연습 · 모델은 시작할 때 로드 · 한 번에 한 세션</p>
      <button className="secondary-button" disabled={checking} onClick={() => { void refresh(); }}>
        {checking ? '확인 중…' : '모델 상태 새로고침'}</button></div>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {busy && <p className="theme-notice" role="status">다른 탭에서 연습이나 실험이 진행 중입니다. 종료 후 시작해 주세요.</p>}
    <section className="theme-grid" aria-label="모델별 연습 테마">{modelThemes.map((theme, index) => {
      const availability = models.find(model => model.id === theme.id);
      return <article key={theme.id} className="theme-card"
        style={{ '--theme-accent': theme.accent, '--theme-tint': theme.tint } as CSSProperties}>
        <div className="theme-card-top"><span className="theme-index">0{index + 1}</span><span className="theme-pill">{theme.tag}</span></div>
        <h2>{theme.name}</h2><p className="theme-model-label">{theme.label}</p><p>{theme.description}</p>
        <p className="theme-common">공통: 얼굴·시선 분석 / 발표·면접 / 음성 피드백</p>
        <p className={`theme-availability ${availability?.available ? 'ready' : ''}`}>
          {availability?.available ? '● 파일 준비됨 · 실제 로딩은 시작 시 확인' : availability?.reason ?? '서버 준비 상태 확인 전'}</p>
        <a className="theme-enter" href={`#practice/${theme.id}`} aria-label={`${theme.name} 테마로 연습하기`}>
          이 테마로 연습하기 <span aria-hidden="true">↗</span></a>
      </article>;
    })}</section>
    {runs.length > 0 && <section className="live-comparison-panel" aria-label="이 탭의 통합 비교 기록"><h2>이 탭에서 완료한 비교 기록</h2>
      <p>테마별 결과를 함께 확인하세요. 직접 재발화한 실험이므로 동일 입력의 통제 실험은 아닙니다.</p>
      {runs.map(run => <details key={run.id}><summary>{run.summary.comparison?.label} · {run.summary.comparison?.mode === 'interview' ? '면접' : '발표'} · {run.summary.incomplete ? '미완료' : '완료'} · {new Date(run.createdAt).toLocaleTimeString('ko-KR')}</summary>
        <p>음성 평균 추론 {run.summary.comparison?.performance?.speech_rate?.average_inference_ms == null ? '미측정' : `${Math.round(run.summary.comparison.performance.speech_rate.average_inference_ms)} ms`} ·
          시선 관찰 {run.summary.comparison?.performance?.gaze?.observations ?? 0}회</p>
        <p>{run.summary.transcript ?? '인식된 음성 없음'}</p><p>메모: {run.note || '미입력'}</p>
        <textarea aria-label={`${run.summary.comparison?.label} 결과 원문`} readOnly rows={5} value={JSON.stringify(run, null, 2)} />
      </details>)}
    </section>}
    <aside className="theme-notice"><strong>비교할 때 알아두세요</strong>
      <p>모든 테마는 동일한 얼굴·시선 모델과 음성 후처리를 사용합니다. 같은 대본·제한시간·카메라 위치로 반복해 보세요.
        직접 다시 말하는 실험이라 행동 차이도 결과에 영향을 줍니다. 동일 녹음의 STT 비교는 상단의 별도 화면에서 가능합니다.</p>
      <p>명료도는 대본/STT 일치도 기반 추정치입니다. 실시간 연습은 VAD 발화 단위이며 Zipformer는 발화마다 상태를 초기화합니다. 파일 비교는 별도 고정 청크 실험입니다.</p>
    </aside>
  </main>;
}
