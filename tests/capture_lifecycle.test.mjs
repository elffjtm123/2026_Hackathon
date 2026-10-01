import test from 'node:test';
import assert from 'node:assert/strict';
import * as lifecycle from '../src/features/practice/sessionLifecycle.ts';
import * as audio from '../src/features/practice/audioTools.ts';

test('flush rejection still closes camera and socket', async () => {
  const calls = [];
  await assert.rejects(lifecycle.completePracticeSession({
    flushMedia: async () => { throw Error('flush'); },
    closeMedia: () => calls.push('media'),
    requestCompletion: async () => { calls.push('completion'); return {}; },
    closeSocket: () => calls.push('socket'),
  }), /flush/);
  assert.deepEqual(calls, ['media', 'socket']);
});

test('late permission after cancellation stops every acquired track', async () => {
  assert.equal(typeof lifecycle.acceptCurrentMedia, 'function');
  let stopped = 0;
  const stream = {getTracks: () => [{stop: () => stopped++}]};
  assert.throws(() => lifecycle.acceptCurrentMedia(stream, 1, 2), /취소/);
  assert.equal(stopped, 1);
});

test('clock starts at running, old socket identity and reordered events rejected', () => {
  assert.equal(typeof lifecycle.acceptServerEvent, 'function');
  assert.equal(lifecycle.acceptServerEvent({version: 2, session_id: 'old', sequence: 4}, 'new', 3), false);
  assert.equal(lifecycle.acceptServerEvent({version: 2, session_id: 'new', sequence: 3}, 'new', 3), false);
  assert.equal(lifecycle.acceptServerEvent({version: 2, session_id: 'new', sequence: 4}, 'new', 3), true);
  assert.equal(lifecycle.practiceElapsedMs(999, null), 0);
  assert.equal(lifecycle.practiceElapsedMs(999, 500), 499);
});

test('capture keeps 16:9 geometry', () => {
  assert.equal(typeof lifecycle.captureSize, 'function');
  assert.deepEqual(lifecycle.captureSize(1920, 1080), {width: 640, height: 360});
});

test('streaming resampling is continuous and anti aliases high frequencies', () => {
  assert.equal(typeof audio.PcmResampler, 'function');
  const input = Float32Array.from({length: 48000}, (_, n) => Math.sin(2 * Math.PI * 12000 * n / 48000));
  const resampler = new audio.PcmResampler(48000);
  const parts = [];
  for (let n = 0; n < input.length; n += 128) parts.push(resampler.push(input.slice(n, n + 128)));
  parts.push(resampler.flush());
  const output = audio.mergeAudioBuffers(parts);
  assert.equal(output.length, 16000);
  const rms = Math.sqrt(output.slice(100).reduce((s, v) => s + v*v, 0) / (output.length-100));
  assert.ok(rms < .05, `aliased RMS ${rms}`);
  const direct = new audio.PcmResampler(16000);
  assert.deepEqual([...direct.push(new Float32Array([.1, .2]))], [...new Float32Array([.1, .2])]);
});

test('buffer and ACK backlog exhaustion are visible errors', () => {
  assert.equal(typeof lifecycle.checkMediaBacklog, 'function');
  assert.throws(() => lifecycle.checkMediaBacklog(256*1024+1, 0), /처리량/);
  assert.throws(() => lifecycle.checkMediaBacklog(0, 32001), /처리량/);
});
