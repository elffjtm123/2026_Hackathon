import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  PracticeMode,
  PracticeSummary,
  PresentationFeatureSettings,
  RealtimeFeedback,
} from "../types";

const gazeAwayStatuses = new Set(["away", "left", "right", "up", "down"]);
const speechWarningStatuses = new Set(["fast", "slow"]);

function createSessionId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return `session-${Date.now()}`;
}

export function usePracticeSession() {
  const [mode, setMode] = useState<PracticeMode>("interview");
  const [featureSettings, setFeatureSettings] =
    useState<PresentationFeatureSettings>({
      karaokeGuideEnabled: true,
      styleTransferEnabled: true,
    });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [latestFeedback, setLatestFeedback] =
    useState<RealtimeFeedback | null>(null);
  const [gazeAwayCount, setGazeAwayCount] = useState(0);
  const [speechPaceWarningCount, setSpeechPaceWarningCount] = useState(0);
  const [fillerTotalCount, setFillerTotalCount] = useState(0);

  const isRunning = startedAt !== null && endedAt === null;

  useEffect(() => {
    if (!isRunning) {
      return;
    }

    const intervalId = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(intervalId);
  }, [isRunning]);

  const elapsedSeconds = useMemo(() => {
    if (!startedAt) {
      return 0;
    }

    const end = endedAt ?? now;
    return Math.max(0, Math.floor((end - startedAt) / 1000));
  }, [endedAt, now, startedAt]);

  const startSession = useCallback(() => {
    const nextSessionId = createSessionId();
    setSessionId(nextSessionId);
    setStartedAt(Date.now());
    setEndedAt(null);
    setNow(Date.now());
    setLatestFeedback(null);
    setGazeAwayCount(0);
    setSpeechPaceWarningCount(0);
    setFillerTotalCount(0);
    return nextSessionId;
  }, []);

  const endSession = useCallback(() => {
    setEndedAt(Date.now());
  }, []);

  const setFeatureEnabled = useCallback(
    (feature: keyof PresentationFeatureSettings, enabled: boolean) => {
      setFeatureSettings((current) => ({ ...current, [feature]: enabled }));
    },
    []
  );

  const receiveFeedback = useCallback((feedback: RealtimeFeedback) => {
    setLatestFeedback(feedback);
    setFillerTotalCount(feedback.filler.totalCount);

    if (gazeAwayStatuses.has(feedback.gaze.status)) {
      setGazeAwayCount((count) => count + 1);
    }

    if (speechWarningStatuses.has(feedback.speech.pace)) {
      setSpeechPaceWarningCount((count) => count + 1);
    }
  }, []);

  const summary: PracticeSummary | null =
    sessionId && endedAt
      ? {
          sessionId,
          durationSeconds: elapsedSeconds,
          gazeAwayCount,
          speechPaceWarningCount,
          fillerTotalCount,
        }
      : null;

  return {
    mode,
    setMode,
    featureSettings,
    setFeatureEnabled,
    sessionId,
    isRunning,
    elapsedSeconds,
    latestFeedback,
    summary,
    startSession,
    endSession,
    receiveFeedback,
  };
}
