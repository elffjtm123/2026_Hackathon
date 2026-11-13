import assert from 'node:assert/strict';
import test from 'node:test';
import {pulseRegions,FaceCropTracker} from '../src/features/pulse/regions.ts';
function face() {
  const landmarks = Array.from({length:478}, () => ({x:0.5,y:0.5}));
  for (const [index,x,y] of [[33,.3,.4],[263,.7,.4],[10,.5,.15],[168,.5,.4],
    [50,.3,.57],[101,.38,.56],[280,.7,.57],[330,.62,.56]]) landmarks[index] = {x,y};
  // Old forehead bbox is 1 pixel high even though face is large and frontal.
  for (const [index,x] of [[108,.42],[337,.58],[151,.5]]) landmarks[index] = {x,y:.25};
  return landmarks;
}
test('normal frontal face has non-degenerate forehead and cheek patches', () => {
  for (const [w,h] of [[320,240],[320,180],[640,480]]) {
    const regions = pulseRegions(face(), w,h);
    assert.equal(regions.length,3);
    assert.ok(regions.every(r => r.valid));
    assert.ok(regions.every(r => r.width*w>=4 && r.height*h>=4));
  }
});

test('neural face capture accepts a usable face below the old eye-distance cutoff',()=>{
  const tracker=new FaceCropTracker();
  const small=face().map(p=>({x:.5+(p.x-.5)*.35,y:.5+(p.y-.5)*.7}));
  assert.ok(Math.hypot(small[263].x-small[33].x,small[263].y-small[33].y)<.15);
  assert.ok(pulseRegions(small,320,240).every(v=>v.valid));
  const result=tracker.update(small,320,240,0);
  assert.ok(result.crop,result.reason);
  assert.ok(result.eyePixels>=24);
});

test('moderate pose is a warning, not a neural input veto; square crops stay in frame',()=>{
  const tracker=new FaceCropTracker();
  const pose=face(); pose[263].y=.6; pose[1].x=.67;
  const first=tracker.update(pose,320,240,0);
  assert.ok(first.crop,first.reason); assert.ok(first.warning);
  const next=tracker.update(pose.map(p=>({x:p.x+.02,y:p.y})),320,240,200);
  assert.ok(next.crop);
  assert.ok(next.crop.x>=0 && next.crop.y>=0);
  assert.ok(next.crop.x+next.crop.side<=320 && next.crop.y+next.crop.side<=240);
  assert.equal(tracker.update(pose,320,240,200),next);
});

test('genuinely unusable neural geometry remains rejected with a specific cause',()=>{
  const tracker=new FaceCropTracker();
  const tiny=face().map(p=>({x:.5+(p.x-.5)*.1,y:.5+(p.y-.5)*.1}));
  assert.equal(tracker.update(tiny,320,240,0).crop,null);
  const outside=face().map(p=>({x:p.x+1,y:p.y}));
  assert.equal(tracker.update(outside,320,240,200).crop,null);
  tracker.reset();
  assert.ok(tracker.update(face(),320,240,400).crop);
  assert.equal(tracker.update([],320,240,600).crop,null);
});
test('out-of-frame and genuinely tiny faces remain rejected', () => {
  assert.deepEqual(pulseRegions(face().map(p => ({x:.5+(p.x-.5)*.1,y:p.y})),320,240),[]);
  const outside = face(); outside[10].y = -.9;
  assert.equal(pulseRegions(outside,320,240)[0].valid,false);
  assert.deepEqual(pulseRegions([],320,240),[]);
});
test('face patches follow translation and scale rather than fixed screen positions', () => {
  const a = pulseRegions(face(),320,240);
  const b = pulseRegions(face().map(p => ({x:p.x+.05,y:p.y+.04})),320,240);
  assert.ok(Math.abs(b[0].x-a[0].x-.05)<.005);
  assert.ok(Math.abs(b[0].y-a[0].y-.04)<.005);
});
