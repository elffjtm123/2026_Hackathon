import { useCallback, useMemo, useState } from "react";
import { FeedbackOverlay } from "./components/FeedbackOverlay";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { SessionControls } from "./components/SessionControls";
import { SessionSummary } from "./components/SessionSummary";
import { VideoPreview } from "./components/VideoPreview";
import { useBackendStreaming } from "./hooks/useBackendStreaming";
import { useFeedbackSocket } from "./hooks/useFeedbackSocket";
import { useMockFeedback } from "./hooks/useMockFeedback";
import { usePracticeSession } from "./hooks/usePracticeSession";
import { useUserMedia } from "./hooks/useUserMedia";

export function PracticePage() {
  const session = usePracticeSession();
  const media = useUserMedia();
  const [isStarting, setIsStarting] = useState(false);
  const [transcriptText, setTranscriptText] = useState(
    "음 저는 오늘 프로젝트의 핵심 기능을 소개하겠습니다."
  );
  const socket = useFeedbackSocket(session.receiveFeedback);

  const isMockMode = useMemo(
    () =>
      session.isRunning &&
      (socket.status === "disconnected" || socket.status === "error"),
    [session.isRunning, socket.status]
  );

  useMockFeedback(
    isMockMode,
    session.sessionId,
    session.receiveFeedback
  );

  useBackendStreaming({
    isActive: session.isRunning && socket.status === "connected",
    stream: media.stream,
    transcriptText,
    sendTranscript: socket.sendTranscript,
    sendVideoFrame: socket.sendVideoFrame,
  });

  const handleStart = useCallback(async () => {
    setIsStarting(true);

    try {
      const nextSessionId = session.startSession();
      await media.startMedia();
      socket.connect(nextSessionId, session.mode);
    } catch {
      session.endSession();
      media.stopMedia();
      socket.disconnect();
    } finally {
      setIsStarting(false);
    }
  }, [media, session, socket]);

  const handleEnd = useCallback(() => {
    if (session.sessionId) {
      socket.send({
        type: "session.end",
        sessionId: session.sessionId,
        timestamp: Date.now(),
      });
    }

    socket.disconnect();
    media.stopMedia();
    session.endSession();
  }, [media, session, socket]);

  return (
    <main className="practice-shell">
      <header className="practice-header">
        <div>
          <p className="eyebrow">Realtime Coach</p>
          <h1>발표 및 면접 실시간 피드백</h1>
        </div>
      </header>

      <SessionControls
        mode={session.mode}
        isRunning={session.isRunning}
        isStarting={isStarting}
        elapsedSeconds={session.elapsedSeconds}
        onModeChange={session.setMode}
        onStart={handleStart}
        onEnd={handleEnd}
      />

      {media.error ? <p className="error-banner">{media.error}</p> : null}

      <div className="practice-layout">
        <section className="video-stage" aria-label="카메라 프리뷰">
          <VideoPreview stream={media.stream} />
          {!media.stream ? (
            <div className="video-placeholder">카메라 프리뷰</div>
          ) : null}
          <FeedbackOverlay feedback={session.latestFeedback} />
        </section>

        <FeedbackPanel
          connectionStatus={socket.status}
          feedback={session.latestFeedback}
          socketError={socket.error}
          isMockMode={isMockMode}
        />
      </div>

      <section className="speech-input-panel" aria-label="백엔드 발화 분석 입력">
        <label htmlFor="transcript-text">백엔드로 보낼 발화 텍스트</label>
        <textarea
          id="transcript-text"
          value={transcriptText}
          onChange={(event) => setTranscriptText(event.target.value)}
          rows={3}
        />
      </section>

      <SessionSummary summary={session.summary} />
    </main>
  );
}
