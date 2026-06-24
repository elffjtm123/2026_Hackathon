import type { RealtimeFeedback } from "../types";

type FeedbackOverlayProps = {
  feedback: RealtimeFeedback | null;
};

export function FeedbackOverlay({ feedback }: FeedbackOverlayProps) {
  if (!feedback) {
    return (
      <div className="feedback-overlay feedback-overlay--empty">
        피드백 대기 중
      </div>
    );
  }

  return (
    <div
      className={`feedback-overlay feedback-overlay--${feedback.severity}`}
      aria-live="polite"
    >
      <div className="overlay-row">
        <span>시선</span>
        <strong>{feedback.gaze.status}</strong>
      </div>
      <div className="overlay-row">
        <span>속도</span>
        <strong>{feedback.speech.pace}</strong>
      </div>
      <div className="overlay-row">
        <span>습관어</span>
        <strong>{feedback.filler.totalCount}</strong>
      </div>
      {feedback.message ? (
        <p className="overlay-message">{feedback.message}</p>
      ) : null}
    </div>
  );
}
