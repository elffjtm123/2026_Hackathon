import type {AdvanceReason} from './types.ts';

// Screen state of a running interview, from the server's `interview.*` and `session.*` events.
// The server decides when a question is hidden or the interview moves on; the client only keeps
// what it needs to draw countdowns. `at` is the local clock (performance.now) of the event's
// arrival, `serverMs` the session clock it carries.

export type BreakStage = 'suspending' | 'generating' | 'resuming' | 'skipped';
export type InterviewQuestion = {id: string; round: number; index: number; total: number; text: string;
  readingMs: number; answerLimitMs: number};
export type BreakInterval = {startMs: number; endMs: number | null};

export type InterviewRunState = {
  status: 'idle' | 'asking' | 'advancing' | 'break' | 'finished';
  question: InterviewQuestion | null;
  textVisible: boolean;
  readingStartedAt: number | null;
  // Answer time used before the clock last stopped (a replay stops it), and when it runs again.
  answerElapsedMs: number;
  answerRunningSince: number | null;
  replayAvailable: boolean;
  replayPending: boolean;
  advanceReason: AdvanceReason | null;
  breakStage: BreakStage | null;
  followUpCount: number | null;
  suspended: boolean;
  breaks: BreakInterval[];
};

export const initialInterviewState: InterviewRunState = {
  status: 'idle', question: null, textVisible: false, readingStartedAt: null, answerElapsedMs: 0,
  answerRunningSince: null, replayAvailable: false, replayPending: false, advanceReason: null,
  breakStage: null, followUpCount: null, suspended: false, breaks: [],
};

export type InterviewAction =
  | {type: 'event'; event: string; data: Record<string, unknown>; at: number; serverMs: number}
  | {type: 'replay_requested'}
  | {type: 'reset'};

const BREAK_STAGES: BreakStage[] = ['suspending', 'generating', 'resuming', 'skipped'];
const REASONS: AdvanceReason[] = ['silence', 'time_limit', 'no_response', 'stopped'];
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function parseQuestion(data: Record<string, unknown>): InterviewQuestion | null {
  const {question_id: id, round, index, total, text, reading_ms: readingMs, answer_limit_ms: answerLimitMs} = data;
  if (typeof id !== 'string' || typeof text !== 'string' || !isNumber(round) || !isNumber(index) || !isNumber(total)
      || !isNumber(readingMs) || !isNumber(answerLimitMs)) return null;
  return {id, round, index, total, text, readingMs, answerLimitMs};
}

// Closes the break that is still open (the session ended during it) at `endMs`.
export const closeOpenBreaks = (breaks: BreakInterval[], endMs: number): {startMs: number; endMs: number}[] =>
  closeBreak(breaks, endMs).map(b => ({startMs: b.startMs, endMs: b.endMs ?? Math.max(endMs, b.startMs)}));

const closeBreak = (breaks: BreakInterval[], endMs: number, startMs?: number): BreakInterval[] =>
  breaks.map((b, i) => i === breaks.length - 1 && b.endMs === null
    ? {startMs: startMs ?? b.startMs, endMs: Math.max(endMs, startMs ?? b.startMs)} : b);

export function interviewReducer(state: InterviewRunState, action: InterviewAction): InterviewRunState {
  if (action.type === 'reset') return initialInterviewState;
  if (action.type === 'replay_requested') return state.replayAvailable ? {...state, replayPending: true} : state;
  const {event, data, at, serverMs} = action;
  switch (event) {
    case 'interview.question': {
      const question = parseQuestion(data);
      if (!question) return state;
      const replay = state.question?.id === question.id && state.status === 'asking';
      const running = state.answerRunningSince;
      return {...state, status: 'asking', question, textVisible: true, advanceReason: null, breakStage: null,
        replayAvailable: data.replay_available === true, replayPending: false,
        readingStartedAt: at,
        // A replay stops the answer clock; a new question starts it from zero.
        answerElapsedMs: replay ? state.answerElapsedMs + (running === null ? 0 : at - running) : 0,
        answerRunningSince: null};
    }
    case 'interview.question_hidden':
      if (state.status !== 'asking' || data.question_id !== state.question?.id || !state.textVisible) return state;
      return {...state, textVisible: false, answerRunningSince: at};
    case 'interview.replay_rejected':
      if (data.question_id !== state.question?.id) return state;
      return {...state, replayAvailable: false, replayPending: false};
    case 'interview.advanced': {
      if (state.status !== 'asking' || data.question_id !== state.question?.id) return state;
      const reason = REASONS.find(r => r === data.reason) ?? null;
      return {...state, status: 'advancing', textVisible: false, advanceReason: reason, replayAvailable: false,
        replayPending: false, answerRunningSince: null};
    }
    case 'interview.round_break': {
      const stage = BREAK_STAGES.find(s => s === data.stage);
      if (!stage) return state;
      return {...state, status: 'break', question: null, textVisible: false, breakStage: stage,
        followUpCount: isNumber(data.follow_up_count) ? data.follow_up_count : state.followUpCount,
        replayAvailable: false, replayPending: false, answerRunningSince: null};
    }
    case 'interview.finished':
      return {...state, status: 'finished', question: null, textVisible: false, replayAvailable: false,
        replayPending: false, answerRunningSince: null};
    case 'session.suspended':
      return state.suspended ? state : {...state, suspended: true, breaks: [...state.breaks, {startMs: serverMs, endMs: null}]};
    case 'session.resumed': {
      const length = isNumber(data.break_ms) && data.break_ms >= 0 ? data.break_ms : null;
      return {...state, suspended: false, breaks: closeBreak(state.breaks, serverMs, length === null ? undefined : serverMs - length)};
    }
    default:
      return state;
  }
}

// The button works once per question, only after the text is hidden, and not while a request is out.
export const canReplay = (state: InterviewRunState) =>
  state.status === 'asking' && !state.textVisible && state.replayAvailable && !state.replayPending;

export function readingRemainingMs(state: InterviewRunState, now: number): number {
  if (!state.question || !state.textVisible || state.readingStartedAt === null) return 0;
  // `now` is a coarse tick and can be older than the event: never more than the full time.
  return Math.min(state.question.readingMs, Math.max(0, state.question.readingMs - (now - state.readingStartedAt)));
}

// Null while the first reading is on screen (no answer time has passed). Stopped during a replay.
export function answerRemainingMs(state: InterviewRunState, now: number): number | null {
  if (!state.question || (state.answerRunningSince === null && state.answerElapsedMs === 0)) return null;
  const used = state.answerElapsedMs + (state.answerRunningSince === null ? 0 : Math.max(0, now - state.answerRunningSince));
  return Math.max(0, state.question.answerLimitMs - used);
}

// Questions still to come in the current round.
export const remainingQuestions = (state: InterviewRunState) =>
  state.question ? Math.max(0, state.question.total - state.question.index) : 0;

export function formatClock(ms: number): string {
  const total = Math.ceil(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

// Which interview screen shows. A session that ended before its first question has no result (the
// server gives the plan back), so it returns to the setup; a finished interview shows its report
// until the user asks for a new one, and its plan is spent meanwhile.
export function interviewScreen({locked, completed, hasSummary, asked, dismissed, interview = true}: {
  locked: boolean; completed: boolean; hasSummary: boolean; asked: boolean; dismissed: boolean;
  // The session mode on screen: a later presentation session says nothing about the interview's end.
  interview?: boolean;
}): {report: boolean; showSetup: boolean; planSpent: boolean; planLost: boolean} {
  const report = completed && hasSummary && asked;
  // Questions were asked but the session never completed (connection lost): the plan cannot be reused.
  return {report, showSetup: !locked && (!report || dismissed), planSpent: report && !dismissed,
    planLost: interview && !locked && asked && !(completed && hasSummary)};
}
