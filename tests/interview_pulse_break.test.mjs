import assert from 'node:assert/strict';
import test from 'node:test';
import {SessionSignalRecorder, pulseSeries} from '../src/features/affect/analysis.ts';

const result = (modelWindows, bpm = 80) => ({status: 'observed', held: false, ended: false, bpm, ageSeconds: 1, modelWindows,
  model: 'm', diagnostics: {resets: 0}});

test('pulse estimates made during a round break are kept in the history', () => {
  const recorder = new SessionSignalRecorder();
  recorder.pulse(result(1, 70), 8000);    // before the break
  recorder.pulse(result(2, 90), 16000);   // inside the break (10 s to 25 s)
  recorder.pulse(result(3, 95), 21000);   // inside the break
  recorder.pulse(result(4, 75), 30000);   // after
  const snapshot = recorder.snapshot([{startMs: 10000, endMs: 25000}], 31000);
  assert.deepEqual(snapshot.pulses.map(p => p.bpm), [70, 90, 95, 75], 'nothing is dropped for being in the break');
  assert.deepEqual(snapshot.breaks, [{startMs: 10000, endMs: 25000}]);
  assert.equal(snapshot.endMs, 31000);
  assert.deepEqual(new SessionSignalRecorder().snapshot().breaks, [], 'a presentation has no breaks');
});

test('the pulse series marks samples in a break; its axis follows the session clock, not the report duration', () => {
  const signals = {faces: [], pulses: [{time: 5000, bpm: 70}, {time: 15000, bpm: 90}, {time: 25000, bpm: 80}, {time: 90000, bpm: 75}],
    breaks: [{startMs: 10000, endMs: 25000}, {startMs: 50000, endMs: 70000}], endMs: 95000};
  const series = pulseSeries(signals);
  assert.deepEqual(series.samples.map(s => [s.timeMs, s.bpm, s.inBreak]),
    [[5000, 70, false], [15000, 90, true], [25000, 80, false], [90000, 75, false]], 'the end of a break is not inside it');
  // The server's duration (no prepare, calibration or break time) would be about 40 s here and would
  // clip the later break and squash the last sample onto the edge; the axis must not use it.
  assert.deepEqual(series.breaks, [{startMs: 10000, endMs: 25000}, {startMs: 50000, endMs: 70000}]);
  assert.equal(series.endMs, 95000);
  assert.equal(pulseSeries({...signals, endMs: undefined}).endMs, 90000, 'without a snapshot end it covers the last sample or break');
  assert.equal(pulseSeries({faces: [], pulses: [{time: 1000, bpm: 70}], breaks: [{startMs: 500, endMs: 4000}]}).endMs, 4000);
  assert.equal(pulseSeries({faces: [], pulses: []}).samples.length, 0);
});

test('thousands of samples are bucketed to a few seconds, a bucket keeps the median and its break flag', () => {
  const pulses = Array.from({length: 3000}, (_, i) => ({time: i * 1000, bpm: 60 + (i % 5)}));
  const series = pulseSeries({faces: [], pulses, breaks: [{startMs: 100000, endMs: 200000}]});
  assert.ok(series.samples.length <= 3000 / 5 + 1, 'about one point per 5 s');
  assert.ok(series.samples.length >= 3000 / 5 - 1);
  const inside = series.samples.find(s => s.timeMs >= 150000);
  assert.equal(inside.inBreak, true);
  assert.equal(series.samples.find(s => s.timeMs >= 250000).inBreak, false);
  assert.equal(pulseSeries({faces: [], pulses: [{time: 0, bpm: 60}, {time: 1000, bpm: 90}, {time: 2000, bpm: 70}]}).samples[0].bpm, 70);
});
