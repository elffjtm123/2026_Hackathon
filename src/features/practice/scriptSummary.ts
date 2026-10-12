import {summaryHints, type ScriptSummaryResult} from './scriptTools';

export async function requestScriptSummary(script: string, signal: AbortSignal): Promise<ScriptSummaryResult> {
  const url = new URL((import.meta.env?.VITE_FEEDBACK_WS_URL as string | undefined)
    ?? 'ws://127.0.0.1:8000/api/v1/ws/practice-demo');
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = url.pathname.replace(/\/ws\/.*$/, '/scripts/summarize');
  url.search = ''; url.hash = '';
  const response = await fetch(url, {method:'POST', signal,
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({script})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message ?? '요약 요청에 실패했습니다. 다시 시도하세요.');
  summaryHints(script, result);
  if (!Number.isFinite(result.elapsed_seconds) || result.elapsed_seconds < 0) {
    throw new Error('요약 응답이 올바르지 않습니다.');
  }
  return result;
}
