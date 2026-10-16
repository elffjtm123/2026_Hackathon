import {scriptSentences, summaryHints, type ScriptSummaryResult, type SummaryProgress} from './scriptTools';

export async function readSummaryStream(response: Response, script: string,
  onProgress: (progress: SummaryProgress) => void): Promise<ScriptSummaryResult> {
  if (!response.ok) {
    const result = await response.json();
    throw new Error(result.error?.message ?? '요약 요청에 실패했습니다. 다시 시도하세요.');
  }
  if (!response.body || !response.headers.get('content-type')?.includes('application/x-ndjson')) {
    throw new Error('요약 진행 응답을 확인할 수 없습니다.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', {fatal:true});
  const total = scriptSentences(script).length;
  let buffer = '', completed = 0, failed = 0, stage = 0, frames = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      buffer += decoder.decode(value, {stream:!done});
      if (buffer.length > 1048576) throw new Error('요약 응답이 너무 큽니다.');
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
        if (!line.trim()) continue;
        if (++frames > 512) throw new Error('요약 진행 응답이 너무 많습니다.');
        const event = JSON.parse(line);
        if (event.event === 'error') throw new Error(event.data?.message ?? '요약에 실패했습니다.');
        if (event.event === 'progress') {
          const p = event.data as SummaryProgress;
          const nextStage = ['preparing','generating','cleaning'].indexOf(p?.stage);
          if (nextStage < stage || nextStage < 0 || p.total_sentences !== total
              || !Number.isInteger(p.completed_sentences) || p.completed_sentences < completed
              || p.completed_sentences > total || !Number.isInteger(p.failed_sentences)
              || p.failed_sentences < failed || p.failed_sentences > p.completed_sentences) {
            throw new Error('요약 진행 정보가 올바르지 않습니다.');
          }
          completed = p.completed_sentences; failed = p.failed_sentences; stage = nextStage;
          onProgress(p);
        } else if (event.event === 'complete') {
          summaryHints(script, event.data);
          if (!Number.isFinite(event.data.elapsed_seconds) || event.data.elapsed_seconds < 0
              || typeof event.data.model !== 'string') throw new Error('요약 응답이 올바르지 않습니다.');
          return event.data;
        } else throw new Error('알 수 없는 요약 응답입니다.');
      }
      if (done) throw new Error('요약 완료 전에 연결이 종료됐습니다. 다시 시도하세요.');
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function requestScriptSummary(script: string, signal: AbortSignal,
  onProgress: (progress: SummaryProgress) => void = () => {}): Promise<ScriptSummaryResult> {
  const url = new URL((import.meta.env?.VITE_FEEDBACK_WS_URL as string | undefined)
    ?? 'ws://127.0.0.1:8000/api/v1/ws/practice-demo');
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = url.pathname.replace(/\/ws\/.*$/, '/scripts/summarize');
  url.search = ''; url.hash = '';
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, {once:true});
  if (signal.aborted) abort();
  const timeout = setTimeout(abort, 610000);
  try {
    const response = await fetch(url, {method:'POST', signal:controller.signal,
      headers:{'Content-Type':'application/json','Accept':'application/x-ndjson'}, body:JSON.stringify({script})});
    return await readSummaryStream(response, script, onProgress);
  } finally {
    clearTimeout(timeout); signal.removeEventListener('abort', abort);
  }
}
