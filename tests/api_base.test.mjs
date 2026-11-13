import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'vite';
import { resolveApiBase, resolveFeedbackWsUrl } from '../src/lib/apiBase.ts';

const ws8001 = 'ws://127.0.0.1:8001/api/v1/ws/practice-demo';

test('HTTP API base follows the feedback WebSocket when no API base is configured', () => {
  assert.equal(resolveApiBase({VITE_FEEDBACK_WS_URL: ws8001}), 'http://127.0.0.1:8001/api/v1');
  assert.equal(resolveApiBase({VITE_FEEDBACK_WS_URL: 'wss://demo.example/api/v1/ws/practice-demo?x=1'}),
    'https://demo.example/api/v1');
});

test('an explicit API base and the old defaults keep working as before', () => {
  assert.equal(resolveApiBase({VITE_API_BASE_URL: 'http://api.example/api/v1/', VITE_FEEDBACK_WS_URL: ws8001}),
    'http://api.example/api/v1');
  assert.equal(resolveApiBase({}), 'http://127.0.0.1:8000/api/v1');
  assert.equal(resolveFeedbackWsUrl({}), 'ws://127.0.0.1:8000/api/v1/ws/practice-demo');
  assert.equal(resolveFeedbackWsUrl({VITE_FEEDBACK_WS_URL: ws8001}), ws8001);
});

// Load the real modules through Vite with only VITE_FEEDBACK_WS_URL set, as the demo runs.
const root = await mkdtemp(join(tmpdir(), 'api-base-env-'));
await writeFile(join(root, '.env'), `VITE_FEEDBACK_WS_URL=${ws8001}\n`);
const server = await createServer({ configFile: false, root: process.cwd(), envDir: root, cacheDir: join(root, 'cache'),
  esbuild: { jsx: 'automatic' }, server: { middlewareMode: true, hmr: false, ws: false, watch: null },
  optimizeDeps: { noDiscovery: true } });
after(async () => { await server.close(); await rm(root, { recursive: true, force: true }); });

test('pulse, model themes, STT experiments and script summary all target the 8001 backend', async () => {
  const { pulseApiBase } = await server.ssrLoadModule('/src/features/pulse/usePulse.ts');
  const { modelApiBase } = await server.ssrLoadModule('/src/features/model-themes/modelThemes.ts');
  const { feedbackWsUrl } = await server.ssrLoadModule('/src/lib/apiBase.ts');
  const { requestScriptSummary } = await server.ssrLoadModule('/src/features/practice/scriptSummary.ts');
  assert.equal(pulseApiBase, 'http://127.0.0.1:8001/api/v1/pulse');
  assert.equal(modelApiBase, 'http://127.0.0.1:8001/api/v1/stt-experiments');
  assert.equal(feedbackWsUrl, ws8001);
  const original = globalThis.fetch;
  let requested;
  globalThis.fetch = async url => { requested = String(url); throw new Error('stop'); };
  try {
    await assert.rejects(requestScriptSummary('대본', new AbortController().signal));
  } finally { globalThis.fetch = original; }
  assert.equal(requested, 'http://127.0.0.1:8001/api/v1/scripts/summarize');
});
