import assert from 'node:assert/strict';
import test from 'node:test';
import { csvCell, jobCsv, pcmWav } from '../src/features/stt-experiments/tools.ts';

test('CSV exports block spreadsheet formulas and preserve quotes/newlines', () => {
  assert.equal(csvCell('=SUM(1,2)'), '"\'=SUM(1,2)"');
  assert.equal(csvCell(' \t+cmd'), '"\' \t+cmd"');
  assert.equal(csvCell('"어"\n음'), '"""어""\n음"');
  assert.equal(csvCell(null), '""');
});

test('WAV export retains exact PCM bytes, including final short block', async () => {
  const samples = new Int16Array([0, 32767, -32768, 100]);
  const wav = await pcmWav([samples.buffer.slice(0, 4), samples.buffer.slice(4)]).arrayBuffer();
  const header = new DataView(wav);
  assert.equal(header.getUint32(24, true), 16000);
  assert.equal(header.getUint16(22, true), 1);
  assert.equal(header.getUint32(40, true), 8);
  assert.deepEqual(new Int16Array(wav.slice(44)), samples);
});

test('CSV leaves unmeasured CER empty instead of implying zero error', () => {
  const csv = jobCsv({
    id: 'job', audio_sha256: 'digest', audio_seconds: 2, chunk_seconds: 2, reference: '',
    results: [{ model_id: 'qwen_q8', state: 'failed', transcript: '', error: 'missing', metrics: null }],
  });
  assert.ok(csv.startsWith('\ufeff'));
  assert.ok(csv.includes('"qwen_q8","failed"'));
  assert.ok(!csv.includes('NaN'));
  assert.ok(!csv.includes('undefined'));
});
