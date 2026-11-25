// Wire types of the interview HTTP API (app/schemas/interview.py) and session report.

export type DocumentKind = 'cover_letter' | 'resume' | 'portfolio';

export type DocumentWarning = {code: 'no_text' | 'truncated'; message: string};
export type ExtractedDocument = {kind: DocumentKind; text: string; warnings: DocumentWarning[]};

export type QuestionKind = 'common' | 'document' | 'follow_up';
export type PlannedQuestion = {
  id: string; kind: QuestionKind; subtype: string; text: string; intent: string;
  source_quote: string | null; rubric_items: string[]; parent_id: string | null;
  bank_id: string | null; round: 1 | 2;
};
export type InterviewPlan = {interview_id: string; questions: PlannedQuestion[]; warnings: string[]};
export type PlanProgress = {stage: string; completed?: number; total?: number};

export type Grade = {
  grade: number; evidence_quote: string; evidence_source: 'main' | 'follow_up';
  reason: string; improvement: string;
};
export type ItemStatus = 'evaluated' | 'not_evaluable' | 'not_scored' | 'failed';
export type NotEvaluableReason = 'no_response' | 'too_short' | 'recognition_failed';
export type ItemEvaluation = {
  question_id: string; status: ItemStatus; not_evaluable_reason: NotEvaluableReason | null;
  grades: Record<string, Grade>; excluded_items: string[]; partial: boolean;
  score: number | null; follow_up_ids: string[];
};
export type EvaluationSummary = {strengths: string[]; improvements: string[]; next_goals: string[]};
export type InterviewEvaluation = {
  items: ItemEvaluation[]; overall_score: number | null; summary: EvaluationSummary;
  model: string; elapsed_seconds: number;
  warnings: ('item_evaluation_failed' | 'summary_failed' | 'evaluation_timeout')[];
};
export type EvaluationProgress = {stage: string; index?: number; total?: number};

export type AdvanceReason = 'silence' | 'time_limit' | 'no_response' | 'stopped';
// One question's record from `session.completed` report.interview_items.
export type InterviewItem = {
  question_id: string; round: number; parent_id: string | null; text: string;
  shown_ms: number; answer_started_ms: number | null; ended_ms: number;
  advance_reason: AdvanceReason; replay_used: boolean; transcript: string;
};
