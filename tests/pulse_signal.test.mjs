import assert from 'node:assert/strict';
import test from 'node:test';
import { PulseBuffer, estimatePulse, estimateNeuralPulse, mergeNeuralWindow, PulseSmoother, PulseReadoutMemory, emptyPulse } from '../src/features/pulse/signal.ts';

function samples(bpm = 72, seconds = 20, fps = 30) {
  return Array.from({length: Math.floor(seconds * fps) + 1}, (_, i) => {
    const t = i / fps, pulse = Math.sin(2 * Math.PI * bpm / 60 * t);
    return {time: t * 1000, light: 110,
      regions: [1, 0.9, 1.1].map(scale => [150 + 0.18 * scale * pulse, 110 + 0.65 * scale * pulse, 80 + 0.08 * scale * pulse])};
  });
}
test('POS estimates a synthetic RGB pulse, without claiming clinical accuracy', () => {
  for (const target of [54, 72, 96, 120, 150]) {
    const result = estimatePulse(samples(target));
    assert.equal(result.status, 'observed');
    assert.ok(Math.abs(result.bpm - target) <= 2, `${target}: ${JSON.stringify(result)}`);
    assert.ok(result.waveform.length > 0);
  }
});

function neural(bpm=72, seconds=20) {
  return Array.from({length: Math.floor(seconds*30)+1},(_,i)=>({time:i*1000/30,
    value:Math.sin(2*Math.PI*bpm/60*i/30)-Math.sin(2*Math.PI*bpm/60*(i-1)/30)}));
}

test('live dropout keeps a timestamped previous reading without manufacturing a new estimate',()=>{
  const memory=new PulseReadoutMemory();
  assert.equal(memory.update(emptyPulse(),0).bpm,null);
  const measured={...estimateNeuralPulse(neural()),diagnostics:{resultAgeSeconds:1}};
  assert.equal(memory.update(measured,10000).held,false);
  const held=memory.update({...emptyPulse('얼굴 없음'),status:'unreliable'},14000);
  assert.equal(held.bpm,72); assert.equal(held.held,true); assert.equal(held.ageSeconds,5);
  assert.equal(held.status,'unreliable'); assert.equal(held.reason,'얼굴 없음');
  assert.equal(memory.update(held,16000).ageSeconds,7);
  assert.equal(memory.finish(20000).bpm,72); assert.equal(memory.finish(20000).ended,true);
  const fresh=memory.update({...measured,bpm:80},21000);
  assert.equal(fresh.bpm,80); assert.equal(fresh.held,false);
  memory.reset(); assert.equal(memory.finish(25000),null);
  assert.equal(memory.update(emptyPulse(),26000).bpm,null);
});

test('early real-signal estimate is explicitly provisional; stable gate still needs 15 seconds',()=>{
  assert.equal(estimateNeuralPulse(neural(72,3)).bpm,null);
  const early=estimateNeuralPulse(neural(72,9));
  assert.equal(early.status,'provisional');
  assert.ok(Math.abs(early.bpm-72)<=1);
  assert.equal(estimateNeuralPulse(neural(72,16)).status,'observed');
  for(const bpm of [45,180]) assert.equal(estimateNeuralPulse(neural(bpm,9)).bpm,null);
  assert.equal(estimateNeuralPulse(neural(72,9).map(v=>({...v,value:0}))).bpm,null);
  assert.equal(estimateNeuralPulse(neural(72,9).map((v,i)=>i===50?{...v,value:NaN}:v)).bpm,null);
});

test('overlapping one-second updates count real time once and reject late output',()=>{
  let wave=[];
  for(let s=0;s<=10;s++) wave=mergeNeuralWindow(wave,s*1000,neural(72,3).slice(0,90).map(v=>v.value));
  const seconds=(wave.at(-1).time-wave[0].time)/1000;
  assert.ok(seconds<13.1 && seconds>12.9);
  assert.ok(wave.slice(1).every((v,i)=>v.time>wave[i].time));
  assert.equal(mergeNeuralWindow(wave,0,Array(90).fill(1)),wave);
  const gap=mergeNeuralWindow(wave,20000,Array(90).fill(1));
  assert.equal(gap.length,90);
  assert.equal(gap[0].time,20000);
});

test('display smoothing does not change raw estimate or invent a value across signal loss',()=>{
  const smoother=new PulseSmoother();
  const clean=estimateNeuralPulse(neural());
  assert.equal(smoother.add(clean).bpm,72);
  const outlier=smoother.add({...clean,bpm:120});
  assert.equal(outlier.rawBpm,120);
  assert.ok(outlier.bpm<120);
  assert.equal(smoother.add({...clean,bpm:null,status:'unreliable'}).bpm,null);
  assert.equal(smoother.add({...clean,bpm:100}).bpm,100);
});
test('short, constant, dim-changing and low frame rate signals do not invent BPM', () => {
  assert.equal(estimatePulse(samples(72, 10)).bpm, null);
  assert.equal(estimatePulse(samples(72, 20, 10)).bpm, null);
  const constant = samples().map(s => ({...s, regions: [[150,110,80],[150,110,80],[150,110,80]]}));
  assert.equal(estimatePulse(constant).bpm, null);
  assert.equal(estimatePulse(samples().map((s, i) => ({...s, light: 100 + i / 2}))).bpm, null);
});
test('irregular capture timestamps are resampled and long gaps suppress BPM', () => {
  const jittered = samples().map((s, i) => ({...s, time: s.time + (i % 2 ? 3 : 0)}));
  assert.ok(Math.abs(estimatePulse(jittered).bpm - 72) <= 2);
  const gap = samples().filter(s => s.time < 8000 || s.time > 8500);
  assert.equal(estimatePulse(gap).bpm, null);
});
test('buffer resets on missing, non-finite or backwards samples and stays bounded', () => {
  const buffer = new PulseBuffer();
  for (const sample of samples(72, 40)) buffer.add(sample);
  assert.ok(buffer.samples.length <= 601);
  buffer.add(samples()[0]); assert.equal(buffer.samples.length, 1);
  buffer.add({...samples()[0], time: NaN}); assert.equal(buffer.samples.length, 0);
  buffer.add(samples()[0]); buffer.add({...samples()[0], time: 1000}); assert.equal(buffer.samples.length, 1);
  buffer.reset(); assert.equal(buffer.samples.length, 0);
});
test('inconsistent regions cannot produce a plausible-looking common BPM', () => {
  const a = samples(60), b = samples(100), c = samples(150);
  assert.equal(estimatePulse(a.map((v,i) => ({...v, regions: [v.regions[0], b[i].regions[1], c[i].regions[2]]}))).bpm, null);
});

test('neural derivative output is integrated and gated, never substituted by POS', () => {
  const values = Array.from({length:600}, (_,i)=>({time:i*1000/30,
    value:Math.sin(2*Math.PI*72/60*i/30)-Math.sin(2*Math.PI*72/60*(i-1)/30)}));
  assert.equal(estimateNeuralPulse(values).bpm,72);
  assert.equal(estimateNeuralPulse(values.slice(0,90)).bpm,null);
  assert.equal(estimateNeuralPulse(values.map(v=>({...v,value:0}))).bpm,null);
  assert.equal(estimateNeuralPulse(values.filter((_,i)=>i<100||i>120)).bpm,null);
});
