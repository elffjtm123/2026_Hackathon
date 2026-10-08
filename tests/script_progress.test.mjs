import assert from 'node:assert/strict';
import test from 'node:test';
import {feedbackForUi} from '../src/lib/realtimeProtocol.ts';
import {reduceFeedback, emptyFeedbackState} from '../src/features/practice/feedbackState.ts';

test('대본 진행 이벤트를 화면으로 전달하고 확정 위치를 유지한다', () => {
  const event = {event:'script.progress', session_id:'s', timestamp_ms:1000,
    data:{alignment_status:'matched',current_token_index:3,current_sentence_index:1,
      progress_ratio:0.8,expected_progress_ratio:0.5,pace_status:'on_time'}};
  const feedback = feedbackForUi(event);
  assert.equal(feedback.source, 'script_sync');
  assert.equal(feedback.scriptProgress.current_token_index, 3);
  assert.equal(reduceFeedback(emptyFeedbackState, feedback).scriptProgress.progress_ratio, 0.8);
});
