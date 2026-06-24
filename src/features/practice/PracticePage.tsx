import { useCallback, useMemo, useState } from "react";
import { FeedbackOverlay } from "./components/FeedbackOverlay";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { FeatureToggles } from "./components/FeatureToggles";
import { KaraokeGuide } from "./components/KaraokeGuide";
import { PresentationSetup } from "./components/PresentationSetup";
import { SessionControls } from "./components/SessionControls";
import { SessionSummary } from "./components/SessionSummary";
import { StyleTransferPanel } from "./components/StyleTransferPanel";
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
  const [presentationScript, setPresentationScript] = useState(
    "안녕하세요. 오늘은 실시간 발표 피드백 서비스의 핵심 기능을 소개하겠습니다. 이 서비스는 시선, 발화 속도, 습관어를 실시간으로 확인해 발표자가 더 안정적으로 연습할 수 있도록 돕습니다."
  );
  const [activePresentationScript, setActivePresentationScript] =
    useState(presentationScript);
  const [timeLimitSeconds, setTimeLimitSeconds] = useState(180);
  const [interviewTranscriptText, setInterviewTranscriptText] = useState(
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
    sendVideoFrame: socket.sendVideoFrame,
  });

  const handleStart = useCallback(async () => {
    setIsStarting(true);

    try {
      const nextSessionId = session.startSession();
      await media.startMedia();
      socket.connect(
        nextSessionId,
        session.mode,
        session.featureSettings,
        activePresentationScript,
        timeLimitSeconds
      );
    } catch {
      session.endSession();
      media.stopMedia();
      socket.disconnect();
    } finally {
      setIsStarting(false);
    }
  }, [activePresentationScript, media, session, socket, timeLimitSeconds]);

  const handlePresentationScriptChange = useCallback((script: string) => {
    setPresentationScript(script);
    setActivePresentationScript(script);
  }, []);

  const handleTimeLimitChange = useCallback((seconds: number) => {
    if (Number.isFinite(seconds)) {
      setTimeLimitSeconds(Math.min(1800, Math.max(30, seconds)));
    }
  }, []);

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

      {session.mode === "presentation" ? (
        <>
          <PresentationSetup
            script={presentationScript}
            timeLimitSeconds={timeLimitSeconds}
            disabled={session.isRunning || isStarting}
            onScriptChange={handlePresentationScriptChange}
            onTimeLimitChange={handleTimeLimitChange}
          />
          <FeatureToggles
            settings={session.featureSettings}
            disabled={session.isRunning || isStarting}
            onChange={session.setFeatureEnabled}
          />
        </>
      ) : null}

      {media.error ? <p className="error-banner">{media.error}</p> : null}

      <div className="practice-layout">
        <section className="video-stage" aria-label="카메라 프리뷰">
          <VideoPreview stream={media.stream} />
          {!media.stream ? (
            <div className="video-placeholder">카메라 프리뷰</div>
          ) : null}
          <FeedbackOverlay feedback={session.latestFeedback} />
          {session.mode === "presentation" ? (
            <KaraokeGuide
              script={activePresentationScript}
              timeLimitSeconds={timeLimitSeconds}
              elapsedSeconds={session.elapsedSeconds}
              karaokeEnabled={session.featureSettings.karaokeGuideEnabled}
              keywordHintEnabled={session.featureSettings.keywordHintEnabled}
              backendProgress={socket.scriptProgress}
            />
          ) : null}
        </section>

        <FeedbackPanel
          connectionStatus={socket.status}
          feedback={session.latestFeedback}
          socketError={socket.error}
          isMockMode={isMockMode}
        />
      </div>

      {session.mode === "interview" ? (
        <section className="speech-input-panel" aria-label="백엔드 발화 분석 입력">
          <label htmlFor="transcript-text">백엔드로 보낼 발화 텍스트</label>
          <textarea
            id="transcript-text"
            value={interviewTranscriptText}
            onChange={(event) => setInterviewTranscriptText(event.target.value)}
            rows={3}
            disabled={!session.isRunning || socket.status !== "connected"}
          />
          <button
            type="button"
            className="primary-button"
            disabled={
              !session.isRunning ||
              socket.status !== "connected" ||
              !interviewTranscriptText.trim()
            }
            onClick={() => socket.sendTranscript(interviewTranscriptText, true)}
          >
            현재 텍스트 분석
          </button>
        </section>
      ) : null}

      <SessionSummary summary={session.summary} />

      {session.mode === "presentation" ? (
        <StyleTransferPanel
          originalScript={presentationScript}
          currentScript={activePresentationScript}
          timeLimitSeconds={timeLimitSeconds}
          disabled={session.isRunning || isStarting}
          enabled={session.featureSettings.styleTransferEnabled}
          onApply={setActivePresentationScript}
          onReset={() => setActivePresentationScript(presentationScript)}
        />
      ) : null}
    </main>
  );
}
