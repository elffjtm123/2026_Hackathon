import type { FeedbackState } from "../feedbackState";

type FeedbackOverlayProps = {
  feedback: FeedbackState;
};

export function FeedbackOverlay({ feedback }: FeedbackOverlayProps) {
  if (!feedback.gaze && !feedback.speech) {
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
  const message =
    feedback.gaze?.gaze?.message ?? feedback.speech?.speech?.message;

  return (
    <div
      className={`feedback-overlay feedback-overlay--${severity}`}
      aria-live="polite"
    >
      <div className="overlay-row">
        <span>시선</span>
        <strong>{feedback.gaze?.gaze?.status ?? "분석 대기"}</strong>
      </div>
      <div className="overlay-row">
        <span>속도</span>
        <strong>{feedback.speech?.speech?.pace ?? "분석 대기"}</strong>
      </div>
      {message ? (
        <p className="overlay-message">{message}</p>
      ) : null}
    </div>
  );
}
