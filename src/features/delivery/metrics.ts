export type DeliveryRow = Record<string, number | null>;
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
