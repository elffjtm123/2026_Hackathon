import { modelThemes, themeFromHash, type ModelTheme } from './features/model-themes/modelThemes.ts';

export type Route =
  | { page: 'practice'; theme: ModelTheme }
  | { page: 'themes' }
  | { page: 'stt-experiments' }
  | { page: 'pulse-pos-experiment' }
  | { page: 'not-found' };

export const themesHash = '#themes';

// An empty hash is ordinary practice with the service theme; model themes are opt-in at #themes.
export function routeFromHash(hash: string): Route {
  if (!hash || hash === '#' || hash === '#pulse-experiment') return { page: 'practice', theme: modelThemes[0] };
  if (hash === themesHash || hash === '#models') return { page: 'themes' };
  if (hash === '#stt-experiments') return { page: 'stt-experiments' };
  if (hash === '#pulse-pos-experiment') return { page: 'pulse-pos-experiment' };
  const theme = themeFromHash(hash);
  return theme ? { page: 'practice', theme } : { page: 'not-found' };
}
