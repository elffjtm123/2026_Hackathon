import type { FeedbackState } from "../feedbackState";
import type { ConnectionStatus } from "../types";

type FeedbackPanelProps = {
  connectionStatus: ConnectionStatus;
  feedback: FeedbackState;
  socketError: string | null;
  isMockMode: boolean;
};

const statusLabels: Record<ConnectionStatus, string> = {
  idle: "대기",
  connecting: "연결 중",
  connected: "백엔드",
  disconnected: "연결 끊김",
  error: "오류",
};

export function FeedbackPanel({
  connectionStatus,
  feedback,
  socketError,
  isMockMode,
}: FeedbackPanelProps) {
  return (
    <section className="side-panel" aria-label="최신 피드백">
      <div className="panel-header">
        <h2>최신 피드백</h2>
        <span className={`status-pill status-pill--${connectionStatus}`}>
          {isMockMode ? "Mock" : statusLabels[connectionStatus]}
        </span>
      </div>

      {socketError ? <p className="error-text">{socketError}</p> : null}

      {feedback.gaze || feedback.speech ? (
        <div className="feedback-detail">
          <div>
            <span className="label">시선 상태</span>
            <strong>{feedback.gaze?.gaze?.status ?? "분석 대기"}</strong>
            <p>{feedback.gaze?.gaze?.message}</p>
          </div>
          <div>
            <span className="label">발화 속도</span>
            <strong>{feedback.speech?.speech?.pace ?? "분석 대기"}</strong>
            <p>{feedback.speech?.speech?.message}</p>
          </div>
          {feedback.speech?.transcript ? (
            <div>
              <span className="label">인식된 음성</span>
              <p>{feedback.speech.transcript}</p>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="muted-text">세션을 시작하면 피드백이 표시됩니다.</p>
      )}
    </section>
  );
}
