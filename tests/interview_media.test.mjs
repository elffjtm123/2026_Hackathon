import assert from 'node:assert/strict';
import test from 'node:test';
import {mediaErrorMessage} from '../src/features/practice/hooks/useUserMedia.ts';

test('a device error is described in Korean only', () => {
  const missing = new DOMException('Requested device not found', 'NotFoundError');
  assert.doesNotMatch(mediaErrorMessage(missing), /[A-Za-z]{4}/);
  assert.match(mediaErrorMessage(missing), /찾지 못했습니다/);
});

test('the error that leaves startMedia carries the Korean message, the raw error stays as its cause', async () => {
  const {mediaStartError} = await import('../src/features/practice/hooks/useUserMedia.ts');
  const raw = new DOMException('Requested device not found', 'NotFoundError');
  const error = mediaStartError(raw);
  assert.equal(error.message, mediaErrorMessage(raw));
  assert.equal(error.cause, raw);
});
