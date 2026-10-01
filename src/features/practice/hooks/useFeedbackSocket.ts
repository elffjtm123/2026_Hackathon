import { useCallback, useEffect, useRef, useState } from 'react';
import type { BackendClientEvent, ClientRealtimeMessage, ConnectionStatus, PracticeMode,
  PresentationFeatureSettings, RealtimeFeedback, SessionCompletionReport } from '../types';
import type { ModuleStatus, RealtimeEvent, SessionPhase, SessionReadyData } from '../../../lib/realtimeProtocol.ts';
import { completionForUi, feedbackForUi } from '../../../lib/realtimeProtocol.ts';
import { encodeMediaV2, type MediaPacket } from '../../../lib/mediaProtocol.ts';
import { acceptServerEvent, checkMediaBacklog } from '../sessionLifecycle.ts';

const feedbackWsUrl = (import.meta.env?.VITE_FEEDBACK_WS_URL as string | undefined)
  ?? 'ws://127.0.0.1:8000/api/v1/ws/practice-demo';

// v1 compatibility adapter; live capture uses v2.
export function toBackendEvent(message: ClientRealtimeMessage): BackendClientEvent {
  if (message.type === 'session.start') return {event: 'session.start', timestamp_ms: message.timestamp,
    data: {sessionId: message.sessionId, mode: message.mode, settings: message.settings,
      ...(message.mode === 'presentation' ? {script: message.script, timeLimitSeconds: message.timeLimitSeconds} : {})}};
  if (message.type === 'client.ping') return {event: 'ping', timestamp_ms: message.timestamp, data: {}};
  return {event: 'session.end', timestamp_ms: message.timestamp, data: {sessionId: message.sessionId}};
}

type Pending<T> = {promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout>};
function pending<T>(milliseconds: number, message: string, onTimeout: (error: Error) => void): Pending<T> {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;});
  void promise.catch(() => undefined);
  const timer = setTimeout(() => {const error = new Error(message); reject(error); onTimeout(error);}, milliseconds);
  return {promise, resolve, reject, timer};
}

export function useFeedbackSocket(onFeedback: (feedback: RealtimeFeedback) => void,
  onPhase: (phase: SessionPhase, sessionId: string, elapsedMs?: number) => void) {
  const socketRef = useRef<WebSocket | null>(null);
  const idRef = useRef('');
  const lastSequenceRef = useRef(0);
  const clientSequenceRef = useRef(0);
  const clockRef = useRef({server: 0, local: 0});
  const readyRef = useRef<Pending<SessionReadyData> | null>(null);
  const completionRef = useRef<Pending<SessionCompletionReport> | null>(null);
  const ackRef = useRef(new Map<number, {pending: Pending<void>; samples: number}>());
  const acknowledgedRef = useRef(0);
  const videoSequenceRef = useRef(0);
  const audioOriginRef = useRef(0);
  const runningRef = useRef(false);
  const callbacks = useRef({onFeedback, onPhase});
  useEffect(() => {callbacks.current = {onFeedback, onPhase};}, [onFeedback, onPhase]);
  const [status, setStatus] = useState<ConnectionStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [modules, setModules] = useState<Record<string, ModuleStatus>>({});

  const rejectPending = useCallback((reason: Error) => {
    for (const value of [readyRef.current, completionRef.current]) {
      if (value) {clearTimeout(value.timer); value.reject(reason);}
    }
    readyRef.current = null; completionRef.current = null;
    for (const value of ackRef.current.values()) {clearTimeout(value.pending.timer); value.pending.reject(reason);}
    ackRef.current.clear();
  }, []);
  const disconnect = useCallback(() => {
    const socket = socketRef.current;
    socketRef.current = null; runningRef.current = false;
    rejectPending(new Error('연결이 종료되었습니다.'));
    socket?.close();
    setStatus(current => current === 'idle' ? current : 'disconnected');
  }, [rejectPending]);
  const fail = useCallback((reason: Error) => {
    setError(reason.message); setStatus('error'); runningRef.current = false;
    rejectPending(reason);
  }, [rejectPending]);
  const sessionTime = useCallback(() => Math.max(0, Math.floor(clockRef.current.server + performance.now() - clockRef.current.local)), []);
  const control = useCallback((event: string, data: Record<string, unknown> = {}) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) throw new Error('WebSocket 연결이 끊겼습니다.');
    socketRef.current.send(JSON.stringify({event, version: 2, session_id: idRef.current || null,
      sequence: ++clientSequenceRef.current, module: 'system', level: 'info', timestamp_ms: sessionTime(), data}));
  }, [sessionTime]);

  const connect = useCallback((_clientId: string, mode: PracticeMode, settings: PresentationFeatureSettings,
      script?: string, timeLimitSeconds?: number): Promise<SessionReadyData> => {
    disconnect();
    setStatus('connecting'); setError(null); setModules({});
    idRef.current = ''; lastSequenceRef.current = 0; acknowledgedRef.current = 0; videoSequenceRef.current = 0;
    clientSequenceRef.current = 0;
    const url = new URL(feedbackWsUrl); url.searchParams.set('protocol', '2');
    const socket = new WebSocket(url); socketRef.current = socket;
    const waiting = pending<SessionReadyData>(5000, '서버 준비 응답 시간이 초과되었습니다.', fail);
    readyRef.current = waiting;
    socket.onopen = () => {
      if (socketRef.current !== socket) return;
      socket.send(JSON.stringify({event: 'session.start', version: 2, session_id: null,
        sequence: ++clientSequenceRef.current, module: 'system', level: 'info', timestamp_ms: 0, data: {
        mode, settings: {karaoke_guide_enabled: settings.karaokeGuideEnabled},
        ...(mode === 'presentation' && script ? {script, time_limit_seconds: timeLimitSeconds} : {})}}));
    };
    socket.onmessage = event => {
      if (socketRef.current !== socket) return;
      try {
        const message = JSON.parse(String(event.data)) as RealtimeEvent;
        if (message.version !== 2 || typeof message.session_id !== 'string' || !message.data) throw new Error('지원하지 않는 서버 응답');
        if (!idRef.current && (message.event === 'session.ready' || message.event === 'error')) idRef.current = message.session_id;
        if (!acceptServerEvent(message, idRef.current, lastSequenceRef.current)) return;
        lastSequenceRef.current = message.sequence;
        if (message.event === 'session.ready') {
          const ready = {sessionId: message.session_id, timestampMs: message.timestamp_ms, modules: message.data.modules as Record<string, ModuleStatus>};
          clockRef.current = {server: message.timestamp_ms, local: performance.now()};
          setModules(ready.modules); setStatus('connected');
          if (readyRef.current) {clearTimeout(readyRef.current.timer); readyRef.current.resolve(ready); readyRef.current = null;}
        } else if (message.event === 'session.calibrating') {
          callbacks.current.onPhase('calibrating', idRef.current);
        } else if (message.event === 'session.running') {
          audioOriginRef.current = Number(message.data.audio_origin_ms); runningRef.current = true;
          callbacks.current.onPhase('running', idRef.current, sessionTime() - Number(message.data.running_started_ms));
        } else if (message.event === 'session.draining') {
          callbacks.current.onPhase('draining', idRef.current);
        } else if (message.event === 'media.ack') {
          const sequence = Number(message.data.accepted_sequence);
          const value = ackRef.current.get(sequence);
          if (value) {clearTimeout(value.pending.timer); value.pending.resolve(); ackRef.current.delete(sequence); acknowledgedRef.current = Math.max(acknowledgedRef.current, sequence);}
        } else if (message.event === 'feedback') {
          callbacks.current.onFeedback(feedbackForUi(message));
        } else if (message.event === 'session.completed') {
          const report = completionForUi(message.data.report as Record<string, unknown>);
          if (completionRef.current) {clearTimeout(completionRef.current.timer); completionRef.current.resolve(report); completionRef.current = null;}
          runningRef.current = false;
        } else if (message.event === 'error') {
          if (message.data.modules) setModules(message.data.modules as Record<string, ModuleStatus>);
          const reason = String(message.data.code) + ': ' + String(message.data.message);
          if (message.data.code === 'CALIBRATION_TIMEOUT') setError(reason);
          else fail(new Error(reason));
        }
      } catch (reason) {fail(reason instanceof Error ? reason : new Error('서버 응답 오류'));}
    };
    socket.onerror = () => {if (socketRef.current === socket) fail(new Error('WebSocket 연결에 실패했습니다. 결과가 미완료될 수 있습니다.'));};
    socket.onclose = () => {if (socketRef.current === socket) fail(new Error('연결이 끊겼습니다. 세션 결과가 미완료될 수 있습니다.'));};
    return waiting.promise;
  }, [disconnect, fail, sessionTime]);

  const sendVideoFrame = useCallback(async (payload: Blob, timestampMs: number) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    const buffer = await payload.arrayBuffer();
    if (socketRef.current !== socket || socket.readyState !== WebSocket.OPEN) return false;
    try {
      checkMediaBacklog(socket.bufferedAmount + buffer.byteLength + 26, 0);
      socket.send(encodeMediaV2({type: 1, sequence: ++videoSequenceRef.current, timestampMs,
        startSample: 0, sampleCount: 0, payload: buffer}));
      return true;
    } catch (reason) {fail(reason as Error); throw reason;}
  }, [fail]);
  const sendAudioPacket = useCallback((packet: Omit<MediaPacket, 'type' | 'timestampMs'>) => {
    try {
      const socket = socketRef.current;
      if (!runningRef.current || socket?.readyState !== WebSocket.OPEN) throw new Error('음성 전송이 중단되었습니다.');
      const unacked = [...ackRef.current.values()].reduce((sum, item) => sum + item.samples, 0);
      checkMediaBacklog(socket.bufferedAmount + packet.payload.byteLength + 26, unacked + packet.sampleCount);
      const waiting = pending<void>(5000, '음성 수신 확인 시간이 초과되었습니다.', fail);
      ackRef.current.set(packet.sequence, {pending: waiting, samples: packet.sampleCount});
      socket.send(encodeMediaV2({...packet, type: 2, timestampMs: audioOriginRef.current + Math.floor(packet.startSample * 1000 / 16000)}));
    } catch (reason) {fail(reason as Error); throw reason;}
  }, [fail]);
  const awaitAudioAck = useCallback((sequence: number) => {
    if (sequence <= acknowledgedRef.current) return Promise.resolve();
    return ackRef.current.get(sequence)?.pending.promise ?? Promise.reject(new Error('음성 수신 확인을 찾을 수 없습니다.'));
  }, []);
  const finish = useCallback((_sessionId: string, incomplete = false) => {
    if (completionRef.current) return completionRef.current.promise;
    const waiting = pending<SessionCompletionReport>(35000, '세션 분석 완료 응답 시간이 초과되었습니다.', fail);
    completionRef.current = waiting;
    try {control('session.end', {incomplete});} catch (reason) {fail(reason as Error);}
    return waiting.promise;
  }, [control, fail]);
  const startCalibration = useCallback(() => {
    control('calibration.start');
    setError(null);
  }, [control]);
  useEffect(() => disconnect, [disconnect]);
  return {status, error, modules, connect, disconnect, sessionTime, sendVideoFrame, sendAudioPacket,
    awaitAudioAck, finish, startCalibration, reportCaptureError: fail};
}
