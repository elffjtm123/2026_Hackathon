import test from 'node:test';
import assert from 'node:assert/strict';
import * as stateTools from '../src/features/practice/feedbackState.ts';
import {feedbackForUi} from '../src/lib/realtimeProtocol.ts';

function feedback(source='gaze', severity='info') {
  return {type:'feedback',sessionId:'one',timestamp:0,source,severity,
    message:source === 'gaze' ? '보정 기준 근처' : '발화 속도가 빠릅니다',
    gaze:source === 'gaze' ? {status:'center',direction:'center',headDirection:'center',headPose:{yaw:0,pitch:0,roll:0},attentionState:'baseline',faceDetected:true,quality:1,calibrated:true,message:'보정 기준 근처'} : undefined,
    speech:source === 'speech_rate' ? {pace:'fast',message:'발화 속도가 빠릅니다'} : undefined};
}

test('gaze expires after 1.5 seconds using receipt time, including timestamp zero', () => {
  assert.equal(typeof stateTools.selectVisibleFeedback,'function');
  const state = stateTools.reduceFeedback(stateTools.emptyFeedbackState,feedback(),100);
  assert.ok(stateTools.selectVisibleFeedback(state,1600).gaze);
  assert.equal(stateTools.selectVisibleFeedback(state,1601).gaze,null);
  assert.equal(stateTools.selectVisibleFeedback(state,1601).gazeStale,true);
});

test('speech warning is not hidden by newer gaze info', () => {
  assert.equal(typeof stateTools.feedbackMessage,'function');
  let state = stateTools.reduceFeedback(stateTools.emptyFeedbackState,feedback('speech_rate','warning'),100);
  state = stateTools.reduceFeedback(state,feedback(),200);
  assert.match(stateTools.feedbackMessage(state),/발화 속도/);
});

test('v2 baseline and head-only are mapped without camera target or invented confidence', () => {
  const raw = {event:'feedback',version:2,session_id:'one',sequence:1,timestamp_ms:0,module:'gaze',level:'info',
    data:{source:'gaze',level:'info',message:'얼굴 방향만 확인하고 있습니다',metrics:{face_detected:true,head_direction:'right',head_pose:{yaw:20,pitch:0,roll:0},gaze_direction:'unknown',attention_state:'unknown',quality:1,calibrated:true,face_detection_confidence:null,recalibration_required:false}}};
  const result = feedbackForUi(raw);
  assert.equal(result.gaze.headDirection,'right');
  assert.equal(result.gaze.direction,'unknown');
  assert.equal(result.gaze.faceDetectionConfidence,null);
  assert.equal(result.gaze.confidence,undefined);
  raw.data.metrics.attention_state = 'baseline';
  assert.equal(feedbackForUi(raw).gaze.attentionState,'baseline');
});

test('UI uses Korean separated directions, no gaze accuracy percentage, warning priority', async () => {
  const {createServer} = await import('vite');
  const {createElement} = await import('react');
  const {renderToStaticMarkup} = await import('react-dom/server');
  const server = await createServer({configFile:false,esbuild:{jsx:'automatic'},server:{middlewareMode:true,hmr:false,ws:false},optimizeDeps:{noDiscovery:true}});
  try {
    const {FeedbackPanel} = await server.ssrLoadModule('/src/features/practice/components/FeedbackPanel.tsx');
    const {FeedbackOverlay} = await server.ssrLoadModule('/src/features/practice/components/FeedbackOverlay.tsx');
    const state = {...stateTools.emptyFeedbackState,gaze:feedback(),speech:feedback('speech_rate','warning')};
    state.gaze.gaze.confidence = .95;
    const panel = renderToStaticMarkup(createElement(FeedbackPanel,{connectionStatus:'connected',feedback:state,socketError:null}));
    assert.match(panel,/얼굴 방향/);
    assert.match(panel,/보정 기준 근처/);
    assert.doesNotMatch(panel,/신뢰도|95%|카메라를 안정적으로|화면을 자연스럽게/);
    const overlay = renderToStaticMarkup(createElement(FeedbackOverlay,{feedback:state}));
    assert.match(overlay,/발화 속도가 빠릅니다/);
  } finally {await server.close();}
});
