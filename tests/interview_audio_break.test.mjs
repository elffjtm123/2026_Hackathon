import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test, {after} from 'node:test';
import {createServer} from 'vite';
import {audioOriginAfterEvent, audioPacketTimestamp, createAudioPacketForwarder} from '../src/features/practice/audioPackets.ts';
import {captureAudioWanted} from '../src/features/practice/sessionLifecycle.ts';

const cacheDir = await mkdtemp(join(tmpdir(), 'interview-audio-vite-'));
const server = await createServer({configFile: false, cacheDir, esbuild: {jsx: 'automatic'},
  server: {middlewareMode: true, hmr: false, ws: false, watch: null}, optimizeDeps: {noDiscovery: true}});
after(async () => { await server.close(); await rm(cacheDir, {recursive: true, force: true}); });

// Runs the real capture worklet; `blocks` are 128-sample input quanta at `rate`.
let loads = 0;
async function captureWorklet(rate, seconds) {
  const registered = {};
  Object.assign(globalThis, {sampleRate: rate, AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.out.push(m)}; this.out = []; } },
    registerProcessor: (name, cls) => { registered[name] = cls; }});
  await server.ssrLoadModule(`/src/features/practice/pcm-capture.worklet.ts?t=${++loads}`);
  const node = new registered['pcm-capture']();
  const block = [new Float32Array(128).fill(0.1)];
  for (let i = 0; i < Math.floor(seconds * rate / 128); i++) node.process([block]);
  return node.out.filter(m => m.event === 'pcm');
}

test('the capture worklet counts samples without a gap for as long as the session clock runs', async () => {
  const packets = await captureWorklet(16000, 30);
  let expected = 0;
  for (const p of packets) { assert.equal(p.startSample, expected, 'start_sample continues where the last packet ended'); expected += p.sampleCount; }
  assert.ok(expected >= 29 * 16000, 'about 30 s of samples were counted');
});

test('the forwarder keeps sequence and start_sample increasing through a round break', async () => {
  const sent = [];
  const forward = createAudioPacketForwarder(packet => sent.push(packet));
  const packets = await captureWorklet(16000, 40);
  const events = [];
  packets.forEach((message, index) => {
    // The break runs from 10 s to 25 s of the session clock: events arrive, the capture is not told.
    const second = message.startSample / 16000;
    if (second >= 10 && !events.includes('suspended')) events.push('suspended');
    if (second >= 25 && !events.includes('resumed')) events.push('resumed');
    forward(message);
    assert.equal(sent.length, index + 1);
  });
  assert.deepEqual(events, ['suspended', 'resumed']);
  sent.forEach((p, i) => { assert.equal(p.sequence, i + 1); if (i) assert.equal(p.startSample, sent[i - 1].startSample + sent[i - 1].sampleCount); });
  const during = sent.filter(p => p.startSample / 16000 >= 10 && p.startSample / 16000 < 25);
  assert.ok(during.length > 0, 'packets keep being produced during the break');
  assert.ok(sent.at(-1).startSample >= 39 * 16000);
});

test('the break events leave the audio origin and the capture switch alone, except that a resume reports the origin again', () => {
  assert.equal(audioOriginAfterEvent({event: 'session.suspended', data: {}}, 1200), 1200);
  assert.equal(audioOriginAfterEvent({event: 'session.resumed', data: {audio_origin_ms: 1200, break_ms: 9000}}, 1200), 1200);
  assert.equal(audioOriginAfterEvent({event: 'session.resumed', data: {audio_origin_ms: 1300}}, 1200), 1300);
  assert.equal(audioOriginAfterEvent({event: 'session.resumed', data: {audio_origin_ms: 'x'}}, 1200), 1200);
  assert.equal(audioOriginAfterEvent({event: 'session.running', data: {audio_origin_ms: 800}}, 0), 800);
  assert.equal(audioPacketTimestamp(1200, 16000 * 30), 31200, 'packet time = origin + samples at 16 kHz, so it follows the session clock');
  // The client phase stays "running" through a break, so capture is never switched off by it.
  assert.equal(captureAudioWanted('running', 'connected'), true);
  assert.equal(captureAudioWanted('draining', 'connected'), true);
  assert.equal(captureAudioWanted('calibrating', 'connected'), false);
  assert.equal(captureAudioWanted('running', 'error'), false);
});
