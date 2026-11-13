import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import * as lifecycle from '../src/features/practice/sessionLifecycle.ts';

const cacheDir = await mkdtemp(join(tmpdir(), 'delivery-settings-vite-'));
const server = await createServer({
  configFile: false,
  cacheDir,
  esbuild: { jsx: 'automatic' },
  server: { middlewareMode: true, hmr: false, ws: false },
  optimizeDeps: { noDiscovery: true },
});
after(async () => {
  await server.close();
  await rm(cacheDir, { recursive: true, force: true });
});

const streamWith = settings => ({ getAudioTracks: () => (settings ? [{ getSettings: () => settings }] : []) });

test('microphone asks for no auto gain and leaves other processing at browser defaults', () => {
  assert.deepEqual(lifecycle.MICROPHONE_CONSTRAINTS, { autoGainControl: false });
});

test('applied autoGainControl is read from the first audio track', () => {
  assert.deepEqual(lifecycle.audioSettingsOf(streamWith({ autoGainControl: false })), { autoGainControl: false });
  assert.deepEqual(lifecycle.audioSettingsOf(streamWith({ autoGainControl: true })), { autoGainControl: true });
});

test('an unreported or missing autoGainControl is not sent', () => {
  assert.equal(lifecycle.audioSettingsOf(streamWith({})), undefined);
  assert.equal(lifecycle.audioSettingsOf(streamWith({ autoGainControl: 'on' })), undefined);
  assert.equal(lifecycle.audioSettingsOf(streamWith(null)), undefined);
  assert.equal(lifecycle.audioSettingsOf(null), undefined);
});

test('session.start data carries delivery_enabled but never waits for audio settings', () => {
  const settings = { karaokeGuideEnabled: true, keywordHintEnabled: false, deliveryEnabled: false };
  assert.deepEqual(lifecycle.sessionStartData('presentation', settings, '대본', 120), {
    mode: 'presentation',
    settings: { karaoke_guide_enabled: true, delivery_enabled: false },
    script: '대본',
    time_limit_seconds: 120,
  });
  assert.deepEqual(lifecycle.sessionStartData('interview', settings, '무시', 120), {
    mode: 'interview',
    settings: { karaoke_guide_enabled: true, delivery_enabled: false },
  });
});

test('audio settings are sent as a follow-up once known, without blocking the caller', async () => {
  const sent = [];
  let resolve;
  const known = new Promise(done => { resolve = done; });
  const delivery = lifecycle.deliverAudioSettings(known, applied => sent.push(applied), () => true);
  assert.deepEqual(sent, []); // the permission prompt is still open
  resolve({ autoGainControl: false });
  await delivery;
  assert.deepEqual(sent, [{ autoGainControl: false }]);
});

test('denied microphone, missing settings or a closed socket send nothing and never throw', async () => {
  const sent = [];
  const send = applied => sent.push(applied);
  await lifecycle.deliverAudioSettings(Promise.reject(new Error('NotAllowedError')), send, () => true);
  await lifecycle.deliverAudioSettings(Promise.resolve(undefined), send, () => true);
  await lifecycle.deliverAudioSettings(undefined, send, () => true);
  await lifecycle.deliverAudioSettings(Promise.resolve({ autoGainControl: true }), send, () => false);
  await lifecycle.deliverAudioSettings(Promise.resolve({ autoGainControl: true }), () => { throw new Error('closed'); }, () => true);
  assert.deepEqual(sent, []);
});

test('the feedback socket sends session.start immediately and the audio settings separately', async () => {
  const source = await readFile(new URL('../src/features/practice/hooks/useFeedbackSocket.ts', import.meta.url), 'utf8');
  const onopen = source.slice(source.indexOf('socket.onopen'), source.indexOf('socket.onmessage'));
  assert.match(onopen, /event: 'session\.start'/);
  assert.doesNotMatch(onopen.slice(0, onopen.indexOf("event: 'session.start'")), /audioSettings/);
  assert.match(onopen, /session\.audio_settings/);
});

test('목소리 전달력 toggle is bound to deliveryEnabled', async () => {
  const { FeatureToggles } = await server.ssrLoadModule('/src/features/practice/components/FeatureToggles.tsx');
  const props = { disabled: false, onChange() {} };
  const on = renderToStaticMarkup(
    createElement(FeatureToggles, { ...props, settings: { karaokeGuideEnabled: true, keywordHintEnabled: false, deliveryEnabled: true } }),
  );
  assert.match(on, /목소리 전달력/);
  const section = markup => markup.slice(markup.indexOf('목소리 전달력'));
  assert.match(section(on), /checked=""/);
  const off = renderToStaticMarkup(
    createElement(FeatureToggles, { ...props, settings: { karaokeGuideEnabled: true, keywordHintEnabled: false, deliveryEnabled: false } }),
  );
  assert.doesNotMatch(section(off), /checked=""/);
  assert.match(section(off), /OFF/);
});
