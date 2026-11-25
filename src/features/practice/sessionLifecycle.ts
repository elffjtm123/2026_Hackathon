import type { PracticeMode, PresentationFeatureSettings, SessionCompletionReport } from "./types";
import { isRecordingPhase, type SessionPhase } from '../../lib/realtimeProtocol.ts';

// Audio is captured from running until the report is requested. A round break does not change the
// client phase, so capture (and its sample counter) runs straight through it.
export function captureAudioWanted(phase: SessionPhase, connection: string): boolean {
  return isRecordingPhase(phase) && connection === 'connected';
}

// Auto gain control flattens loudness, which the delivery analysis measures. Echo cancellation and
// noise suppression stay at browser defaults.
export const MICROPHONE_CONSTRAINTS = { autoGainControl: false };

export type AudioSettings = { autoGainControl: boolean };

export function audioSettingsOf(stream: Pick<MediaStream, 'getAudioTracks'> | null): AudioSettings | undefined {
  const applied = stream?.getAudioTracks()[0]?.getSettings().autoGainControl;
  return typeof applied === 'boolean' ? { autoGainControl: applied } : undefined;
}

// A server `error` event ends the session unless it only reports something that was handled. A failed
// round break is followed by `interview.finished`, so the session still has to end normally.
const NON_FATAL_ERRORS = ['CALIBRATION_TIMEOUT', 'INTERVIEW_ROUND_BREAK_FAILED'];
export const isFatalServerError = (code: string) => !NON_FATAL_ERRORS.includes(code);

export type InterviewStart = {interview_id: string; question_ids: string[]};

export function sessionStartData(mode: PracticeMode, settings: PresentationFeatureSettings,
    script: string | undefined, timeLimitSeconds: number | undefined, interview?: InterviewStart | null) {
  return {
    mode,
    ...(mode === 'interview' && interview ? {interview} : {}),
    settings: {karaoke_guide_enabled: settings.karaokeGuideEnabled, delivery_enabled: settings.deliveryEnabled},
    ...(mode === 'presentation' && script ? {script, time_limit_seconds: timeLimitSeconds} : {}),
  };
}

// The applied AGC is only known after the microphone permission prompt. It is sent as a follow-up
// event so model preparation (and its readiness timer) never waits for the prompt. A denied or
// missing microphone, a closed socket or a failing send simply leaves agc_on unreported.
export async function deliverAudioSettings(audioSettings: Promise<AudioSettings | undefined> | undefined,
    send: (applied: AudioSettings) => void, isOpen: () => boolean) {
  try {
    const applied = await audioSettings;
    if (applied && isOpen()) send(applied);
  } catch { /* nothing to report */ }
}

type CompletePracticeSessionOptions = {
  flushMedia: () => Promise<void>;
  closeMedia: () => void;
  requestCompletion: () => Promise<SessionCompletionReport>;
  closeSocket: () => void;
};

export async function completePracticeSession({
  flushMedia,
  closeMedia,
  requestCompletion,
  closeSocket,
}: CompletePracticeSessionOptions) {
  let mediaClosed = false;
  try {
    await flushMedia();
    mediaClosed = true;
    closeMedia();
    return await requestCompletion();
  } finally {
    try { if (!mediaClosed) closeMedia(); } finally { closeSocket(); }
  }
}

export function acceptCurrentMedia(stream: MediaStream, generation: number, current: number) {
  if (generation !== current) {
    stream.getTracks().forEach(track => track.stop());
    throw new Error('시작이 취소되었습니다.');
  }
  return stream;
}

export function acceptServerEvent(event: {version: number; session_id: string; sequence: number}, sessionId: string, lastSequence: number) {
  return event.version === 2 && event.session_id === sessionId && Number.isSafeInteger(event.sequence) && event.sequence > lastSequence;
}

export function practiceElapsedMs(now: number, runningStarted: number | null) {
  return runningStarted === null ? 0 : Math.max(0, now - runningStarted);
}

export function captureSize(width: number, height: number) {
  const scale = Math.min(1, 640 / width);
  return {width: Math.round(width * scale), height: Math.round(height * scale)};
}

export function checkMediaBacklog(bufferedBytes: number, unackedSamples: number) {
  if (bufferedBytes > 256 * 1024 || unackedSamples > 32000) {
    throw new Error('실시간 처리량 한도를 초과했습니다. 세션 결과가 미완료될 수 있습니다.');
  }
}
