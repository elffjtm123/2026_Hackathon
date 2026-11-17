import type { RefObject } from 'react';
import type { FeedbackState } from '../feedbackState';
import type { ScriptProgress, SessionPhase } from '../../../lib/realtimeProtocol';
import type { ConnectionStatus, PresentationFeatureSettings } from '../types';
import type { PulseResult } from '../../pulse/signal';
import { PulseOverlay } from '../../pulse/PulseOverlay';
import { FeedbackOverlay } from './FeedbackOverlay';
import { FeedbackPanel } from './FeedbackPanel';
import { KaraokeGuide } from './KaraokeGuide';
import { SessionStatus } from './SessionStatus';
import { VideoPreview } from './VideoPreview';

type LiveStageProps = {
  stream: MediaStream | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  pulse: PulseResult;
  feedback: FeedbackState;
  scriptProgress?: ScriptProgress;
  script: string;
  timeLimitSeconds: number;
  elapsedSeconds: number;
  featureSettings: PresentationFeatureSettings;
  sentenceHints: Record<number, string>;
  phase: SessionPhase;
  connectionStatus: ConnectionStatus;
  socketError: string | null;
  onRecalibrate: () => void;
};

// The practice phase: the camera with its readings and the script line, the status beside it,
// and the latest feedback on the right.
export function LiveStage({stream, videoRef, pulse, feedback, scriptProgress, script, timeLimitSeconds, elapsedSeconds,
  featureSettings, sentenceHints, phase, connectionStatus, socketError, onRecalibrate}: LiveStageProps) {
  return (
    <div className="live-stage">
      <div className="live-stage__main">
        <SessionStatus phase={phase} connectionStatus={connectionStatus} onRecalibrate={onRecalibrate} />
        <section className="video-stage" aria-label="카메라 프리뷰">
          <VideoPreview stream={stream} videoRef={videoRef} />
          <PulseOverlay result={pulse} active={!!stream} />
          {!stream ? <div className="video-placeholder">카메라 프리뷰</div> : null}
          <FeedbackOverlay feedback={feedback} />
        </section>
        <KaraokeGuide
          script={script}
          timeLimitSeconds={timeLimitSeconds}
          elapsedSeconds={elapsedSeconds}
          karaokeEnabled={featureSettings.karaokeGuideEnabled}
          keywordHintEnabled={featureSettings.keywordHintEnabled}
          progress={scriptProgress}
          sentenceHints={sentenceHints}
          phase={phase}
        />
      </div>
      <FeedbackPanel connectionStatus={connectionStatus} feedback={feedback} socketError={socketError} />
    </div>
  );
}
