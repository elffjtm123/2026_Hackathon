import { useEffect, useRef, useState } from "react";
import { FeatureToggles } from "./components/FeatureToggles";
import { InterviewContent } from "./components/InterviewContent";
import { LiveStage } from "./components/LiveStage";
import { PresentationSetup, TimeLimitField } from "./components/PresentationSetup";
import { SessionControls } from "./components/SessionControls";
import { SessionStatus } from "./components/SessionStatus";
import { SessionSummary } from "./components/SessionSummary";
import { useBackendStreaming } from "./hooks/useBackendStreaming";
import { useFeedbackSocket } from "./hooks/useFeedbackSocket";
import { usePracticeSession } from "./hooks/usePracticeSession";
import { useUserMedia } from "./hooks/useUserMedia";
import { usePracticeLifecycle } from "./hooks/usePracticeLifecycle";
import { usePresentationScript } from "./hooks/usePresentationScript";
import { useSessionSignals } from "./hooks/useSessionSignals";
import { DataNotes } from "./components/DataNotes";
import { practiceStage, showPageSocketError } from "./practiceStage";
import {selectVisibleFeedback} from './feedbackState';
import {isRecordingPhase} from '../../lib/realtimeProtocol';
import { readSessionValue } from './sessionValue';
import { usePulseEstimate } from '../pulse/usePulseEstimate';
import { pulseResearchCaution } from '../pulse/pulseReport';
import {SessionInsights} from '../affect/SessionInsights';
import '../delivery/delivery.css';

export function PracticePage({onActivityChange}: {onActivityChange?: (busy: boolean) => void}) {
  const session = usePracticeSession(readSessionValue('live-practice-mode') === 'interview' ? 'interview' : 'presentation');
  const media = useUserMedia();
  const presentationVideo = useRef<HTMLVideoElement | null>(null);
  const script = usePresentationScript(session.mode);
  const socket = useFeedbackSocket(session.receiveFeedback, session.applyPhase);
  const signals = useSessionSignals(session.phase, socket.sessionTime, session.summary?.sessionId ?? null);
  const streaming = useBackendStreaming({
    isActive: ['calibrating', 'running', 'draining'].includes(session.phase) && socket.status === "connected",
    captureAudio: isRecordingPhase(session.phase) && socket.status === 'connected',
    stream: media.stream,
    videoRef: presentationVideo,
    audioContext: media.audioContext,
    sessionTime: socket.sessionTime,
    sendVideoFrame: socket.sendVideoFrame,
    sendAudioPacket: socket.sendAudioPacket,
    awaitAudioAck: socket.awaitAudioAck,
    onError: socket.reportCaptureError,
  });
  // Pulse and face features run for every practice, with no panel: the same estimator the
  // experiment panel uses, the pretrained model first and browser POS when the backend cannot run it.
  const pulseEstimate = usePulseEstimate({stream: media.stream, enabled: true, requestedMode: 'efficientphys', videoRef: presentationVideo,
    autoFallback: true, onResult: signals.receivePulse,
    faceFeatures: {enabled: true, onResult: signals.receiveFaceFeatures, sessionTime: socket.sessionTime}});
  const lifecycle = usePracticeLifecycle({session, media, socket, flushStreaming: streaming.stopStreaming,
    script: script.script, timeLimitSeconds: script.timeLimitSeconds, isSummaryPending: script.isSummaryPending,
    onBeforeStart: signals.resetRecording, onActivityChange});
  const {locked, isStarting, isStopping, operationError, completedMode} = lifecycle;
  const busy = locked || script.isSummarizing;
  useEffect(() => { onActivityChange?.(busy); return () => onActivityChange?.(false); }, [busy, onActivityChange]);
  const [feedbackNow, setFeedbackNow] = useState(performance.now());
  useEffect(() => {
    if (!session.isActive) return;
    const timer = window.setInterval(() => setFeedbackNow(performance.now()), 250);
    return () => window.clearInterval(timer);
  }, [session.isActive]);
  const visibleFeedback = selectVisibleFeedback(session.feedbackState, feedbackNow);
  const stage = practiceStage({locked, hasSummary: !!session.summary});
  const interview = session.mode === "interview";
  const socketErrorShown = showPageSocketError({error: socket.error, stage, interview,
    interviewReport: completedMode === "interview" && !!session.summary, operationError});

  const setup = <PresentationSetup
    script={script.script}
    timeLimitSeconds={script.timeLimitSeconds}
    disabled={session.isActive || isStarting}
    onScriptChange={script.changeScript}
    onTimeLimitChange={script.changeTimeLimit}
    groups={script.groups}
    onHintChange={script.changeHint}
    onSummarize={() => { if (!locked) void script.summarize(); }}
    isSummarizing={script.isSummarizing}
    summaryError={script.summaryError}
    summaryProgress={script.summaryProgress}
    summarySeconds={script.summarySeconds}
    showTimeLimit={false}
  />;
  const toggles = <FeatureToggles
    analysisLocked={locked}
    settings={session.featureSettings}
    disabled={false}
    onChange={session.setFeatureEnabled}
  />;
  const guide = !session.summary ? <aside className="affect-run-guide" aria-label="목소리 활성도 분석 안내">
    <strong>목소리 활성도·최종 피드백</strong>
    <p>연습 종료 후 본인 기준 대비 목소리 활성도 변화와 시선·발화 속도·습관어 피드백을 함께 보여줍니다. 기준은 시작 30초 이후 구간으로 잡고, 근거가 부족하면 결과를 보류합니다. 맥박 추정값은 참고용·미검증으로 따로 표시합니다.</p>
  </aside> : null;
  const prepare = <div className="prepare">
    <div className="prepare__main">{setup}</div>
    <div className="prepare__side">
      <TimeLimitField timeLimitSeconds={script.timeLimitSeconds} disabled={session.isActive || isStarting}
        onTimeLimitChange={script.changeTimeLimit} />
      {toggles}
      <p className="pulse-caution">{pulseResearchCaution}</p>
      <DataNotes pulseMode={pulseEstimate.modeState.mode} />
      {guide}
    </div>
  </div>;

  return (
    <>
      <SessionControls
        mode={session.mode}
        isRunning={session.isActive}
        isStarting={isStarting || session.phase === 'calibrating'}
        isStopping={isStopping}
        elapsedSeconds={session.elapsedSeconds}
        onModeChange={session.setMode}
        onStart={lifecycle.start}
        onEnd={lifecycle.end}
        startBlocked={script.isSummarizing}
      />
    <main className={`practice-shell${interview ? " practice-shell--interview" : ""}`}>
      <div className="screen">
        <h1>{interview ? "면접 연습" : "발표 및 면접 실시간 피드백"}</h1>
        {media.error ? <p className="error-banner">{media.error}</p> : null}
        {operationError ? <p className="error-banner" role="alert">{operationError}</p> : null}
        {socketErrorShown ? <p className="error-banner" role="alert">{socket.error}</p> : null}

        {interview ? <>
          <SessionStatus phase={session.phase} connectionStatus={socket.status} onRecalibrate={socket.startCalibration} />
          <InterviewContent
            stream={media.stream}
            feedback={visibleFeedback}
            connectionStatus={socket.status}
            socketError={socket.error}
            isRunning={session.isActive}
            isStopping={isStopping}
            onEnd={lifecycle.end}
            summary={completedMode === "interview" ? session.summary : null}
            videoRef={presentationVideo}
          />
          <div className="live-assist__notes"><p className="pulse-caution">{pulseResearchCaution}</p><DataNotes pulseMode={pulseEstimate.modeState.mode} /></div>
          {guide}
        </> : stage === 'live' ? <>
          <LiveStage
            stream={media.stream}
            videoRef={presentationVideo}
            pulse={signals.pulse}
            feedback={visibleFeedback}
            scriptProgress={session.feedbackState.scriptProgress}
            script={script.script}
            timeLimitSeconds={script.timeLimitSeconds}
            elapsedSeconds={session.elapsedSeconds}
            featureSettings={session.featureSettings}
            sentenceHints={script.sentenceHints}
            phase={session.phase}
            connectionStatus={socket.status}
            socketError={socket.error}
            onRecalibrate={socket.startCalibration}
          />
          <div className="live-assist">{toggles}<div className="live-assist__notes"><p className="pulse-caution">{pulseResearchCaution}</p><DataNotes pulseMode={pulseEstimate.modeState.mode} /></div></div>
        </> : stage === 'result' ? <>
          <SessionSummary summary={session.summary} />
          {session.summary && signals.recorded && <SessionInsights summary={session.summary} signals={signals.recorded} />}
          <section className="next-run" aria-labelledby="next-run-title">
            <h2 id="next-run-title">다음 연습 준비</h2>
            {prepare}
          </section>
        </> : prepare}

        {interview && session.summary && signals.recorded ? <SessionInsights summary={session.summary} signals={signals.recorded} /> : null}
      </div>
    </main>
    </>
  );
}
