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
  const gazeStatus = feedback.gaze?.gaze
    ? feedback.gaze.gaze.calibrated
      ? feedback.gaze.gaze.faceDetected && feedback.gaze.gaze.quality >= 0.5
        ? feedback.gaze.gaze.status
        : "판단 어려움"
      : "보정 중"
    : "분석 대기";

  return (
    <div
      className={`feedback-overlay feedback-overlay--${severity}`}
      aria-live="polite"
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
        <p className="overlay-message">{message}</p>
      ) : null}
    </div>
  );
}
