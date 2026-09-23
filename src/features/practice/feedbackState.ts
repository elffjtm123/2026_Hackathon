import type { RealtimeFeedback } from "./types";

export type FeedbackState = {
  gaze: RealtimeFeedback | null;
  speech: RealtimeFeedback | null;
  pronunciation: RealtimeFeedback | null;
};

export const emptyFeedbackState: FeedbackState = {
  gaze: null,
  speech: null,
  pronunciation: null,
};

export function reduceFeedback(
  state: FeedbackState,
  feedback: RealtimeFeedback
): FeedbackState {
  if (feedback.source === "gaze") {
    return { ...state, gaze: feedback };
  }
  if (feedback.source === "speech_rate") {
    return { ...state, speech: feedback };
  }
  if (feedback.source === "pronunciation") {
    return { ...state, pronunciation: feedback };
  }
  return state;
}
