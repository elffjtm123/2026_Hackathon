import type {EvaluationProgress, Grade, InterviewEvaluation, InterviewItem, ItemEvaluation, NotEvaluableReason,
  PlannedQuestion} from './types.ts';

const RUBRIC_LABELS: Record<string, string> = {
  understanding: '질문·직무 이해', reasoning: '문제 해결과 판단 근거', specificity: '경험·행동의 구체성',
  learning: '결과와 학습', collaboration: '협업과 의사소통',
};
export const rubricLabel = (key: string) => RUBRIC_LABELS[key] ?? key;

const NOT_EVALUABLE: Record<NotEvaluableReason, string> = {
  no_response: '무응답', too_short: '답변이 너무 짧음', recognition_failed: '인식 실패',
};
export const notEvaluableText = (reason: NotEvaluableReason | null | undefined) => reason ? NOT_EVALUABLE[reason] : '평가 불가';

export const gradeSourceLabel = (source: Grade['evidence_source']) => source === 'follow_up' ? '추가 답변' : '본 답변';
export const formatScore = (score: number | null | undefined) => score == null ? '점수 없음' : `${score.toFixed(1)} / 20`;

export type Badge = {tone: 'ok' | 'partial' | 'neutral' | 'failed' | 'pending'; label: string};
export function itemBadge(item: ItemEvaluation | undefined): Badge {
  if (!item) return {tone: 'pending', label: '평가 전'};
  if (item.status === 'not_evaluable') return {tone: 'neutral', label: `평가 불가 · ${notEvaluableText(item.not_evaluable_reason)}`};
  if (item.status === 'not_scored') return {tone: 'neutral', label: '마무리 질문 · 평가하지 않음'};
  if (item.status === 'failed') return {tone: 'failed', label: '평가 실패 · 점수에서 제외'};
  if (item.partial) return {tone: 'partial', label: `부분 평가 · 제외된 항목: ${item.excluded_items.map(rubricLabel).join(', ')}`};
  return {tone: 'ok', label: '평가 완료'};
}

export type ReportItem = Pick<InterviewItem, 'question_id' | 'parent_id' | 'round' | 'text' | 'transcript' | 'advance_reason' | 'replay_used'>;
export type ReportCard = {id: string; text: string; transcript: string; round: number; advanceReason: ReportItem['advance_reason'];
  replayUsed: boolean; sourceQuote: string | null; evaluation: ItemEvaluation | undefined; followUps: ReportCard[]};

// One card per main question; follow-ups sit in their parent. A follow-up whose parent is missing
// gets a card of its own so no answer is lost.
export function buildReportCards(items: ReportItem[], questions: Pick<PlannedQuestion, 'id' | 'source_quote'>[],
    evaluation: InterviewEvaluation | null): ReportCard[] {
  const known = new Set(items.map(i => i.question_id));
  const card = (item: ReportItem): ReportCard => ({id: item.question_id, text: item.text, transcript: item.transcript,
    round: item.round, advanceReason: item.advance_reason, replayUsed: item.replay_used,
    sourceQuote: questions.find(q => q.id === item.question_id)?.source_quote ?? null,
    evaluation: evaluation?.items.find(e => e.question_id === item.question_id), followUps: []});
  const cards: ReportCard[] = [];
  const byId = new Map<string, ReportCard>();
  for (const item of items) {
    if (item.parent_id !== null && known.has(item.parent_id)) continue;
    const next = card(item);
    cards.push(next); byId.set(next.id, next);
  }
  for (const item of items) {
    if (item.parent_id !== null && known.has(item.parent_id)) byId.get(item.parent_id)?.followUps.push(card(item));
  }
  return cards;
}

export function evaluationProgressLabel(progress: EvaluationProgress): string {
  switch (progress.stage) {
    case 'loading': return '평가 모델을 불러오는 중';
    case 'evaluating': return progress.total ? `질문별 답변을 평가하는 중 (${progress.index ?? 0}/${progress.total})` : '질문별 답변을 평가하는 중';
    case 'summarizing': return '종합 피드백을 만드는 중';
    case 'cleaning': return '모델을 정리하는 중';
    default: return '평가를 준비하는 중';
  }
}
