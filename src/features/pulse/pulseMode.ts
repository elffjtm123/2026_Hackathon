// Which pulse method runs: the local backend's pretrained model, or browser-only POS as fallback.
export type PulseMethod = 'pos' | 'efficientphys';
export type PulseModeState = {mode: PulseMethod; fallbackReason: string | null};
export type PulseBackendCheck = {ok: true} | {ok: false; reason: string};
type FetchLike = (url: string) => Promise<{ok: boolean; json: () => Promise<unknown>}>;

const LOCAL_HOSTS = ['127.0.0.1', 'localhost', '[::1]'];

/** Can the local backend run `modelId`? Face crops are never sent to a non-local host. */
export async function checkPulseBackend(api: string, modelId: string,
  fetchImpl: FetchLike = fetch): Promise<PulseBackendCheck> {
  if (!LOCAL_HOSTS.includes(new URL(api).hostname))
    return {ok: false, reason: '얼굴 크롭은 로컬 백엔드에만 전송할 수 있습니다.'};
  try {
    const response = await fetchImpl(`${api}/model?model_id=${modelId}`);
    const status = await response.json() as {available?: boolean; error?: {message?: string}};
    if (!response.ok || !status.available)
      return {ok: false, reason: status.error?.message ?? 'EfficientPhys 가중치가 준비되지 않았습니다.'};
    return {ok: true};
  } catch {
    return {ok: false, reason: '맥박 백엔드 연결 실패'};
  }
}

export const initialPulseMode = (requested: PulseMethod): PulseModeState => ({mode: requested, fallbackReason: null});

/** With auto fallback, a backend model that cannot run hands over to browser POS. */
export function pulseModeAfterCheck(state: PulseModeState, check: PulseBackendCheck,
  autoFallback: boolean): PulseModeState {
  if (check.ok || !autoFallback || state.mode !== 'efficientphys') return state;
  return {mode: 'pos', fallbackReason: check.reason};
}

export function pulseMethodLabel(state: PulseModeState, modelName: string): string {
  return state.mode === 'pos' ? '브라우저 추정(POS)' : `사전학습 모델(${modelName})`;
}
