import { useCallback, useEffect, useRef, useState } from 'react';
import { encodePcm16 } from '../practice/audioTools';
import { jobCsv, pcmWav } from './tools';
import type { ExperimentJob, ModelOption, ModelResult } from './types';
import { useExperimentRecorder } from './useExperimentRecorder';
import './experiments.css';
import { apiBase } from '../../lib/apiBase';

const base = `${apiBase}/stt-experiments`;
const stateLabels: Record<string, string> = {
  loading: '모델 로딩 중', warming: '워밍업 중', running: '받아쓰기 중',
  completed: '완료', cancelled: '취소됨', failed: '실패',
};
const sample = '안녕하세요. 오늘은 실시간 발표 피드백 서비스를 소개하겠습니다. 어, 이 서비스는 음성과 시선을 분석합니다. 음, FastAPI와 WebSocket을 사용해서 분석 결과를 전달합니다. 그러니까 사용자가 발표를 연습하면서 자신의 습관을 확인할 수 있습니다. 감사합니다.';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message ?? `요청 실패 (${response.status})`);
  return body as T;
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function metric(value: number | null | undefined, unit = '', digits = 2) {
  return value == null ? '미측정' : `${value.toFixed(digits)}${unit}`;
}

function ResultCard({ result }: { result: ModelResult }) {
  const counts = Object.entries(result.metrics?.filler_counts ?? {});
  return <article className="experiment-result">
    <div className="experiment-result-heading"><h3>{result.label}</h3>
      <span className={`experiment-badge ${result.state}`}>{stateLabels[result.state] ?? result.state}</span></div>
    {result.error && <p className="error-banner" role="alert">{result.error}</p>}
    <p className="experiment-transcript">{result.transcript || (result.state === 'completed'
      ? '인식된 문장 없음 — 무음 차단 여부와 청크별 결과를 확인하세요.' : '실제 모델 결과를 기다리고 있습니다.')}</p>
    <dl className="experiment-metrics">
      <div><dt>문자 오류율 CER ↓</dt><dd>{metric(result.metrics?.cer == null ? null : result.metrics.cer * 100, '%')}</dd></div>
      <div><dt>RTF ↓ · 추론/음성 길이</dt><dd>{metric(result.metrics?.rtf, '', 3)}</dd></div>
      <div><dt>청크 처리 P95 ↓</dt><dd>{metric(result.metrics?.p95_chunk_ms, ' ms', 0)}</dd></div>
      <div><dt>백엔드+자식 최대 RSS</dt><dd>{metric(result.memory?.process_tree_peak_rss_mb, ' MiB', 0)}</dd></div>
    </dl>
    <p className="experiment-muted">로딩 {metric(result.load_ms, ' ms', 0)} · 워밍업 {metric(result.warmup_ms, ' ms', 0)} ·
      전사 기반 필러워드 {counts.length ? counts.map(([word, count]) => `${word} ${count}회`).join(' / ') : '없음 또는 미측정'}</p>
    {result.chunks.length > 0 && <details><summary>청크별 받아쓰기 · {result.chunks.length}개</summary>
      <ol className="experiment-chunks">{result.chunks.map(chunk => <li key={chunk.index}>
        <span>{chunk.start_seconds.toFixed(1)}–{(chunk.start_seconds + chunk.duration_seconds).toFixed(1)}초 · {chunk.latency_ms.toFixed(0)} ms
          {chunk.skipped ? ' · RMS/VAD 차단' : ''}</span>
        <p>{chunk.text || '(전사 없음)'}</p>
      </li>)}</ol>
    </details>}
  </article>;
}

export function ExperimentPage({ onActivityChange }: {onActivityChange?: (busy: boolean) => void}) {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selected, setSelected] = useState<string[]>([
    'service_qwen', 'qwen_q8', 'whisper_small_int8', 'whisper_base_int8', 'zipformer_int8',
  ]);
  const [audio, setAudio] = useState<Blob | null>(null);
  const [audioName, setAudioName] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [reference, setReference] = useState('');
  const [warmup, setWarmup] = useState(true);
  const [chunkSeconds, setChunkSeconds] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<ExperimentJob | null>(null);
  const [jobId, setJobId] = useState(() => sessionStorage.getItem('stt-experiment-job') ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [converting, setConverting] = useState(false);
  const [serverBusy, setServerBusy] = useState(false);
  const [pollFailed, setPollFailed] = useState(false);
  const disposed = useRef(false);
  useEffect(() => { disposed.current = false; return () => { disposed.current = true; }; }, []);

  const acceptAudio = useCallback((blob: Blob) => {
    setAudio(blob); setAudioName('마이크 녹음 · 16kHz mono PCM16'); setError(null);
  }, []);
  const recorder = useExperimentRecorder(acceptAudio);
  const running = submitting || (jobId !== '' && (!job || job.state === 'running'));
  const locked = running || recorder.recording || recorder.starting || converting;
  useEffect(() => { onActivityChange?.(locked); return () => onActivityChange?.(false); }, [locked, onActivityChange]);

  const refresh = useCallback(async () => {
    try {
      const body = await request<{ models: ModelOption[]; busy: boolean }>(`${base}/models`);
      if (disposed.current) return;
      setModels(body.models); setServerBusy(body.busy); setError(null);
    } catch (cause) {
      if (!disposed.current) setError(cause instanceof Error ? cause.message : '백엔드에 연결하지 못했습니다.');
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!audio) return;
    const url = URL.createObjectURL(audio); setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [audio]);

  useEffect(() => {
    if (!jobId || pollFailed) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const body = await request<ExperimentJob>(`${base}/jobs/${jobId}`, { signal: controller.signal });
        if (stopped) return;
        setJob(body);
        if (body.state === 'running') timer = setTimeout(() => { void poll(); }, 750);
        else { setServerBusy(false); void refresh(); }
      } catch (cause) {
        if (!stopped) {
          setError(cause instanceof Error ? cause.message : '결과 조회 실패');
          setPollFailed(true);
        }
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, [jobId, pollFailed, refresh]);

  async function upload(file?: File) {
    if (!file) return;
    setError(null); setConverting(true);
    let context: AudioContext | null = null;
    try {
      if (file.size > 25 * 1024 * 1024) throw new Error('25MB 이하의 60초 이내 음성 파일을 선택하세요.');
      context = new AudioContext();
      const decoded = await context.decodeAudioData(await file.arrayBuffer());
      if (decoded.duration < 0.1 || decoded.duration > 60) throw new Error('음성 길이는 0.1초 이상 60초 이하여야 합니다.');
      const offline = new OfflineAudioContext(1, Math.round(decoded.duration * 16000), 16000);
      const source = offline.createBufferSource(); source.buffer = decoded; source.connect(offline.destination); source.start();
      const mono = await offline.startRendering();
      if (!disposed.current) {
        setAudio(pcmWav([encodePcm16(mono.getChannelData(0))]));
        setAudioName(`${file.name} · 16kHz mono PCM16으로 변환`);
      }
    } catch (cause) {
      if (!disposed.current) setError(cause instanceof Error ? cause.message : '이 음성 형식은 브라우저에서 열 수 없습니다.');
    } finally {
      if (context) await context.close();
      if (!disposed.current) setConverting(false);
    }
  }

  async function run() {
    if (!audio || !selected.length) return;
    setSubmitting(true); setError(null); setPollFailed(false);
    try {
      const form = new FormData(); form.append('audio', audio, 'comparison.wav');
      form.append('models', JSON.stringify(selected)); form.append('reference', reference);
      form.append('warmup', String(warmup)); form.append('chunk_seconds', String(chunkSeconds));
      const body = await request<ExperimentJob>(`${base}/jobs`, { method: 'POST', body: form });
      setJob(body); setJobId(body.id); sessionStorage.setItem('stt-experiment-job', body.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '실험을 시작하지 못했습니다.');
    } finally { setSubmitting(false); }
  }

  async function cancel() {
    try {
      if (jobId) setJob(await request<ExperimentJob>(`${base}/jobs/${jobId}/cancel`, { method: 'POST' }));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '취소 요청 실패'); }
  }

  return <main className="practice-shell experiment-shell">
    <header className="practice-header"><div><p className="eyebrow">CPU STT LAB</p>
      <h1>받아쓰기 비교 실험</h1></div>
      <a className="secondary-button experiment-link" href="#themes" aria-disabled={locked}
        onClick={event => { if (locked) event.preventDefault(); }}>모델 테마 선택</a></header>
    <p className="experiment-intro">한 번 녹음하고, 같은 음성을 다섯 가지 설정으로 비교하세요.
      기존 서비스는 그대로 유지하고 실제 모델의 받아쓰기와 처리 성능만 따로 확인합니다.</p>
    <div className="experiment-notice">CPU 순차 실행 · 기본 2초 비중첩 청크 · 한국어 · 공통 RMS/VAD · 정답 대본은 평가에만 사용</div>
    {(error || recorder.error) && <p className="error-banner" role="alert">{error ?? recorder.error}</p>}
    <section className="experiment-section" aria-labelledby="capture-title">
      <div className="experiment-section-heading"><h2 id="capture-title">01 · 비교할 음성 준비</h2><span>최대 60초</span></div>
      <p>20~40초 정도 읽고, 중간에 2~3초 쉬거나 ‘어’, ‘음’을 넣어 보세요. 모든 모델에 동일한 파일이 전달됩니다.</p>
      <div className="experiment-actions">
        <button className="primary-button" disabled={locked} onClick={() => { void recorder.start(); }}>
          {recorder.starting ? '마이크 준비 중…' : '마이크 녹음 시작'}</button>
        <button className="secondary-button" disabled={!recorder.recording} onClick={() => { void recorder.stop(); }}>녹음 종료</button>
        <label className={`secondary-button experiment-upload ${locked ? 'disabled' : ''}`}>음성 파일 선택
          <input aria-label="비교할 음성 파일" type="file" accept="audio/*,.wav,.mp3,.m4a" disabled={locked}
            onChange={event => { void upload(event.target.files?.[0]); event.target.value = ''; }} /></label>
        <span role="status">{recorder.recording ? `● 녹음 중 ${recorder.seconds.toFixed(1)}초` : converting ? '음성 변환 중…' : audioName || '아직 음성이 없습니다.'}</span>
      </div>
      {recorder.recording && <meter aria-label="마이크 입력 레벨" min="0" max="1" value={recorder.level} />}
      {audioUrl && <div className="experiment-audio"><audio controls src={audioUrl} />
        <button className="secondary-button" disabled={locked} onClick={() => audio && save(audio, 'stt-comparison.wav')}>같은 음성 WAV 저장</button></div>}
      <details><summary>테스트용 예시 대본</summary><p className="experiment-sample">{sample}</p>
        <button className="secondary-button" disabled={locked} onClick={() => setReference(sample)}>정답 입력란에 복사</button>
        <p className="experiment-muted">예시와 다르게 말했으면 정답도 실제 발화대로 수정해야 CER이 유효합니다.</p></details>
    </section>
    <section className="experiment-section" aria-labelledby="settings-title">
      <div className="experiment-section-heading"><h2 id="settings-title">02 · 모델과 평가 조건</h2>
        <button className="secondary-button" disabled={locked} onClick={() => { void refresh(); }}>준비 상태 새로고침</button></div>
      <div className="experiment-models">{models.map(model => <label key={model.id} className="experiment-model">
        <input type="checkbox" checked={selected.includes(model.id)} disabled={locked}
          onChange={event => setSelected(previous => event.target.checked ? [...previous, model.id] : previous.filter(id => id !== model.id))} />
        <span><strong>{model.label}</strong><small className={model.available ? 'ready' : 'unavailable'}>
          {model.available ? '준비됨' : '준비 필요'} · {model.reason}</small></span>
      </label>)}</div>
      <p className="experiment-muted">준비되지 않은 모델은 실패 사유를 표시하고 다음 모델로 넘어갑니다. 다른 모델로 대체하거나 가짜 전사를 만들지 않습니다.</p>
      <label className="experiment-reference">정답 전사 · 선택 사항
        <textarea rows={4} value={reference} maxLength={10000} disabled={locked}
          placeholder="실제로 말한 내용 그대로 입력하세요. 어·음·반복 표현도 포함하면 좋습니다. 비워 두면 CER은 미측정입니다."
          onChange={event => setReference(event.target.value)} /></label>
      <div className="experiment-actions">
        <label>청크 길이 <select value={chunkSeconds} disabled={locked} onChange={event => setChunkSeconds(Number(event.target.value))}>
          <option value={2}>2초 · 현재 서비스 기준</option><option value={4}>4초 · 경계 영향 비교</option></select></label>
        <label><input type="checkbox" checked={warmup} disabled={locked} onChange={event => setWarmup(event.target.checked)} />
          첫 유효 청크로 워밍업 후 측정</label>
      </div>
      <p className="experiment-muted">Zipformer는 이 실험에서 청크마다 상태를 초기화합니다. 지속 스트리밍 최적 성능을 측정하는 모드는 아닙니다.</p>
      <p className="experiment-muted">실행 엔진·스레드 설정도 함께 비교합니다. Qwen Q8의 차이를 양자화만의 효과로 해석하면 안 됩니다.
        기존 서비스 모델은 이미 로딩된 상태이며 RSS에는 기존 시선·음성 모델도 포함됩니다.</p>
      <div className="experiment-actions">
        <button className="primary-button" disabled={locked || !audio || !selected.length || !models.length || serverBusy}
          onClick={() => { void run(); }}>{submitting ? '실험 요청 중…' : '선택 모델 순차 비교 시작'}</button>
        {running && <button className="secondary-button" disabled={job?.cancel_requested} onClick={() => { void cancel(); }}>
          {job?.cancel_requested ? '현재 작업 종료 후 취소 중…' : '비교 취소'}</button>}
        {serverBusy && !running && <span>다른 실험 또는 연습 세션이 실행 중입니다. 종료 후 상태를 새로고침하세요.</span>}
      </div>
    </section>
    {(job || running) && <section className="experiment-section" aria-labelledby="results-title">
      <div className="experiment-section-heading"><h2 id="results-title">03 · 비교 결과</h2><span role="status">
        {job ? stateLabels[job.state] ?? job.state : '실험 복원 중…'}
        {job?.progress && ` · ${job.progress.chunk}/${job.progress.total} 청크`}</span></div>
      {pollFailed && <div className="experiment-actions">
        <button className="secondary-button" onClick={() => setPollFailed(false)}>결과 조회 재시도</button>
        <button className="secondary-button" onClick={() => {
          setJobId(''); setJob(null); setPollFailed(false); sessionStorage.removeItem('stt-experiment-job'); void refresh();
        }}>조회 연결 해제</button><span>연결 해제는 서버 작업을 취소하지 않습니다.</span>
      </div>}
      {job && <>
        <p className="experiment-muted">음성 {job.audio_seconds.toFixed(2)}초 · {job.chunk_seconds}초 청크 ·
          워밍업 {job.warmup ? 'ON' : 'OFF'} · SHA-256 {job.audio_sha256.slice(0, 16)}…</p>
        {job.error && <p className="error-banner">{job.error}</p>}
        <div className="experiment-results">{job.results.map(result => <ResultCard key={result.model_id} result={result} />)}</div>
        {job.state !== 'running' && <div className="experiment-actions">
          <button className="secondary-button" onClick={() => save(new Blob([JSON.stringify(job, null, 2)], { type: 'application/json' }), `stt-${job.id}.json`)}>상세 JSON 저장</button>
          <button className="secondary-button" onClick={() => save(new Blob([jobCsv(job)], { type: 'text/csv;charset=utf-8' }), `stt-${job.id}.csv`)}>비교표 CSV 저장</button>
        </div>}
        {job.state !== 'running' && <details><summary>다운로드가 안 되면 결과 텍스트 복사</summary>
          <p className="experiment-muted">아래 내용을 선택해 복사할 수 있습니다. 내장 브라우저에서 파일 저장이 제한될 때 사용하세요.</p>
          <label className="experiment-reference">비교표 CSV 원문<textarea rows={5} readOnly value={jobCsv(job)} /></label>
          <label className="experiment-reference">상세 JSON 원문<textarea rows={5} readOnly value={JSON.stringify(job, null, 2)} /></label>
        </details>}
        <details><summary>측정 조건 및 해석 주의</summary><ul>{job.notes.map(note => <li key={note}>{note}</li>)}</ul>
          <pre>{JSON.stringify(job.environment, null, 2)}</pre></details>
      </>}
    </section>}
    <aside className="experiment-section experiment-muted"><h2>처음 실행할 때</h2>
      <p>실험 전용 패키지와 모델을 준비해야 합니다. 모델은 로컬에 저장하며 실행 중에는 다운로드하지 않습니다.</p>
      <code>.venv\Scripts\python.exe -m scripts.prepare_stt_experiments --llama</code>
      <p>음성과 결과는 서버 메모리에만 보관됩니다. 서버를 재시작하면 사라지므로 필요한 결과는 직접 저장하세요.</p>
      <p>RTF가 1 미만이어도 서비스 전체의 실시간 동작을 보장하지 않습니다. 시선 분석 동시 실행과 전송 지연은 별도 검증 대상입니다.</p>
    </aside>
  </main>;
}
