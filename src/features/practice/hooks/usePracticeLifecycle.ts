import { useCallback, useEffect, useRef, useState } from 'react';
import type { PracticeMode } from '../types';
import { audioSettingsOf, completePracticeSession } from '../sessionLifecycle';
import { ensureThemeReady, sttModelIdFor, type ModelTheme } from '../../model-themes/modelThemes';
import type { usePracticeSession } from './usePracticeSession';
import type { useUserMedia } from './useUserMedia';
import type { useFeedbackSocket } from './useFeedbackSocket';

type Options = {
  theme: ModelTheme;
  session: ReturnType<typeof usePracticeSession>;
  media: ReturnType<typeof useUserMedia>;
  socket: ReturnType<typeof useFeedbackSocket>;
  flushStreaming: () => Promise<void>;
  script: string;
  timeLimitSeconds: number;
  isSummaryPending: () => boolean;
  onBeforeStart: () => void;
  onActivityChange?: (busy: boolean) => void;
};

// Start → prepare → calibrate → run → complete, including cancellation, socket failure and the
// presentation time limit. A stale start (generation changed) never touches the newer attempt.
export function usePracticeLifecycle({theme, session, media, socket, flushStreaming, script, timeLimitSeconds,
  isSummaryPending, onBeforeStart, onActivityChange}: Options) {
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [completedMode, setCompletedMode] = useState<PracticeMode | null>(null);
  const generationRef = useRef(0);
  const endingRef = useRef(false);

  const start = useCallback(async () => {
    if (isSummaryPending()) return;
    const generation = ++generationRef.current;
    setIsStarting(true);
    onActivityChange?.(true);
    setOperationError(null);
    setCompletedMode(null);
    try {
      await ensureThemeReady(theme);
      if (generation !== generationRef.current) return;
      const nextSessionId = session.startSession();
      onBeforeStart();
      const mediaReady = media.startMedia();
      const audioSettings = mediaReady.then(audioSettingsOf, () => undefined);
      const ready = socket.connect(nextSessionId, session.mode, session.featureSettings, script,
        timeLimitSeconds, sttModelIdFor(theme), audioSettings);
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
  }, [isSummaryPending, onActivityChange, theme, session, onBeforeStart, media, socket, script, timeLimitSeconds]);

  const end = useCallback(async () => {
    if (isStarting && !session.isActive) {
      generationRef.current++; setIsStarting(false); media.stopMedia(); socket.disconnect(); return;
    }
    if (!session.sessionId || endingRef.current) return;
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
        flushMedia: flushStreaming,
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
  }, [media, session, socket, flushStreaming, isStarting]);

  useEffect(() => {
    if (socket.status === 'error' && session.isActive && !endingRef.current) {
      generationRef.current++;
      media.stopMedia(); session.endSession(); setIsStarting(false);
      socket.disconnect();
    }
  }, [media, session, socket]);

  useEffect(() => {
    if (session.mode === 'presentation' && session.isRunning && session.elapsedSeconds >= timeLimitSeconds) void end();
  }, [end, session.elapsedSeconds, session.isRunning, session.mode, timeLimitSeconds]);

  const locked = session.isActive || isStarting || isStopping;
  return { start, end, isStarting, isStopping, locked, operationError, completedMode };
}
