import type { ExperimentJob } from './types';

export function csvCell(value: unknown): string {
  const text = value == null ? '' : String(value);
  // Exported transcripts/references are untrusted spreadsheet cells.
  const safe = /^[\s]*[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function jobCsv(job: ExperimentJob): string {
  const rows: unknown[][] = [[
    'job_id', 'audio_sha256', 'model', 'state', 'audio_seconds', 'chunk_seconds',
    'load_ms', 'warmup_ms', 'processing_ms', 'rtf', 'p95_chunk_ms', 'cer',
    'process_tree_peak_rss_mb', 'process_tree_rss_increase_mb', 'transcript', 'reference', 'error',
  ]];
  for (const result of job.results) rows.push([
    job.id, job.audio_sha256, result.model_id, result.state, job.audio_seconds, job.chunk_seconds,
    result.load_ms, result.warmup_ms, result.metrics?.processing_ms, result.metrics?.rtf,
    result.metrics?.p95_chunk_ms, result.metrics?.cer, result.memory?.process_tree_peak_rss_mb,
    result.memory?.process_tree_rss_increase_mb, result.transcript, job.reference, result.error,
  ]);
  return '\ufeff' + rows.map(row => row.map(csvCell).join(',')).join('\r\n');
}

export function pcmWav(buffers: ArrayBuffer[]): Blob {
  const bytes = buffers.reduce((sum, part) => sum + part.byteLength, 0);
  const header = new ArrayBuffer(44);
  const view = new DataView(header);
  for (const [offset, text] of [[0, 'RIFF'], [8, 'WAVE'], [12, 'fmt '], [36, 'data']] as const)
    [...text].forEach((letter, index) => view.setUint8(offset + index, letter.charCodeAt(0)));
  view.setUint32(4, 36 + bytes, true); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); view.setUint32(40, bytes, true);
  return new Blob([header, ...buffers], { type: 'audio/wav' });
}
