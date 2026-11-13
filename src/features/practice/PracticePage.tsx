import { useEffect, useRef, useState, type CSSProperties } from "react";
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
import { usePracticeLifecycle } from "./hooks/usePracticeLifecycle";
import { usePresentationScript } from "./hooks/usePresentationScript";
import { useSessionSignals } from "./hooks/useSessionSignals";
import { useThemeAvailability } from "./hooks/useThemeAvailability";
import {selectVisibleFeedback} from './feedbackState';
import {isRecordingPhase, modelStatusLabel} from '../../lib/realtimeProtocol';
import { modelThemes, type ModelTheme } from '../model-themes/modelThemes';
import { LiveComparisonPanel } from '../model-themes/LiveComparisonPanel';
import { readSessionValue } from '../model-themes/runHistory';
import '../model-themes/themes.css';
import { PulsePanel } from '../pulse/PulsePanel';
import { PulseOverlay } from '../pulse/PulseOverlay';
import { FaceFeaturePanel } from '../face-features/FaceFeaturePanel';
import { featureSnapshot } from '../face-features/snapshot';
import {SessionInsights} from '../affect/SessionInsights';
import '../delivery/delivery.css';
import { themesHash } from '../../routes';

export function PracticePage({theme = modelThemes[0], onActivityChange}: {
  theme?: ModelTheme; onActivityChange?: (busy: boolean) => void;
}) {
  const session = usePracticeSession(readSessionValue('live-practice-mode') === 'interview' ? 'interview' : 'presentation');
  const media = useUserMedia();
  const presentationVideo = useRef<HTMLVideoElement | null>(null);
  const script = usePresentationScript(session.mode);
  const {availability, availabilityError, refreshAvailability} = useThemeAvailability(theme);
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
  const lifecycle = usePracticeLifecycle({theme, session, media, socket, flushStreaming: streaming.stopStreaming,
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

  return (
    <main className={`practice-shell themed-practice${session.mode === "interview" ? " practice-shell--interview" : ""}`}
      data-model-theme={theme.id} style={{'--theme-accent': theme.accent, '--theme-tint': theme.tint} as CSSProperties}>
      <header className="practice-header">
        <div>
          <p className="eyebrow">Realtime Coach · {theme.name}</p>
          <h1>{session.mode === "interview" ? "면접 연습" : "발표 및 면접 실시간 피드백"}</h1>
        </div>
        <nav className="theme-nav" aria-label="모델 실험 이동">
          <a href={themesHash} className="secondary-button theme-link" aria-disabled={locked}
            onClick={event => { if (locked) event.preventDefault(); }}>테마 선택</a>
          <a href="#stt-experiments" className="secondary-button theme-link" aria-disabled={locked}
            onClick={event => { if (locked) event.preventDefault(); }}>동일 음성 파일 비교</a>
          <a href="#pulse-pos-experiment" className="secondary-button theme-link" aria-disabled={busy}
            onClick={event => { if (busy) event.preventDefault(); }}>POS 비교 실험</a>
        </nav>
      </header>
      <section className="live-theme-banner" aria-label="선택한 모델 테마"><h2>{theme.label}</h2>
        <p>음성 모델만 변경 · 얼굴 방향/눈 시선 보정과 대본·음성 후처리는 기존 기능 그대로</p>
        <p>{socket.modules.speech?.status === 'ready' && locked ? `현재 실행 모델: ${socket.modules.speech.model}`
          : !theme.experiment ? '기본 서비스 모델 · 시작하면 모델 로딩 후 카메라 보정이 진행됩니다.'
          : availability?.available ? '파일 준비됨 · 시작하면 모델 로딩 후 카메라 보정이 진행됩니다.'
          : availability?.reason ?? '준비 상태 확인 중…'}</p>
        <p>대본·제한시간·발표/면접 선택은 이 탭에서 테마 간 유지됩니다. 각 테마는 새로 시선을 보정합니다.</p>
        {availabilityError && <p role="alert">{availabilityError}</p>}
        {theme.experiment && <button className="secondary-button" disabled={locked} onClick={() => { void refreshAvailability(); }}>준비 상태 확인</button>}
      </section>

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

      {session.mode === "presentation" ? (
        <>
          <PresentationSetup
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
          />
          <FeatureToggles
            analysisLocked={locked}
            settings={session.featureSettings}
            disabled={false}
            onChange={session.setFeatureEnabled}
          />
        </>
      ) : null}

      {media.error ? <p className="error-banner">{media.error}</p> : null}
      {!session.summary&&<section className="affect-run-guide" aria-label="목소리 활성도 분석 안내">
        <strong>목소리 활성도·최종 피드백</strong>
        <p>연습 종료 후 본인 기준 대비 목소리 활성도 변화와 시선·발화 속도·습관어 피드백을 함께 보여줍니다. 기준은 시작 30초 이후 구간으로 잡고, 근거가 부족하면 결과를 보류합니다. 맥박 추정값은 참고용·미검증으로 따로 표시합니다.</p>
      </section>}
      {operationError ? <p className="error-banner" role="alert">{operationError}</p> : null}
      {session.phase === 'preparing' ? <p role="status">음성·시선 모델을 준비 중입니다. 준비와 보정이 끝난 뒤 연습 시간이 시작됩니다.</p> : null}
      {session.phase === 'calibrating' ? <p role="status">카메라를 바라보며 보정 중입니다. 연습 시간은 보정 완료 후 시작합니다.</p> : null}
      {['calibrating', 'running'].includes(session.phase) && socket.status === 'connected' ? <button type="button" className="secondary-button" onClick={socket.startCalibration}>다시 보정</button> : null}
      {session.phase === 'draining' ? <p role="status">마지막 음성을 분석하고 있습니다.</p> : null}
      <div aria-label="모델 상태">{Object.entries(socket.modules).map(([name, module]) =>
        <span key={name}>{name === 'gaze' ? '시선' : '음성'}: {modelStatusLabel(module)} · {module.model ?? module.provider}{module.device ? ' (' + module.device + ')' : ''} · </span>
      )}</div>

      {session.mode === "interview" ? (
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
      ) : (
        <>
          <div className="practice-layout">
            <section className="video-stage" aria-label="카메라 프리뷰">
              <VideoPreview stream={media.stream} videoRef={presentationVideo} />
              <PulseOverlay result={signals.pulse} active={!!media.stream} />
              {!media.stream ? (
                <div className="video-placeholder">카메라 프리뷰</div>
              ) : null}
              <FeedbackOverlay feedback={visibleFeedback} />
              <KaraokeGuide
                script={script.script}
                timeLimitSeconds={script.timeLimitSeconds}
                elapsedSeconds={session.elapsedSeconds}
                karaokeEnabled={session.featureSettings.karaokeGuideEnabled}
                keywordHintEnabled={session.featureSettings.keywordHintEnabled}
                progress={session.feedbackState.scriptProgress}
                sentenceHints={script.sentenceHints}
                phase={session.phase}
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
      <FaceFeaturePanel result={signals.faceFeatures} enabled={signals.faceFeaturesEnabled} active={!!media.stream}
        onEnabledChange={signals.setFaceFeaturesEnabled}
        snapshot={() => featureSnapshot(signals.faceFeatures, signals.pulse, visibleFeedback, socket.sessionTime(), session.sessionId, session.phase)} />
      <PulsePanel stream={media.stream} mode="efficientphys" autoFallback embedded videoRef={presentationVideo} onResult={signals.receivePulse}
        faceFeatures={{enabled: signals.faceFeaturesEnabled, onResult: signals.receiveFaceFeatures, sessionTime: socket.sessionTime}} />
      {session.summary&&signals.recorded&&<SessionInsights summary={session.summary} signals={signals.recorded} />}
      <LiveComparisonPanel key={session.summary?.sessionId ?? 'pending'} summary={session.summary} />
    </main>
  );
}
