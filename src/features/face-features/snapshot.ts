import type {FaceFeatures} from './features';
import type {PulseResult} from '../pulse/signal';
import type {FeedbackState} from '../practice/feedbackState';

// A timestamped snapshot of separate observations, not a synchronized training label or emotion score.
export function featureSnapshot(face: FaceFeatures, pulse: PulseResult, feedback: FeedbackState,
  nowMs: number, sessionId: string | null, phase: string) {
  const recent = (timestamp: number | undefined, maxAge: number) =>
    timestamp !== undefined && nowMs >= timestamp && nowMs - timestamp <= maxAge;
  const gaze = feedback.gaze, speech = feedback.speech;
  const gazeFresh = recent(gaze?.timestamp, 1500) && !feedback.gazeStale;
  const speechFresh = recent(speech?.timestamp, 5000);
  const pulseFresh = phase !== 'completed' && phase !== 'failed' && !pulse.ended && !pulse.held && pulse.bpm !== null
    && (pulse.status === 'observed' || pulse.status === 'provisional');
  return {schema: 'presentation-features.v1', sessionId, phase, exportedAtSessionMs: nowMs,
    note: 'Separate timestamped observations. Speech rate describes the last utterance; no emotion score is inferred.',
    face,
    pulse: {bpm: pulseFresh ? pulse.bpm : null, status: pulseFresh ? pulse.status : 'not_current',
      source: pulse.model ?? null, resultAgeSeconds: pulse.diagnostics?.resultAgeSeconds ?? pulse.ageSeconds ?? null,
      lastEstimate: pulse.bpm, lastEstimateIsHistorical: !!pulse.held || !!pulse.ended},
    gaze: {timestampMs: gaze?.timestamp ?? null, current: gazeFresh,
      headPose: gazeFresh ? gaze?.gaze?.headPose ?? null : null,
      gazeAngles: gazeFresh ? gaze?.gaze?.gazeAngles ?? null : null,
      qualityFlags: gaze?.gaze?.qualityFlags ?? []},
    speech: {timestampMs: speech?.timestamp ?? null, recent: speechFresh,
      syllablesPerSecond: speechFresh ? speech?.speech?.syllablesPerSecond ?? null : null,
      pace: speechFresh ? speech?.speech?.pace ?? 'unknown' : 'unknown'}};
}
