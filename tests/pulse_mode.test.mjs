import assert from 'node:assert/strict';
import test from 'node:test';
import {checkPulseBackend, initialPulseMode, pulseModeAfterCheck, pulseMethodLabel} from '../src/features/pulse/pulseMode.ts';

const api = 'http://127.0.0.1:8001/api/v1/pulse';
const reply = (status, body) => async () => ({ok: status < 400, json: async () => body});

test('a missing backend model or an unreachable backend is reported, a ready model is not', async () => {
  assert.deepEqual(await checkPulseBackend(api, 'ma_ubfc_tscan', reply(200, {available: true})), {ok: true});
  const missing = await checkPulseBackend(api, 'ma_ubfc_tscan', reply(200, {available: false}));
  assert.equal(missing.ok, false);
  assert.match(missing.reason, /가중치/);
  const down = await checkPulseBackend(api, 'ma_ubfc_tscan', async () => { throw new TypeError('Failed to fetch'); });
  assert.equal(down.ok, false);
  assert.match(down.reason, /연결/);
  let called = false;
  const remote = await checkPulseBackend('https://example.com/api/v1/pulse', 'ma_ubfc_tscan', async () => { called = true; });
  assert.equal(remote.ok, false);
  assert.equal(called, false);
});

test('the practice screen switches to browser POS when the backend model cannot run', () => {
  const start = initialPulseMode('efficientphys');
  assert.deepEqual(start, {mode: 'efficientphys', fallbackReason: null});
  const fallen = pulseModeAfterCheck(start, {ok: false, reason: 'EfficientPhys 가중치가 준비되지 않았습니다.'}, true);
  assert.equal(fallen.mode, 'pos');
  assert.equal(fallen.fallbackReason, 'EfficientPhys 가중치가 준비되지 않았습니다.');
  assert.equal(pulseMethodLabel(fallen, 'TS-CAN'), '브라우저 추정(POS)');
  // With weights ready nothing changes; without auto fallback the failure stays a failure.
  assert.equal(pulseModeAfterCheck(start, {ok: true}, true), start);
  assert.equal(pulseModeAfterCheck(start, {ok: false, reason: 'x'}, false), start);
  assert.equal(pulseMethodLabel(start, 'TS-CAN · MA-UBFC-rPPG'), '사전학습 모델(TS-CAN · MA-UBFC-rPPG)');
});
