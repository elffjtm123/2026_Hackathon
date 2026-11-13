import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
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
import { audioSettingsOf, completePracticeSession } from "./sessionLifecycle";
import type { PracticeMode } from "./types";
import {selectVisibleFeedback} from './feedbackState';
import {manualSummaryGroups, groupHints, replacementSummaryGroups, type ScriptSummaryGroup, type SummaryProgress} from './scriptTools';
import {requestScriptSummary} from './scriptSummary';
import {modelStatusLabel} from '../../lib/realtimeProtocol';
import { modelThemes, readModelAvailability, type ModelTheme, type ModelAvailability } from '../model-themes/modelThemes';
import { LiveComparisonPanel } from '../model-themes/LiveComparisonPanel';
import { readSessionValue } from '../model-themes/runHistory';
import '../model-themes/themes.css';
import { PulsePanel } from '../pulse/PulsePanel';
import { PulseOverlay } from '../pulse/PulseOverlay';
import { emptyPulse, type PulseResult } from '../pulse/signal';
import { FaceFeaturePanel } from '../face-features/FaceFeaturePanel';
import { emptyFaceFeatures, type FaceFeatures } from '../face-features/features';
import { featureSnapshot } from '../face-features/snapshot';
import {SessionSignalRecorder} from '../affect/analysis';
import {SessionInsights} from '../affect/SessionInsights';
import '../delivery/delivery.css';

export function PracticePage({theme = modelThemes[0], onActivityChange}: {
  theme?: ModelTheme; onActivityChange?: (busy: boolean) => void;
}) {
  const session = usePracticeSession(readSessionValue('live-practice-mode') === 'interview' ? 'interview' : 'presentation');
  const media = useUserMedia();
  const presentationVideo = useRef<HTMLVideoElement | null>(null);
  const [presentationPulse, setPresentationPulse] = useState<PulseResult>(emptyPulse);
  const [faceFeaturesEnabled, setFaceFeaturesEnabled] = useState(true);
  const [faceFeatures, setFaceFeatures] = useState<FaceFeatures>(emptyFaceFeatures);
  const signalRecorder=useRef(new SessionSignalRecorder());
  const phaseRef=useRef(session.phase);phaseRef.current=session.phase;
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [availability, setAvailability] = useState<ModelAvailability | null>(null);
  const [availabilityError, setAvailabilityError] = useState<string | null>(null);
  const locked = session.isActive || isStarting || isStopping;
  useEffect(() => { onActivityChange?.(locked); return () => onActivityChange?.(false); }, [locked, onActivityChange]);
  const refreshAvailability = useCallback(async (isDisposed: () => boolean = () => false) => {
    try {
      const body = await readModelAvailability();
      if (!isDisposed()) { setAvailability(body.models.find(model => model.id === theme.id) ?? null); setAvailabilityError(null); }
    } catch (cause) { if (!isDisposed()) setAvailabilityError(cause instanceof Error ? cause.message : '모델 상태 확인 실패'); }
  }, [theme.id]);
  useEffect(() => { let disposed = false; void refreshAvailability(() => disposed); return () => { disposed = true; }; }, [refreshAvailability]);
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
    () => readSessionValue('live-practice-script') ?? "안녕하세요. 오늘은 실시간 발표 피드백 서비스의 핵심 기능을 소개하겠습니다. 이 서비스는 시선, 발화 속도, 대본 일치도를 확인해 발표자가 더 안정적으로 연습할 수 있도록 돕습니다."
  );
  const [timeLimitSeconds, setTimeLimitSeconds] = useState(() => {
    const saved = Number(readSessionValue('live-practice-time'));
    return Number.isFinite(saved) && saved >= 30 && saved <= 1800 ? saved : 180;
  });
  useEffect(() => {
    try {
      sessionStorage.setItem('live-practice-script', presentationScript);
      sessionStorage.setItem('live-practice-time', String(timeLimitSeconds));
      sessionStorage.setItem('live-practice-mode', session.mode);
    } catch { /* Storage is optional. */ }
  }, [presentationScript, timeLimitSeconds, session.mode]);
  const [summaryGroups, setSummaryGroups] = useState<ScriptSummaryGroup[] | null>(null);
  const groups = summaryGroups ?? manualSummaryGroups(presentationScript);
  const sentenceHints = groupHints(groups);
  const [isSummarizing, setIsSummarizing] = useState(false);
  useEffect(() => { onActivityChange?.(locked || isSummarizing); }, [locked, isSummarizing, onActivityChange]);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryProgress, setSummaryProgress] = useState<SummaryProgress | null>(null);
  const [summarySeconds, setSummarySeconds] = useState<number | null>(null);
  const summaryRequest = useRef<AbortController | null>(null);
  const scriptVersion = useRef(0);
  useEffect(() => () => summaryRequest.current?.abort(), []);

  const handleScriptChange = (script: string) => {
    scriptVersion.current++;
    setPresentationScript(script); setSummaryGroups(null); setSummaryProgress(null);
    setSummaryError(null); setSummarySeconds(null);
  };
  const handleSummarize = async () => {
    if (session.isActive || isStarting || isStopping || summaryRequest.current) return;
    if (Object.values(sentenceHints).some(hint => hint.trim())
        && !window.confirm('현재 요약을 새 AI 초안으로 바꿀까요? 직접 수정한 내용이 덮어써질 수 있습니다.')) return;
    const controller = new AbortController();
    const version = scriptVersion.current;
    summaryRequest.current = controller;
    setIsSummarizing(true); setSummaryError(null); setSummaryProgress(null);
    try {
      const result = await requestScriptSummary(presentationScript, controller.signal, progress => {
        if (!controller.signal.aborted && version === scriptVersion.current) setSummaryProgress(progress);
      });
      if (controller.signal.aborted || version !== scriptVersion.current) return;
      setSummaryGroups(replacementSummaryGroups(presentationScript, result, groups));
      setSummarySeconds(result.elapsed_seconds);
    } catch (error) {
      if (!controller.signal.aborted && version === scriptVersion.current)
        setSummaryError(error instanceof Error ? error.message : '요약하지 못했습니다. 다시 시도하세요.');
    } finally {
      if (summaryRequest.current === controller) {
        summaryRequest.current = null;
        if (!controller.signal.aborted) setIsSummarizing(false);
      }
    }
  };
  const socket = useFeedbackSocket(session.receiveFeedback, session.applyPhase);
  const receiveFaceFeatures=useCallback((result:FaceFeatures)=>{
    if(['running','draining'].includes(phaseRef.current))signalRecorder.current.face(result);
    setFaceFeatures(result);
  },[]);
  const receivePulse=useCallback((result:PulseResult)=>{
    if(['running','draining'].includes(phaseRef.current))signalRecorder.current.pulse(result,socket.sessionTime());
    setPresentationPulse(result);
  },[socket.sessionTime]);
  const streaming = useBackendStreaming({
    isActive: ['calibrating', 'running', 'draining'].includes(session.phase) && socket.status === "connected",
    captureAudio: ['running', 'draining'].includes(session.phase) && socket.status === 'connected',
    stream: media.stream,
    videoRef: presentationVideo,
    audioContext: media.audioContext,
    sessionTime: socket.sessionTime,
    sendVideoFrame: socket.sendVideoFrame,
    sendAudioPacket: socket.sendAudioPacket,
    awaitAudioAck: socket.awaitAudioAck,
    onError: socket.reportCaptureError,
  });

  const handleStart = useCallback(async () => {
    if (summaryRequest.current) return;
    const generation = ++generationRef.current;
    setIsStarting(true);
    onActivityChange?.(true);
    setOperationError(null);
    setCompletedMode(null);

    try {
      const models = await readModelAvailability();
      if (generation !== generationRef.current) return;
      const selected = models.models.find(model => model.id === theme.id);
      if (models.busy) throw new Error('다른 연습이나 비교 실험이 진행 중입니다. 종료 후 다시 시작해 주세요.');
      if (!selected?.available) throw new Error(selected?.reason ?? '선택한 모델이 준비되지 않았습니다.');
      const nextSessionId = session.startSession();
      signalRecorder.current.reset();
      const mediaReady = media.startMedia();
      const audioSettings = mediaReady.then(audioSettingsOf, () => undefined);
      const ready = socket.connect(
        nextSessionId,
        session.mode,
        session.featureSettings,
        presentationScript,
        timeLimitSeconds,
        theme.id,
        audioSettings
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
  }, [media, presentationScript, session, socket, timeLimitSeconds, theme.id, onActivityChange]);

  const handleTimeLimitChange = useCallback((seconds: number) => {
    if (Number.isFinite(seconds)) {
      setTimeLimitSeconds(Math.min(1800, Math.max(30, seconds)));
    }
  }, []);

  const handleEnd = useCallback(async () => {
    if (isStarting && !session.isActive) {
      generationRef.current++; setIsStarting(false); media.stopMedia(); socket.disconnect(); return;
    }
    if (!session.sessionId || endingRef.current) {
      return;
    }

    setIsStopping(true);
    endingRef.current = true;
    generationRef.current++;
    setIsStarting(false);
    try {
      if (session.phase === 'preparing') {
        media.stopMedia(); socket.disconnect(); session.endSession(); return;
      }
      if (session.phase === 'calibrating') {
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
  }, [media, session, socket, streaming.stopStreaming, isStarting]);

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
    <main className={`practice-shell themed-practice${session.mode === "interview" ? " practice-shell--interview" : ""}`}
      data-model-theme={theme.id} style={{'--theme-accent': theme.accent, '--theme-tint': theme.tint} as CSSProperties}>
      <header className="practice-header">
        <div>
          <p className="eyebrow">Realtime Coach · {theme.name}</p>
          <h1>{session.mode === "interview" ? "면접 연습" : "발표 및 면접 실시간 피드백"}</h1>
        </div>
        <nav className="theme-nav" aria-label="모델 실험 이동">
          <a href="#" className="secondary-button theme-link" aria-disabled={locked}
            onClick={event => { if (locked) event.preventDefault(); }}>테마 선택</a>
          <a href="#stt-experiments" className="secondary-button theme-link" aria-disabled={locked}
            onClick={event => { if (locked) event.preventDefault(); }}>동일 음성 파일 비교</a>
          <a href="#pulse-pos-experiment" className="secondary-button theme-link" aria-disabled={locked || isSummarizing}
            onClick={event => { if (locked || isSummarizing) event.preventDefault(); }}>POS 비교 실험</a>
        </nav>
      </header>
      <section className="live-theme-banner" aria-label="선택한 모델 테마"><h2>{theme.label}</h2>
        <p>음성 모델만 변경 · 얼굴 방향/눈 시선 보정과 대본·음성 후처리는 기존 기능 그대로</p>
        <p>{socket.modules.speech?.status === 'ready' && locked ? `현재 실행 모델: ${socket.modules.speech.model}`
          : availability?.available ? '파일 준비됨 · 시작하면 모델 로딩 후 카메라 보정이 진행됩니다.'
          : availability?.reason ?? '준비 상태 확인 중…'}</p>
        <p>대본·제한시간·발표/면접 선택은 이 탭에서 테마 간 유지됩니다. 각 테마는 새로 시선을 보정합니다.</p>
        {availabilityError && <p role="alert">{availabilityError}</p>}
        <button className="secondary-button" disabled={locked} onClick={() => { void refreshAvailability(); }}>준비 상태 확인</button>
      </section>

      <SessionControls
        mode={session.mode}
        isRunning={session.isActive}
        isStarting={isStarting || session.phase === 'calibrating'}
        isStopping={isStopping}
        elapsedSeconds={session.elapsedSeconds}
        onModeChange={session.setMode}
        onStart={handleStart}
        onEnd={handleEnd}
        startBlocked={isSummarizing}
      />

      {session.mode === "presentation" ? (
        <>
          <PresentationSetup
            script={presentationScript}
            timeLimitSeconds={timeLimitSeconds}
            disabled={session.isActive || isStarting}
            onScriptChange={handleScriptChange}
            onTimeLimitChange={handleTimeLimitChange}
            groups={groups}
            onHintChange={(index, hint) => {
              setSummaryGroups(current => (current ?? manualSummaryGroups(presentationScript))
                .map((group, i) => i === index ? {...group, hint, error:null} : group));
            }}
            onSummarize={() => void handleSummarize()}
            isSummarizing={isSummarizing}
            summaryError={summaryError}
            summaryProgress={summaryProgress}
            summarySeconds={summarySeconds}
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
      {!session.summary&&<section className="affect-run-guide" aria-label="종합 상태 분석 안내">
        <strong>종합 상태·최종 피드백</strong>
        <p>연습 종료 후 맥박·표정·음성의 종합 상태와 시선·발화 속도·습관어 피드백을 함께 보여줍니다. 세 신호가 함께 관찰된 구간을 개인 기준과 비교하며, 근거가 부족하면 판단을 보류합니다.</p>
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
          onEnd={handleEnd}
          summary={completedMode === "interview" ? session.summary : null}
          videoRef={presentationVideo}
        />
      ) : (
        <>
          <div className="practice-layout">
            <section className="video-stage" aria-label="카메라 프리뷰">
              <VideoPreview stream={media.stream} videoRef={presentationVideo} />
              <PulseOverlay result={presentationPulse} active={!!media.stream} />
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
                progress={session.feedbackState.scriptProgress}
                sentenceHints={sentenceHints}
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
      <FaceFeaturePanel result={faceFeatures} enabled={faceFeaturesEnabled} active={!!media.stream}
        onEnabledChange={setFaceFeaturesEnabled}
        snapshot={() => featureSnapshot(faceFeatures, presentationPulse, visibleFeedback, socket.sessionTime(), session.sessionId, session.phase)} />
      <PulsePanel stream={media.stream} mode="efficientphys" embedded videoRef={presentationVideo} onResult={receivePulse}
        faceFeatures={{enabled: faceFeaturesEnabled, onResult: receiveFaceFeatures, sessionTime: socket.sessionTime}} />
      {session.summary&&<SessionInsights summary={session.summary} signals={signalRecorder.current.snapshot()} />}
      <LiveComparisonPanel key={session.summary?.sessionId ?? 'pending'} summary={session.summary} />
    </main>
  );
}
