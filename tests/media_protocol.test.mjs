import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

test('v2 PCM fixture has big endian header and untouched little endian payload', async () => {
  const url = new URL('../src/lib/mediaProtocol.ts', import.meta.url);
  assert.ok(existsSync(url), 'v2 encoder missing');
  const { encodeMediaV2 } = await import(url);
  const buffer = encodeMediaV2({type: 2, sequence: 1, timestampMs: 0, startSample: 0, sampleCount: 8, payload: new TextEncoder().encode('AB'.repeat(8)).buffer});
  assert.equal(Buffer.from(buffer).toString('hex'), '020200000001000000000000000000000000000000000000000841424142414241424142414241424142');
  assert.throws(() => encodeMediaV2({type: 2, sequence: 1, timestampMs: NaN, startSample: 0, sampleCount: 8, payload: new ArrayBuffer(16)}));
});
