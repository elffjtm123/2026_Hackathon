import {apiBase} from '../../lib/apiBase.ts';
import type {DocumentKind, EvaluationProgress, ExtractedDocument, InterviewEvaluation, InterviewPlan,
  PlanProgress} from './types.ts';

export class InterviewApiError extends Error {
  code: string;
  status?: number;
  constructor(code: string, message: string, status?: number) {
    super(message);
    this.name = 'InterviewApiError';
    this.code = code;
    this.status = status;
  }
}

const MESSAGES: Record<string, string> = {
  INTERVIEW_DOCUMENT_REQUEST_INVALID: '문서 요청 형식이 올바르지 않습니다. 종류별로 파일을 하나씩, 최대 3개까지 올려 주세요.',
  INTERVIEW_DOCUMENT_TOO_LARGE: '파일이 너무 큽니다. 더 작은 파일을 올리거나 내용을 붙여넣어 주세요.',
  INTERVIEW_DOCUMENT_UNREADABLE: '파일을 읽지 못했습니다. 손상·암호화된 파일이거나 형식이 맞지 않습니다. PDF로 다시 저장하거나 내용을 붙여넣어 주세요.',
  INTERVIEW_PLAN_REQUEST_INVALID: '서류 글자 수가 한도를 넘었습니다. 내용을 줄여 주세요.',
  INTERVIEW_MODEL_UNAVAILABLE: '로컬 생성 모델과 실행 파일이 준비되지 않았습니다. 모델을 준비한 뒤 다시 시도하세요.',
  INTERVIEW_PLAN_FAILED: '질문 생성에 실패했습니다. 다시 시도하세요.',
  INTERVIEW_PLAN_CANCELLED: '질문 생성을 중단했습니다.',
  INTERVIEW_NOT_FOUND: '면접 기록을 찾지 못했습니다. 서버가 다시 시작되면 기록이 사라집니다.',
  INTERVIEW_NOT_READY: '면접이 끝난 뒤 평가할 수 있습니다.',
  INTERVIEW_EVALUATION_FAILED: '답변 평가에 실패했습니다. 다시 시도하세요.',
  INTERVIEW_EVALUATION_CANCELLED: '평가를 중단했습니다.',
  INTERVIEW_BUSY: '진행 중인 면접 준비 또는 평가가 끝난 뒤 다시 시도하세요.',
  SUMMARY_BUSY: '대본 요약을 마친 뒤 다시 시도하세요.',
  PRACTICE_ACTIVE: '진행 중인 연습 세션을 종료한 뒤 다시 시도하세요.',
  LOCAL_MODE_REQUIRED: '면접 연습은 로컬 AI 모드에서만 지원합니다.',
  DEVELOPMENT_ONLY: '로컬 개발 화면에서만 면접 연습을 쓸 수 있습니다.',
  VALIDATION_ERROR: '입력값이 올바르지 않습니다. 직무는 30자 이하로 입력해 주세요.',
};

export function interviewErrorMessage(code: string | undefined, serverMessage?: string): string {
  return (code && MESSAGES[code]) || serverMessage || '요청에 실패했습니다. 다시 시도하세요.';
}

type FetchLike = (input: string, init: RequestInit) => Promise<Response>;
type CallOptions = {signal?: AbortSignal; fetch?: FetchLike};
const base = () => `${apiBase}/interview`;
const doFetch = (options: CallOptions): FetchLike => options.fetch ?? ((url, init) => fetch(url, init));
const BAD_RESPONSE = '서버 응답을 확인할 수 없습니다.';

async function failure(response: Response): Promise<InterviewApiError> {
  try {
    const body = await response.json();
    const code = typeof body?.error?.code === 'string' ? body.error.code : 'HTTP_ERROR';
    return new InterviewApiError(code, interviewErrorMessage(code, body?.error?.message), response.status);
  } catch {
    return new InterviewApiError('HTTP_ERROR', '서버에 연결할 수 없거나 응답이 올바르지 않습니다.', response.status);
  }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isStrings = (value: unknown) => Array.isArray(value) && value.every(v => typeof v === 'string');

export function parsePlan(data: unknown): InterviewPlan {
  if (!isObject(data) || typeof data.interview_id !== 'string' || !Array.isArray(data.questions)
      || !isStrings(data.warnings)
      || !data.questions.every(q => isObject(q) && typeof q.id === 'string' && typeof q.text === 'string'
        && Array.isArray(q.rubric_items))) throw new InterviewApiError('BAD_RESPONSE', BAD_RESPONSE);
  return data as unknown as InterviewPlan;
}

export function parseEvaluation(data: unknown): InterviewEvaluation {
  const summary = isObject(data) ? data.summary : null;
  if (!isObject(data) || !Array.isArray(data.items) || !isObject(summary) || !isStrings(summary.strengths)
      || !isStrings(summary.improvements) || !isStrings(summary.next_goals) || !isStrings(data.warnings)
      || !data.items.every(i => isObject(i) && typeof i.question_id === 'string' && typeof i.status === 'string'
        && isObject(i.grades))) throw new InterviewApiError('BAD_RESPONSE', BAD_RESPONSE);
  return data as unknown as InterviewEvaluation;
}

const MAX_BUFFER = 4 * 1024 * 1024;
const MAX_FRAMES = 1024;

// Reads `progress` lines and returns the data of the final `complete` line; an `error` line, a
// stream that ends early and malformed lines all reject.
export async function readInterviewStream<P = Record<string, unknown>, T = unknown>(response: Response,
    options: {onProgress?: (progress: P) => void} = {}): Promise<T> {
  if (!response.ok) throw await failure(response);
  if (!response.body || !response.headers.get('content-type')?.includes('application/x-ndjson'))
    throw new InterviewApiError('BAD_RESPONSE', BAD_RESPONSE);
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', {fatal: true});
  let buffer = '', frames = 0;
  const bad = (message = BAD_RESPONSE) => new InterviewApiError('BAD_RESPONSE', message);
  // Returns the data of the `complete` line, or undefined for a progress line.
  const handle = (line: string): {data: T} | undefined => {
    if (!line.trim()) return undefined;
    if (++frames > MAX_FRAMES) throw bad('진행 응답이 너무 많습니다.');
    let event: unknown;
    try { event = JSON.parse(line); } catch { throw bad(); }
    if (!isObject(event) || !isObject(event.data)) throw bad();
    if (event.event === 'error') {
      const code = typeof event.data.code === 'string' ? event.data.code : 'HTTP_ERROR';
      throw new InterviewApiError(code, interviewErrorMessage(code, String(event.data.message ?? '')));
    }
    if (event.event === 'progress') {
      if (typeof event.data.stage !== 'string') throw bad();
      options.onProgress?.(event.data as P);
      return undefined;
    }
    if (event.event === 'complete') return {data: event.data as T};
    throw bad();
  };
  try {
    while (true) {
      const {done, value} = await reader.read();
      try { buffer += decoder.decode(value, {stream: !done}); } catch { throw bad(); }
      if (buffer.length > MAX_BUFFER) throw bad('응답이 너무 큽니다.');
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
        const result = handle(line);
        if (result) return result.data;
      }
      if (done) {
        const result = handle(buffer);  // a final line may come without a newline
        if (result) return result.data;
        throw bad('완료 전에 연결이 종료됐습니다. 다시 시도하세요.');
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function uploadDocuments(entries: {kind: DocumentKind; file: File}[],
    options: CallOptions = {}): Promise<ExtractedDocument[]> {
  const form = new FormData();
  for (const {kind, file} of entries) { form.append('files', file, file.name); form.append('kinds', kind); }
  // No Content-Type header: the browser adds the multipart boundary.
  const response = await doFetch(options)(`${base()}/documents`, {method: 'POST', body: form, signal: options.signal});
  if (!response.ok) throw await failure(response);
  let data: unknown;
  try { data = await response.json(); } catch { throw new InterviewApiError('BAD_RESPONSE', BAD_RESPONSE); }
  if (!Array.isArray(data) || !data.every(d => isObject(d) && typeof d.kind === 'string'
      && typeof d.text === 'string' && Array.isArray(d.warnings))) throw new InterviewApiError('BAD_RESPONSE', BAD_RESPONSE);
  return data as ExtractedDocument[];
}

export type PlanRequest = {documents: {kind: DocumentKind; text: string}[]; job: string | null; exclude_common_ids: string[]};

export async function requestPlan(body: PlanRequest,
    options: CallOptions & {onProgress?: (progress: PlanProgress) => void} = {}): Promise<InterviewPlan> {
  const response = await doFetch(options)(`${base()}/plans`, {method: 'POST', signal: options.signal,
    headers: {'Content-Type': 'application/json', Accept: 'application/x-ndjson'}, body: JSON.stringify(body)});
  return parsePlan(await readInterviewStream<PlanProgress>(response, {onProgress: options.onProgress}));
}

export async function requestEvaluation(interviewId: string,
    options: CallOptions & {onProgress?: (progress: EvaluationProgress) => void} = {}): Promise<InterviewEvaluation> {
  const response = await doFetch(options)(`${base()}/${encodeURIComponent(interviewId)}/evaluation`,
    {method: 'GET', signal: options.signal, headers: {Accept: 'application/x-ndjson'}});
  return parseEvaluation(await readInterviewStream<EvaluationProgress>(response, {onProgress: options.onProgress}));
}

// Resolves when the server has stopped llama-server (204), also when nothing was running.
export async function cancelEvaluation(interviewId: string, options: Pick<CallOptions, 'fetch'> = {}): Promise<void> {
  const response = await doFetch(options)(`${base()}/${encodeURIComponent(interviewId)}/evaluation`, {method: 'DELETE'});
  if (!response.ok) throw await failure(response);
}
