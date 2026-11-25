import assert from 'node:assert/strict';
import test from 'node:test';
import {InterviewApiError} from '../src/features/interview/api.ts';
import {createOnceGate, resultSaveKey, runEvaluation, shouldAutoEvaluate, storedResultFor} from '../src/features/interview/evaluationRun.ts';
import {loadResults, saveResult} from '../src/features/interview/storage.ts';
import {isFatalServerError} from '../src/features/practice/sessionLifecycle.ts';

const memory = () => { const d = new Map(); return {getItem: k => d.has(k) ? d.get(k) : null, setItem: (k, v) => d.set(k, v), removeItem: k => d.delete(k)}; };
const evaluation = {items: [], overall_score: 11, summary: {strengths: [], improvements: [], next_goals: []}, model: 'm', elapsed_seconds: 1, warnings: []};
const busy = () => new InterviewApiError('PRACTICE_ACTIVE', 'busy', 409);

test('the once gate lets a key through once until it is reset (session.end after interview.finished)', () => {
  const gate = createOnceGate();
  assert.equal(gate.take('finished'), true);
  assert.equal(gate.take('finished'), false);
  assert.equal(gate.take('other'), true);
  gate.reset();
  assert.equal(gate.take('finished'), true);
});

test('evaluation starts once per finished session, and only when there are answers and a plan', () => {
  const gate = createOnceGate();
  const base = {sessionId: 's1', hasPlan: true, itemCount: 2};
  assert.equal(shouldAutoEvaluate(gate, {...base, sessionId: null}), false);
  assert.equal(shouldAutoEvaluate(gate, {...base, hasPlan: false}), false);
  assert.equal(shouldAutoEvaluate(gate, {...base, itemCount: 0}), false);
  assert.equal(shouldAutoEvaluate(gate, base), true);
  assert.equal(shouldAutoEvaluate(gate, base), false, 'a re-render does not start it again');
  assert.equal(shouldAutoEvaluate(gate, {...base, sessionId: 's2'}), true);
});

test('a busy server (practice session still closing) is retried, then the evaluation completes', async () => {
  let calls = 0, waits = 0;
  const outcome = await runEvaluation('iv', {signal: new AbortController().signal,
    request: async () => { if (++calls < 3) throw busy(); return evaluation; }, wait: async () => { waits++; }, retries: 6, onProgress() {}});
  assert.deepEqual(outcome, {status: 'complete', evaluation, error: null});
  assert.equal(calls, 3);
  assert.equal(waits, 2);
});

test('it gives up after the retries, and other errors fail at once', async () => {
  let calls = 0;
  const failed = await runEvaluation('iv', {signal: new AbortController().signal, request: async () => { calls++; throw busy(); },
    wait: async () => {}, retries: 2, onProgress() {}});
  assert.equal(failed.status, 'failed');
  assert.equal(calls, 3);
  const other = await runEvaluation('iv', {signal: new AbortController().signal,
    request: async () => { throw new InterviewApiError('INTERVIEW_EVALUATION_FAILED', '실패'); }, wait: async () => {}, retries: 6, onProgress() {}});
  assert.deepEqual(other, {status: 'failed', evaluation: null, error: '실패'});
  const cancelled = await runEvaluation('iv', {signal: new AbortController().signal,
    request: async () => { throw new InterviewApiError('INTERVIEW_EVALUATION_CANCELLED', '중단'); }, wait: async () => {}, retries: 6, onProgress() {}});
  assert.equal(cancelled.status, 'cancelled');
});

test('an abort during the wait or the request ends the run without a result', async () => {
  const controller = new AbortController();
  let calls = 0;
  const outcome = await runEvaluation('iv', {signal: controller.signal, request: async () => { calls++; throw busy(); },
    wait: async () => { controller.abort(); }, retries: 6, onProgress() {}});
  assert.equal(outcome, null);
  assert.equal(calls, 1);
  const during = new AbortController();
  assert.equal(await runEvaluation('iv', {signal: during.signal, request: async () => { during.abort(); throw new Error('aborted'); },
    wait: async () => {}, retries: 6, onProgress() {}}), null);
});

const plan = {interview_id: 'iv', warnings: [], questions: [
  {id: 'q1', kind: 'document', subtype: 's', text: '역할은', intent: '', source_quote: '근거', rubric_items: ['a'], parent_id: null, bank_id: null, round: 1}]};
const items = [{question_id: 'q1', round: 1, parent_id: null, text: '역할은', shown_ms: 0, answer_started_ms: 1, ended_ms: 2,
  advance_reason: 'silence', replay_used: false, transcript: '제가 구현했습니다'}];
const summary = {durationSeconds: 60, gazeAwayRatio: 0.1, speechPaceWarningCount: 0, averageSyllablesPerMinute: 250, fillerWordCounts: {}, incomplete: false, transcript: 'x'};

test('a failed evaluation is stored as a transcript-only result, and a successful retry replaces it', () => {
  const store = memory();
  const failed = storedResultFor({plan, items, summary, status: 'failed', evaluation: null, date: 'd1'});
  assert.equal(failed.evaluation, null);
  assert.equal(failed.evaluation_status, 'failed');
  saveResult(store, failed);
  assert.notEqual(resultSaveKey(plan, 'failed'), resultSaveKey(plan, 'complete'), 'a retry is saved again');
  saveResult(store, storedResultFor({plan, items, summary, status: 'complete', evaluation, date: 'd2'}));
  const saved = loadResults(store);
  assert.equal(saved.length, 1);
  assert.equal(saved[0].evaluation.overall_score, 11);
  assert.equal(saved[0].items[0].transcript, '제가 구현했습니다');
  assert.equal(saved[0].questions[0].source_quote, '근거');
  assert.equal(storedResultFor({plan, items, summary, status: 'cancelled', evaluation, date: 'd'}).evaluation, null, 'only a complete run keeps the evaluation');
});

test('only calibration timeouts and a failed round break leave the socket open', () => {
  assert.equal(isFatalServerError('CALIBRATION_TIMEOUT'), false);
  assert.equal(isFatalServerError('INTERVIEW_ROUND_BREAK_FAILED'), false);
  assert.equal(isFatalServerError('INTERVIEW_ALREADY_STARTED'), true);
  assert.equal(isFatalServerError('MODEL_UNAVAILABLE_OR_BUSY'), true);
});
