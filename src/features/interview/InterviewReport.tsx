import type { ReactNode } from 'react';
import type { EvaluationState } from './useInterviewEvaluation.ts';
import { buildReportCards, evaluationProgressLabel, formatScore, gradeSourceLabel, itemBadge, rubricLabel,
  type ReportCard, type ReportItem } from './reportModel.ts';
import type { AdvanceReason, PlannedQuestion } from './types.ts';
import './interview.css';

const ADVANCE_LABEL: Record<AdvanceReason, string> = {
  silence: '침묵이 이어져 다음 질문으로 넘어감', time_limit: '답변 제한 시간이 지나 넘어감',
  no_response: '답변이 없어 넘어감', stopped: '면접을 중단함',
};
const WARNING_LABEL: Record<string, string> = {
  item_evaluation_failed: '일부 질문은 평가하지 못해 점수에서 뺐습니다.',
  summary_failed: '종합 피드백을 만들지 못했습니다.',
  evaluation_timeout: '평가 시간이 부족해 남은 질문은 평가하지 못했습니다.',
};

type InterviewReportProps = {
  items: ReportItem[];
  questions: Pick<PlannedQuestion, 'id' | 'source_quote'>[];
  evaluation: EvaluationState;
  onCancelEvaluation?: () => void;
  onRetryEvaluation?: () => void;
  // The voice and gaze results, shown below the questions with or without an evaluation.
  children?: ReactNode;
};

function Answer({ text }: { text: string }) {
  return text.trim()
    ? <p className="interview-answer">{text}</p>
    : <p className="interview-answer interview-answer--empty">인식된 답변이 없습니다.</p>;
}

function Card({ card, evaluationDone }: { card: ReportCard; evaluationDone: boolean }) {
  const badge = itemBadge(evaluationDone ? card.evaluation : undefined);
  const grades = card.evaluation ? Object.entries(card.evaluation.grades) : [];
  return (
    <article className="interview-card">
      <header>
        <h3>{card.text}</h3>
        <span className={`interview-badge interview-badge--${badge.tone}`}>{badge.label}</span>
      </header>
      <small className="interview-meta">
        {card.round === 2 ? '추가 질문 · ' : ''}{ADVANCE_LABEL[card.advanceReason]}{card.replayUsed ? ' · 질문 다시 보기 사용' : ''}
      </small>
      {card.sourceQuote ? <blockquote className="interview-q__source"><span className="label">서류의 근거 문장</span>{card.sourceQuote}</blockquote> : null}
      <h4>답변 받아쓰기</h4>
      <Answer text={card.transcript} />
      {card.followUps.map(follow => (
        <div key={follow.id} className="interview-followup">
          <h4>추가 질문: {follow.text}</h4>
          <Answer text={follow.transcript} />
        </div>
      ))}
      {evaluationDone && card.evaluation?.score != null ? <p className="interview-score">질문 점수 {formatScore(card.evaluation.score)}</p> : null}
      {grades.length > 0 ? (
        <ul className="interview-grades">
          {grades.map(([key, grade]) => (
            <li key={key}>
              <strong>{rubricLabel(key)}</strong> <span className="interview-grade">{grade.grade} / 4</span>
              {grade.evidence_quote ? <blockquote><span className="label">근거 ({gradeSourceLabel(grade.evidence_source)})</span>{grade.evidence_quote}</blockquote> : null}
              {grade.reason ? <p>{grade.reason}</p> : null}
              {grade.improvement ? <p className="interview-improve"><span className="label">보완점</span> {grade.improvement}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function SummaryList({ title, values }: { title: string; values: string[] }) {
  return values.length > 0 ? <div><h4>{title}</h4><ul>{values.map(v => <li key={v}>{v}</li>)}</ul></div> : null;
}

export function InterviewReport({ items, questions, evaluation, onCancelEvaluation, onRetryEvaluation, children }: InterviewReportProps) {
  const result = evaluation.evaluation;
  const done = evaluation.status === 'complete' && result !== null;
  const cards = buildReportCards(items, questions, done ? result : null);
  const { status, progress, error } = evaluation;
  return (
    <div className="interview-results">
      <section className="interview-panel" aria-label="종합 피드백">
        <h2>종합 피드백</h2>
        {status === 'running' ? (
          <div className="interview-progress" role="status" aria-live="polite">
            <progress aria-label="평가 진행" max={progress?.total || undefined}
              value={progress?.total ? Math.max(0, (progress.index ?? 1) - 1) : undefined} />
            <span>{progress ? evaluationProgressLabel(progress) : '평가를 시작하는 중'}</span>
            <small>받아쓰기와 아래의 음성·시선 결과는 평가가 끝나기 전에도 볼 수 있습니다.</small>
            {onCancelEvaluation ? <button type="button" className="secondary-button" onClick={onCancelEvaluation}>평가 중단</button> : null}
          </div>
        ) : null}
        {(status === 'failed' || status === 'cancelled') ? (
          <div role="alert" className="interview-eval-error">
            <p className="error-text">{error ?? '평가하지 못했습니다.'}</p>
            <p className="interview-note">받아쓰기와 음성·시선 결과는 아래에서 확인할 수 있습니다.</p>
            {onRetryEvaluation ? <button type="button" className="secondary-button" onClick={onRetryEvaluation}>다시 평가</button> : null}
          </div>
        ) : null}
        {status === 'idle' && items.length === 0 ? <p className="interview-note">평가할 답변이 없습니다. 질문이 나오기 전에 면접을 마쳤습니다.</p> : null}
        {done && result ? (
          <div className="interview-overall">
            <p className="interview-overall__score"><span className="label">전체 점수</span><strong>{formatScore(result.overall_score)}</strong></p>
            {result.warnings.map(code => <p key={code} className="interview-warning">{WARNING_LABEL[code] ?? code}</p>)}
            <SummaryList title="강점" values={result.summary.strengths} />
            <SummaryList title="보완할 점" values={result.summary.improvements} />
            <SummaryList title="다음 연습 목표" values={result.summary.next_goals} />
          </div>
        ) : null}
        <p className="interview-note">
          평가는 음성 받아쓰기를 바탕으로 하므로 인식 오류가 점수에 영향을 줄 수 있습니다. 시선·맥박·목소리 활성도는 점수에 넣지 않았습니다.
        </p>
      </section>
      <section className="interview-results__cards" aria-label="질문별 결과">
        <h2>질문별 결과</h2>
        {cards.length === 0 ? <p className="interview-note">질문별 기록이 없습니다.</p> : null}
        {cards.map(card => <Card key={card.id} card={card} evaluationDone={done} />)}
      </section>
      {children}
    </div>
  );
}
