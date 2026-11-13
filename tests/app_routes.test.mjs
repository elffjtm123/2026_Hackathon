import assert from 'node:assert/strict';
import test from 'node:test';
import {ensureThemeReady, modelThemes, sttModelIdFor} from '../src/features/model-themes/modelThemes.ts';
import {routeFromHash} from '../src/routes.ts';

const serviceTheme = modelThemes[0];
const experimentTheme = modelThemes.find(theme => theme.id === 'whisper_small_int8');

test('the default service theme starts without asking the experiments API', async () => {
  let calls = 0;
  const read = async () => { calls++; throw new Error('404 실험 기능을 사용할 수 없습니다.'); };
  await ensureThemeReady(serviceTheme, read);
  assert.equal(calls, 0);
  assert.equal(sttModelIdFor(serviceTheme), undefined);
});

test('experiment themes still require an available, idle model', async () => {
  await assert.rejects(ensureThemeReady(experimentTheme, async () => { throw new Error('LOCAL_ONLY'); }), /LOCAL_ONLY/);
  await assert.rejects(ensureThemeReady(experimentTheme, async () => ({busy: true, models: [{id: experimentTheme.id, available: true, reason: '', label: ''}]})), /진행 중/);
  await assert.rejects(ensureThemeReady(experimentTheme, async () => ({busy: false, models: [{id: experimentTheme.id, available: false, reason: '가중치 없음', label: ''}]})), /가중치 없음/);
  await ensureThemeReady(experimentTheme, async () => ({busy: false, models: [{id: experimentTheme.id, available: true, reason: '', label: ''}]}));
  assert.equal(sttModelIdFor(experimentTheme), 'whisper_small_int8');
});

test('an empty hash opens practice with the service theme; theme selection lives at #themes', () => {
  for (const hash of ['', '#', '#practice', '#pulse-experiment']) assert.deepEqual(routeFromHash(hash), {page: 'practice', theme: serviceTheme});
  for (const hash of ['#themes', '#models']) assert.deepEqual(routeFromHash(hash), {page: 'themes'});
  for (const theme of modelThemes) assert.deepEqual(routeFromHash(`#practice/${theme.id}`), {page: 'practice', theme});
  assert.deepEqual(routeFromHash('#stt-experiments'), {page: 'stt-experiments'});
  assert.deepEqual(routeFromHash('#pulse-pos-experiment'), {page: 'pulse-pos-experiment'});
  assert.deepEqual(routeFromHash('#practice/not-real'), {page: 'not-found'});
});
