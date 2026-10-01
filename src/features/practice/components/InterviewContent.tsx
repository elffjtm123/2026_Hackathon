import { useEffect, useRef } from "react";
import type { FeedbackState } from "../feedbackState";
import type { ConnectionStatus, PracticeSummary } from "../types";
import { FeedbackOverlay } from "./FeedbackOverlay";
import { FeedbackPanel } from "./FeedbackPanel";
import { SessionSummary } from "./SessionSummary";
import { VideoPreview } from "./VideoPreview";

type InterviewContentProps = {
  stream: MediaStream | null;
  feedback: FeedbackState;
  connectionStatus: ConnectionStatus;
  socketError: string | null;
  isRunning: boolean;
  isStopping: boolean;
  onEnd: () => void;
  summary: PracticeSummary | null;
};

export function InterviewContent({
  stream,
  feedback,
  connectionStatus,
  socketError,
  isRunning,
  isStopping,
  onEnd,
  summary,
}: InterviewContentProps) {
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const resultSessionId = summary?.sessionId;

  useEffect(() => {
    if (resultSessionId) {
      resultHeadingRef.current?.focus();
    }
  }, [resultSessionId]);

  if (summary) {
    return (
      <section className="interview-report" aria-label="면접 연습 결과">
        <header className="interview-report__intro">
          <span className="label">연습 종료</span>
          <h2 ref={resultHeadingRef} tabIndex={-1}>면접 연습 결과</h2>
          <p>이번 연습에서 실제로 수집된 음성·시선 결과를 확인하세요.</p>
        </header>
        <div className="interview-report__grid">
          <aside className="interview-report__questions" aria-label="질문별 결과">
            <h2>질문별 결과</h2>
            <p>질문별 결과는 아직 제공되지 않습니다.</p>
            <p>질문 생성과 질문별 기록이 연결되면 이곳에 표시됩니다.</p>
          </aside>
          <SessionSummary summary={summary} />
        </div>
      </section>
    );
  }

  return (
    <div className="interview-live">
      <div className="interview-live__main">
        <section className="interview-question" aria-label="면접 질문">
          <span className="label">면접 질문</span>
          <h2>질문이 여기에 표시됩니다</h2>
          <p>질문 생성 기능은 아직 연결되지 않았습니다.</p>
        </section>
        <section className="video-stage" aria-label="카메라 프리뷰">
          <VideoPreview stream={stream} />
          {!stream ? <div className="video-placeholder">카메라 프리뷰</div> : null}
          <FeedbackOverlay feedback={feedback} />
        </section>
      </div>
      <aside className="interview-live__side">
        <FeedbackPanel
          connectionStatus={connectionStatus}
          feedback={feedback}
          socketError={socketError}
        />
        <section className="interview-action" aria-label="면접 진행">
          <h2>{isRunning ? "면접 연습 중" : "면접 연습 준비"}</h2>
          <p>
            {isRunning
              ? "연습을 마치면 종료를 눌러 결과를 확인하세요."
              : "위의 시작 버튼을 눌러 카메라와 마이크를 연결하세요."}
          </p>
          <button
            type="button"
            className="primary-button"
            onClick={onEnd}
            disabled={!isRunning || isStopping}
          >
            {isStopping ? "분석 중" : "면접 종료"}
          </button>
        </section>
      </aside>
    </div>
  );
}
