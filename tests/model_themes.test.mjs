import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { modelThemes, themeFromHash } from '../src/features/model-themes/modelThemes.ts';
import { historyKey, readRuns, storeRun } from '../src/features/model-themes/runHistory.ts';
import { completionForUi } from '../src/lib/realtimeProtocol.ts';

test('five explicit model routes; unknown model never falls back', () => {
  assert.equal(modelThemes.length, 5);
  for (const theme of modelThemes) assert.equal(themeFromHash(`#practice/${theme.id}`), theme);
  assert.equal(themeFromHash('#practice'), modelThemes[0]);
  assert.equal(themeFromHash('#practice/not-real'), undefined);
  assert.equal(themeFromHash('#stt-experiments'), undefined);
});

test('comparison history is bounded, updates notes and tolerates corrupt storage', () => {
  const data = new Map();
  const storage = { getItem: key => data.get(key), setItem: (key, value) => data.set(key, value) };
  for (let i = 0; i < 25; i++) storeRun(storage, { id: `${i}`, createdAt: '2026-10-09', note: '',
    summary: { durationSeconds: 10, comparison: { model_id: 'qwen_q8' } } });
  assert.equal(readRuns(storage).length, 20);
  const newest = readRuns(storage)[0];
  storeRun(storage, { ...newest, note: '시선과 자막 확인' });
  assert.equal(readRuns(storage)[0].note, '시선과 자막 확인');
  assert.equal(readRuns(storage).length, 20);
  data.set(historyKey, '{broken');
  assert.deepEqual(readRuns(storage), []);
});

test('backend comparison and raw evidence survive completion mapping', () => {
  const raw = { transcript: '실제 전사', incomplete: false,
    comparison: { model_id: 'zipformer_int8', performance: { gaze: { observations: 9 } } } };
  const result = completionForUi(raw);
  assert.equal(result.comparison, raw.comparison);
  assert.equal(result.backendReport, raw);
  assert.equal(result.transcript, '실제 전사');
  assert.equal(completionForUi({ incomplete: false }).comparison, undefined);
});

const cacheDir = await mkdtemp(join(tmpdir(), 'model-themes-vite-'));
const server = await createServer({ configFile: false, cacheDir, esbuild: { jsx: 'automatic' },
  server: { middlewareMode: true, hmr: false, ws: false, watch: null }, optimizeDeps: { noDiscovery: true } });
after(async () => { await server.close(); await rm(cacheDir, { recursive: true, force: true }); });

test('theme hub includes all five full-service entry points and separate controlled experiment', async () => {
  const { ModelThemesPage } = await server.ssrLoadModule('/src/features/model-themes/ModelThemesPage.tsx');
  const html = renderToStaticMarkup(createElement(ModelThemesPage));
  for (const theme of modelThemes) assert.ok(html.includes(`href="#practice/${theme.id}"`));
  assert.match(html, /얼굴 방향 \+ 눈 시선/);
  assert.match(html, /대본 가이드 \+ 자막/);
  assert.match(html, /href="#stt-experiments"/);
});

test('every model reuses the complete practice screen rather than an STT-only page', async () => {
  const { PracticePage } = await server.ssrLoadModule('/src/features/practice/PracticePage.tsx');
  for (const theme of modelThemes) {
    const html = renderToStaticMarkup(createElement(PracticePage, { theme }));
    assert.ok(html.includes(`data-model-theme="${theme.id}"`));
    for (const feature of ['카메라 프리뷰', '발표 대본', '필러워드', '발음 명료도', '시선', '최신 피드백']) {
      assert.ok(html.includes(feature), `${theme.id}: missing ${feature}`);
    }
  }
});

test('pulse panel starts off with no invented reading and identifies unconnected research tools', async () => {
  const { PulsePanel } = await server.ssrLoadModule('/src/features/pulse/PulsePanel.tsx');
  const html = renderToStaticMarkup(createElement(PulsePanel, {stream: null}));
  assert.match(html, /실험용 분석 켜기/);
  assert.match(html, /현재 상태/);
  assert.match(html, /꺼짐/);
  assert.doesNotMatch(html, /<input[^>]*checked/);
  assert.match(html, /외부 전송하지 않습니다/);
  assert.match(html, /아직 학습 모델 미연결/);
  assert.match(html, /UBFC-rPPG/);
  assert.match(html, /UBFC-Phys/);
  assert.match(html, /진단이나 면접 평가 점수에 사용하지 않습니다/);
});

test('standalone pulse screen does not automatically request camera access or microphone', async () => {
  const { PulseExperimentPage } = await server.ssrLoadModule('/src/features/pulse/PulseExperimentPage.tsx');
  const html = renderToStaticMarkup(createElement(PulseExperimentPage));
  assert.match(html, /카메라만 시작/);
  assert.match(html, /카메라 꺼짐/);
});

test('presentation uses pretrained pulse on the same video, not a separate camera experiment', async () => {
  const {PracticePage} = await server.ssrLoadModule('/src/features/practice/PracticePage.tsx');
  const html = renderToStaticMarkup(createElement(PracticePage));
  assert.match(html, /발표 영상 실시간 맥박/);
  assert.match(html, /EfficientPhys/);
  assert.match(html, /UBFC-rPPG 사전학습/);
  assert.match(html, /발표 카메라의 같은 영상을 분석/);
  assert.match(html, /로컬 백엔드에서만 추론/);
  assert.equal((html.match(/<video/g) ?? []).length, 1);
});

test('provisional and ended pulse values are labeled instead of presented as verified readings', async()=>{
  const {PulseOverlay}=await server.ssrLoadModule('/src/features/pulse/PulseOverlay.tsx');
  const result={status:'provisional',bpm:72,seconds:9,fps:30,snr:2,waveform:[],reason:'test',model:'TS-CAN · UBFC-rPPG'};
  const live=renderToStaticMarkup(createElement(PulseOverlay,{result,active:true}));
  assert.match(live,/72 BPM/); assert.match(live,/잠정 추정/); assert.match(live,/TS-CAN/);
  const ended=renderToStaticMarkup(createElement(PulseOverlay,{result:{...result,ended:true},active:false}));
  assert.match(ended,/72 BPM/); assert.match(ended,/종료 · 마지막 잠정값/);
});
