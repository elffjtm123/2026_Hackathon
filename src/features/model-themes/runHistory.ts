import type { PracticeSummary } from '../../lib/realtimeProtocol.ts';
import { deliveryForUi, deliveryForUser } from '../delivery/metrics.ts';

export const historyKey = 'live-model-runs-v1';
export type SavedRun = { id: string; createdAt: string; note: string; summary: PracticeSummary };
type RunStorage = {getItem(key: string): string | null; setItem(key: string, value: string): void};
export function readRuns(storage: RunStorage): SavedRun[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(historyKey) ?? '[]');
    if (!Array.isArray(value)) return [];
    return value.filter(run => typeof run?.id === 'string' && typeof run?.createdAt === 'string'
      && typeof run?.note === 'string' && typeof run?.summary?.durationSeconds === 'number'
      && typeof run?.summary?.comparison?.model_id === 'string').slice(0, 20);
  } catch { return []; }
}
// Exported and stored copies carry only the delivery measures users may see.
export function summaryForUser(summary: PracticeSummary): PracticeSummary {
  const raw = summary.backendReport;
  const backendReport = raw && 'delivery_metrics' in raw
    ? {...raw, delivery_metrics: deliveryForUser(deliveryForUi(raw.delivery_metrics)) ?? null} : raw;
  return {...summary, backendReport, deliveryMetrics: deliveryForUser(summary.deliveryMetrics)};
}
export function storeRun(storage: RunStorage, run: SavedRun) {
  run = {...run, summary: summaryForUser(run.summary)};
  storage.setItem(historyKey, JSON.stringify([run, ...readRuns(storage).filter(old => old.id !== run.id)].slice(0, 20)));
}
export function readSessionValue(key: string): string | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(key); } catch { return null; }
}
