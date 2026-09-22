import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  PracticeMode,
  PracticeSummary,
  PresentationFeatureSettings,
  RealtimeFeedback,
  SessionCompletionReport,
} from "../types";
import {
  emptyFeedbackState,
  reduceFeedback,
  type FeedbackState,
} from "../feedbackState";
import { appendTranscript } from "../scriptTools";

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
    });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [feedbackState, setFeedbackState] = useState<FeedbackState>(
    emptyFeedbackState
  );
  const [completionReport, setCompletionReport] =
    useState<SessionCompletionReport | null>(null);
  const [gazeAwayDurationMs, setGazeAwayDurationMs] = useState(0);
  const [pronunciationAccuracy, setPronunciationAccuracy] = useState<
    number | null
  >(null);
  const [speechPaceWarningCount, setSpeechPaceWarningCount] = useState(0);
  const gazeAwayDurationMsRef = useRef(0);
  const lastGazeSampleAtRef = useRef<number | null>(null);
  const lastGazeWasAwayRef = useRef(false);
  const pronunciationScoresRef = useRef<number[]>([]);
  const transcriptRef = useRef("");

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
    setFeedbackState(emptyFeedbackState);
    setCompletionReport(null);
    setGazeAwayDurationMs(0);
    setPronunciationAccuracy(null);
    setSpeechPaceWarningCount(0);
    gazeAwayDurationMsRef.current = 0;
    lastGazeSampleAtRef.current = null;
    lastGazeWasAwayRef.current = false;
    pronunciationScoresRef.current = [];
    transcriptRef.current = "";
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
    setFeedbackState((current) => reduceFeedback(current, feedback));

    if (feedback.transcript) {
      transcriptRef.current = appendTranscript(
        transcriptRef.current,
        feedback.transcript
      );
    }

    if (feedback.source === undefined || feedback.source === "gaze") {
      const observedAt = feedback.timestamp || Date.now();
      const lastGazeSampleAt = lastGazeSampleAtRef.current;

      if (lastGazeWasAwayRef.current && lastGazeSampleAt !== null) {
        gazeAwayDurationMsRef.current += Math.max(0, observedAt - lastGazeSampleAt);
        setGazeAwayDurationMs(gazeAwayDurationMsRef.current);
      }

      lastGazeSampleAtRef.current = observedAt;
      lastGazeWasAwayRef.current = gazeAwayStatuses.has(
        feedback.gaze?.status ?? "unknown"
      );
    }

    const accuracy = feedback.pronunciation?.accuracy;
    if (typeof accuracy === "number" && Number.isFinite(accuracy)) {
      pronunciationScoresRef.current = [
        ...pronunciationScoresRef.current,
        accuracy,
      ];
      const total = pronunciationScoresRef.current.reduce(
        (sum, score) => sum + score,
        0
      );
      setPronunciationAccuracy(total / pronunciationScoresRef.current.length);
    }

    if (
      (feedback.source === undefined || feedback.source === "speech_rate") &&
      speechWarningStatuses.has(feedback.speech?.pace ?? "unknown")
    ) {
      setSpeechPaceWarningCount((count) => count + 1);
    }
  }, []);

  const completeSession = useCallback((report: SessionCompletionReport) => {
    setCompletionReport(report);
    gazeAwayDurationMsRef.current = report.gaze.awayDurationMs;
    setGazeAwayDurationMs(report.gaze.awayDurationMs);
    setEndedAt(Date.now());
  }, []);

  const summary: PracticeSummary | null =
    sessionId && endedAt
      ? {
          sessionId,
          durationSeconds: elapsedSeconds,
          gazeAwayRatio:
            elapsedSeconds > 0
              ? Math.min(
                  1,
                  (completionReport?.gaze.awayDurationMs ?? gazeAwayDurationMs) /
                    (elapsedSeconds * 1000)
                )
              : 0,
          pronunciationAccuracy:
            pronunciationAccuracy === null
              ? null
              : Math.round(pronunciationAccuracy * 10) / 10,
          speechPaceWarningCount,
          averageSyllablesPerMinute:
            completionReport?.speech.averageSyllablesPerMinute ?? 0,
          fillerWordCounts: completionReport?.filler.counts ?? {},
          transcript:
            completionReport?.transcript ?? (transcriptRef.current || null),
          incomplete: completionReport?.incomplete ?? true,
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
    feedbackState,
    summary,
    startSession,
    endSession,
    completeSession,
    receiveFeedback,
  };
}
