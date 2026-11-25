import type {AdvanceReason, InterviewEvaluation, PlannedQuestion} from './types.ts';

// Browser storage of past interviews (design 6.1). Document text is never stored; a result holds
// the questions (with their evidence sentence), the transcripts and the evaluation.
export const HISTORY_KEY = 'interview.history.v1';
export const RESULTS_KEY = 'interview.results.v1';
export const MAX_ENTRIES = 10;
const EXCLUDE_RECENT = 3;
const MAX_EXCLUDE_IDS = 50;  // the plan request accepts at most 50 ids of at most 64 characters
const MAX_ID_LENGTH = 64;

export type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export type HistoryEntry = {interview_id: string; date: string; common_bank_ids: string[]};
export type StoredQuestion = Pick<PlannedQuestion, 'id' | 'kind' | 'text' | 'source_quote' | 'round' | 'parent_id' | 'bank_id'>;
export type StoredItem = {question_id: string; text: string; round: number; parent_id: string | null; transcript: string; advance_reason: AdvanceReason; replay_used: boolean};
export type StoredSummary = {durationSeconds: number; gazeAwayRatio: number | null; speechPaceWarningCount: number | null;
  averageSyllablesPerMinute: number | null; fillerWordCounts: Record<string, number> | null; incomplete: boolean};
export type EvaluationStatus = 'complete' | 'failed' | 'cancelled';
export type StoredResult = {interview_id: string; date: string; questions: StoredQuestion[]; items: StoredItem[];
  evaluation: InterviewEvaluation | null; evaluation_status: EvaluationStatus; summary: Partial<StoredSummary> | null};

export function browserStorage(): StorageLike | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function readList<T>(storage: StorageLike | null, key: string, valid: (value: unknown) => value is T): T[] {
  try {
    const parsed = JSON.parse(storage?.getItem(key) ?? 'null');
    return Array.isArray(parsed) ? parsed.filter(valid) : [];
  } catch { return []; }
}
function writeList(storage: StorageLike | null, key: string, list: unknown[]): boolean {
  try { storage?.setItem(key, JSON.stringify(list)); return !!storage; } catch { return false; }
}

const isEntry = (value: unknown): value is HistoryEntry => isObject(value) && typeof value.interview_id === 'string'
  && typeof value.date === 'string' && Array.isArray(value.common_bank_ids)
  && value.common_bank_ids.every(id => typeof id === 'string');

export function loadHistory(storage: StorageLike | null = browserStorage()): HistoryEntry[] {
  return readList(storage, HISTORY_KEY, isEntry).slice(-MAX_ENTRIES);
}

// Oldest first. Recorded when the interview session starts, so questions that were asked count
// even if the evaluation never finishes. Recording the same interview again moves it to the end.
export function recordInterviewStart(storage: StorageLike | null, entry: HistoryEntry): void {
  const kept = loadHistory(storage).filter(e => e.interview_id !== entry.interview_id);
  const clean = {interview_id: entry.interview_id, date: entry.date, common_bank_ids: [...entry.common_bank_ids]};
  writeList(storage, HISTORY_KEY, [...kept, clean].slice(-MAX_ENTRIES));
}

// Bank ids of the 3 most recent interviews, oldest to newest as the planner expects; a repeated id
// counts at its last position.
export function excludeCommonIds(storage: StorageLike | null = browserStorage()): string[] {
  const ids = loadHistory(storage).slice(-EXCLUDE_RECENT).flatMap(e => e.common_bank_ids)
    .filter(id => id.length > 0 && id.length <= MAX_ID_LENGTH);
  const unique = ids.filter((id, index) => ids.lastIndexOf(id) === index);
  return unique.slice(-MAX_EXCLUDE_IDS);
}

const isResult = (value: unknown): value is StoredResult => isObject(value) && typeof value.interview_id === 'string'
  && typeof value.date === 'string' && Array.isArray(value.questions) && Array.isArray(value.items);

// Newest first.
export function loadResults(storage: StorageLike | null = browserStorage()): StoredResult[] {
  return readList(storage, RESULTS_KEY, isResult).slice(0, MAX_ENTRIES);
}

const num = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null;

// Copies only the declared fields, so nothing else a caller holds (document text) can be stored.
function sanitize(result: StoredResult): StoredResult {
  const summary = isObject(result.summary) ? result.summary : null;
  const evaluation = isObject(result.evaluation) && Array.isArray(result.evaluation.items) ? result.evaluation : null;
  return {
    interview_id: result.interview_id, date: result.date,
    questions: result.questions.map(q => ({id: q.id, kind: q.kind, text: q.text, source_quote: q.source_quote ?? null,
      round: q.round, parent_id: q.parent_id ?? null, bank_id: q.bank_id ?? null})),
    items: result.items.map(i => ({question_id: i.question_id, text: i.text ?? '', round: i.round ?? 1, parent_id: i.parent_id ?? null,
      transcript: i.transcript,
      advance_reason: i.advance_reason, replay_used: i.replay_used === true})),
    evaluation, evaluation_status: result.evaluation_status,
    summary: summary && {durationSeconds: num(summary.durationSeconds) ?? 0, gazeAwayRatio: num(summary.gazeAwayRatio),
      speechPaceWarningCount: num(summary.speechPaceWarningCount),
      averageSyllablesPerMinute: num(summary.averageSyllablesPerMinute),
      fillerWordCounts: isObject(summary.fillerWordCounts) ? summary.fillerWordCounts as Record<string, number> : null,
      incomplete: summary.incomplete === true},
  };
}

// Returns false when nothing could be stored. A full storage drops the oldest results first.
export function saveResult(storage: StorageLike | null, result: StoredResult): boolean {
  const next = [sanitize(result), ...loadResults(storage).filter(r => r.interview_id !== result.interview_id)]
    .slice(0, MAX_ENTRIES);
  for (let keep = next.length; keep >= 1; keep--) {
    if (writeList(storage, RESULTS_KEY, next.slice(0, keep))) return true;
  }
  return false;
}

export function deleteResult(storage: StorageLike | null, interviewId: string): void {
  writeList(storage, RESULTS_KEY, loadResults(storage).filter(r => r.interview_id !== interviewId));
}

export function clearResults(storage: StorageLike | null = browserStorage()): void {
  try { storage?.removeItem(RESULTS_KEY); } catch { /* Storage is optional. */ }
}
