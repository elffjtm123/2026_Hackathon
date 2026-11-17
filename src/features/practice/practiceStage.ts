export type PracticeStage = 'prepare' | 'live' | 'result';

// Which part of the screen shows, from state the page already has: a locked session is live, a
// finished one with a summary shows its result, anything else is preparation.
export function practiceStage({locked, hasSummary}: {locked: boolean; hasSummary: boolean}): PracticeStage {
  return locked ? 'live' : hasSummary ? 'result' : 'prepare';
}

// A socket failure ends the session and unmounts the live stage, so the banner moves to the page.
// While FeedbackPanel is on screen (live stage, or the interview live view) it shows the error itself.
export function showPageSocketError({error, stage, interview, interviewReport, operationError = null}: {
  error: string | null; stage: PracticeStage; interview: boolean; interviewReport: boolean; operationError?: string | null;
}): boolean {
  if (!error || error === operationError) return false;
  return interview ? interviewReport : stage !== 'live';
}
