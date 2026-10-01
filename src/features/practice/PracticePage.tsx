import { useCallback, useEffect, useRef, useState } from "react";
import { FeedbackOverlay } from "./components/FeedbackOverlay";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { FeatureToggles } from "./components/FeatureToggles";
import { InterviewContent } from "./components/InterviewContent";
import { KaraokeGuide } from "./components/KaraokeGuide";
import { PresentationSetup } from "./components/PresentationSetup";
import { SessionControls } from "./components/SessionControls";
import { SessionSummary } from "./components/SessionSummary";
import { VideoPreview } from "./components/VideoPreview";
import { useBackendStreaming } from "./hooks/useBackendStreaming";
import { useFeedbackSocket } from "./hooks/useFeedbackSocket";
import { usePracticeSession } from "./hooks/usePracticeSession";
import { useUserMedia } from "./hooks/useUserMedia";
import { completePracticeSession } from "./sessionLifecycle";
import type { PracticeMode } from "./types";
import {selectVisibleFeedback} from './feedbackState';

export function PracticePage() {
  const session = usePracticeSession();
  const media = useUserMedia();
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [feedbackNow, setFeedbackNow] = useState(performance.now());
  useEffect(() => {
    if (!session.isActive) return;
    const timer = window.setInterval(() => setFeedbackNow(performance.now()), 250);
    return () => window.clearInterval(timer);
  }, [session.isActive]);
  const visibleFeedback = selectVisibleFeedback(session.feedbackState, feedbackNow);
  const generationRef = useRef(0);
  const endingRef = useRef(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [completedMode, setCompletedMode] = useState<PracticeMode | null>(null);
  const [presentationScript, setPresentationScript] = useState(
    "안녕하세요. 오늘은 실시간 발표 피드백 서비스의 핵심 기능을 소개하겠습니다. 이 서비스는 시선, 발화 속도, 발음 정확도를 확인해 발표자가 더 안정적으로 연습할 수 있도록 돕습니다."
  );
  const [timeLimitSeconds, setTimeLimitSeconds] = useState(180);
  const socket = useFeedbackSocket(session.receiveFeedback, session.applyPhase);
  const streaming = useBackendStreaming({
    isActive: ['calibrating', 'running', 'draining'].includes(session.phase) && socket.status === "connected",
    captureAudio: ['running', 'draining'].includes(session.phase) && socket.status === 'connected',
    stream: media.stream,
    audioContext: media.audioContext,
    sessionTime: socket.sessionTime,
    sendVideoFrame: socket.sendVideoFrame,
    sendAudioPacket: socket.sendAudioPacket,
    awaitAudioAck: socket.awaitAudioAck,
    onError: socket.reportCaptureError,
  });

  const handleStart = useCallback(async () => {
    const generation = ++generationRef.current;
    setIsStarting(true);
    setOperationError(null);
    setCompletedMode(null);

    try {
      const nextSessionId = session.startSession();
      const mediaReady = media.startMedia();
      const ready = socket.connect(
        nextSessionId,
        session.mode,
        session.featureSettings,
        presentationScript,
        timeLimitSeconds
      );
      await Promise.all([mediaReady, ready]);
      if (generation !== generationRef.current) return;
      socket.startCalibration();
    } catch (error) {
      if (generation === generationRef.current) {
        setOperationError(error instanceof Error ? error.message : '시작하지 못했습니다.');
        session.endSession(); media.stopMedia(); socket.disconnect();
      }
    } finally {
      if (generation === generationRef.current) setIsStarting(false);
    }
  }, [media, presentationScript, session, socket, timeLimitSeconds]);

  const handleTimeLimitChange = useCallback((seconds: number) => {
    if (Number.isFinite(seconds)) {
      setTimeLimitSeconds(Math.min(1800, Math.max(30, seconds)));
    }
  }, []);

  const handleEnd = useCallback(async () => {
    if (!session.sessionId || endingRef.current) {
      return;
    }

    setIsStopping(true);
    endingRef.current = true;
    generationRef.current++;
    setIsStarting(false);
    try {
      if (session.phase === 'preparing' || session.phase === 'calibrating') {
        media.stopMedia();
        const report = await socket.finish(session.sessionId);
        session.completeSession(report);
        socket.disconnect();
        return;
      }
      const report = await completePracticeSession({
        flushMedia: streaming.stopStreaming,
        closeMedia: media.stopMedia,
        requestCompletion: () => socket.finish(session.sessionId!),
        closeSocket: socket.disconnect,
      });
      session.completeSession(report);
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '결과가 미완료되었습니다.');
      media.stopMedia(); socket.disconnect();
      session.endSession();
    } finally {
      setCompletedMode(session.mode);
      setIsStopping(false);
      endingRef.current = false;
    }
  }, [media, session, socket, streaming.stopStreaming]);

  useEffect(() => {
    if (socket.status === 'error' && session.isActive && !endingRef.current) {
      generationRef.current++;
      media.stopMedia(); session.endSession(); setIsStarting(false);
      socket.disconnect();
    }
  }, [media, session, socket]);

  useEffect(() => {
    if (
      session.mode === "presentation" &&
      session.isRunning &&
      session.elapsedSeconds >= timeLimitSeconds
    ) {
      void handleEnd();
    }
  }, [
    handleEnd,
    session.elapsedSeconds,
    session.isRunning,
    session.mode,
    timeLimitSeconds,
  ]);

  return (
    <main className={`practice-shell${session.mode === "interview" ? " practice-shell--interview" : ""}`}>
      <header className="practice-header">
        <div>
          <p className="eyebrow">Realtime Coach</p>
          <h1>{session.mode === "interview" ? "면접 연습" : "발표 및 면접 실시간 피드백"}</h1>
        </div>
      </header>

      <SessionControls
        mode={session.mode}
        isRunning={session.isActive}
        isStarting={isStarting || session.phase === 'calibrating'}
        isStopping={isStopping}
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
            disabled={session.isActive || isStarting}
            onScriptChange={setPresentationScript}
            onTimeLimitChange={handleTimeLimitChange}
          />
          <FeatureToggles
            settings={session.featureSettings}
            disabled={false}
            onChange={session.setFeatureEnabled}
          />
        </>
      ) : null}

      {media.error ? <p className="error-banner">{media.error}</p> : null}
      {operationError ? <p className="error-banner" role="alert">{operationError}</p> : null}
      {session.phase === 'calibrating' ? <p role="status">카메라를 바라보며 보정 중입니다. 연습 시간은 보정 완료 후 시작합니다.</p> : null}
      {['calibrating', 'running'].includes(session.phase) && socket.status === 'connected' ? <button type="button" className="secondary-button" onClick={socket.startCalibration}>다시 보정</button> : null}
      {session.phase === 'draining' ? <p role="status">마지막 음성을 분석하고 있습니다.</p> : null}
      <div aria-label="모델 상태">{Object.entries(socket.modules).map(([name, module]) =>
        <span key={name}>{name === 'gaze' ? '시선' : '음성'}: {module.status === 'unavailable' ? '사용 불가' : module.model ?? module.provider}{module.device ? ' (' + module.device + ')' : ''} · </span>
      )}</div>

      {session.mode === "interview" ? (
        <InterviewContent
          stream={media.stream}
          feedback={visibleFeedback}
          connectionStatus={socket.status}
          socketError={socket.error}
          isRunning={session.isActive}
          isStopping={isStopping}
          onEnd={handleEnd}
          summary={completedMode === "interview" ? session.summary : null}
        />
      ) : (
        <>
          <div className="practice-layout">
            <section className="video-stage" aria-label="카메라 프리뷰">
              <VideoPreview stream={media.stream} />
              {!media.stream ? (
                <div className="video-placeholder">카메라 프리뷰</div>
              ) : null}
              <FeedbackOverlay feedback={visibleFeedback} />
              <KaraokeGuide
                script={presentationScript}
                timeLimitSeconds={timeLimitSeconds}
                elapsedSeconds={session.elapsedSeconds}
                karaokeEnabled={session.featureSettings.karaokeGuideEnabled}
                keywordHintEnabled={session.featureSettings.keywordHintEnabled}
              />
            </section>
            <FeedbackPanel
              connectionStatus={socket.status}
              feedback={visibleFeedback}
              socketError={socket.error}
            />
          </div>
          <SessionSummary summary={session.summary} />
        </>
      )}
    </main>
  );
}
