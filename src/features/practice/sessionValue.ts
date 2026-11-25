// This tab's sessionStorage, read defensively: it is missing during SSR and can throw when blocked.
export function readSessionValue(key: string): string | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(key); } catch { return null; }
}
