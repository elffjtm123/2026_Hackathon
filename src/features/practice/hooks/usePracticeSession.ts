import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  PracticeMode,
  PresentationFeatureSettings,
  RealtimeFeedback,
  SessionCompletionReport,
} from "../types";
import {
  emptyFeedbackState,
  reduceFeedback,
  type FeedbackState,
} from "../feedbackState";
import type { SessionPhase } from '../../../lib/realtimeProtocol';
import {summaryForUi} from '../../../lib/realtimeProtocol';
import { practiceElapsedMs } from '../sessionLifecycle';

function createSessionId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return `session-${Date.now()}`;
}

export function usePracticeSession() {
  const [phase, setPhase] = useState<SessionPhase>('completed');
  const [mode, setMode] = useState<PracticeMode>("presentation");
  const [featureSettings, setFeatureSettings] =
    useState<PresentationFeatureSettings>({
      karaokeGuideEnabled: true,
      keywordHintEnabled: false,
    });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [now, setNow] = useState(performance.now());
  const [feedbackState, setFeedbackState] = useState<FeedbackState>(
    emptyFeedbackState
  );
  const [completionReport, setCompletionReport] =
    useState<SessionCompletionReport | null>(null);
  const transcriptRef = useRef("");

  const isRunning = phase === 'running';
  const isActive = ['preparing', 'calibrating', 'running', 'draining'].includes(phase);

  useEffect(() => {
    if (!isRunning) {
      return;
    }

    const intervalId = window.setInterval(() => setNow(performance.now()), 500);
    return () => window.clearInterval(intervalId);
  }, [isRunning]);

  const elapsedSeconds = useMemo(() => {
    const end = endedAt ?? now;
    return Math.floor(practiceElapsedMs(end, startedAt) / 1000);
  }, [endedAt, now, startedAt]);

  const startSession = useCallback(() => {
    const nextSessionId = createSessionId();
    setSessionId(nextSessionId);
    setPhase('preparing');
    setStartedAt(null);
    setEndedAt(null);
    setNow(performance.now());
    setFeedbackState(emptyFeedbackState);
    setCompletionReport(null);
    transcriptRef.current = "";
    return nextSessionId;
  }, []);

  const endSession = useCallback(() => {
    setPhase('failed');
    setEndedAt(performance.now());
  }, []);

  const applyPhase = useCallback((next: SessionPhase, serverId: string, elapsedMs = 0) => {
    setPhase(next); setSessionId(serverId);
    if (next === 'running') {setStartedAt(performance.now() - Math.max(0, elapsedMs)); setNow(performance.now());}
    if (next === 'draining') setEndedAt(current => current ?? performance.now());
  }, []);

  const setFeatureEnabled = useCallback(
    (feature: keyof PresentationFeatureSettings, enabled: boolean) => {
      setFeatureSettings((current) => ({ ...current, [feature]: enabled }));
    },
    []
  );

  const receiveFeedback = useCallback((feedback: RealtimeFeedback) => {
    setFeedbackState((current) => reduceFeedback(current, feedback));

    if (typeof feedback.transcriptSnapshot === 'string')
      transcriptRef.current = feedback.transcriptSnapshot;

  }, []);

  const completeSession = useCallback((report: SessionCompletionReport) => {
    setCompletionReport(report);
    setPhase('completed');
    setEndedAt(current => current ?? performance.now());
  }, []);

  const summary =
    sessionId && endedAt && (phase === 'completed' || phase === 'failed')
      ? summaryForUi(sessionId, completionReport, elapsedSeconds, transcriptRef.current || null)
      : null;

  return {
    mode,
    setMode,
    featureSettings,
    setFeatureEnabled,
    sessionId,
    phase,
    isActive,
    applyPhase,
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
