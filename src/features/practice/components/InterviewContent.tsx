import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import type { FeedbackState } from "../feedbackState";
import type { ConnectionStatus, PracticeSummary } from "../types";
import { FeedbackOverlay } from "./FeedbackOverlay";
import { FeedbackPanel } from "./FeedbackPanel";
import { SessionSummary } from "./SessionSummary";
import { VideoPreview } from "./VideoPreview";
import { InterviewReport } from "../../interview/InterviewReport";
import { answerRemainingMs, canReplay, formatClock, initialInterviewState, readingRemainingMs, remainingQuestions,
  type BreakStage, type InterviewRunState } from "../../interview/interviewState";
import type { ReportItem } from "../../interview/reportModel";
import type { EvaluationState } from "../../interview/useInterviewEvaluation";
import type { PlannedQuestion } from "../../interview/types";
import "../../interview/interview.css";

type InterviewContentProps = {
  stream: MediaStream | null;
  feedback: FeedbackState;
  connectionStatus: ConnectionStatus;
  socketError: string | null;
  isRunning: boolean;
  isStopping: boolean;
  summary: PracticeSummary | null;
  videoRef?: RefObject<HTMLVideoElement | null>;
  // Live view: the server-driven question state and the local clock (performance.now).
  run?: InterviewRunState;
  now?: number;
  onReplay?: () => void;
  // Result view.
  reportItems?: ReportItem[];
  reportQuestions?: Pick<PlannedQuestion, "id" | "source_quote">[];
  evaluation?: EvaluationState;
  onCancelEvaluation?: () => void;
  onRetryEvaluation?: () => void;
  onNewInterview?: () => void;
};

const BREAK_TEXT: Record<BreakStage, string> = {
  suspending: "답변을 정리하고 있습니다. 잠시 면접을 멈춥니다.",
  generating: "방금 답변을 바탕으로 추가 질문을 만들고 있습니다.",
  resuming: "면접을 다시 시작할 준비를 하고 있습니다.",
  skipped: "추가 질문 없이 면접을 마칩니다.",
};

const noEvaluation: EvaluationState = { status: "idle", progress: null, evaluation: null, error: null };

function QuestionPanel({ run, now, isRunning, isStopping, onReplay }: {
  run: InterviewRunState; now: number; isRunning: boolean; isStopping: boolean; onReplay?: () => void;
}) {
  const { question } = run;
  const answerLeft = answerRemainingMs(run, now);
  // `live` is announced when it changes (question text, stage messages); `rest` holds the countdowns
  // that tick every 250 ms and must stay out of the live region.
  let live: ReactNode = null, rest: ReactNode = null;
  if (isStopping) {
    live = <p className="interview-question__status">면접을 마치고 결과를 정리하고 있습니다.</p>;
  } else if (run.status === "break" && run.breakStage) {
    live = (
      <>
        <p className="interview-question__text">{run.suspended || run.breakStage !== "skipped" ? "잠시 쉬어 가는 시간입니다" : "면접을 마무리합니다"}</p>
        <p className="interview-question__status">{BREAK_TEXT[run.breakStage]}</p>
      </>
    );
    rest = <p className="interview-note">카메라와 마이크는 켜진 채로 있습니다. 이 시간은 말하기 분석에서 제외됩니다.</p>;
  } else if (run.status === "finished") {
    live = <p className="interview-question__status">면접이 끝났습니다. 결과를 정리하고 있습니다.</p>;
  } else if (run.status === "advancing") {
    live = <p className="interview-question__text">다음 질문입니다</p>;
  } else if (run.status === "asking" && question) {
    live = run.textVisible
      ? <><p className="interview-question__meta">{question.round === 2 ? "추가 질문" : "질문"} {question.index} / {question.total}</p>
          <p className="interview-question__text">{question.text}</p></>
      : <><p className="interview-question__meta">{question.round === 2 ? "추가 질문" : "질문"} {question.index} / {question.total}</p>
          <p className="interview-question__text interview-question__text--hidden">질문이 가려졌습니다. 답변해 주세요.</p></>;
    rest = (
      <>
        {run.textVisible ? (
          <p className="interview-question__status">읽는 시간 {Math.ceil(readingRemainingMs(run, now) / 1000)}초 · 말을 시작하면 질문이 사라집니다</p>
        ) : (
          <dl className="interview-timers">
            <div><dt>남은 답변 시간</dt><dd>{answerLeft === null ? "-" : formatClock(answerLeft)}</dd></div>
            <div><dt>남은 질문</dt><dd>{remainingQuestions(run)}개</dd></div>
          </dl>
        )}
        <button type="button" className="secondary-button" onClick={onReplay} disabled={!canReplay(run) || !onReplay}>
          {run.replayAvailable || run.textVisible ? "질문 다시 보기 (1회)" : "질문 다시 보기를 사용했습니다"}
        </button>
      </>
    );
  } else {
    live = (
      <>
        <p className="interview-question__text">질문이 여기에 표시됩니다</p>
        <p>{isRunning ? "카메라와 마이크를 맞춘 뒤 첫 질문이 나옵니다." : "질문을 고른 뒤 시작 버튼을 눌러 주세요."}</p>
      </>
    );
  }
  return (
    <section className="interview-question" aria-label="면접 질문">
      <h2>면접 질문</h2>
      <div aria-live="polite" aria-atomic="true">{live}</div>
      {rest}
    </section>
  );
}

export function InterviewContent({
  stream,
  feedback,
  connectionStatus,
  socketError,
  isRunning,
  isStopping,
  summary,
  videoRef,
  run = initialInterviewState,
  now = 0,
  onReplay,
  reportItems = [],
  reportQuestions = [],
  evaluation = noEvaluation,
  onCancelEvaluation,
  onRetryEvaluation,
  onNewInterview,
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
          <h2 ref={resultHeadingRef} tabIndex={-1}>면접 연습 결과</h2>
          <p>질문별 평가와 이번 연습에서 실제로 수집된 음성·시선 결과를 확인하세요.</p>
          {onNewInterview ? (
            <button type="button" className="primary-button" onClick={onNewInterview} disabled={evaluation.status === "running"}>새 면접 준비</button>
          ) : null}
          {evaluation.status === "running" ? <p className="interview-note">평가가 끝나거나 중단한 뒤 새 면접을 준비할 수 있습니다.</p> : null}
        </header>
        <InterviewReport
          items={reportItems}
          questions={reportQuestions}
          evaluation={evaluation}
          onCancelEvaluation={onCancelEvaluation}
          onRetryEvaluation={onRetryEvaluation}
        >
          <SessionSummary summary={summary} interview />
        </InterviewReport>
      </section>
    );
  }

  return (
    <div className="interview-live">
      <div className="interview-live__main">
        <QuestionPanel run={run} now={now} isRunning={isRunning} isStopping={isStopping} onReplay={onReplay} />
        <section className="video-stage" aria-label="카메라 프리뷰">
          <VideoPreview stream={stream} videoRef={videoRef} />
          {!stream ? <div className="video-placeholder">카메라 프리뷰</div> : null}
          {run.suspended ? <div className="interview-break-badge" role="status">휴식 중</div> : null}
          <FeedbackOverlay feedback={feedback} />
        </section>
      </div>
      <aside className="interview-live__side">
        <FeedbackPanel
          connectionStatus={connectionStatus}
          feedback={feedback}
          socketError={socketError}
          showPronunciation={false}
        />
        <section className="interview-action" aria-label="면접 진행">
          <h2>{isRunning ? "면접 연습 중" : "면접 연습 준비"}</h2>
          <p>
            {isRunning
              ? "중간에 멈추려면 위쪽의 종료 버튼을 누르세요. 그때까지의 답변으로 결과를 보여 드립니다."
              : "위의 시작 버튼을 눌러 카메라와 마이크를 연결하세요."}
          </p>
        </section>
      </aside>
    </div>
  );
}
