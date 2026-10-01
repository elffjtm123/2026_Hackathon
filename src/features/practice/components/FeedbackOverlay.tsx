import type { FeedbackState } from "../feedbackState";
import {feedbackMessage, gazeLabel} from '../feedbackState';

type FeedbackOverlayProps = {
  feedback: FeedbackState;
};

export function FeedbackOverlay({ feedback }: FeedbackOverlayProps) {
  if (!feedback.gaze && !feedback.speech && !feedback.gazeStale) {
    return (
      <div className="feedback-overlay feedback-overlay--empty">
        피드백 대기 중
      </div>
    );
  }

  const severity =
    feedback.gaze?.severity === "danger" ||
    feedback.speech?.severity === "danger"
      ? "danger"
      : feedback.gaze?.severity === "warning" ||
          feedback.speech?.severity === "warning"
        ? "warning"
        : "info";
  const message = feedbackMessage(feedback);
  const gazeStatus = gazeLabel(feedback);

  return (
    <div
      className={`feedback-overlay feedback-overlay--${severity}`}
    >
      <div className="overlay-row">
        <span>시선</span>
        <strong>{gazeStatus}</strong>
      </div>
      <div className="overlay-row">
        <span>속도</span>
        <strong>{feedback.speech?.speech?.pace ?? "분석 대기"}</strong>
      </div>
      {message ? (
        <p className="overlay-message" role={severity === 'info' ? undefined : 'status'}>{message}</p>
      ) : null}
    </div>
  );
}
