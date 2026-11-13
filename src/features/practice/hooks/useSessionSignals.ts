import { useCallback, useMemo, useRef, useState } from 'react';
import { isRecordingPhase, type SessionPhase } from '../../../lib/realtimeProtocol';
import { emptyPulse, type PulseResult } from '../../pulse/signal';
import { emptyFaceFeatures, type FaceFeatures } from '../../face-features/features';
import { SessionSignalRecorder } from '../../affect/analysis';

// Browser-side face and pulse readouts: the live display values plus the bounded in-memory
// recording of the running practice that the end-of-session insights use.
export function useSessionSignals(phase: SessionPhase, sessionTime: () => number, completedSessionId: string | null) {
  const [pulse, setPulse] = useState<PulseResult>(emptyPulse);
  const [faceFeaturesEnabled, setFaceFeaturesEnabled] = useState(true);
  const [faceFeatures, setFaceFeatures] = useState<FaceFeatures>(emptyFaceFeatures);
  const recorder = useRef(new SessionSignalRecorder());
  const phaseRef = useRef(phase); phaseRef.current = phase;
  const receiveFaceFeatures = useCallback((result: FaceFeatures) => {
    if (isRecordingPhase(phaseRef.current)) recorder.current.face(result);
    setFaceFeatures(result);
  }, []);
  const receivePulse = useCallback((result: PulseResult) => {
    if (isRecordingPhase(phaseRef.current)) recorder.current.pulse(result, sessionTime());
    setPulse(result);
  }, [sessionTime]);
  const resetRecording = useCallback(() => recorder.current.reset(), []);
  // One stable copy per completed session, so the insights are not recomputed on every render.
  const recorded = useMemo(() => completedSessionId ? recorder.current.snapshot() : null, [completedSessionId]);
  return { pulse, faceFeatures, faceFeaturesEnabled, setFaceFeaturesEnabled, receiveFaceFeatures, receivePulse,
    resetRecording, recorded };
}
