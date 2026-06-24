import type { ConnectionStatus, RealtimeFeedback } from "../types";

type FeedbackPanelProps = {
  connectionStatus: ConnectionStatus;
  feedback: RealtimeFeedback | null;
  socketError: string | null;
  isMockMode: boolean;
};

const statusLabels: Record<ConnectionStatus, string> = {
  idle: "대기",
  connecting: "연결 중",
  connected: "연결됨",
  disconnected: "Mock",
  error: "Mock",
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

      {feedback ? (
        <div className="feedback-detail">
          <div>
            <span className="label">시선 상태</span>
            <strong>{feedback.gaze.status}</strong>
            <p>{feedback.gaze.message}</p>
          </div>
          <div>
            <span className="label">발화 속도</span>
            <strong>{feedback.speech.pace}</strong>
            <p>{feedback.speech.message}</p>
          </div>
          <div>
            <span className="label">습관어</span>
            <strong>{feedback.filler.totalCount}회</strong>
            <div className="filler-list">
              {Object.entries(feedback.filler.counts ?? {}).map(
                ([word, count]) => (
                  <span key={word}>
                    {word} {count}
                  </span>
                )
              )}
            </div>
          </div>
        </div>
      ) : (
        <p className="muted-text">세션을 시작하면 피드백이 표시됩니다.</p>
      )}
    </section>
  );
}
