import type {DocumentKind, DocumentWarning, InterviewPlan, PlanProgress, PlannedQuestion} from './types.ts';
import type {PlanRequest} from './api.ts';
import type {HistoryEntry} from './storage.ts';

export const MAX_TOTAL_CHARS = 30000;
export const MAX_JOB_CHARS = 30;

export const DOCUMENT_KINDS: {kind: DocumentKind; label: string}[] = [
  {kind: 'cover_letter', label: '자기소개서'}, {kind: 'resume', label: '이력서'}, {kind: 'portfolio', label: '포트폴리오'}];

export type DocumentTexts = Partial<Record<DocumentKind, string>>;

export function classifyFile(name: string): {ok: true} | {ok: false; message: string} {
  const extension = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : '';
  if (['pdf', 'docx', 'txt'].includes(extension)) return {ok: true};
  if (extension === 'hwp' || extension === 'hwpx')
    return {ok: false, message: '한글(HWP/HWPX) 파일은 올릴 수 없습니다. 한글에서 PDF로 저장한 뒤 올리거나 내용을 붙여넣어 주세요.'};
  return {ok: false, message: 'PDF, DOCX, TXT 파일만 올릴 수 있습니다.'};
}

export const totalChars = (texts: DocumentTexts) => Object.values(texts).reduce((sum, text) => sum + (text?.length ?? 0), 0);

export function documentStatus(warnings: DocumentWarning[]): string {
  const messages: string[] = [];
  if (warnings.some(w => w.code === 'no_text'))
    messages.push('파일에서 글자를 찾지 못했습니다. 스캔·이미지 파일일 수 있으니 내용을 아래에 직접 붙여넣어 주세요.');
  if (warnings.some(w => w.code === 'truncated'))
    messages.push('글자 수 한도(합계 30,000자) 때문에 뒷부분이 잘렸습니다. 필요한 내용을 직접 붙여넣어 주세요.');
  return messages.join(' ');
}

export function buildPlanRequest(texts: DocumentTexts, job: string, excludeCommonIds: string[]): PlanRequest {
  const documents = DOCUMENT_KINDS.flatMap(({kind}) => (texts[kind] ?? '').trim() ? [{kind, text: texts[kind] as string}] : []);
  const trimmed = job.trim().slice(0, MAX_JOB_CHARS);
  return {documents, job: trimmed || null, exclude_common_ids: excludeCommonIds};
}

export function moveQuestion(order: string[], id: string, direction: -1 | 1): string[] {
  const from = order.indexOf(id), to = from + direction;
  if (from < 0 || to < 0 || to >= order.length) return order;
  const next = [...order];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

export const toggleQuestion = (selected: string[], id: string) =>
  selected.includes(id) ? selected.filter(s => s !== id) : [...selected, id];

// The chosen questions in list order, not click order.
export const selectedIds = (order: string[], selected: string[]) => order.filter(id => selected.includes(id));
export const canStartInterview = (order: string[], selected: string[]) => selectedIds(order, selected).length > 0;

export const startPayload = (plan: Pick<InterviewPlan, 'interview_id'>, order: string[], selected: string[]) =>
  ({interview_id: plan.interview_id, question_ids: selectedIds(order, selected)});

// Bank ids of the questions the user chose to practice, which later plans should avoid.
export function historyEntryFor(plan: {interview_id: string; questions: Pick<PlannedQuestion, 'id' | 'bank_id'>[]},
    chosen: string[], date: string): HistoryEntry {
  return {interview_id: plan.interview_id, date,
    common_bank_ids: plan.questions.filter(q => chosen.includes(q.id) && q.bank_id).map(q => q.bank_id as string)};
}

export function planProgressLabel(progress: PlanProgress): string {
  switch (progress.stage) {
    case 'loading': return '질문 생성 모델을 불러오는 중';
    case 'extracting': return progress.total
      ? `서류에서 질문 재료를 찾는 중 (${progress.completed ?? 0}/${progress.total})` : '서류에서 질문 재료를 찾는 중';
    case 'generating': return '질문을 만드는 중';
    case 'validating': return '질문을 검토하는 중';
    case 'cleaning': return '모델을 정리하는 중';
    case 'done': return '질문 생성을 마무리하는 중';
    default: return '질문을 준비하는 중';
  }
}

const PLAN_WARNINGS: Record<string, string> = {
  document_questions_failed: '서류 기반 질문을 만들지 못해 공통 질문으로 채웠습니다. 서류 내용을 확인하거나 다시 생성해 보세요.',
  few_materials: '서류에서 찾은 질문 재료가 적어 일부를 공통 질문으로 채웠습니다.',
};
export const planWarningText = (code: string) => PLAN_WARNINGS[code] ?? '질문 생성 중 알림이 있습니다.';
