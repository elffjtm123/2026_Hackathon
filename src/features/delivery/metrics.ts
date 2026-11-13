export type DeliveryRow = Record<string, number | null>;
// Per-sentence and per-window measures the backend analyzer emits (app/modules/delivery).
export type DeliveryField = 'start_ms' | 'end_ms' | 'voiced_ms' | 'coverage' | 'speech_rate' | 'articulation_rate'
  | 'f0_median_hz' | 'f0_st' | 'pvq' | 'loudness_dbfs' | 'loudness_rel_db' | 'alpha_ratio_db' | 'hammarberg_db'
  | 'pause_count' | 'longest_pause_ms' | 'sentence_end_pause_ms' | 'disfluency_density' | 'sentence_index';
export type DeliveryMetrics = {
  status: 'observed' | 'unavailable' | 'disabled' | 'failed'; agc_on: boolean | null;
  report: {status?: string; reason?: string | null; total_voiced_ms: number;
    sentences: DeliveryRow[]; baseline: DeliveryRow; bursts: DeliveryRow[]} | null;
  windows: {window_ms: number; baseline: DeliveryRow; windows: DeliveryRow[]} | null;
};
const object = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const number = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v : null;
const row = (v: unknown): DeliveryRow => object(v) ? Object.fromEntries(Object.entries(v).map(([k, v]) => [k, number(v)])) : {};
const rows = (v: unknown) => Array.isArray(v) ? v.filter(object).map(row) : [];
export function deliveryForUi(raw: unknown): DeliveryMetrics | undefined {
  if (!object(raw) || !['observed', 'unavailable', 'disabled', 'failed'].includes(String(raw.status))) return undefined;
  const report = object(raw.report) ? raw.report : null, windows = object(raw.windows) ? raw.windows : null;
  return {status: raw.status as DeliveryMetrics['status'], agc_on: typeof raw.agc_on === 'boolean' ? raw.agc_on : null,
    report: report ? {status: typeof report.status === 'string' ? report.status : undefined,
      reason: typeof report.reason === 'string' ? report.reason : null, total_voiced_ms: number(report.total_voiced_ms) ?? 0,
      sentences: rows(report.sentences), baseline: row(report.baseline), bursts: rows(report.bursts)} : null,
    windows: windows ? {window_ms: number(windows.window_ms) ?? 10000, baseline: row(windows.baseline), windows: rows(windows.windows).slice(0,720)} : null};
}

// Measured for the backend analysis but withheld from users: PVQ (no evidence it tracks delivery),
// absolute loudness (depends on the microphone and room) and spectral balance (not validated).
const WITHHELD = ['pvq', 'loudness_dbfs', 'alpha_ratio_db', 'hammarberg_db'] as const satisfies readonly DeliveryField[];
// Loudness is shown only as a change within the session, and only when AGC was confirmed off.
export function deliveryForUser(metrics: DeliveryMetrics | undefined): DeliveryMetrics | undefined {
  if (!metrics) return undefined;
  const hidden: readonly string[] = metrics.agc_on === false ? WITHHELD : [...WITHHELD, 'loudness_rel_db' satisfies DeliveryField];
  const visible = (value: DeliveryRow): DeliveryRow => Object.fromEntries(Object.entries(value).filter(([key]) => !hidden.includes(key)));
  return {...metrics,
    report: metrics.report ? {...metrics.report, sentences: metrics.report.sentences.map(visible), baseline: visible(metrics.report.baseline)} : null,
    windows: metrics.windows ? {...metrics.windows, windows: metrics.windows.windows.map(visible), baseline: visible(metrics.windows.baseline)} : null};
}
