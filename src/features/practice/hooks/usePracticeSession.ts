import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [mode, setMode] = useState<PracticeMode>("presentation");
  const [featureSettings, setFeatureSettings] =
    useState<PresentationFeatureSettings>({
      karaokeGuideEnabled: true,
      keywordHintEnabled: false,
      styleTransferEnabled: true,
    });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [latestFeedback, setLatestFeedback] =
    useState<RealtimeFeedback | null>(null);
  const [gazeAwayDurationMs, setGazeAwayDurationMs] = useState(0);
  const [speechPaceWarningCount, setSpeechPaceWarningCount] = useState(0);
  const [fillerTotalCount, setFillerTotalCount] = useState(0);
  const gazeAwayDurationMsRef = useRef(0);
  const lastGazeSampleAtRef = useRef<number | null>(null);
  const lastGazeWasAwayRef = useRef(false);

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
    setGazeAwayDurationMs(0);
    setSpeechPaceWarningCount(0);
    setFillerTotalCount(0);
    gazeAwayDurationMsRef.current = 0;
    lastGazeSampleAtRef.current = null;
    lastGazeWasAwayRef.current = false;
    return nextSessionId;
  }, []);

  const endSession = useCallback(() => {
    const endedAtMs = Date.now();
    const lastGazeSampleAt = lastGazeSampleAtRef.current;

    if (lastGazeWasAwayRef.current && lastGazeSampleAt !== null) {
      gazeAwayDurationMsRef.current += Math.max(0, endedAtMs - lastGazeSampleAt);
      setGazeAwayDurationMs(gazeAwayDurationMsRef.current);
      lastGazeSampleAtRef.current = endedAtMs;
    }

    setEndedAt(endedAtMs);
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

    if (feedback.source === undefined || feedback.source === "gaze") {
      const observedAt = feedback.timestamp || Date.now();
      const lastGazeSampleAt = lastGazeSampleAtRef.current;

      if (lastGazeWasAwayRef.current && lastGazeSampleAt !== null) {
        gazeAwayDurationMsRef.current += Math.max(0, observedAt - lastGazeSampleAt);
        setGazeAwayDurationMs(gazeAwayDurationMsRef.current);
      }

      lastGazeSampleAtRef.current = observedAt;
      lastGazeWasAwayRef.current = gazeAwayStatuses.has(feedback.gaze.status);
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
          gazeAwayRatio:
            elapsedSeconds > 0
              ? Math.min(1, gazeAwayDurationMs / (elapsedSeconds * 1000))
              : 0,
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
