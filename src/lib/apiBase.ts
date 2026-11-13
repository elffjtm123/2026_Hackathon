// The one place that decides which backend the browser talks to.
type BackendEnv = {VITE_API_BASE_URL?: string; VITE_FEEDBACK_WS_URL?: string};

const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1';
const DEFAULT_FEEDBACK_WS_URL = 'ws://127.0.0.1:8000/api/v1/ws/practice-demo';

/** `ws(s)://host/api/v1/ws/...` -> `http(s)://host/api/v1`. */
export function httpBaseFromWs(wsUrl: string): string {
  const url = new URL(wsUrl);
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = url.pathname.replace(/\/ws\/.*$/, '');
  url.search = ''; url.hash = '';
  return url.toString().replace(/\/$/, '');
}

export function resolveFeedbackWsUrl(env: BackendEnv): string {
  return env.VITE_FEEDBACK_WS_URL ?? DEFAULT_FEEDBACK_WS_URL;
}

/** VITE_API_BASE_URL wins; otherwise the HTTP API lives on the feedback WebSocket's backend. */
export function resolveApiBase(env: BackendEnv): string {
  if (env.VITE_API_BASE_URL !== undefined) return env.VITE_API_BASE_URL.replace(/\/$/, '');
  if (env.VITE_FEEDBACK_WS_URL !== undefined) return httpBaseFromWs(env.VITE_FEEDBACK_WS_URL);
  return DEFAULT_API_BASE;
}

const env: BackendEnv = {
  VITE_API_BASE_URL: import.meta.env?.VITE_API_BASE_URL as string | undefined,
  VITE_FEEDBACK_WS_URL: import.meta.env?.VITE_FEEDBACK_WS_URL as string | undefined,
};
export const apiBase = resolveApiBase(env);
export const feedbackWsUrl = resolveFeedbackWsUrl(env);
