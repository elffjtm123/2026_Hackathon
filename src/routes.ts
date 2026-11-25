export type Route =
  | { page: 'practice' }
  | { page: 'pulse-pos-experiment' }
  | { page: 'not-found' };

// An empty hash and `#practice` both open the practice screen.
export function routeFromHash(hash: string): Route {
  if (!hash || hash === '#' || hash === '#practice' || hash === '#pulse-experiment') return { page: 'practice' };
  if (hash === '#pulse-pos-experiment') return { page: 'pulse-pos-experiment' };
  return { page: 'not-found' };
}
