import assert from 'node:assert/strict';
import test from 'node:test';
import {FaceFeatureTracker, blendshapeNames, featurePose, emptyFaceFeatures} from '../src/features/face-features/features.ts';
import {featureSnapshot} from '../src/features/face-features/snapshot.ts';
import {emptyPulse} from '../src/features/pulse/signal.ts';

const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
function detection(blink=.1,jaw=.2) {
  return {faceLandmarks:[Array.from({length:478},(_,i)=>({x:i%2?.3:.7,y:i%3?.25:.75}))],
    faceBlendshapes:[{categories:blendshapeNames.map(categoryName=>({categoryName,
      score:categoryName.startsWith('eyeBlink')?blink:categoryName==='jawOpen'?jaw:.1}))}],
    facialTransformationMatrixes:[{data:identity}]};
}
const add=(tracker,time,result=detection())=>tracker.add(result,time,10000+time,320,240,120);

test('all 52 movement coefficients and timestamped 10-second statistics are available without emotion inference',()=>{
  const tracker=new FaceFeatureTracker(); let result;
  for(let time=0;time<=12000;time+=100) result=add(tracker,time,detection(.1,time<6000?.2:.6));
  assert.equal(result.status,'observed'); assert.equal(Object.keys(result.coefficients).length,52);
  assert.equal(result.timestampMs,22000); assert.equal(result.mediaTimeMs,12000);
  assert.equal(result.window.durationSeconds,10); assert.equal(result.window.validSeconds,10);
  assert.equal(result.window.coverage,1); assert.equal(result.window.observedFps,9.9);
  assert.ok(result.window.std.jawOpen>.15); assert.equal(result.window.change.jawOpen,.4);
  assert.equal(result.window.closedEyeRatio,0); assert.equal('emotion' in result,false);
});

test('observed bilateral close/reopen counts one blink; held closure and a gap never add false blinks',()=>{
  const tracker=new FaceFeatureTracker(); add(tracker,0); add(tracker,100,detection(.8));
  add(tracker,200,detection(.9)); let result=add(tracker,300);
  assert.equal(result.totalBlinks,1);
  for(let time=400;time<=1500;time+=100) result=add(tracker,time,detection(.9));
  result=add(tracker,1600); assert.equal(result.totalBlinks,1);
  add(tracker,1700,detection(.9)); result=add(tracker,2100);
  assert.equal(result.totalBlinks,1); assert.ok(result.window.coverage<1);
});

test('no face, multiple faces, bad lighting and incomplete/nonfinite outputs are missing observations, not zero movement',()=>{
  for(const kind of ['no-face','multiple','dark','missing','nan']) {
    const tracker=new FaceFeatureTracker(); add(tracker,0); add(tracker,100,detection(.9));
    const result=detection();
    if(kind==='no-face') result.faceLandmarks=[];
    if(kind==='multiple') result.faceLandmarks.push(result.faceLandmarks[0]);
    if(kind==='missing') result.faceBlendshapes[0].categories.pop();
    if(kind==='nan') result.faceBlendshapes[0].categories[3].score=NaN;
    const missing=tracker.add(result,200,10200,320,240,kind==='dark'?5:120);
    assert.equal(missing.status,'unavailable',kind); assert.equal(missing.coefficients,null,kind);
    assert.equal(add(tracker,300).totalBlinks,0,kind);
  }
});

test('short gaps and invalid timestamps do not inflate observed time or bridge blink events',()=>{
  const tracker=new FaceFeatureTracker(); add(tracker,0); add(tracker,100,detection(.9));
  add(tracker,50); const result=add(tracker,200);
  assert.equal(result.totalBlinks,0);
  const sparse=new FaceFeatureTracker(); let value;
  for(let time=0;time<=10000;time+=500) value=add(sparse,time);
  assert.equal(value.window.validSeconds,0); assert.equal(value.window.closedEyeRatio,null);
  assert.equal(value.window.blinksPerMinute,null);
});

test('column-major head rotation is distinct from eye/face movement coefficients',()=>{
  assert.deepEqual(featurePose(identity),{yaw:0,pitch:-0,roll:0});
  const angle=20*Math.PI/180, matrix=[Math.cos(angle),0,-Math.sin(angle),0,0,1,0,0,Math.sin(angle),0,Math.cos(angle),0,0,0,0,1];
  assert.ok(Math.abs(featurePose(matrix).yaw+20)<.001);
  assert.equal(featurePose(Array(16).fill(0)),null);
});

test('fusion snapshot excludes historical pulse and stale speech/gaze from current features',()=>{
  const pulse={...emptyPulse(),status:'observed',bpm:63,held:true,ageSeconds:141.8};
  const feedback={gaze:{timestamp:100,gaze:{headPose:{yaw:20}}},speech:{timestamp:100,speech:{syllablesPerSecond:5}}};
  const snapshot=featureSnapshot(emptyFaceFeatures(),pulse,feedback,20000,'test','running');
  assert.equal(snapshot.pulse.bpm,null); assert.equal(snapshot.pulse.lastEstimate,63);
  assert.equal(snapshot.gaze.headPose,null); assert.equal(snapshot.speech.syllablesPerSecond,null);
  assert.equal(snapshot.pulse.lastEstimateIsHistorical,true);
});
