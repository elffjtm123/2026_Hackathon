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
