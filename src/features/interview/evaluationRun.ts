import { InterviewApiError } from './api.ts';
import type { StoredResult, EvaluationStatus as StoredStatus } from './storage.ts';
import type { EvaluationProgress, InterviewEvaluation, InterviewItem, InterviewPlan } from './types.ts';

// Pure pieces of the post-interview flow, kept out of the hooks so they can be tested.

// Lets a key through once until reset: ending the session on `interview.finished`, starting the
// evaluation of a session, saving a result.
export function createOnceGate() {
  const seen = new Set<string>();
  return { take: (key: string) => !seen.has(key) && !!seen.add(key), reset: () => seen.clear() };
}

export function shouldAutoEvaluate(gate: ReturnType<typeof createOnceGate>,
    input: { sessionId: string | null; hasPlan: boolean; itemCount: number }): boolean {
  return !!input.sessionId && input.hasPlan && input.itemCount > 0 && gate.take(input.sessionId);
}

export type EvaluationOutcome =
  | { status: 'complete'; evaluation: InterviewEvaluation; error: null }
  | { status: 'failed' | 'cancelled'; evaluation: null; error: string };

type RunOptions = {
  signal: AbortSignal;
  request: () => Promise<InterviewEvaluation>;
  wait: () => Promise<void>;
  retries: number;
  onProgress: (progress: EvaluationProgress) => void;
};

// Runs one evaluation. The server may still be closing the practice session right after
// `session.completed`, so a "practice active" answer is retried. Null means it was aborted.
export async function runEvaluation(_interviewId: string, { signal, request, wait, retries }: RunOptions): Promise<EvaluationOutcome | null> {
  for (let attempt = 0; ; attempt++) {
    try {
      const evaluation = await request();
      return signal.aborted ? null : { status: 'complete', evaluation, error: null };
    } catch (reason) {
      if (signal.aborted) return null;
      if (reason instanceof InterviewApiError && reason.code === 'PRACTICE_ACTIVE' && attempt < retries) {
        await wait();
        if (signal.aborted) return null;
        continue;
      }
      const cancelled = reason instanceof InterviewApiError && reason.code === 'INTERVIEW_EVALUATION_CANCELLED';
      return { status: cancelled ? 'cancelled' : 'failed', evaluation: null,
        error: reason instanceof Error ? reason.message : '평가하지 못했습니다.' };
    }
  }
}

export const resultSaveKey = (plan: Pick<InterviewPlan, 'interview_id'>, status: string) => `${plan.interview_id}:${status}`;

// The record kept in the browser: the evaluation only when it finished, the transcripts always.
export function storedResultFor({ plan, items, summary, status, evaluation, date }: {
  plan: InterviewPlan; items: InterviewItem[]; status: StoredStatus; evaluation: InterviewEvaluation | null; date: string;
  summary: { durationSeconds: number; gazeAwayRatio: number | null; speechPaceWarningCount: number | null;
    averageSyllablesPerMinute: number | null; fillerWordCounts: Record<string, number> | null; incomplete: boolean };
}): StoredResult {
  return {
    interview_id: plan.interview_id, date,
    questions: plan.questions.map(q => ({ id: q.id, kind: q.kind, text: q.text, source_quote: q.source_quote,
      round: q.round, parent_id: q.parent_id, bank_id: q.bank_id })),
    items: items.map(i => ({ question_id: i.question_id, text: i.text, round: i.round, parent_id: i.parent_id,
      transcript: i.transcript, advance_reason: i.advance_reason, replay_used: i.replay_used })),
    evaluation: status === 'complete' ? evaluation : null, evaluation_status: status,
    summary: { durationSeconds: summary.durationSeconds, gazeAwayRatio: summary.gazeAwayRatio,
      speechPaceWarningCount: summary.speechPaceWarningCount, averageSyllablesPerMinute: summary.averageSyllablesPerMinute,
      fillerWordCounts: summary.fillerWordCounts, incomplete: summary.incomplete },
  };
}
