import assert from 'node:assert/strict';
import test from 'node:test';
import {CPU_INIT_TIMEOUT_MS, FrameWatchdog, GPU_INIT_TIMEOUT_MS, WORKER_HANG_MS, initTimeoutMs, unresponsiveWorkerAction} from '../src/features/pulse/frameWatchdog.ts';

// Watchdog ticks every 500ms in the hook; simulate the same cadence.
const ticks = (watch, from, to) => {
  const verdicts = [];
  for (let now = from; now <= to; now += 500) verdicts.push(watch.check(now));
  return verdicts;
};

test('a frame the worker is still processing (slow first GPU detect) is never judged a video stall', () => {
  const watch = new FrameWatchdog(0);
  watch.frameStarted(100);
  const verdicts = ticks(watch, 500, 3000);
  assert.equal(verdicts.includes('stall'), false);
  assert.equal(verdicts.at(-1), 'slow', 'long in-flight frame is reported as model processing');
  assert.equal(watch.inFlight, true);
  watch.frameSettled(3413);
  assert.equal(watch.inFlight, false);
  assert.equal(watch.check(3500), 'ok');
});

test('an idle worker with no new video frame triggers one reset per stall, then resumes when frames return', () => {
  const watch = new FrameWatchdog(0);
  watch.frameStarted(0); watch.frameSettled(10);
  const stalled = ticks(watch, 500, 6000);
  assert.equal(stalled.filter(v => v === 'stall').length, 1, 'no repeated reset every 500ms');
  assert.equal(stalled.indexOf('stall'), 3, 'first tick past 1.5s of silence');
  watch.frameStarted(6100); watch.frameSettled(6110);
  assert.equal(watch.check(6500), 'ok');
  const again = ticks(watch, 7000, 9000);
  assert.equal(again.filter(v => v === 'stall').length, 1, 'a later stall is detected again');
});

test('a worker that has not answered one frame for 10s is reported hung once so the hook can recover', () => {
  assert.equal(WORKER_HANG_MS, 10000);
  const watch = new FrameWatchdog(0);
  watch.frameStarted(0);
  const verdicts = ticks(watch, 500, 15000);
  assert.equal(verdicts.filter(v => v === 'hung').length, 1);
  assert.equal(verdicts.indexOf('hung'), 20, 'first tick past 10s in flight');
  assert.equal(verdicts.includes('stall'), false);
});

test('an external reset (hidden tab, ended track) restarts the stall timer without forgetting the in-flight frame', () => {
  const watch = new FrameWatchdog(0);
  watch.frameStarted(0); watch.frameSettled(10);
  assert.equal(watch.check(2000), 'stall');
  watch.restart(2100);
  assert.equal(watch.check(3000), 'ok', 'fresh 1.5s window after the reset');
  assert.equal(watch.check(3700), 'stall', 'still re-armed when frames never return');
  watch.frameStarted(4000);
  watch.restart(4500);
  assert.equal(watch.inFlight, true);
  assert.equal(watch.check(6000), 'slow');
});

test('a GPU worker that stops answering (in init or on a frame) gets one CPU retry; a CPU worker or a second hang fails', () => {
  assert.equal(unresponsiveWorkerAction({delegate: 'GPU', cpuRetried: false}), 'retry-cpu');
  assert.equal(unresponsiveWorkerAction({delegate: 'CPU', cpuRetried: false}), 'fail', 'pulse-only workers already run on CPU');
  assert.equal(unresponsiveWorkerAction({delegate: 'CPU', cpuRetried: true}), 'fail');
  assert.equal(unresponsiveWorkerAction({delegate: 'GPU', cpuRetried: true}), 'fail', 'never loops back to GPU');
});

test('a GPU init gives up sooner than a CPU init so a stuck GPU warm-up does not double the wait', () => {
  assert.equal(initTimeoutMs('GPU'), GPU_INIT_TIMEOUT_MS);
  assert.equal(initTimeoutMs('CPU'), CPU_INIT_TIMEOUT_MS);
  assert.equal(CPU_INIT_TIMEOUT_MS, 30000, 'CPU keeps the previous 30s budget');
  assert.ok(GPU_INIT_TIMEOUT_MS < CPU_INIT_TIMEOUT_MS);
  assert.ok(GPU_INIT_TIMEOUT_MS + CPU_INIT_TIMEOUT_MS <= 45000, 'worst case GPU hang then CPU init stays under 45s');
});
