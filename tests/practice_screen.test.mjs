import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { modelThemes } from '../src/features/model-themes/modelThemes.ts';

const cacheDir = await mkdtemp(join(tmpdir(), 'practice-screen-vite-'));
const server = await createServer({ configFile: false, cacheDir, esbuild: { jsx: 'automatic' },
  server: { middlewareMode: true, hmr: false, ws: false, watch: null }, optimizeDeps: { noDiscovery: true } });
after(async () => { await server.close(); await rm(cacheDir, { recursive: true, force: true }); });

const load = path => server.ssrLoadModule(path);
const servicePage = async () => {
  const { PracticePage } = await load('/src/features/practice/PracticePage.tsx');
  return renderToStaticMarkup(createElement(PracticePage, { theme: modelThemes[0] }));
};

test('the service screen shows none of the verification blocks', async () => {
  const html = await servicePage();
  for (const gone of ['live-theme-banner', 'aria-label="선택한 모델 테마"', '준비 상태 확인', '통합 모델 비교 기록',
    'aria-label="모델 상태"', 'face-feature-panel', '발표 표정 특징 추출', 'pulse-panel', '맥박 추정 모델',
    'theme-nav', '테마 선택', '동일 음성 파일 비교', 'POS 비교 실험', 'class="eyebrow"'])
    assert.ok(!html.includes(gone), `still renders ${gone}`);
});

test('the service screen keeps the camera stage inside the preparation phase', async () => {
  const html = await servicePage();
  assert.match(html, /Realtime Coach/);
  assert.match(html, /<h1[^>]*>발표 및 면접 실시간 피드백<\/h1>/);
  assert.match(html, /발표 대본 설정/);
  assert.match(html, /발표 보조 기능/);
  assert.match(html, /연구용 추정치입니다/);
  assert.match(html, /진단이나 면접 평가 점수에 사용하지 않습니다/);
  assert.ok(!html.includes('aria-label="카메라 프리뷰"'), 'the stage belongs to the practice phase');
});

test('pulse and face analyses are always on: no switch for them in 보조 기능', async () => {
  const html = await servicePage();
  assert.ok(!html.includes('발표 중 맥박 분석'));
  assert.ok(!html.includes('표정 특징 추출'));
  const switches = html.match(/class="switch"/g) ?? [];
  assert.equal(switches.length, 3, 'only the three existing assist switches');
});

test('face features and pulse start enabled for the session signals', async () => {
  const { useSessionSignals } = await load('/src/features/practice/hooks/useSessionSignals.ts');
  let seen;
  const Probe = () => { seen = useSessionSignals('idle', () => 0, null); return null; };
  renderToStaticMarkup(createElement(Probe));
  assert.equal(seen.faceFeaturesEnabled, true);
});

test('an experiment theme still renders its banner and availability check', async () => {
  const { PracticePage } = await load('/src/features/practice/PracticePage.tsx');
  const theme = modelThemes.find(item => item.experiment);
  const html = renderToStaticMarkup(createElement(PracticePage, { theme }));
  assert.ok(html.includes('live-theme-banner'));
  assert.ok(html.includes(theme.label));
  assert.match(html, /준비 상태 확인/);
  assert.ok(!html.includes('face-feature-panel'));
});

test('the screen phase follows lock and summary only', async () => {
  const { practiceStage } = await load('/src/features/practice/practiceStage.ts');
  assert.equal(practiceStage({ locked: false, hasSummary: false }), 'prepare');
  assert.equal(practiceStage({ locked: true, hasSummary: false }), 'live');
  assert.equal(practiceStage({ locked: true, hasSummary: true }), 'live');
  assert.equal(practiceStage({ locked: false, hasSummary: true }), 'result');
});

test('headless pulse reports exactly what the embedded panel reported', async () => {
  const { pulseForReport } = await load('/src/features/pulse/pulseReport.ts');
  const { emptyPulse } = await load('/src/features/pulse/signal.ts');
  const live = { ...emptyPulse(), bpm: 72, status: 'observed' };
  assert.equal(pulseForReport(true, true, live), live);
  const ended = { ...live, ended: true };
  assert.equal(pulseForReport(true, false, ended), ended);
  assert.equal(pulseForReport(true, false, live).reason, '발표 시작 대기');
  assert.equal(pulseForReport(true, false, live).bpm, null);
  assert.equal(pulseForReport(false, true, live).reason, '맥박 분석 꺼짐');
  assert.equal(pulseForReport(false, false, ended).bpm, null);
});

test('the panel and the practice page share one estimator hook', async () => {
  const { usePulseEstimate } = await load('/src/features/pulse/usePulseEstimate.ts');
  let seen;
  const Probe = () => {
    seen = usePulseEstimate({ stream: null, enabled: true, requestedMode: 'efficientphys', autoFallback: true });
    return null;
  };
  renderToStaticMarkup(createElement(Probe));
  assert.equal(seen.modeState.mode, 'efficientphys');
  assert.equal(seen.result.bpm, null);
});

test('the pulse overlay keeps the reading and status but not the model name', async () => {
  const { PulseOverlay } = await load('/src/features/pulse/PulseOverlay.tsx');
  const result = { status: 'provisional', bpm: 72, seconds: 9, fps: 30, snr: 2, waveform: [], reason: 'test', model: 'TS-CAN · UBFC-rPPG' };
  const html = renderToStaticMarkup(createElement(PulseOverlay, { result, active: true }));
  assert.match(html, /72 BPM/);
  assert.match(html, /잠정 추정/);
  assert.doesNotMatch(html, /TS-CAN|UBFC/);
});

test('the feedback panel drops debug words and the duplicate filler cell', async () => {
  const { FeedbackPanel } = await load('/src/features/practice/components/FeedbackPanel.tsx');
  const { emptyFeedbackState } = await load('/src/features/practice/feedbackState.ts');
  const gaze = { source: 'gaze', severity: 'info', gaze: { status: 'ok', message: '정면', headDirection: 'center',
    qualityFlags: ['x'], headPose: { yaw: 1, pitch: 2 }, gazeAngles: { yaw: 3, pitch: 4 } } };
  const speech = { source: 'speech_rate', severity: 'info', speech: { pace: 'normal', message: '적절' },
    filler: { status: 'ok', totalCount: 2, counts: { 음: 2 } } };
  const html = renderToStaticMarkup(createElement(FeedbackPanel, { connectionStatus: 'connected',
    feedback: { ...emptyFeedbackState, gaze, speech }, socketError: null }));
  assert.match(html, />연결됨</);
  assert.doesNotMatch(html, /백엔드|관찰 진단|품질 플래그|yaw|최근 음성 청크/);
  assert.match(html, /발음 명료도/);
  assert.match(html, /음 2회/);
});

test('the summary text shows no timing line or model name', async () => {
  const { PresentationSetup } = await load('/src/features/practice/components/PresentationSetup.tsx');
  const props = { script: '서비스를 소개합니다.', timeLimitSeconds: 60, disabled: false, onScriptChange() {}, onTimeLimitChange() {},
    groups: [], onHintChange() {}, onSummarize() {}, isSummarizing: false, summaryError: null, summaryProgress: null, summarySeconds: 1.2 };
  const done = renderToStaticMarkup(createElement(PresentationSetup, props));
  assert.match(done, /AI 초안/);
  assert.match(done, /내용 확인 필요/);
  assert.doesNotMatch(done, /소요/);
  const pending = renderToStaticMarkup(createElement(PresentationSetup, { ...props, isSummarizing: true,
    summaryProgress: { stage: 'generating', completed_sentences: 1, total_sentences: 2, failed_sentences: 0 } }));
  assert.match(pending, /원문 2문장 중 1문장 처리/);
  assert.doesNotMatch(pending, /Qwen|Q4_K_M|미로드/);
});

test('the time limit can be placed beside the setup instead of inside it', async () => {
  const { PresentationSetup, TimeLimitField } = await load('/src/features/practice/components/PresentationSetup.tsx');
  const props = { script: 'a', timeLimitSeconds: 90, disabled: false, onScriptChange() {}, onTimeLimitChange() {},
    groups: [], onHintChange() {}, onSummarize() {}, isSummarizing: false, summaryError: null, summaryProgress: null, summarySeconds: null };
  assert.ok(!renderToStaticMarkup(createElement(PresentationSetup, { ...props, showTimeLimit: false })).includes('id="time-limit"'));
  assert.ok(renderToStaticMarkup(createElement(PresentationSetup, props)).includes('id="time-limit"'));
  assert.ok(renderToStaticMarkup(createElement(TimeLimitField, { timeLimitSeconds: 90, disabled: false, onTimeLimitChange() {} })).includes('id="time-limit"'));
});

test('result screens offer no JSON download buttons', async () => {
  const { DeliveryReport } = await load('/src/features/delivery/DeliveryReport.tsx');
  const row = { start_ms: 0, end_ms: 10000, voiced_ms: 8000, coverage: 0.8, speech_rate: 300 };
  const delivery = renderToStaticMarkup(createElement(DeliveryReport, { sessionId: 's',
    metrics: { status: 'observed', agc_on: false, report: { total_voiced_ms: 60000, sentences: [{ ...row }], baseline: { ...row }, bursts: [] },
      windows: { window_ms: 10000, baseline: { ...row }, windows: [{ ...row }] } } }));
  assert.doesNotMatch(delivery, /JSON 내려받기/);
  assert.match(delivery, /시간 구간별 특징/);
});

test('the script progress bar scales instead of resizing', async () => {
  const { KaraokeGuide } = await load('/src/features/practice/components/KaraokeGuide.tsx');
  const html = renderToStaticMarkup(createElement(KaraokeGuide, { script: '하나 둘 셋.', timeLimitSeconds: 60, elapsedSeconds: 0,
    karaokeEnabled: true, keywordHintEnabled: false, progress: { current_token_index: 1, current_sentence_index: 0, progress_ratio: 0.5 } }));
  assert.match(html, /scaleX\(0\.5\)/);
  assert.doesNotMatch(html, /style="width/);
});

test('the top bar carries the wordmark with unchanged mode and action labels', async () => {
  const { SessionControls } = await load('/src/features/practice/components/SessionControls.tsx');
  const html = renderToStaticMarkup(createElement(SessionControls, { mode: 'presentation', isRunning: false, isStarting: false,
    isStopping: false, elapsedSeconds: 65, onModeChange() {}, onStart() {}, onEnd() {} }));
  assert.match(html, /Realtime Coach/);
  for (const label of ['>발표<', '>면접<', '>시작<', '>종료<', '01:05']) assert.ok(html.includes(label), label);
});

test('a socket error stays visible once the live stage is gone', async () => {
  const { showPageSocketError } = await load('/src/features/practice/practiceStage.ts');
  assert.equal(showPageSocketError({ error: null, stage: 'prepare', interview: false, interviewReport: false }), false);
  assert.equal(showPageSocketError({ error: 'x', stage: 'live', interview: false, interviewReport: false }), false, 'FeedbackPanel shows it');
  assert.equal(showPageSocketError({ error: 'x', stage: 'prepare', interview: false, interviewReport: false }), true);
  assert.equal(showPageSocketError({ error: 'x', stage: 'result', interview: false, interviewReport: false }), true);
  assert.equal(showPageSocketError({ error: 'x', stage: 'prepare', interview: true, interviewReport: false }), false, 'interview live view shows it in FeedbackPanel');
  assert.equal(showPageSocketError({ error: 'x', stage: 'prepare', interview: true, interviewReport: true }), true);
});

test('data handling notes follow the estimator mode and share one source with the panel', async () => {
  const { DataNotes } = await load('/src/features/practice/components/DataNotes.tsx');
  const local = renderToStaticMarkup(createElement(DataNotes, { pulseMode: 'efficientphys' }));
  assert.match(local, /데이터 처리 안내/);
  assert.match(local, /72×72 RGB 얼굴 크롭은 이 컴퓨터의 로컬 백엔드에서만 추론합니다\. 영상·맥파·BPM을 파일이나 DB에 저장하지 않고, 종료 시 마지막 값만 이 화면 메모리에 남깁니다\. 인터넷 서버로 보내지 않습니다\./);
  assert.match(local, /기존 연습의 영상·음성은 원래처럼 로컬 백엔드로 전송됩니다\./);
  assert.match(local, /표정 특징은 브라우저 메모리에서 처리하며 자동 저장·전송하지 않습니다\./);
  const pos = renderToStaticMarkup(createElement(DataNotes, { pulseMode: 'pos' }));
  assert.match(pos, /본 맥박 기능의 프레임·RGB 신호·생체 추정값은 브라우저 메모리에서만 처리하며 저장·외부 전송하지 않습니다\./);
  assert.doesNotMatch(pos, /로컬 백엔드에서만 추론/);
  const { PulsePanel } = await load('/src/features/pulse/PulsePanel.tsx');
  const panel = renderToStaticMarkup(createElement(PulsePanel, { stream: null, mode: 'efficientphys', embedded: true }));
  assert.match(panel, /72×72 RGB 얼굴 크롭은 이 컴퓨터의 로컬 백엔드에서만 추론합니다/);
  const html = await servicePage();
  assert.match(html, /인터넷 서버로 보내지 않습니다/);
  assert.match(html, /자동 저장·전송하지 않습니다/);
});

test('the insights charts carry no dot-joined aria or title strings', async () => {
  const { readFile } = await import('node:fs/promises');
  const source = await readFile(new URL('../src/features/affect/SessionInsights.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /(aria-label="[^"]* · |<title>\{`[^`]* · )/);
});

test('interview mode shows the same privacy notes as presentation', async () => {
  const { PracticePage } = await load('/src/features/practice/PracticePage.tsx');
  globalThis.sessionStorage = { getItem: key => key === 'live-practice-mode' ? 'interview' : null, setItem() {} };
  try {
    const html = renderToStaticMarkup(createElement(PracticePage, { theme: modelThemes[0] }));
    assert.match(html, /<h1[^>]*>면접 연습<\/h1>/);
    assert.match(html, /데이터 처리 안내/);
    assert.match(html, /인터넷 서버로 보내지 않습니다/);
    assert.match(html, /자동 저장·전송하지 않습니다/);
    assert.match(html, /연구용 추정치입니다/);
  } finally { delete globalThis.sessionStorage; }
});

test('interview mode puts the question and camera before the passive notices', async () => {
  const { PracticePage } = await load('/src/features/practice/PracticePage.tsx');
  globalThis.sessionStorage = { getItem: key => key === 'live-practice-mode' ? 'interview' : null, setItem() {} };
  try {
    const html = renderToStaticMarkup(createElement(PracticePage, { theme: modelThemes[0] }));
    const question = html.indexOf('aria-label="면접 질문"');
    assert.ok(question >= 0, 'question section renders');
    for (const notice of ['데이터 처리 안내', '연구용 추정치입니다', 'affect-run-guide'])
      assert.ok(html.indexOf(notice) > question, `${notice} must come after the question`);
  } finally { delete globalThis.sessionStorage; }
});

test('the same text in socket and operation errors is shown once', async () => {
  const { showPageSocketError } = await load('/src/features/practice/practiceStage.ts');
  assert.equal(showPageSocketError({ error: 'x', stage: 'prepare', interview: false, interviewReport: false, operationError: 'x' }), false);
  assert.equal(showPageSocketError({ error: 'x', stage: 'prepare', interview: false, interviewReport: false, operationError: 'y' }), true);
});
