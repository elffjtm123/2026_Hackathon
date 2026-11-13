import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {deliveryForUser} from '../src/features/delivery/metrics.ts';

const row = {start_ms: 0, end_ms: 10000, voiced_ms: 5000, coverage: .5, speech_rate: 300, articulation_rate: 330,
  f0_median_hz: 200, f0_st: .5, pvq: .12, loudness_dbfs: -21.5, loudness_rel_db: 2.5, alpha_ratio_db: -8, hammarberg_db: 14,
  pause_count: 2, longest_pause_ms: 800, disfluency_density: 3};
const metrics = agc_on => ({status: 'observed', agc_on,
  report: {total_voiced_ms: 60000, sentences: [{...row, sentence_index: 0}], baseline: {...row}, bursts: []},
  windows: {window_ms: 10000, baseline: {...row}, windows: [{...row}]}});

test('withheld measures never reach users; relative loudness only with AGC confirmed off', () => {
  const off = deliveryForUser(metrics(false));
  for (const r of [off.windows.windows[0], off.report.sentences[0], off.windows.baseline, off.report.baseline]) {
    for (const key of ['pvq', 'loudness_dbfs', 'alpha_ratio_db', 'hammarberg_db']) assert.ok(!(key in r), key);
    assert.equal(r.loudness_rel_db, 2.5);
    assert.equal(r.speech_rate, 300);
  }
  for (const agc of [true, null]) {
    const user = deliveryForUser(metrics(agc));
    assert.ok(!('loudness_rel_db' in user.windows.windows[0]));
    assert.ok(!('loudness_rel_db' in user.report.sentences[0]));
  }
  assert.equal(deliveryForUser(undefined), undefined);
});

const cacheDir = await mkdtemp(join(tmpdir(), 'delivery-report-vite-'));
const server = await createServer({configFile: false, cacheDir, esbuild: {jsx: 'automatic'},
  server: {middlewareMode: true, hmr: false, ws: false, watch: null}, optimizeDeps: {noDiscovery: true}});
after(async () => { await server.close(); await rm(cacheDir, {recursive: true, force: true}); });

test('the delivery report shows no PVQ, dBFS or spectral balance and keeps the rest', async () => {
  const {DeliveryReport} = await server.ssrLoadModule('/src/features/delivery/DeliveryReport.tsx');
  const off = renderToStaticMarkup(createElement(DeliveryReport, {metrics: metrics(false), sessionId: 's'}));
  assert.doesNotMatch(off, /PVQ|dBFS|Alpha|Hammarberg|-21\.5|14\.0/);
  assert.match(off, /기준 대비 음량/);
  for (const label of ['발화 속도', '쉼', '습관어·반복 밀도', '시간 구간별 특징']) assert.match(off, new RegExp(label));
  for (const agc of [true, null]) {
    const html = renderToStaticMarkup(createElement(DeliveryReport, {metrics: metrics(agc), sessionId: 's'}));
    assert.doesNotMatch(html, /PVQ|dBFS|Alpha|Hammarberg|기준 대비 음량/);
  }
});
