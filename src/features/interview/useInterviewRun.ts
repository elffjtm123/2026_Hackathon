import { useCallback, useReducer } from 'react';
import type { RealtimeEvent } from '../../lib/realtimeProtocol.ts';
import { initialInterviewState, interviewReducer } from './interviewState.ts';

// Screen state of the running interview, from the server's question and break events.
export function useInterviewRun() {
  const [run, dispatch] = useReducer(interviewReducer, initialInterviewState);
  const receiveEvent = useCallback((event: RealtimeEvent) =>
    dispatch({type: 'event', event: event.event, data: event.data, at: performance.now(), serverMs: event.timestamp_ms}), []);
  const markReplayRequested = useCallback(() => dispatch({type: 'replay_requested'}), []);
  const reset = useCallback(() => dispatch({type: 'reset'}), []);
  return {run, receiveEvent, markReplayRequested, reset};
}
