import type { RealtimeFeedback } from "./types";
import type { ScriptProgress } from '../../lib/realtimeProtocol';

export type FeedbackState = {
  scriptProgress?: ScriptProgress;
  gaze: RealtimeFeedback | null;
  speech: RealtimeFeedback | null;
  pronunciation: RealtimeFeedback | null;
  receivedAt?: Partial<Record<'gaze' | 'speech' | 'pronunciation', number>>;
  gazeStale?: boolean;
};

export const emptyFeedbackState: FeedbackState = {
  gaze: null,
  speech: null,
  pronunciation: null,
};

export function reduceFeedback(
  state: FeedbackState,
  feedback: RealtimeFeedback,
  receivedAt = performance.now()
): FeedbackState {
  if (feedback.source === 'script_sync') return {...state,scriptProgress:feedback.scriptProgress};
  if (feedback.source === "gaze") {
    return { ...state, gaze: feedback, receivedAt: {...state.receivedAt, gaze: receivedAt}, gazeStale: false };
  }
  if (feedback.source === "speech_rate") {
    if (feedback.utteranceId && feedback.utteranceId === state.speech?.utteranceId &&
        feedback.revision === state.speech?.revision) return state;
    return { ...state, speech: feedback, receivedAt: {...state.receivedAt, speech: receivedAt} };
  }
  if (feedback.source === "pronunciation") {
    return { ...state, pronunciation: feedback, receivedAt: {...state.receivedAt, pronunciation: receivedAt} };
  }
  return state;
}

export const directionLabels: Record<string,string> = {center:'정면',left:'왼쪽',right:'오른쪽',up:'위쪽',down:'아래쪽',unknown:'판단 불가',away:'기준 이탈'};
export const speechPaceLabels = {slow:'느림',normal:'설정 범위',fast:'빠름',unknown:'판단 대기'};

export function selectVisibleFeedback(state: FeedbackState, nowMs: number): FeedbackState {
  if (state.gaze && nowMs - (state.receivedAt?.gaze ?? -Infinity) > 1500) {
    return {...state, gaze:null, gazeStale:true};
  }
  return state;
}

export function gazeLabel(state: FeedbackState): string {
  const gaze = state.gaze?.gaze;
  if (!gaze) return state.gazeStale ? '관찰 지연·판단 불가' : '분석 대기';
  if (gaze.recalibrationRequired) return '다시 보정 필요';
  if (!gaze.calibrated) return `보정 중 (${gaze.calibrationProgress ?? 0}/${gaze.calibrationTarget ?? 16})`;
  if (!gaze.faceDetected || gaze.attentionState === 'unknown') return '판단 불가';
  return gaze.attentionState === 'away' ? `기준 이탈 (${directionLabels[gaze.direction]})` : '보정 기준 근처';
}

export function feedbackMessage(state: FeedbackState): string | undefined {
  const feedbacks = [state.gaze,state.speech,state.pronunciation].filter((item): item is RealtimeFeedback => item !== null);
  const rank = {info:0,warning:1,danger:2};
  feedbacks.sort((a,b) => rank[b.severity]-rank[a.severity]);
  const selected = feedbacks[0];
  return selected?.message ?? selected?.gaze?.message ?? selected?.speech?.message ?? selected?.pronunciation?.message ?? (state.gazeStale ? '영상 관찰이 지연되어 시선을 판단할 수 없습니다.' : undefined);
}
