import type { FeedbackState } from "../feedbackState";
import {directionLabels, gazeLabel, speechPaceLabels} from '../feedbackState';
import type { ConnectionStatus } from "../types";

type FeedbackPanelProps = {
  connectionStatus: ConnectionStatus;
  feedback: FeedbackState;
  socketError: string | null;
  // The script-match card has no meaning without a script, so interviews turn it off.
  showPronunciation?: boolean;
};

const statusLabels: Record<ConnectionStatus, string> = {
  idle: "대기",
  connecting: "연결 중",
  connected: "연결됨",
  disconnected: "연결 끊김",
  error: "오류",
};

export function FeedbackPanel({
  connectionStatus,
  feedback,
  socketError,
  showPronunciation = true,
}: FeedbackPanelProps) {
  return (
    <section className="side-panel" aria-label="최신 피드백">
      <div className="panel-header">
        <h2>최신 피드백</h2>
        <span className={`status-pill status-pill--${connectionStatus}`}>
          {statusLabels[connectionStatus]}
        </span>
      </div>

      {socketError ? <p className="error-text">{socketError}</p> : null}

      {feedback.gaze || feedback.speech || feedback.gazeStale || feedback.partialTranscript ? (
        <div className="feedback-detail">
          <div>
            <span className="label">시선 상태</span>
            <strong>{gazeLabel(feedback)}</strong>
            <p>{feedback.gaze?.gaze?.message}</p>
          </div>
          <div>
            <span className="label">얼굴 방향</span>
            <strong>{directionLabels[feedback.gaze?.gaze?.headDirection ?? 'unknown']}</strong>
            <small>좌우는 사용자 몸 기준입니다. 프리뷰는 거울처럼 표시됩니다.</small>
          </div>
          <div>
            <span className="label">발화 속도</span>
            <strong>{speechPaceLabels[feedback.speech?.speech?.pace ?? 'unknown']}</strong>
            <p>{feedback.speech?.speech?.message}</p>
          </div>
          {feedback.speech?.filler ? <div>
            <span className="label">받아쓰기에서 검출된 습관어</span>
            <strong>{feedback.speech.filler.status === 'disabled' ? '비활성' : feedback.speech.filler.totalCount === null ? '분석 없음' : `${feedback.speech.filler.totalCount}회`}</strong>
            <p>{feedback.speech.filler.totalCount === null ? '인식된 발화가 있어야 집계할 수 있습니다.' : Object.entries(feedback.speech.filler.counts ?? {})
              .map(([word,count]) => `${word} ${count}회`).join(', ') || '검출 없음'}</p>
            <small>음성 인식에서 생략된 습관어는 집계되지 않을 수 있습니다.</small>
          </div> : null}
          {feedback.speech?.transcript || feedback.partialTranscript ? (
            <div>
              <span className="label">인식된 음성</span>
              {feedback.speech?.transcript ? <p>{feedback.speech.transcript}</p> : null}
              {feedback.partialTranscript ? (
                <p className="transcript-partial" aria-live="polite">
                  {feedback.partialTranscript.text} <small>(인식 중)</small>
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="muted-text">세션을 시작하면 피드백이 표시됩니다.</p>
      )}
      {showPronunciation ? <div className="feedback-detail">
        <div>
          <span className="label">발음 명료도, 대본 일치도 추정</span>
          <strong>{feedback.pronunciation?.pronunciation?.accuracy == null ? '미측정'
            : `${Math.round(feedback.pronunciation.pronunciation.accuracy)} / 100`}</strong>
          <p>{feedback.pronunciation?.pronunciation?.message
            ?? '대본과 실제 STT 결과가 있어야 추정합니다. 음향학적 발음 정확도는 아닙니다.'}</p>
        </div>
      </div> : null}
    </section>
  );
}
