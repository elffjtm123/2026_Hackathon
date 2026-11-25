import assert from 'node:assert/strict';
import test from 'node:test';
import {routeFromHash} from '../src/routes.ts';

test('an empty hash and #practice open the practice screen', () => {
  for (const hash of ['', '#', '#practice', '#pulse-experiment']) assert.deepEqual(routeFromHash(hash), {page: 'practice'});
  assert.deepEqual(routeFromHash('#pulse-pos-experiment'), {page: 'pulse-pos-experiment'});
});

test('the removed model theme and STT experiment hashes are not found', () => {
  for (const hash of ['#themes', '#models', '#stt-experiments', '#practice/service_qwen', '#practice/not-real'])
    assert.deepEqual(routeFromHash(hash), {page: 'not-found'});
});
