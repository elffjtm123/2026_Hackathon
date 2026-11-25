import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const cacheDir = await mkdtemp(join(tmpdir(), 'practice-pulse-vite-'));
const server = await createServer({ configFile: false, cacheDir, esbuild: { jsx: 'automatic' },
  server: { middlewareMode: true, hmr: false, ws: false, watch: null }, optimizeDeps: { noDiscovery: true } });
after(async () => { await server.close(); await rm(cacheDir, { recursive: true, force: true }); });

test('the practice screen has no link to the verification routes and renders the complete live stage', async () => {
  const { PracticePage } = await server.ssrLoadModule('/src/features/practice/PracticePage.tsx');
  const html = renderToStaticMarkup(createElement(PracticePage));
  assert.doesNotMatch(html, /href="#themes"|href="#stt-experiments"|href="#pulse-pos-experiment"/);
  assert.doesNotMatch(html, /href="#"/);
  assert.ok(html.includes('발표 대본'));
  const { LiveStage } = await server.ssrLoadModule('/src/features/practice/components/LiveStage.tsx');
  const { emptyFeedbackState } = await server.ssrLoadModule('/src/features/practice/feedbackState.ts');
  const { emptyPulse } = await server.ssrLoadModule('/src/features/pulse/signal.ts');
  const stage = renderToStaticMarkup(createElement(LiveStage, { stream: null, videoRef: { current: null }, pulse: emptyPulse(),
    feedback: emptyFeedbackState, script: '대본입니다.', timeLimitSeconds: 60, elapsedSeconds: 0,
    featureSettings: { karaokeGuideEnabled: true, keywordHintEnabled: false, deliveryEnabled: true }, sentenceHints: {},
    phase: 'running', connectionStatus: 'connected', socketError: null, onRecalibrate() {} }));
  for (const feature of ['카메라 프리뷰', '발음 명료도', '피드백 대기 중', '최신 피드백', '다시 보정']) {
    assert.ok(stage.includes(feature), `live stage: missing ${feature}`);
  }
  assert.equal((stage.match(/<video/g) ?? []).length, 1);
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

test('presentation runs the pretrained pulse on the same video without a diagnostics panel', async () => {
  const {PracticePage} = await server.ssrLoadModule('/src/features/practice/PracticePage.tsx');
  const html = renderToStaticMarkup(createElement(PracticePage));
  assert.doesNotMatch(html, /EfficientPhys|UBFC-rPPG 사전학습/);
  assert.match(html, /로컬 백엔드에서만 추론합니다/);
  assert.match(html, /자동 저장·전송하지 않습니다/);
  const {PulsePanel} = await server.ssrLoadModule('/src/features/pulse/PulsePanel.tsx');
  const panel = renderToStaticMarkup(createElement(PulsePanel, {stream: null, mode: 'efficientphys', autoFallback: true, embedded: true}));
  assert.match(panel, /발표 영상 맥박 추정/);
  assert.match(panel, /UBFC-rPPG 사전학습/);
  assert.match(panel, /발표 카메라의 같은 영상을 분석/);
  assert.match(panel, /로컬 백엔드에서만 추론/);
});

test('provisional and ended pulse values are labeled instead of presented as verified readings', async()=>{
  const {PulseOverlay}=await server.ssrLoadModule('/src/features/pulse/PulseOverlay.tsx');
  const result={status:'provisional',bpm:72,seconds:9,fps:30,snr:2,waveform:[],reason:'test',model:'TS-CAN · UBFC-rPPG'};
  const live=renderToStaticMarkup(createElement(PulseOverlay,{result,active:true}));
  assert.match(live,/72 BPM/); assert.match(live,/잠정 추정/); assert.doesNotMatch(live,/TS-CAN/);
  const ended=renderToStaticMarkup(createElement(PulseOverlay,{result:{...result,ended:true},active:false}));
  assert.match(ended,/72 BPM/); assert.match(ended,/종료, 마지막 잠정값/);
});
