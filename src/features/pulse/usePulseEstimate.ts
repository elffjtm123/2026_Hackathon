import { useCallback, useEffect, useState, type RefObject } from 'react';
import { usePulse, type FaceFeatureOptions } from './usePulse';
import { pulseForReport } from './pulseReport';
import type { PulseModelId } from './models';
import type { PulseResult } from './signal';
import { initialPulseMode, pulseModeAfterCheck } from './pulseMode';

type Options = {
  stream: MediaStream | null;
  enabled: boolean;
  requestedMode?: 'pos' | 'efficientphys';
  videoRef?: RefObject<HTMLVideoElement | null>;
  modelId?: PulseModelId;
  faceFeatures?: FaceFeatureOptions;
  /** Switch to browser POS, instead of failing, when the backend model cannot run. */
  autoFallback?: boolean;
  onResult?: (result: PulseResult) => void;
};

// The pulse estimator without any panel: shared by the experiment panel and the practice screen.
export function usePulseEstimate({stream, enabled, requestedMode = 'pos', videoRef, modelId = 'ma_ubfc_tscan',
  faceFeatures, autoFallback = false, onResult}: Options) {
  const [modeState, setModeState] = useState(() => initialPulseMode(requestedMode));
  const fallBack = useCallback((reason: string) =>
    setModeState(current => pulseModeAfterCheck(current, {ok: false, reason}, true)), []);
  const result = usePulse(stream, enabled, modeState.mode, videoRef, modelId, faceFeatures, autoFallback ? fallBack : undefined);
  useEffect(() => { onResult?.(pulseForReport(enabled, !!stream, result)); }, [result, enabled, stream, onResult]);
  return {result, modeState};
}
