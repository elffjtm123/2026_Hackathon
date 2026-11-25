import assert from 'node:assert/strict';
import test from 'node:test';
import {HISTORY_KEY, RESULTS_KEY, clearResults, deleteResult, excludeCommonIds, loadHistory, loadResults,
  recordInterviewStart, saveResult} from '../src/features/interview/storage.ts';

const memory = (seed = {}, {quota = Infinity} = {}) => {
  const data = new Map(Object.entries(seed));
  return {data, getItem: k => data.has(k) ? data.get(k) : null,
    setItem(k, v) { if (v.length > quota) throw new DOMException('full', 'QuotaExceededError'); data.set(k, v); },
    removeItem: k => data.delete(k)};
};
const entry = (n, ids = [`b${n}`]) => ({interview_id: `i${n}`, date: `2026-11-${String(n).padStart(2, '0')}T09:00:00.000Z`, common_bank_ids: ids});
const result = (n, extra = {}) => ({interview_id: `i${n}`, date: entry(n).date,
  questions: [{id: 'q1', kind: 'common', text: '자기소개', source_quote: null, round: 1, parent_id: null, bank_id: 'b1'}],
  items: [{question_id: 'q1', text: '자기소개', round: 1, parent_id: null, transcript: '답변', advance_reason: 'silence', replay_used: false}],
  evaluation: null, evaluation_status: 'failed', summary: {durationSeconds: 60}, ...extra});

test('history keeps the 10 newest interviews, oldest first, and a repeated interview moves to the end', () => {
  const store = memory();
  for (let n = 1; n <= 12; n++) recordInterviewStart(store, entry(n));
  assert.deepEqual(loadHistory(store).map(e => e.interview_id), ['i3', 'i4', 'i5', 'i6', 'i7', 'i8', 'i9', 'i10', 'i11', 'i12']);
  recordInterviewStart(store, entry(5, ['again']));
  const ids = loadHistory(store).map(e => e.interview_id);
  assert.equal(ids.length, 10);
  assert.equal(ids.at(-1), 'i5');
  assert.deepEqual(loadHistory(store).at(-1).common_bank_ids, ['again']);
});

test('exclude ids come from the 3 most recent interviews, ordered oldest to newest, without repeats', () => {
  const store = memory();
  assert.deepEqual(excludeCommonIds(store), []);
  recordInterviewStart(store, entry(1, ['old']));
  recordInterviewStart(store, entry(2, ['a', 'b']));
  recordInterviewStart(store, entry(3, ['c', 'a']));
  recordInterviewStart(store, entry(4, ['d']));
  assert.deepEqual(excludeCommonIds(store), ['b', 'c', 'a', 'd']);
});

test('exclude ids respect the server limits (50 ids of at most 64 characters)', () => {
  const store = memory();
  recordInterviewStart(store, entry(1, Array.from({length: 40}, (_, i) => `x${i}`)));
  recordInterviewStart(store, entry(2, [...Array.from({length: 30}, (_, i) => `y${i}`), 'z'.repeat(65)]));
  const ids = excludeCommonIds(store);
  assert.equal(ids.length, 50);
  assert.equal(ids.at(-1), 'y29');
  assert.ok(ids.every(id => id.length <= 64));
});

test('corrupt or malformed stored data reads as empty and never throws', () => {
  for (const bad of ['{not json', '"text"', '{"a":1}', 'null', '[1,"x",{"interview_id":5}]']) {
    const store = memory({[HISTORY_KEY]: bad, [RESULTS_KEY]: bad});
    assert.deepEqual(loadHistory(store), []);
    assert.deepEqual(loadResults(store), []);
    assert.deepEqual(excludeCommonIds(store), []);
    recordInterviewStart(store, entry(1));
    assert.equal(loadHistory(store).length, 1, 'a write replaces the corrupt value');
  }
  const mixed = memory({[HISTORY_KEY]: JSON.stringify([entry(1), {interview_id: 'bad'}, entry(2)])});
  assert.deepEqual(loadHistory(mixed).map(e => e.interview_id), ['i1', 'i2']);
  assert.doesNotThrow(() => loadHistory({getItem() { throw new Error('denied'); }, setItem() {}, removeItem() {}}));
  assert.doesNotThrow(() => recordInterviewStart({getItem: () => null, setItem() { throw new Error('denied'); }, removeItem() {}}, entry(1)));
  assert.deepEqual(loadHistory(null), []);
});

test('results keep the 10 newest first-in-last-out and can be deleted one by one or all', () => {
  const store = memory();
  for (let n = 1; n <= 11; n++) saveResult(store, result(n));
  const ids = loadResults(store).map(r => r.interview_id);
  assert.equal(ids.length, 10);
  assert.equal(ids[0], 'i11', 'newest first');
  assert.ok(!ids.includes('i1'));
  saveResult(store, result(5, {evaluation_status: 'complete'}));
  assert.equal(loadResults(store).filter(r => r.interview_id === 'i5').length, 1);
  assert.equal(loadResults(store)[0].evaluation_status, 'complete');
  deleteResult(store, 'i5');
  assert.ok(!loadResults(store).some(r => r.interview_id === 'i5'));
  clearResults(store);
  assert.deepEqual(loadResults(store), []);
});

test('a full storage drops the oldest results instead of losing the new one', () => {
  const big = n => result(n, {items: [{question_id: 'q1', transcript: 'ㄱ'.repeat(300), advance_reason: 'silence', replay_used: false}]});
  const store = memory({}, {quota: 1500});
  for (let n = 1; n <= 6; n++) assert.equal(saveResult(store, big(n)), true);
  const ids = loadResults(store).map(r => r.interview_id);
  assert.equal(ids[0], 'i6');
  assert.ok(ids.length < 6);
  assert.equal(saveResult(memory({}, {quota: 10}), big(1)), false);
});

test('a result never carries the document text, only the fields it declares', () => {
  const store = memory();
  saveResult(store, {...result(1), documents: [{kind: 'resume', text: '서류 전문'}], document_text: '서류 전문'});
  const raw = store.data.get(RESULTS_KEY);
  assert.doesNotMatch(raw, /서류 전문/);
  assert.doesNotMatch(raw, /documents|document_text/);
});
