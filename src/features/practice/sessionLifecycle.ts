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
  await flushMedia();
  closeMedia();
  try {
    return await requestCompletion();
  } finally {
    closeSocket();
  }
}
