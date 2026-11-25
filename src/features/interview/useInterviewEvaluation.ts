import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelEvaluation, requestEvaluation } from './api.ts';
import { runEvaluation } from './evaluationRun.ts';
import type { EvaluationProgress, InterviewEvaluation } from './types.ts';

export type EvaluationStatus = 'idle' | 'running' | 'complete' | 'failed' | 'cancelled';
export type EvaluationState = {status: EvaluationStatus; progress: EvaluationProgress | null;
  evaluation: InterviewEvaluation | null; error: string | null};
const idle: EvaluationState = {status: 'idle', progress: null, evaluation: null, error: null};
const BUSY_RETRIES = 6;
const BUSY_DELAY_MS = 700;
const wait = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
  const timer = setTimeout(resolve, ms);
  signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, {once: true});
});

// Evaluation of a finished interview (the retry and result rules are in evaluationRun.ts).
export function useInterviewEvaluation() {
  const [state, setState] = useState<EvaluationState>(idle);
  const controller = useRef<AbortController | null>(null);
  const current = useRef<string | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const start = useCallback(async (interviewId: string) => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine; current.current = interviewId;
    setState({status: 'running', progress: null, evaluation: null, error: null});
    const outcome = await runEvaluation(interviewId, {signal: mine.signal, retries: BUSY_RETRIES,
      request: () => requestEvaluation(interviewId, {signal: mine.signal,
        onProgress: progress => { if (!mine.signal.aborted) setState(s => ({...s, progress})); }}),
      wait: () => wait(BUSY_DELAY_MS, mine.signal), onProgress() {}});
    if (outcome && !mine.signal.aborted) setState({...outcome, progress: null});
  }, []);

  // Stops the model on the server first (the call returns when it is gone), then drops the stream.
  const cancel = useCallback(async () => {
    const id = current.current, mine = controller.current;
    if (!id || !mine) return;
    try { await cancelEvaluation(id); } catch { /* the stream below ends it anyway */ }
    mine.abort();
    setState(s => s.status === 'running' ? {status: 'cancelled', progress: null, evaluation: null, error: '평가를 중단했습니다.'} : s);
  }, []);

  const reset = useCallback(() => { controller.current?.abort(); controller.current = null; current.current = null; setState(idle); }, []);
  return {state, start, cancel, reset};
}
