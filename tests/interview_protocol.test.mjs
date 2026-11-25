import assert from 'node:assert/strict';
import test from 'node:test';
import {completionForUi, interviewItemsForUi} from '../src/lib/realtimeProtocol.ts';
import {sessionStartData} from '../src/features/practice/sessionLifecycle.ts';

const settings = {karaokeGuideEnabled: true, keywordHintEnabled: false, deliveryEnabled: true};

test('the session start carries the chosen questions in interview mode only', () => {
  const interview = {interview_id: 'iv', question_ids: ['q2', 'q1']};
  assert.deepEqual(sessionStartData('interview', settings, undefined, undefined, interview).interview, interview);
  assert.equal('interview' in sessionStartData('interview', settings, undefined, undefined), false, 'a question-less interview still starts');
  assert.equal('interview' in sessionStartData('presentation', settings, '대본', 60, interview), false);
});

test('the completion report keeps the per-question records and drops malformed ones', () => {
  const items = [
    {question_id: 'q1', round: 1, parent_id: null, text: '자기소개', shown_ms: 100, answer_started_ms: 900, ended_ms: 9000,
      advance_reason: 'silence', replay_used: true, transcript: '답변입니다', utterances: [{text: 'x'}]},
    {question_id: 'f1', round: 2, parent_id: 'q1', text: '추가', shown_ms: 9100, answer_started_ms: null, ended_ms: 9500,
      advance_reason: 'no_response', replay_used: false, transcript: ''},
    {text: 'no id'}, null, 'x',
  ];
  const report = completionForUi({interview_items: items, incomplete: false});
  assert.deepEqual(report.interviewItems.map(i => i.question_id), ['q1', 'f1']);
  assert.equal(report.interviewItems[0].transcript, '답변입니다');
  assert.equal(report.interviewItems[0].replay_used, true);
  assert.equal(report.interviewItems[1].parent_id, 'q1');
  assert.equal(report.interviewItems[1].answer_started_ms, null);
  assert.deepEqual(completionForUi({}).interviewItems, []);
  assert.deepEqual(interviewItemsForUi('nope'), []);
  assert.equal(interviewItemsForUi([{question_id: 'a', text: 't', advance_reason: 'weird'}])[0].advance_reason, 'stopped');
});
