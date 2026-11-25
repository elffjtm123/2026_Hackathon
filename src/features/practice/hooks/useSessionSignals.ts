import { useCallback, useMemo, useRef, useState } from 'react';
import { isRecordingPhase, type SessionPhase } from '../../../lib/realtimeProtocol';
import { emptyPulse, type PulseResult } from '../../pulse/signal';
import { emptyFaceFeatures, type FaceFeatures } from '../../face-features/features';
import { closeOpenBreaks } from '../../interview/interviewState';
import { SessionSignalRecorder, type TimeSpan } from '../../affect/analysis';

// Browser-side face and pulse readouts: the live display values plus the bounded in-memory
// recording of the running practice that the end-of-session insights use.
// `getBreaks` gives the interview's round-break spans (session ms); the one still open at the end is
// closed at the session clock. Pulse estimates are recorded through a break, never cut out.
export function useSessionSignals(phase: SessionPhase, sessionTime: () => number, completedSessionId: string | null,
    getBreaks?: () => {startMs: number; endMs: number | null}[]) {
  const [pulse, setPulse] = useState<PulseResult>(emptyPulse);
  const [faceFeaturesEnabled, setFaceFeaturesEnabled] = useState(true);
  const [faceFeatures, setFaceFeatures] = useState<FaceFeatures>(emptyFaceFeatures);
  const recorder = useRef(new SessionSignalRecorder());
  const phaseRef = useRef(phase); phaseRef.current = phase;
  const breaksRef = useRef(getBreaks); breaksRef.current = getBreaks;
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
  const recorded = useMemo(() => {
    if (!completedSessionId) return null;
    const now = sessionTime();
    const breaks: TimeSpan[] = closeOpenBreaks(breaksRef.current?.() ?? [], now);
    return recorder.current.snapshot(breaks, now);
  }, [completedSessionId, sessionTime]);
  return { pulse, faceFeatures, faceFeaturesEnabled, setFaceFeaturesEnabled, receiveFaceFeatures, receivePulse,
    resetRecording, recorded };
}
