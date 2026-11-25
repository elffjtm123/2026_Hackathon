import assert from 'node:assert/strict';
import test from 'node:test';
import {formatClock, answerRemainingMs, canReplay, initialInterviewState, interviewReducer, readingRemainingMs,
  remainingQuestions, closeOpenBreaks} from '../src/features/interview/interviewState.ts';

const ev = (event, data, at, serverMs = at) => ({type: 'event', event, data, at, serverMs});
const question = (id, extra = {}) => ({question_id: id, round: 1, index: 1, total: 3, text: `질문 ${id}`,
  reading_ms: 5000, answer_limit_ms: 120000, replay_available: true, ...extra});
const replayRequested = state => interviewReducer(state, {type: 'replay_requested'});
const run = (events, state = initialInterviewState) => events.reduce(interviewReducer, state);

test('a question is visible while it is read, then hidden by the server event', () => {
  let s = run([ev('interview.question', question('q1'), 1000)]);
  assert.equal(s.status, 'asking');
  assert.equal(s.question.text, '질문 q1');
  assert.equal(s.textVisible, true);
  assert.equal(readingRemainingMs(s, 3000), 3000);
  assert.equal(readingRemainingMs(s, 9000), 0, 'the countdown never goes below zero, the server decides when to hide');
  assert.equal(answerRemainingMs(s, 3000), null, 'no answer clock while the question is shown');
  s = interviewReducer(s, ev('interview.question_hidden', {question_id: 'q1'}, 6000));
  assert.equal(s.textVisible, false);
  assert.equal(answerRemainingMs(s, 36000), 120000 - 30000);
  assert.equal(answerRemainingMs(s, 6000 + 999999), 0);
  assert.equal(remainingQuestions(s), 2);
});

test('hiding a question that is not the current one is ignored', () => {
  const s = run([ev('interview.question', question('q1'), 0), ev('interview.question_hidden', {question_id: 'old'}, 10)]);
  assert.equal(s.textVisible, true);
});

test('the speaker starting early hides the question before the reading time ends', () => {
  const s = run([ev('interview.question', question('q1'), 0), ev('interview.question_hidden', {question_id: 'q1'}, 1500)]);
  assert.equal(s.textVisible, false);
  assert.equal(readingRemainingMs(s, 2000), 0);
});

test('replay is available once: requested, shown again with the answer clock stopped, then used up', () => {
  let s = run([ev('interview.question', question('q1'), 0), ev('interview.question_hidden', {question_id: 'q1'}, 5000)]);
  assert.equal(canReplay(s), true);
  s = replayRequested(s);
  assert.equal(canReplay(s), false, 'the button is disabled while the request is on its way');
  s = interviewReducer(s, ev('interview.question', question('q1', {replay_available: false}), 20000));
  assert.equal(s.textVisible, true);
  assert.equal(s.question.index, 1);
  assert.equal(canReplay(s), false);
  assert.equal(answerRemainingMs(s, 25000), 120000 - 15000, 'the 15 s before the replay counted, the replay does not');
  s = interviewReducer(s, ev('interview.question_hidden', {question_id: 'q1'}, 25000));
  assert.equal(answerRemainingMs(s, 35000), 120000 - 15000 - 10000);
  assert.equal(canReplay(s), false);
});

test('a rejected replay re-enables nothing: the button stays off', () => {
  let s = run([ev('interview.question', question('q1'), 0), ev('interview.question_hidden', {question_id: 'q1'}, 5000)]);
  s = replayRequested(s);
  s = interviewReducer(s, ev('interview.replay_rejected', {question_id: 'q1'}, 5100));
  assert.equal(canReplay(s), false);
  assert.equal(s.textVisible, false);
  assert.equal(answerRemainingMs(s, 5100), 120000 - 100);
});

test('the replay button is off while the text is on screen, and when the server says it is used', () => {
  assert.equal(canReplay(run([ev('interview.question', question('q1'), 0)])), false);
  const used = run([ev('interview.question', question('q1', {replay_available: false}), 0), ev('interview.question_hidden', {question_id: 'q1'}, 5000)]);
  assert.equal(canReplay(used), false);
  assert.equal(canReplay(initialInterviewState), false);
});

test('advancing shows a short transition, and the next question resets the replay and the clocks', () => {
  let s = run([ev('interview.question', question('q1'), 0), ev('interview.question_hidden', {question_id: 'q1'}, 5000),
    ev('interview.advanced', {question_id: 'q1', reason: 'silence'}, 30000)]);
  assert.equal(s.status, 'advancing');
  assert.equal(s.advanceReason, 'silence');
  s = interviewReducer(s, ev('interview.question', question('q2', {index: 2}), 30500));
  assert.equal(s.status, 'asking');
  assert.equal(s.question.id, 'q2');
  assert.equal(s.advanceReason, null);
  assert.equal(canReplay(s), false);
  s = interviewReducer(s, ev('interview.question_hidden', {question_id: 'q2'}, 35500));
  assert.equal(canReplay(s), true);
  assert.equal(remainingQuestions(s), 1);
});

test('the round break shows its stage, the suspended event marks the break interval, resume closes it', () => {
  let s = run([ev('interview.question', question('q3', {index: 3}), 0), ev('interview.advanced', {question_id: 'q3', reason: 'stopped'}, 1000),
    ev('interview.round_break', {stage: 'suspending'}, 1100), ev('session.suspended', {}, 1500, 61500)]);
  assert.equal(s.status, 'break');
  assert.equal(s.breakStage, 'suspending');
  assert.equal(s.suspended, true);
  assert.deepEqual(s.breaks, [{startMs: 61500, endMs: null}]);
  s = interviewReducer(s, ev('interview.round_break', {stage: 'generating'}, 2000));
  assert.equal(s.breakStage, 'generating');
  s = interviewReducer(s, ev('interview.round_break', {stage: 'resuming', follow_up_count: 2}, 3000));
  assert.equal(s.breakStage, 'resuming');
  assert.equal(s.followUpCount, 2);
  s = interviewReducer(s, ev('session.resumed', {audio_origin_ms: 1200, break_ms: 9000}, 4000, 70000));
  assert.equal(s.suspended, false);
  assert.deepEqual(s.breaks, [{startMs: 61000, endMs: 70000}], 'the interval comes from the server break length');
  s = interviewReducer(s, ev('interview.question', question('f1', {round: 2, index: 1, total: 2}), 4100));
  assert.equal(s.status, 'asking');
  assert.equal(s.breakStage, null);
  assert.equal(s.question.round, 2);
  assert.equal(remainingQuestions(s), 1);
});

test('a skipped break and the finished event end the interview', () => {
  let s = run([ev('interview.round_break', {stage: 'skipped', follow_up_count: 0}, 0)]);
  assert.equal(s.breakStage, 'skipped');
  s = interviewReducer(s, ev('interview.finished', {}, 10));
  assert.equal(s.status, 'finished');
  assert.equal(s.question, null);
});

test('stopping during the break leaves the interval open until the session end closes it', () => {
  const s = run([ev('session.suspended', {}, 0, 5000)]);
  assert.deepEqual(s.breaks, [{startMs: 5000, endMs: null}]);
  assert.deepEqual(closeOpenBreaks(s.breaks, 9000), [{startMs: 5000, endMs: 9000}]);
  const closed = interviewReducer(s, ev('session.resumed', {}, 1, 8000));
  assert.deepEqual(closeOpenBreaks(closed.breaks, 9500), [{startMs: 5000, endMs: 8000}], 'a closed break keeps its end');
});

test('malformed events are ignored and reset returns to the start', () => {
  const s = run([ev('interview.question', {question_id: 'q1'}, 0), ev('interview.advanced', {}, 1), ev('unknown.event', {}, 2)]);
  assert.deepEqual(s, initialInterviewState);
  const used = run([ev('interview.question', question('q1'), 0)]);
  assert.deepEqual(interviewReducer(used, {type: 'reset'}), initialInterviewState);
});

test('the countdowns never exceed their limits even when the local clock lags the event', () => {
  const s = run([ev('interview.question', question('q1', {answer_limit_ms: 90000, reading_ms: 5000}), 1000),
    ev('interview.question_hidden', {question_id: 'q1'}, 6000)]);
  assert.equal(answerRemainingMs(s, 5800), 90000, 'now (a 250 ms tick) is older than the hide event');
  assert.equal(formatClock(answerRemainingMs(s, 5800)), '1:30');
  const early = run([ev('interview.question', question('q1'), 1000)]);
  assert.equal(readingRemainingMs(early, 900), 5000);
});

test('a connection lost after the first question loses the plan', async () => {
  const {interviewScreen} = await import('../src/features/interview/interviewState.ts');
  const lost = {locked: false, completed: false, hasSummary: true, asked: true, dismissed: false};
  assert.deepEqual(interviewScreen(lost), {report: false, showSetup: true, planSpent: false, planLost: true});
  assert.equal(interviewScreen({...lost, asked: false}).planLost, false, 'before the first question the plan is given back');
  assert.equal(interviewScreen({...lost, completed: true}).planLost, false);
  assert.equal(interviewScreen({...lost, locked: true}).planLost, false);
});

test('the screen returns to the question list when the session ended before its first question', async () => {
  const {interviewScreen} = await import('../src/features/interview/interviewState.ts');
  const base = {locked: false, completed: true, hasSummary: true, asked: false, dismissed: false};
  assert.deepEqual(interviewScreen(base), {report: false, showSetup: true, planSpent: false, planLost: false}, 'start cancelled or connection lost');
  assert.deepEqual(interviewScreen({...base, asked: true}), {report: true, showSetup: false, planSpent: true, planLost: false}, 'the plan is spent while the report shows');
  assert.deepEqual(interviewScreen({...base, asked: true, dismissed: true}), {report: true, showSetup: true, planSpent: false, planLost: false});
  assert.equal(interviewScreen({...base, asked: true, locked: true}).showSetup, false);
  assert.equal(interviewScreen({...base, completed: false, hasSummary: false}).showSetup, true);
});

test('a later presentation session or a failed end never reads as a lost interview', async () => {
  const {interviewScreen} = await import('../src/features/interview/interviewState.ts');
  const finished = {locked: false, completed: true, hasSummary: true, asked: true, dismissed: false, interview: true};
  assert.equal(interviewScreen(finished).planLost, false, 'a normal end');
  // The user then switches to 발표 and starts or cancels a presentation: completed is false, the run still says asked.
  assert.equal(interviewScreen({...finished, completed: false, interview: false}).planLost, false);
  assert.equal(interviewScreen({...finished, completed: false, hasSummary: false, interview: false}).planLost, false);
  // The end failed (timeout, socket died): the interview's own session has no summary, so the plan is lost.
  assert.equal(interviewScreen({...finished, hasSummary: false}).planLost, true);
  assert.equal(interviewScreen({...finished, completed: false}).planLost, true);
});
