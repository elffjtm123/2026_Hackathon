import assert from 'node:assert/strict';
import test from 'node:test';
import {feedbackForUi, completionForUi} from '../src/lib/realtimeProtocol.ts';
import {reduceFeedback, emptyFeedbackState} from '../src/features/practice/feedbackState.ts';

function event(metrics, transcript='음 안녕하세요') {
  return {event:'feedback',version:2,session_id:'one',sequence:1,timestamp_ms:0,
    module:'speech_rate',level:'info',data:{source:'speech_rate',level:'info',message:'분석 중',
      transcript,metrics}};
}

test('server unknown pace is preserved even when the numerical rate is high', () => {
  const result = feedbackForUi(event({pace:'unknown',syllables_per_minute:600,
    utterance_id:'u1',revision:1,transcript_snapshot:'네 네',filler_counts_total:{음:2},
    filler_words:[{word:'음',count:1}],warning_episode_count:3}));
  assert.equal(result.speech.pace,'unknown');
  assert.equal(result.speech.syllablesPerSecond,undefined);
  assert.equal(result.transcriptSnapshot,'네 네');
  assert.equal(result.utteranceId,'u1');
  assert.deepEqual(result.filler.counts,{음:2});
  assert.equal(result.speech.warningEpisodeCount,3);
});

test('same final ID is ignored but identical text from a new ID is accepted', () => {
  const first = feedbackForUi(event({pace:'normal',utterance_id:'u1',revision:1}));
  const state = reduceFeedback(emptyFeedbackState,first,100);
  const replay = {...first,message:'replay'};
  assert.equal(reduceFeedback(state,replay,200),state);
  const next = {...first,utteranceId:'u2'};
  assert.equal(reduceFeedback(state,next,300).speech,next);
});

test('completion uses the server warning episode count', () => {
  assert.equal(completionForUi({incomplete:false,speech_rate_metrics:{warning_episode_count:2}})
    .speech.warningEpisodeCount,2);
});

test('silence waiting does not mean zero observed fillers', () => {
  const feedback = feedbackForUi(event({pace:'unknown',filler_status:'unavailable',filler_counts_total:{}}, undefined));
  assert.equal(feedback.filler.totalCount,null);
  assert.equal(feedback.filler.counts,null);
  assert.equal(feedback.filler.status,'unavailable');
});

test('speech panel shows server cumulative filler counts and Korean pace label', async () => {
  const {createServer} = await import('vite');
  const {createElement} = await import('react');
  const {renderToStaticMarkup} = await import('react-dom/server');
  const server = await createServer({configFile:false,esbuild:{jsx:'automatic'},
    server:{middlewareMode:true,hmr:false,ws:false},optimizeDeps:{noDiscovery:true}});
  try {
    const {FeedbackPanel} = await server.ssrLoadModule('/src/features/practice/components/FeedbackPanel.tsx');
    const speech = feedbackForUi(event({pace:'normal',syllables_per_minute:300,
      filler_counts_total:{음:2},filler_words:[{word:'음',count:1}]}));
    const html = renderToStaticMarkup(createElement(FeedbackPanel,{connectionStatus:'connected',
      feedback:{...emptyFeedbackState,speech},socketError:null}));
    assert.match(html,/음 2회/);
    assert.match(html,/설정 범위/);
    assert.doesNotMatch(html,/>normal</);
  } finally {await server.close();}
});

function partialEvent(utterance_id, text, start_ms = 0, end_ms = 1600) {
  return {event:'transcript.partial',version:2,session_id:'one',sequence:1,timestamp_ms:end_ms,
    module:'speech_rate',level:'info',data:{text,utterance_id,start_ms,end_ms}};
}

test('a partial transcript is shown until the final of the same utterance replaces it', () => {
  const partial = feedbackForUi(partialEvent('u1','안녕하세요 오늘은'));
  let state = reduceFeedback(emptyFeedbackState, partial, 100);
  assert.deepEqual(state.partialTranscript, {utteranceId:'u1', text:'안녕하세요 오늘은', startMs:0, endMs:1600});
  // A partial is display-only: it is not the latest speech feedback.
  assert.equal(state.speech, null);
  assert.equal(partial.transcriptSnapshot, undefined);
  state = reduceFeedback(state, feedbackForUi(partialEvent('u1','안녕하세요 오늘은 발표', 0, 3200)), 200);
  assert.equal(state.partialTranscript.text, '안녕하세요 오늘은 발표');
  const final = feedbackForUi(event({pace:'normal',utterance_id:'u1',revision:1}, '안녕하세요 오늘은 발표를'));
  state = reduceFeedback(state, final, 300);
  assert.equal(state.partialTranscript, null);
  assert.equal(state.speech.transcript, '안녕하세요 오늘은 발표를');
  // A late preview of an already finalized utterance never comes back.
  assert.equal(reduceFeedback(state, feedbackForUi(partialEvent('u1','늦은 미리보기')), 400).partialTranscript, null);
});

test('a final of an earlier utterance keeps the newer partial', () => {
  let state = reduceFeedback(emptyFeedbackState, feedbackForUi(partialEvent('u2','다음 문장', 8000, 9600)), 100);
  state = reduceFeedback(state, feedbackForUi(event({pace:'normal',utterance_id:'u1',revision:1})), 200);
  assert.equal(state.partialTranscript.utteranceId, 'u2');
});

test('silence or an empty result after the partial started clears it', () => {
  const partial = reduceFeedback(emptyFeedbackState, feedbackForUi(partialEvent('u3','말하던', 5000, 6600)), 100);
  const waiting = {...feedbackForUi(event({pace:'unknown',filler_status:'unavailable'}, null)), timestamp:9000};
  assert.equal(reduceFeedback(partial, waiting, 200).partialTranscript, null);
  const older = {...waiting, timestamp:1000};
  assert.equal(reduceFeedback(partial, older, 200).partialTranscript.utteranceId, 'u3');
});
