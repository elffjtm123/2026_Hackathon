import type { SessionCompletionReport } from "./types";

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
