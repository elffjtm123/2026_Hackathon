import { useCallback, useEffect, useRef } from 'react';
import type { PracticeSummary } from '../../lib/realtimeProtocol.ts';
import type { InterviewRunState } from './interviewState.ts';
import { historyEntryFor } from './planSelection.ts';
import { browserStorage, recordInterviewStart, saveResult } from './storage.ts';
import { createOnceGate, resultSaveKey, shouldAutoEvaluate, storedResultFor } from './evaluationRun.ts';
import { useInterviewEvaluation } from './useInterviewEvaluation.ts';
import type { InterviewItem, InterviewPlan } from './types.ts';

type Options = {
  run: InterviewRunState;
  plan: InterviewPlan | null;
  chosenIds: string[];
  // The finished session's summary and records (null while no interview result is on screen).
  summary: PracticeSummary | null;
  items: InterviewItem[];
  // The server says the last question is done: the page ends the session.
  onFinished: () => void;
};

// From the first question to the stored result: the history entry when the questions really
// start, the end of the session on `interview.finished`, the automatic evaluation after the
// session completes, and the result in browser storage when the evaluation settles.
export function useInterviewResult({run, plan, chosenIds, summary, items, onFinished}: Options) {
  const evaluation = useInterviewEvaluation();
  const recorded = useRef<string | null>(null);
  const gates = useRef({evaluate: createOnceGate(), save: createOnceGate(), finish: createOnceGate()});
  const callbacks = useRef({onFinished});
  useEffect(() => { callbacks.current = {onFinished}; }, [onFinished]);

  const resetEvaluation = evaluation.reset;
  const reset = useCallback(() => {
    resetEvaluation();
    recorded.current = null;
    Object.values(gates.current).forEach(gate => gate.reset());
  }, [resetEvaluation]);

  // Written when the first question appears, so the exclusion of asked questions works even when
  // the evaluation later fails.
  useEffect(() => {
    if (run.status !== 'asking' || !plan || recorded.current === plan.interview_id) return;
    recorded.current = plan.interview_id;
    recordInterviewStart(browserStorage(), historyEntryFor(plan, chosenIds, new Date().toISOString()));
  }, [run.status, plan, chosenIds]);

  // The session is ended once, by the page, when the server says the interview is over.
  useEffect(() => {
    if (run.status === 'finished' && gates.current.finish.take('finished')) callbacks.current.onFinished();
  }, [run.status]);

  const sessionId = summary?.sessionId ?? null;
  const startEvaluation = evaluation.start;
  useEffect(() => {
    if (plan && shouldAutoEvaluate(gates.current.evaluate, {sessionId, hasPlan: true, itemCount: items.length}))
      void startEvaluation(plan.interview_id);
  }, [sessionId, plan, items, startEvaluation]);

  // Stored with the evaluation when it finished, transcript-only when it failed or was cancelled.
  // A retry that succeeds replaces the transcript-only entry.
  const { status, evaluation: result } = evaluation.state;
  useEffect(() => {
    if (!summary || !plan || items.length === 0) return;
    if (status !== 'complete' && status !== 'failed' && status !== 'cancelled') return;
    if (!gates.current.save.take(resultSaveKey(plan, status))) return;
    saveResult(browserStorage(), storedResultFor({plan, items, summary, status, evaluation: result, date: new Date().toISOString()}));
  }, [status, result, summary, plan, items]);

  return {evaluation, reset};
}
